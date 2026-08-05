"""Controlled materialization helpers for small derived marts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .queries import QuerySpecError, quote_identifier

ALLOWED_SOURCE_RELATIONS = frozenset(
    {
        "canonical.screen",
        "canonical.returns_wide",
        "canonical.last_screen",
        "signals.all_signals",
        "signals.latest_signals",
    }
)


@dataclass(frozen=True)
class MaterializationSpec:
    name: str
    source_relation: str
    replace: bool = True

    def __post_init__(self) -> None:
        if not self.name or "." in self.name or not self.name.replace("_", "").isalnum():
            raise QuerySpecError(f"invalid mart name: {self.name!r}")
        if self.source_relation not in ALLOWED_SOURCE_RELATIONS:
            raise QuerySpecError(f"source relation is not allowed: {self.source_relation!r}")


@dataclass(frozen=True)
class MartRefreshResult:
    """Summary of one reproducible presentation-mart refresh."""

    status: str
    release_id: str
    tables: tuple[str, ...]
    artifact_count: int
    run_count: int
    latest_screen_date: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "release_id": self.release_id,
            "tables": list(self.tables),
            "artifact_count": self.artifact_count,
            "run_count": self.run_count,
            "latest_screen_date": self.latest_screen_date,
        }


def materialize(connection: Any, spec: MaterializationSpec, *, catalog_release_id: str | None = None) -> int:
    schema_sql = quote_identifier("marts")
    table_sql = quote_identifier(spec.name)
    source_sql = ".".join(quote_identifier(part) for part in spec.source_relation.split("."))
    statement = "CREATE OR REPLACE TABLE" if spec.replace else "CREATE TABLE IF NOT EXISTS"
    connection.execute(f"{statement} {schema_sql}.{table_sql} AS SELECT * FROM {source_sql}")
    rows = int(connection.execute(f"SELECT COUNT(*) FROM {schema_sql}.{table_sql}").fetchone()[0])
    connection.execute(
        "INSERT OR REPLACE INTO meta.materialization_registry "
        "(materialization_name, source_relation, row_count, catalog_release_id, refreshed_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [spec.name, spec.source_relation, rows, catalog_release_id, datetime.now(UTC)],
    )
    return rows


def refresh_presentation_marts(
    connection: Any,
    *,
    data_root: str | Path,
    artifact_root: str | Path,
    release_id: str,
    latest_screen_date: str | None = None,
) -> MartRefreshResult:
    """Build bounded dashboard marts and register source artifacts/runs.

    The function only reads explicit artifact paths and the already-created
    canonical release.  Dashboard consumers can therefore query these small
    tables without scanning the canonical Screen or Returns relations.
    """

    artifacts = Path(artifact_root).resolve()
    if latest_screen_date is None:
        latest_screen_date = _latest_screen_date(connection)
    if latest_screen_date is None:
        raise ValueError("cannot materialize marts without a latest Screen date")
    latest = date.fromisoformat(str(latest_screen_date)[:10])
    tables: list[str] = []

    connection.execute(
        "CREATE OR REPLACE TABLE marts.company_master_latest AS "
        'SELECT * EXCLUDE (__tp_partition_year, __tp_partition_month) '
        'FROM canonical.screen WHERE __tp_partition_year = ? AND __tp_partition_month = ? AND "Date" = ?',
        [latest.year, latest.month, latest],
    )
    tables.append("marts.company_master_latest")
    connection.execute(
        "CREATE OR REPLACE TABLE marts.latest_screen_summary AS "
        "SELECT CAST(? AS DATE) AS latest_screen_date, COUNT(*)::BIGINT AS security_rows, "
        "COUNT(DISTINCT \"ISIN\")::BIGINT AS unique_isins "
        "FROM marts.company_master_latest",
        [latest],
    )
    tables.append("marts.latest_screen_summary")

    signal_files = sorted((artifacts / "signals").glob("*.parquet"))
    if signal_files:
        signal_sql = _path_list(signal_files)
        connection.execute(
            "CREATE OR REPLACE TABLE signals.all_signals AS "
            f"SELECT * FROM read_parquet([{signal_sql}], union_by_name=true, hive_partitioning=false)"
        )
        connection.execute(
            "CREATE OR REPLACE TABLE signals.latest_signals AS "
            "SELECT * FROM signals.all_signals WHERE \"Date\" = (SELECT MAX(\"Date\") FROM signals.all_signals)"
        )
    else:
        connection.execute(
            "CREATE OR REPLACE TABLE signals.all_signals AS "
            "SELECT CAST(NULL AS DATE) AS \"Date\", CAST(NULL AS VARCHAR) AS signal_family WHERE FALSE"
        )
        connection.execute("CREATE OR REPLACE TABLE signals.latest_signals AS SELECT * FROM signals.all_signals")
    tables.extend(("signals.all_signals", "signals.latest_signals"))
    connection.execute("CREATE OR REPLACE TABLE marts.latest_signals AS SELECT * FROM signals.latest_signals")
    tables.append("marts.latest_signals")

    for table_name, pattern in (
        ("marts.latest_regime", "%regime%"),
        ("marts.latest_country_scores", "%country%"),
        ("marts.latest_sector_scores", "%sector%"),
        ("marts.latest_factor_recommendation", "%factor%"),
    ):
        family_filter = (
            "(lower(coalesce(signal_family, '')) LIKE ? "
            "OR lower(coalesce(signal_name, '')) LIKE ?)"
        )
        connection.execute(
            f"CREATE OR REPLACE TABLE {table_name} AS "
            "SELECT * FROM signals.all_signals "
            f"WHERE {family_filter} AND \"Date\" = ("
            "SELECT MAX(\"Date\") FROM signals.all_signals "
            f"WHERE {family_filter})",
            [pattern, pattern, pattern, pattern],
        )
        tables.append(table_name)

    candidate_path = artifacts / "candidates" / "latest_candidates.parquet"
    portfolio_path = artifacts / "portfolios" / "latest_target_weights.parquet"
    tables.append(_materialize_artifact_table(connection, "marts.latest_candidates", candidate_path))
    tables.append(_materialize_artifact_table(connection, "marts.latest_portfolio", portfolio_path))

    run_rows = _register_pipeline_runs(connection, artifacts, release_id=release_id)
    artifact_count = _register_artifacts(connection, artifacts, release_id=release_id)
    connection.execute(
        "CREATE OR REPLACE TABLE marts.pipeline_run_summary AS "
        "SELECT run_id, run_type, status, catalog_release_id, started_at, completed_at "
        "FROM meta.run_registry ORDER BY completed_at DESC NULLS LAST"
    )
    tables.append("marts.pipeline_run_summary")
    connection.execute(
        "CREATE OR REPLACE TABLE marts.research_run_summary AS "
        "SELECT * FROM marts.pipeline_run_summary WHERE lower(coalesce(run_type, '')) LIKE '%research%'"
    )
    tables.append("marts.research_run_summary")

    _materialize_backtest_summary(connection, artifacts, release_id=release_id)
    tables.append("marts.latest_backtest_summary")
    connection.execute(
        "CREATE OR REPLACE TABLE marts.backtest_run_catalog AS "
        "SELECT * FROM marts.pipeline_run_summary "
        "WHERE lower(coalesce(run_type, '')) LIKE '%backtest%' OR lower(coalesce(run_id, '')) LIKE '%backtest%'"
    )
    tables.append("marts.backtest_run_catalog")

    connection.execute(
        "CREATE OR REPLACE TABLE marts.data_health AS "
        "SELECT dataset_name, dataset_version, check_name, status, details_json, checked_at "
        "FROM meta.data_quality_results ORDER BY checked_at DESC"
    )
    tables.append("marts.data_health")
    connection.execute(
        "CREATE OR REPLACE TABLE marts.dashboard_overview AS "
        "SELECT CAST(? AS DATE) AS latest_screen_date, CAST(? AS VARCHAR) AS release_id, "
        "(SELECT COUNT(*) FROM marts.latest_signals)::BIGINT AS latest_signal_rows, "
        "(SELECT COUNT(*) FROM marts.latest_candidates)::BIGINT AS candidate_rows, "
        "(SELECT COUNT(*) FROM marts.latest_portfolio)::BIGINT AS portfolio_rows, "
        "(SELECT COUNT(*) FROM marts.data_health)::BIGINT AS data_health_rows",
        [latest, release_id],
    )
    tables.append("marts.dashboard_overview")
    for table_name in tables:
        _register_materialization(connection, table_name, release_id=release_id)
    return MartRefreshResult(
        status="passed",
        release_id=release_id,
        tables=tuple(tables),
        artifact_count=artifact_count,
        run_count=run_rows,
        latest_screen_date=latest.isoformat(),
    )


def _latest_screen_date(connection: Any) -> str | None:
    row = connection.execute('SELECT MAX("Date") FROM canonical.screen').fetchone()
    return row[0].isoformat() if row and row[0] is not None else None


def _materialize_artifact_table(connection: Any, table_name: str, path: Path) -> str:
    if path.exists():
        connection.execute(
            f"CREATE OR REPLACE TABLE {table_name} AS "
            f"SELECT * FROM read_parquet([{_path_list([path])}], union_by_name=true, hive_partitioning=false)"
        )
    else:
        connection.execute(
            f"CREATE OR REPLACE TABLE {table_name} AS "
            "SELECT CAST(NULL AS VARCHAR) AS artifact_path WHERE FALSE"
        )
    return table_name


def _register_pipeline_runs(connection: Any, artifacts: Path, *, release_id: str) -> int:
    manifests = sorted((artifacts / "pipeline_runs" / "manifests").glob("*/*_latest.json"))
    count = 0
    for path in manifests:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        step = str(payload.get("step") or path.parent.name)
        run_id = str(payload.get("run_id") or f"{step}:{path.name}")
        connection.execute(
            "INSERT OR REPLACE INTO meta.run_registry "
            "(run_id, run_type, status, dataset_version, catalog_release_id, query_hash, started_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                str(payload.get("run_type") or step),
                str(payload.get("status") or "unknown"),
                None,
                release_id,
                None,
                payload.get("started_at"),
                payload.get("finished_at") or payload.get("completed_at"),
            ],
        )
        count += 1
    return count


def _register_artifacts(connection: Any, artifacts: Path, *, release_id: str) -> int:
    candidates = list((artifacts / "signals").glob("*.parquet"))
    candidates.extend(path for path in (artifacts / "candidates", artifacts / "portfolios") if path.exists() for path in path.glob("*.parquet"))
    candidates.extend((artifacts / "pipeline_runs" / "manifests").glob("*/*_latest.json"))
    count = 0
    for path in candidates:
        digest = _sha256_file(path)
        artifact_id = f"{path.as_posix()}:{digest}"
        connection.execute(
            "INSERT OR REPLACE INTO meta.artifact_registry "
            "(artifact_id, artifact_type, path, sha256, run_id, catalog_release_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [artifact_id, path.suffix.lstrip("."), str(path), digest, None, release_id, datetime.now(UTC)],
        )
        count += 1
    return count


def _materialize_backtest_summary(connection: Any, artifacts: Path, *, release_id: str) -> None:
    path = artifacts / "pipeline_runs" / "manifests" / "run_backtest" / "run_backtest_latest.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        connection.execute(
            "CREATE OR REPLACE TABLE marts.latest_backtest_summary AS "
            "SELECT ? AS run_id, ? AS status, ? AS manifest_path, ? AS finished_at, ? AS summary_json",
            [str(payload.get("run_id") or "run_backtest_latest"), payload.get("status"), str(path), payload.get("finished_at"), json.dumps(payload, ensure_ascii=False)],
        )
    else:
        connection.execute(
            "CREATE OR REPLACE TABLE marts.latest_backtest_summary AS "
            "SELECT CAST(NULL AS VARCHAR) AS run_id, CAST(NULL AS VARCHAR) AS status, "
            "CAST(NULL AS VARCHAR) AS manifest_path, CAST(NULL AS VARCHAR) AS finished_at, "
            "CAST(NULL AS VARCHAR) AS summary_json WHERE FALSE"
        )
    _register_materialization(connection, "marts.latest_backtest_summary", release_id=release_id)


def _register_materialization(connection: Any, name: str, *, release_id: str) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO meta.materialization_registry "
        "(materialization_name, source_relation, row_count, catalog_release_id, refreshed_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [name, "canonical/supplemental/artifact", int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]), release_id, datetime.now(UTC)],
    )


def _path_list(paths: list[Path]) -> str:
    return ", ".join("'" + str(path.resolve()).replace("'", "''").replace("\\", "/") + "'" for path in paths)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ALLOWED_SOURCE_RELATIONS",
    "MartRefreshResult",
    "MaterializationSpec",
    "materialize",
    "refresh_presentation_marts",
]

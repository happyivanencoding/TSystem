"""DuckDB catalog schemas, manifest views, and release registration."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import DuckDBConfig
from .connection import connect
from .contracts import CATALOG_SCHEMA_VERSION, CATALOG_SCHEMAS, CatalogHealth, CatalogRelease
from .locking import FileLock
from .manifests import DatasetManifest, load_manifest, resolve_partition_path

CATALOG_TABLES: tuple[str, ...] = (
    "meta.schema_migrations",
    "meta.dataset_registry",
    "meta.dataset_versions",
    "meta.partition_registry",
    "meta.schema_registry",
    "meta.data_quality_results",
    "meta.catalog_releases",
    "meta.artifact_registry",
    "meta.run_registry",
    "meta.pipeline_manifest_registry",
    "meta.benchmark_registry",
    "meta.query_benchmark_results",
    "meta.materialization_registry",
)


def initialize_catalog(connection: Any) -> None:
    """Create the foundation schemas/tables idempotently."""

    for schema in CATALOG_SCHEMAS:
        connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    for statement in _TABLE_DDL:
        connection.execute(statement)
    existing = connection.execute(
        "SELECT COUNT(*) FROM meta.schema_migrations WHERE version = ?",
        [CATALOG_SCHEMA_VERSION],
    ).fetchone()[0]
    if not existing:
        connection.execute(
            "INSERT INTO meta.schema_migrations(version, applied_at, checksum) VALUES (?, ?, ?)",
            [CATALOG_SCHEMA_VERSION, datetime.now(UTC), CATALOG_SCHEMA_VERSION],
        )


def catalog_health(connection: Any) -> CatalogHealth:
    schemas = tuple(
        row[0]
        for row in connection.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ("
            + ",".join("?" for _ in CATALOG_SCHEMAS)
            + ") ORDER BY schema_name",
            list(CATALOG_SCHEMAS),
        ).fetchall()
    )
    tables: list[str] = []
    table_rows: dict[str, int] = {}
    for relation in CATALOG_TABLES:
        schema, table = relation.split(".", 1)
        count = connection.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"').fetchone()[0]
        tables.append(relation)
        table_rows[relation] = int(count)
    version_rows = connection.execute(
        "SELECT version FROM meta.schema_migrations ORDER BY applied_at"
    ).fetchall()
    versions = tuple(row[0] for row in version_rows)
    return CatalogHealth(
        ok=set(CATALOG_SCHEMAS).issubset(schemas) and set(CATALOG_TABLES).issubset(tables),
        schemas=schemas,
        tables=tuple(tables),
        table_rows=table_rows,
        schema_version=versions[-1] if versions else "unknown",
    )


def register_release(connection: Any, release: CatalogRelease) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO meta.catalog_releases "
        "(release_id, created_at, database_path, screen_dataset_version, "
        "returns_dataset_version, validation_status, manifest_path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            release.release_id,
            release.created_at,
            release.database_path,
            release.screen_dataset_version,
            release.returns_dataset_version,
            release.validation_status,
            release.manifest_path,
        ],
    )


def latest_release(connection: Any) -> dict[str, Any] | None:
    rows = connection.execute(
        "SELECT release_id, created_at, database_path, screen_dataset_version, "
        "returns_dataset_version, validation_status, manifest_path "
        "FROM meta.catalog_releases ORDER BY created_at DESC LIMIT 1"
    ).fetchall()
    if not rows:
        return None
    columns = [item[0] for item in connection.description]
    return dict(zip(columns, rows[0], strict=True))


def initialize_database(
    config: DuckDBConfig,
    *,
    release_id: str | None = None,
    screen_dataset_version: str | None = None,
    returns_dataset_version: str | None = None,
) -> CatalogHealth:
    """Initialize a database under the single-writer lock."""

    if config.read_only:
        raise ValueError("initialize_database requires read_only=False")
    lock_path = config.database_path.with_suffix(config.database_path.suffix + ".lock")
    with FileLock(lock_path), connect(config) as connection:
        initialize_catalog(connection)
        if release_id is not None:
            register_release(
                connection,
                CatalogRelease(
                    release_id=release_id,
                    database_path=str(config.database_path),
                    screen_dataset_version=screen_dataset_version,
                    returns_dataset_version=returns_dataset_version,
                ),
            )
        return catalog_health(connection)


def create_canonical_views(
    connection: Any,
    *,
    screen_manifest: DatasetManifest,
    returns_manifest: DatasetManifest,
    data_root: str | Path,
) -> tuple[str, ...]:
    """Create canonical views from explicit immutable manifest file lists."""

    initialize_catalog(connection)
    root = Path(data_root).resolve()
    views = {
        "canonical.screen": screen_manifest,
        "canonical.returns_wide": returns_manifest,
    }
    for relation, manifest in views.items():
        schema_name, relation_name = relation.split(".", 1)
        expression = _read_parquet_expression(manifest, root=root)
        if manifest.dataset_name == "screen":
            expression = (
                f"(SELECT * EXCLUDE (year, month), CAST(year AS INTEGER) AS __tp_partition_year, "
                f"CAST(month AS INTEGER) AS __tp_partition_month FROM {expression})"
            )
        else:
            expression = f"(SELECT * EXCLUDE (year), CAST(year AS INTEGER) AS __tp_partition_year FROM {expression})"
        connection.execute(
            f'CREATE OR REPLACE VIEW "{schema_name}"."{relation_name}" AS SELECT * FROM {expression}'
        )
        _register_manifest(connection, manifest, root=root)
    return tuple(views)


def build_catalog_release(
    config: DuckDBConfig,
    *,
    release_id: str,
    screen_manifest_path: str | Path,
    returns_manifest_path: str | Path,
    update_latest: bool = False,
    refresh_marts: bool = False,
) -> dict[str, Any]:
    """Build one immutable catalog release without changing production defaults."""

    if config.read_only:
        raise ValueError("build_catalog_release requires read_only=False")
    if update_latest:
        raise ValueError(
            "direct latest-pointer updates are disabled; use "
            "tp-duckdb-activate-authority after the evidence gate"
        )
    root = config.data_root.resolve()
    screen_manifest = _load_manifest_reference(screen_manifest_path, root=root)
    returns_manifest = _load_manifest_reference(returns_manifest_path, root=root)
    if screen_manifest.dataset_name != "screen":
        raise ValueError(f"screen manifest has unexpected dataset: {screen_manifest.dataset_name!r}")
    if returns_manifest.dataset_name != "returns_wide":
        raise ValueError(f"returns manifest has unexpected dataset: {returns_manifest.dataset_name!r}")

    release_root = config.artifact_root / "analytics" / "duckdb" / "releases"
    release_dir = release_root / release_id
    final_database = release_dir / "tp_analytics.duckdb"
    if final_database.exists():
        raise FileExistsError(f"catalog release already exists: {final_database}")
    release_root.mkdir(parents=True, exist_ok=True)
    staging_root = config.artifact_root / "analytics" / "duckdb" / "staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f"{release_id}-{os.getpid()}-", dir=staging_root))
    staging_database = staging_dir / "tp_analytics.duckdb"
    writer_lock = config.database_path.with_suffix(config.database_path.suffix + ".lock")
    try:
        build_config = config.with_database(staging_database, read_only=False)
        with FileLock(writer_lock), connect(build_config) as connection:
            create_canonical_views(
                connection,
                screen_manifest=screen_manifest,
                returns_manifest=returns_manifest,
                data_root=root,
            )
            mart_summary: dict[str, Any] | None = None
            if refresh_marts:
                from .materializations import refresh_presentation_marts

                mart_summary = refresh_presentation_marts(
                    connection,
                    data_root=root,
                    artifact_root=config.artifact_root,
                    release_id=release_id,
                    latest_screen_date=str(screen_manifest.payload.get("date_max"))
                    if screen_manifest.payload.get("date_max")
                    else None,
                ).as_dict()
            register_release(
                connection,
                CatalogRelease(
                    release_id=release_id,
                    database_path=str(final_database),
                    screen_dataset_version=screen_manifest.dataset_version,
                    returns_dataset_version=returns_manifest.dataset_version,
                    validation_status="marts_ready" if refresh_marts else "shadow_ready",
                    manifest_path=str(screen_manifest.path),
                ),
            )
            health = catalog_health(connection)
        release_dir.mkdir(parents=True, exist_ok=False)
        os.replace(staging_database, final_database)
        summary = {
            "status": "applied",
            "release_id": release_id,
            "database_path": str(final_database),
            "screen_dataset_version": screen_manifest.dataset_version,
            "returns_dataset_version": returns_manifest.dataset_version,
            "screen_manifest_path": str(screen_manifest.path),
            "returns_manifest_path": str(returns_manifest.path),
            "catalog_health": health.as_dict(),
            "read_only_shadow": True,
            "marts": mart_summary,
        }
        return summary
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _load_manifest_reference(path: str | Path, *, root: Path) -> DatasetManifest:
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    if target.name == "current.json":
        payload = json.loads(target.read_text(encoding="utf-8"))
        manifest_path = Path(str(payload["manifest_path"]))
        if not manifest_path.is_absolute():
            manifest_path = root / manifest_path
        target = manifest_path
    return load_manifest(target, require_files=True, root=root)


def _read_parquet_expression(manifest: DatasetManifest, *, root: Path) -> str:
    partitions = list(manifest.partitions)
    if not partitions:
        raise ValueError(f"manifest has no partitions: {manifest.path}")
    files = [resolve_partition_path(manifest, partition, root=root).resolve() for partition in partitions]
    missing = [str(path) for path in files if not path.exists()]
    if missing:
        raise FileNotFoundError(f"manifest partitions are missing: {missing[:3]}")
    branches: list[str] = []
    for partition, path in zip(partitions, files, strict=True):
        year = int(partition["year"])
        partition_columns = f", {year} AS year"
        if partition.get("month") is not None:
            partition_columns += f", {int(partition['month'])} AS month"
        normalized_path = _sql_string(str(path).replace("\\", "/"))
        branches.append(
            "SELECT *"
            f"{partition_columns} FROM read_parquet([{normalized_path}], "
            "union_by_name=true, hive_partitioning=false)"
        )
    return "(" + " UNION ALL BY NAME ".join(branches) + ")"


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _register_manifest(connection: Any, manifest: DatasetManifest, *, root: Path) -> None:
    created_at = manifest.payload.get("created_at") or datetime.now(UTC).isoformat()
    connection.execute(
        "INSERT OR REPLACE INTO meta.dataset_registry "
        "(dataset_name, current_dataset_version, current_manifest_path, updated_at) VALUES (?, ?, ?, ?)",
        [manifest.dataset_name, manifest.dataset_version, str(manifest.path), datetime.now(UTC)],
    )
    connection.execute(
        "INSERT OR REPLACE INTO meta.dataset_versions "
        "(dataset_name, dataset_version, manifest_path, schema_fingerprint, row_count, validation_status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            manifest.dataset_name,
            manifest.dataset_version,
            str(manifest.path),
            manifest.payload.get("schema_fingerprint"),
            int(manifest.payload.get("row_count", 0)),
            manifest.payload.get("validation_status", "unknown"),
            created_at,
        ],
    )
    for partition in manifest.partitions:
        path = resolve_partition_path(manifest, partition, root=root)
        connection.execute(
            "INSERT OR REPLACE INTO meta.partition_registry "
            "(dataset_name, dataset_version, partition_key, path, sha256, row_count, bytes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                manifest.dataset_name,
                manifest.dataset_version,
                partition.get("partition_key"),
                str(path),
                partition.get("sha256"),
                int(partition.get("row_count", 0)),
                int(partition.get("bytes", 0)),
                created_at,
            ],
        )
    connection.execute(
        "INSERT OR REPLACE INTO meta.schema_registry "
        "(schema_name, object_name, object_type, schema_fingerprint, registered_at) VALUES (?, ?, ?, ?, ?)",
        ["canonical", manifest.dataset_name, "view", manifest.payload.get("schema_fingerprint"), datetime.now(UTC)],
    )
    connection.execute(
        "INSERT INTO meta.data_quality_results "
        "(dataset_name, dataset_version, check_name, status, details_json, checked_at) VALUES (?, ?, ?, ?, ?, ?)",
        [
            manifest.dataset_name,
            manifest.dataset_version,
            "manifest_validation",
            manifest.payload.get("validation_status", "unknown"),
            json.dumps({"partition_count": len(manifest.partitions), "root": str(root)}),
            datetime.now(UTC),
        ],
    )


_TABLE_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS meta.schema_migrations (
        version VARCHAR PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL,
        checksum VARCHAR NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS meta.dataset_registry (
        dataset_name VARCHAR PRIMARY KEY,
        current_dataset_version VARCHAR,
        current_manifest_path VARCHAR,
        updated_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS meta.dataset_versions (
        dataset_name VARCHAR,
        dataset_version VARCHAR,
        manifest_path VARCHAR,
        schema_fingerprint VARCHAR,
        row_count BIGINT,
        validation_status VARCHAR,
        created_at TIMESTAMPTZ,
        PRIMARY KEY(dataset_name, dataset_version)
    )""",
    """CREATE TABLE IF NOT EXISTS meta.partition_registry (
        dataset_name VARCHAR,
        dataset_version VARCHAR,
        partition_key VARCHAR,
        path VARCHAR,
        sha256 VARCHAR,
        row_count BIGINT,
        bytes BIGINT,
        created_at TIMESTAMPTZ,
        PRIMARY KEY(dataset_name, dataset_version, partition_key, path)
    )""",
    """CREATE TABLE IF NOT EXISTS meta.schema_registry (
        schema_name VARCHAR,
        object_name VARCHAR,
        object_type VARCHAR,
        schema_fingerprint VARCHAR,
        registered_at TIMESTAMPTZ,
        PRIMARY KEY(schema_name, object_name, object_type)
    )""",
    """CREATE TABLE IF NOT EXISTS meta.data_quality_results (
        dataset_name VARCHAR,
        dataset_version VARCHAR,
        check_name VARCHAR,
        status VARCHAR,
        details_json VARCHAR,
        checked_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS meta.catalog_releases (
        release_id VARCHAR PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL,
        database_path VARCHAR NOT NULL,
        screen_dataset_version VARCHAR,
        returns_dataset_version VARCHAR,
        validation_status VARCHAR NOT NULL,
        manifest_path VARCHAR
    )""",
    """CREATE TABLE IF NOT EXISTS meta.artifact_registry (
        artifact_id VARCHAR,
        artifact_type VARCHAR,
        path VARCHAR,
        sha256 VARCHAR,
        run_id VARCHAR,
        catalog_release_id VARCHAR,
        created_at TIMESTAMPTZ,
        PRIMARY KEY(artifact_id)
    )""",
    """CREATE TABLE IF NOT EXISTS meta.run_registry (
        run_id VARCHAR PRIMARY KEY,
        run_type VARCHAR,
        status VARCHAR,
        dataset_version VARCHAR,
        catalog_release_id VARCHAR,
        query_hash VARCHAR,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS meta.pipeline_manifest_registry (
        manifest_id VARCHAR PRIMARY KEY,
        step_name VARCHAR,
        path VARCHAR,
        status VARCHAR,
        run_id VARCHAR,
        created_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS meta.benchmark_registry (
        benchmark_id VARCHAR PRIMARY KEY,
        workload VARCHAR,
        engine VARCHAR,
        result_fingerprint VARCHAR,
        elapsed_seconds DOUBLE,
        peak_memory_bytes BIGINT,
        bytes_read BIGINT,
        created_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS meta.query_benchmark_results (
        benchmark_id VARCHAR,
        query_hash VARCHAR,
        cold_or_warm VARCHAR,
        elapsed_seconds DOUBLE,
        result_fingerprint VARCHAR,
        created_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS meta.materialization_registry (
        materialization_name VARCHAR PRIMARY KEY,
        source_relation VARCHAR,
        row_count BIGINT,
        catalog_release_id VARCHAR,
        refreshed_at TIMESTAMPTZ
    )""",
)


__all__ = [
    "CATALOG_TABLES",
    "build_catalog_release",
    "catalog_health",
    "create_canonical_views",
    "initialize_catalog",
    "initialize_database",
    "latest_release",
    "register_release",
]

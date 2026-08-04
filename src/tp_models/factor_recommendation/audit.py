"""仓库、canonical 数据与 factor recommendation integration 审计。

审计输出固定落在 ``16_factor_recommendation_model/audit``，只读取 parquet
metadata 和指定列，不写回 ``00_screen``。完整 screen 的 key/date/coverage
读取采用列式读取，避免 materialize 不必要的 canonical 字段。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH

from .config import DEFAULT_FACTOR_DEFINITIONS_PATH, DEFAULT_REGION_UNIVERSES_PATH
from .factor_definitions import FactorDefinition, load_factor_definitions
from .universe import RegionUniverse, UniverseComponent, load_region_universes


PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AUDIT_DIR = PACKAGE_ROOT / "16_factor_recommendation_model" / "audit"


def _metadata(path: Path) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - project dependency, defensive only
        raise RuntimeError("audit requires pyarrow for parquet metadata") from exc
    parquet = pq.ParquetFile(path)
    schema_names = list(parquet.schema_arrow.names)
    return {
        "path": str(path),
        "exists": path.exists(),
        "row_count": int(parquet.metadata.num_rows),
        "schema_column_count": int(len(schema_names)),
        "schema_columns": schema_names,
        "row_group_count": int(parquet.metadata.num_row_groups),
    }


def _metadata_stats(path: Path, column_name: str) -> tuple[Any, Any] | None:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("audit requires pyarrow for parquet metadata") from exc
    parquet = pq.ParquetFile(path)
    minimum: Any = None
    maximum: Any = None
    found = False
    for group_index in range(parquet.metadata.num_row_groups):
        group = parquet.metadata.row_group(group_index)
        for column_index in range(group.num_columns):
            column = group.column(column_index)
            if column.path_in_schema != column_name or column.statistics is None:
                continue
            found = True
            value_min = column.statistics.min
            value_max = column.statistics.max
            if minimum is None or value_min < minimum:
                minimum = value_min
            if maximum is None or value_max > maximum:
                maximum = value_max
    return (minimum, maximum) if found else None


def _read_columns(path: Path, columns: Iterable[str]) -> pd.DataFrame:
    """按列读取，并还原 screen 的 ISIN index。"""

    requested = tuple(dict.fromkeys(str(column) for column in columns))
    frame = pd.read_parquet(path, columns=list(requested))
    if "ISIN" not in frame.columns and frame.index.name == "ISIN":
        frame = frame.reset_index()
    elif "ISIN" not in frame.columns and len(frame.index) == len(frame):
        # pandas parquet index metadata can occasionally lose its name.
        frame.insert(0, "ISIN", frame.index.astype(str))
    return frame


def _date_payload(frame: pd.DataFrame, date_column: str = "Date") -> dict[str, Any]:
    if date_column not in frame.columns or frame.empty:
        return {"date_count": 0, "date_min": None, "date_max": None}
    dates = pd.to_datetime(frame[date_column], errors="coerce").dropna()
    if dates.empty:
        return {"date_count": 0, "date_min": None, "date_max": None}
    return {
        "date_count": int(dates.nunique()),
        "date_min": dates.min().date().isoformat(),
        "date_max": dates.max().date().isoformat(),
    }


def _screen_data_audit(path: Path, definitions: tuple[FactorDefinition, ...], regions: Mapping[str, RegionUniverse]) -> dict[str, Any]:
    meta = _metadata(path)
    date_stats = _metadata_stats(path, "Date")
    key_frame = _read_columns(path, ["ISIN", "Date"])
    key_frame["Date"] = pd.to_datetime(key_frame["Date"], errors="coerce")
    duplicate_mask = key_frame.duplicated(["ISIN", "Date"], keep=False)
    audit: dict[str, Any] = {
        **meta,
        "pandas_data_column_count": int(max(0, len(meta["schema_columns"]) - 1))
        if "ISIN" in meta["schema_columns"]
        else int(len(meta["schema_columns"])),
        "key_columns": ["ISIN", "Date"],
        "key_duplicate_rows": int(duplicate_mask.sum()),
        "key_duplicate_groups": int(key_frame.loc[duplicate_mask].groupby(["ISIN", "Date"]).ngroups),
        "null_isin_rows": int(key_frame["ISIN"].isna().sum()),
        "null_date_rows": int(key_frame["Date"].isna().sum()),
        "date_metadata_min": str(date_stats[0]) if date_stats else None,
        "date_metadata_max": str(date_stats[1]) if date_stats else None,
        "date_columnar": _date_payload(key_frame),
        "weight_columns": sorted(
            {
                component.weight_column
                for spec in regions.values()
                for component in spec.components
            }
        ),
    }
    return audit


def _returns_data_audit(path: Path) -> dict[str, Any]:
    meta = _metadata(path)
    stats = _metadata_stats(path, "__index_level_0__")
    date_frame = pd.read_parquet(path, columns=[])
    dates = pd.to_datetime(date_frame.index, errors="coerce")
    duplicate_dates = int(dates.duplicated(keep=False).sum())
    return {
        **meta,
        "pandas_data_column_count": int(max(0, len(meta["schema_columns"]) - 1)),
        "date_index_name": date_frame.index.name,
        "date_columnar": {
            "date_count": int(dates.nunique()),
            "date_min": dates.min().date().isoformat() if len(dates) else None,
            "date_max": dates.max().date().isoformat() if len(dates) else None,
        },
        "date_metadata_min": str(stats[0]) if stats else None,
        "date_metadata_max": str(stats[1]) if stats else None,
        "duplicate_date_rows": duplicate_dates,
        "security_column_count": int(len(date_frame.columns) or max(0, len(meta["schema_columns"]) - 1)),
    }


def build_data_audit(
    *,
    screen_path: str | Path = SCREEN_AGGREGATE_PATH,
    returns_path: str | Path = RETURNS_PATH,
    definitions: tuple[FactorDefinition, ...] | None = None,
    regions: Mapping[str, RegionUniverse] | None = None,
) -> dict[str, Any]:
    definitions = definitions or load_factor_definitions()
    regions = regions or load_region_universes()
    screen = Path(screen_path)
    returns = Path(returns_path)
    if not screen.exists():
        raise FileNotFoundError(screen)
    if not returns.exists():
        raise FileNotFoundError(returns)
    screen_audit = _screen_data_audit(screen, definitions, regions)
    return {
        "schema_version": "factor_recommendation.data_audit.v1",
        "screen": screen_audit,
        "returns": _returns_data_audit(returns),
        "region_contracts": {
            name: {
                "display_name": spec.display_name,
                "aliases": list(spec.aliases),
                "aggregation_weights": dict(spec.aggregation_weights),
                "component_aggregation_weights": dict(spec.component_aggregation_weights),
                "currency_basis": spec.currency_basis,
                "minimum_monthly_constituents": spec.minimum_monthly_constituents,
                "minimum_weight_coverage": spec.minimum_weight_coverage,
                "history_start": spec.history_start,
                "production_eligible": spec.production_eligible,
                "approval_status": spec.approval_status,
                "research_only": spec.research_only,
                "benchmark_approved": spec.benchmark_approved,
            }
            for name, spec in regions.items()
        },
        "pit_contract": {
            "screen_key": ["ISIN", "Date"],
            "screen_date_semantics": "monthly as-of snapshot",
            "returns_semantics": "daily return rows indexed by trading Date and columns by Company SEDOL",
            "feature_lag_months": 1,
            "target_horizon_months": 1,
        },
    }


def build_factor_column_audit(
    screen_path: str | Path,
    definitions: tuple[FactorDefinition, ...] | None = None,
) -> pd.DataFrame:
    definitions = definitions or load_factor_definitions()
    path = Path(screen_path)
    metadata = _metadata(path)
    available = set(metadata["schema_columns"])
    requested = ["Date"] + [source for definition in definitions for source in definition.source_columns]
    frame = _read_columns(path, [column for column in dict.fromkeys(requested) if column in available])
    rows: list[dict[str, Any]] = []
    total_rows = len(frame)
    for definition in definitions:
        for source in definition.source_columns:
            actual = source if source in frame.columns else None
            if actual is None:
                normalized = {str(column).strip().lower(): column for column in frame.columns}
                actual = normalized.get(source.strip().lower())
            if actual is None:
                rows.append(
                    {
                        "factor": definition.name,
                        "source_column": source,
                        "actual_column": None,
                        "exists": False,
                        "row_count": int(total_rows),
                        "non_null_rows": 0,
                        "coverage_pct": 0.0,
                        "date_count_with_value": 0,
                    }
                )
                continue
            values = pd.to_numeric(frame[actual], errors="coerce")
            non_null = values.notna()
            rows.append(
                {
                    "factor": definition.name,
                    "source_column": source,
                    "actual_column": str(actual),
                    "exists": True,
                    "row_count": int(total_rows),
                    "non_null_rows": int(non_null.sum()),
                    "coverage_pct": float(non_null.mean()) if total_rows else 0.0,
                    "date_count_with_value": int(
                        frame.loc[non_null, "Date"].nunique() if "Date" in frame.columns else 0
                    ),
                }
            )
    return pd.DataFrame(rows)


def _component_audit_rows(
    screen_path: Path,
    regions: Mapping[str, RegionUniverse],
) -> pd.DataFrame:
    columns = ["Date", "Exchange Country Iso2"]
    for spec in regions.values():
        for component in spec.components:
            columns.append(component.weight_column)
            if component.country_column:
                columns.append(component.country_column)
    available = set(_metadata(screen_path)["schema_columns"])
    frame = _read_columns(screen_path, [column for column in dict.fromkeys(columns) if column in available])
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    latest_date = frame["Date"].max()
    rows: list[dict[str, Any]] = []
    for region_name, spec in regions.items():
        for component in spec.components:
            weight = pd.to_numeric(frame[component.weight_column], errors="coerce").fillna(0.0)
            positive = weight.gt(0)
            allowlist_mask = pd.Series(True, index=frame.index)
            if component.country_allowlist:
                allowlist_mask &= frame[component.country_column].astype("string").isin(
                    list(component.country_allowlist)
                )
            if component.exclude_countries:
                allowlist_mask &= ~frame[component.country_column].astype("string").isin(
                    list(component.exclude_countries)
                )
            retained = positive & allowlist_mask
            latest = frame.loc[frame["Date"].eq(latest_date)]
            latest_weight = pd.to_numeric(latest[component.weight_column], errors="coerce").fillna(0.0)
            latest_positive = latest_weight.gt(0)
            latest_allowlist = pd.Series(True, index=latest.index)
            if component.country_allowlist:
                latest_allowlist &= latest[component.country_column].astype("string").isin(
                    list(component.country_allowlist)
                )
            if component.exclude_countries:
                latest_allowlist &= ~latest[component.country_column].astype("string").isin(
                    list(component.exclude_countries)
                )
            latest_retained = latest_positive & latest_allowlist
            # 先记录 raw coverage，再进行 component 内归一化。
            raw_total = float(latest_weight.loc[latest_positive].sum())
            raw_retained = float(latest_weight.loc[latest_retained].sum())
            normalized_sum = raw_retained / raw_retained if raw_retained > 0 else np.nan
            row: dict[str, Any] = {
                "region": region_name,
                "component": component.name,
                "benchmark": component.benchmark,
                "display_name": spec.display_name,
                "component_aggregation_weight": float(
                    spec.aggregation_weights.get(component.name, np.nan)
                ),
                "currency_basis": spec.currency_basis,
                "minimum_monthly_constituents": int(spec.minimum_monthly_constituents),
                "minimum_weight_coverage": float(spec.minimum_weight_coverage),
                "history_start": spec.history_start,
                "production_eligible": bool(spec.production_eligible),
                "approval_status": spec.approval_status,
                "aliases": "|".join(spec.aliases),
                "weight_column": component.weight_column,
                "country_column": component.country_column,
                "country_allowlist": "|".join(component.country_allowlist),
                "pit_boundary_note": component.pit_boundary_note,
                "research_only": bool(spec.research_only),
                "benchmark_approved": bool(spec.benchmark_approved),
                "component_rule": "positive_weight" if component.positive_weight else "nonzero_weight",
                "raw_positive_rows": int(positive.sum()),
                "raw_positive_date_count": int(frame.loc[positive, "Date"].nunique()),
                "raw_positive_date_min": frame.loc[positive, "Date"].min().date().isoformat()
                if positive.any()
                else None,
                "raw_positive_date_max": frame.loc[positive, "Date"].max().date().isoformat()
                if positive.any()
                else None,
                "latest_date": latest_date.date().isoformat() if pd.notna(latest_date) else None,
                "latest_raw_positive_rows": int(latest_positive.sum()),
                "latest_allowlist_rows": int(latest_retained.sum()),
                "latest_raw_weight_sum": raw_total,
                "latest_raw_retained_weight_sum": raw_retained,
                "latest_raw_retained_coverage_ratio": raw_retained / raw_total if raw_total else np.nan,
                "latest_normalized_component_weight_sum": normalized_sum,
                "normalization_policy": "normalize after raw coverage is recorded",
                "country_filtered_date_count": int(frame.loc[retained, "Date"].nunique()),
                "aggregation_policy": spec.aggregation_policy,
            }
            if component.benchmark == "NIKKEI" and "Exchange Country Iso2" in frame.columns:
                jp_mask = positive & frame["Exchange Country Iso2"].astype("string").eq("JP")
                row["diagnostic_iso2_jp_positive_date_count"] = int(
                    frame.loc[jp_mask, "Date"].nunique()
                )
            rows.append(row)
    return pd.DataFrame(rows)


def build_repository_audit(
    *,
    screen_path: str | Path = SCREEN_AGGREGATE_PATH,
    returns_path: str | Path = RETURNS_PATH,
    definitions_path: str | Path = DEFAULT_FACTOR_DEFINITIONS_PATH,
    regions_path: str | Path = DEFAULT_REGION_UNIVERSES_PATH,
) -> dict[str, Any]:
    package_dir = Path(__file__).resolve().parent
    return {
        "schema_version": "factor_recommendation.repository_audit.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository_root": str(PACKAGE_ROOT),
        "package_dir": str(package_dir),
        "package_files": sorted(path.name for path in package_dir.glob("*.py")),
        "config_files": [str(Path(definitions_path)), str(Path(regions_path))],
        "canonical_inputs": {
            "screen_aggregate": str(Path(screen_path)),
            "returns": str(Path(returns_path)),
        },
        "write_scope": [
            "src/tp_models/factor_recommendation/",
            "16_factor_recommendation_model/config/",
            "16_factor_recommendation_model/audit/",
            "tests/models/factor_recommendation/",
        ],
        "canonical_write_policy": "read_only",
    }


def build_integration_map() -> dict[str, Any]:
    return {
        "schema_version": "factor_recommendation.integration_map.v1",
        "canonical_inputs": {
            "screen": "tp_core.data_sources.SCREEN_AGGREGATE_PATH -> screen_aggregate.parquet",
            "returns": "tp_core.data_sources.RETURNS_PATH -> returns.parquet",
            "screen_key": ["ISIN", "Date"],
            "returns_key": ["Date", "Company SEDOL columns"],
        },
        "modules": {
            "config": "tp_models.factor_recommendation.config",
            "contracts": "tp_models.factor_recommendation.contracts",
            "universe": "tp_models.factor_recommendation.universe",
            "factor_definitions": "tp_models.factor_recommendation.factor_definitions",
            "features": "tp_models.factor_recommendation.features",
            "targets": "tp_models.factor_recommendation.targets",
            "models": "tp_models.factor_recommendation.models",
            "evaluation": "tp_models.factor_recommendation.evaluation",
            "persistence": "tp_models.factor_recommendation.persistence",
            "exporter": "tp_models.factor_recommendation.exporter",
            "sleeve_engine": "tp_models.factor_recommendation.sleeve_engine",
            "audit": "tp_models.factor_recommendation.audit",
            "cli": "tp_models.factor_recommendation.cli",
        },
        "official_sleeve": {
            "adapter_id": "tp_core.backtesting.OfficialPortfolioBacktest",
            "entrypoint": "tp_core.backtesting.OfficialPortfolioBacktest",
            "local_nav_implementation": False,
            "asia_aggregate": "research_only / benchmark_unapproved; component results only",
        },
        "asia_definition": {
            "JAPAN": "NIKKEI positive weight + Exchange Country Iso2 allowlist ['JP'] for the ASIA component; raw NIKKEI coverage remains separately audited",
            "ASIA_EX_JAPAN": "MSCI EM positive weight + fixed ISO2 allowlist CN/HK/IN/KR/TW/SG/MY/TH/ID/PH",
            "component_aggregation_weights": {"JAPAN": 0.5, "ASIA_EX_JAPAN": 0.5},
            "weight_policy": "record raw coverage first; normalize within component only after coverage audit; never adjust aggregate weights",
            "aggregate_status": "research_only / benchmark_unapproved",
        },
    }


def write_audit_artifacts(
    *,
    output_dir: str | Path = DEFAULT_AUDIT_DIR,
    screen_path: str | Path = SCREEN_AGGREGATE_PATH,
    returns_path: str | Path = RETURNS_PATH,
    definitions_path: str | Path = DEFAULT_FACTOR_DEFINITIONS_PATH,
    regions_path: str | Path = DEFAULT_REGION_UNIVERSES_PATH,
) -> dict[str, str]:
    """生成 Prompt 固定的五个审计文件。"""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    definitions = load_factor_definitions(definitions_path)
    regions = load_region_universes(regions_path)
    repository = build_repository_audit(
        screen_path=screen_path,
        returns_path=returns_path,
        definitions_path=definitions_path,
        regions_path=regions_path,
    )
    data = build_data_audit(
        screen_path=screen_path,
        returns_path=returns_path,
        definitions=definitions,
        regions=regions,
    )
    universe = _component_audit_rows(Path(screen_path), regions)
    factor_columns = build_factor_column_audit(Path(screen_path), definitions)
    integration = build_integration_map()
    paths = {
        "repository_audit": str(output / "repository_audit.json"),
        "data_audit": str(output / "data_audit.json"),
        "universe_audit": str(output / "universe_audit.csv"),
        "factor_column_audit": str(output / "factor_column_audit.csv"),
        "integration_map": str(output / "integration_map.json"),
    }
    Path(paths["repository_audit"]).write_text(
        json.dumps(repository, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(paths["data_audit"]).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    universe.to_csv(paths["universe_audit"], index=False, encoding="utf-8-sig")
    factor_columns.to_csv(paths["factor_column_audit"], index=False, encoding="utf-8-sig")
    Path(paths["integration_map"]).write_text(
        json.dumps(integration, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return paths


inspect_repository = write_audit_artifacts


__all__ = [
    "DEFAULT_AUDIT_DIR",
    "build_data_audit",
    "build_factor_column_audit",
    "build_integration_map",
    "build_repository_audit",
    "inspect_repository",
    "write_audit_artifacts",
]

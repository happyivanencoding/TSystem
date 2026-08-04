"""刷新 research-only 月度因子推荐产物。

这个 pipeline step 只写 ``16_factor_recommendation_model/outputs`` 和独立的
factor recommendation signal。它不会进入 ``export_signals``，也不会改写
security candidates、optimizer 或任何生产模型文件。

版本化配置存在时，区域成员资格只来自 canonical screen 的 PIT benchmark
weight；ASIA 明确按照 JAPAN(NIKKEI) + ASIA_EX_JAPAN(MSCI EM allowlist) 的
固定 0.5/0.5 研究定义聚合。旧式 ``factor_columns`` 测试配置保留一个隔离的
兼容分支，不能覆盖生产配置路径。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH, TP_ROOT
from tp_core.io import read_screen_aggregate
from tp_core.signals import validate_signal_frame, write_signal_frame
from tp_core.workspace import SIGNALS_DIR
from tp_models.factor_recommendation.factor_definitions import (
    FactorDefinition,
    compute_factor_scores,
    load_factor_definitions,
)
from tp_models.factor_recommendation.universe import (
    RegionUniverse,
    load_region_universes,
    select_universe,
)

from .common import StepManifest, path_profile
from .configs import RefreshFactorRecommendationConfig


PROJECT_ROOT = TP_ROOT / "16_factor_recommendation_model"
DEFAULT_UNIVERSE_CONFIG = PROJECT_ROOT / "config" / "region_universes_v1.json"
DEFAULT_FACTOR_CONFIG = PROJECT_ROOT / "config" / "factor_definitions_v1.json"
DEFAULT_MODEL_CONFIG = PROJECT_ROOT / "config" / "model_v1.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs"
DEFAULT_PANEL_OUTPUT = DEFAULT_OUTPUT_DIR / "factor_recommendation_panel.parquet"
DEFAULT_HISTORY_OUTPUT = DEFAULT_OUTPUT_DIR / "factor_recommendation_history.parquet"
DEFAULT_SUMMARY_OUTPUT = DEFAULT_OUTPUT_DIR / "factor_recommendation_summary.json"
DEFAULT_VALIDATION_OUTPUT = DEFAULT_OUTPUT_DIR / "factor_recommendation_validation.json"
DEFAULT_PROJECT_MANIFEST_OUTPUT = DEFAULT_OUTPUT_DIR / "factor_recommendation_manifest.json"
DEFAULT_SIGNAL_OUTPUT = SIGNALS_DIR / "factor_recommendation_signals.parquet"
FROZEN_MODEL_DIR = TP_ROOT / "artifacts" / "reports" / "factor_model_archive"

OUTPUT_REGIONS = ("US", "EU", "ASIA", "JAPAN", "GLOBAL")
DEFAULT_LEGACY_FACTOR_COLUMNS = {
    "Value": "Value Avg Percentile",
    "Quality": "Quality Avg Percentile",
    "Momentum": "Mom Avg Percentile",
    "Growth": "Growth Avg Percentile",
    "LowVol": "LowVol Avg Percentile",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if value is pd.NA or value is pd.NaT:
        return None
    return str(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def _file_fingerprint(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not path.exists() or not path.is_file():
        return result
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    result.update({"bytes": path.stat().st_size, "sha256": digest.hexdigest()})
    return result


def _config_value(payload: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return default


def _normalise_region(value: Any) -> str:
    text = "" if value is None else str(value).strip().upper()
    if text in {"EUROPE", "EUR", "EMU"}:
        return "EU"
    if text in {"JP", "JAPAN"}:
        return "JAPAN"
    if text in {"WORLD", "GLOBAL"}:
        return "GLOBAL"
    if text in {"US", "USA", "UNITED STATES", "NORTH AMERICA"}:
        return "US"
    if "ASIA" in text:
        return "ASIA"
    return text or "UNKNOWN"


def _display_region(region: str) -> str:
    return "EU" if str(region).upper() == "EUROPE" else str(region).upper()


def _factor_columns(payload: Mapping[str, Any], frame: pd.DataFrame) -> dict[str, str]:
    """读取旧式测试配置；版本化定义由 ``load_factor_definitions`` 处理。"""

    configured = _config_value(payload, "factor_columns", "factors")
    result: dict[str, str] = {}
    if isinstance(configured, Mapping):
        for name, value in configured.items():
            if isinstance(value, str):
                result[str(name)] = value
            elif isinstance(value, Mapping):
                column = value.get("column") or value.get("source")
                if column:
                    result[str(name)] = str(column)
    elif isinstance(configured, list):
        for value in configured:
            if isinstance(value, str):
                result[value] = value
            elif isinstance(value, Mapping):
                name = value.get("name") or value.get("factor") or value.get("label")
                column = value.get("column") or value.get("source") or name
                if name and column:
                    result[str(name)] = str(column)
    if not result:
        result = dict(DEFAULT_LEGACY_FACTOR_COLUMNS)
    return {name: column for name, column in result.items() if column in frame.columns}


def _legacy_score_0_100(value: Any) -> float | None:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        return None
    value_float = float(number)
    if abs(value_float) <= 1.0:
        value_float *= 100.0
    elif abs(value_float) <= 10.0:
        value_float *= 10.0
    return max(0.0, min(100.0, value_float))


def _recommendation(score_0_100: float | None) -> str:
    if score_0_100 is None:
        return "Unavailable"
    if score_0_100 >= 66.6667:
        return "Positive"
    if score_0_100 <= 33.3333:
        return "Negative"
    return "Neutral"


def _model_version(model_config: Mapping[str, Any], use_frozen_model: bool) -> str:
    configured = _config_value(model_config, "model_version", "version")
    if configured:
        return str(configured)
    return "frozen-factor-model" if use_frozen_model else "factor_recommendation_v1"


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.notna()
    if not valid.any():
        return None
    numeric = numeric.loc[valid].astype(float)
    weight = pd.to_numeric(weights, errors="coerce").reindex(numeric.index).fillna(0.0)
    if float(weight.sum()) <= 0:
        return float(numeric.mean())
    return float(np.average(numeric, weights=weight))


def _history_start(spec: RegionUniverse) -> pd.Timestamp | None:
    if not spec.history_start:
        return None
    return pd.Timestamp(f"{spec.history_start}-01")


def _projection_columns(
    screen_path: Path,
    definitions: Iterable[FactorDefinition],
    regions: Mapping[str, RegionUniverse],
) -> list[str] | None:
    """只读生产刷新需要的 canonical 列，避免复制 301 列。"""

    requested = {"Date", "Exchange Country Iso2"}
    for spec in regions.values():
        for component in spec.components:
            requested.add(component.weight_column)
            if component.country_column:
                requested.add(component.country_column)
    for definition in definitions:
        requested.update(definition.source_columns)
    try:
        import pyarrow.parquet as pq

        available = set(pq.ParquetFile(screen_path).schema.names)
    except Exception:
        return None
    return sorted(column for column in requested if column in available)


def _load_versioned_screen(
    screen_path: Path,
    definitions: Iterable[FactorDefinition],
    regions: Mapping[str, RegionUniverse],
) -> pd.DataFrame:
    columns = _projection_columns(screen_path, definitions, regions)
    screen = read_screen_aggregate(screen_path, columns=columns)
    if screen.index.name == "ISIN" and "ISIN" not in screen.columns:
        screen = screen.reset_index()
    if "ISIN" not in screen.columns:
        raise KeyError("canonical screen must expose ISIN as its index or column")
    return screen


def _aggregate_component_factor(
    selection: pd.DataFrame,
    definition: FactorDefinition,
    spec: RegionUniverse,
) -> tuple[float | None, int, int, float, float, float]:
    """返回 score、covered rows、universe rows、因子覆盖、权重覆盖和组件权重和。"""

    if selection.empty:
        return None, 0, 0, 0.0, 0.0, 0.0
    factor = pd.to_numeric(selection[definition.name], errors="coerce")
    covered = int(factor.notna().sum())
    universe_rows = int(len(selection))
    component_values: list[float] = []
    component_factor_coverage: list[float] = []
    component_weight_coverage: list[float] = []
    present_weight = 0.0
    for component_name, group in selection.groupby("universe_component", sort=False):
        component_weight = pd.to_numeric(group["universe_weight"], errors="coerce").fillna(0.0)
        raw_weight_sum = float(component_weight.clip(lower=0.0).sum())
        valid = pd.to_numeric(group[definition.name], errors="coerce").notna()
        valid_weight_sum = float(component_weight.where(valid, 0.0).clip(lower=0.0).sum())
        component_factor_coverage.append(float(valid.mean()) if len(group) else 0.0)
        component_weight_coverage.append(
            valid_weight_sum / raw_weight_sum if raw_weight_sum > 0 else 0.0
        )
        if valid.any():
            value = _weighted_mean(group[definition.name], component_weight)
            if value is not None:
                fixed_weight = float(spec.aggregation_weights[str(component_name)])
                component_values.append(value * fixed_weight)
                present_weight += fixed_weight
    score = float(sum(component_values)) if component_values else None
    factor_coverage = float(
        sum(
            float(spec.aggregation_weights[str(name)]) * coverage
            for name, coverage in zip(
                selection["universe_component"].drop_duplicates(), component_factor_coverage
            )
        )
    ) if component_factor_coverage else 0.0
    weight_coverage = float(
        sum(
            float(spec.aggregation_weights[str(name)]) * coverage
            for name, coverage in zip(
                selection["universe_component"].drop_duplicates(), component_weight_coverage
            )
        )
    ) if component_weight_coverage else 0.0
    return score, covered, universe_rows, factor_coverage, weight_coverage, present_weight


def _build_versioned_panel(
    frame: pd.DataFrame,
    *,
    as_of: str | None,
    all_history: bool,
    regions: Mapping[str, RegionUniverse],
    definitions: tuple[FactorDefinition, ...],
    model_config: Mapping[str, Any],
    use_frozen_model: bool,
    minimum_coverage: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    data = frame.copy()
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce").dt.normalize()
    data = data.dropna(subset=["Date"])
    if as_of:
        data = data.loc[data["Date"].le(pd.Timestamp(as_of).normalize())].copy()
    if data.empty:
        return pd.DataFrame(), {"reason": "canonical screen 没有可用日期"}
    data = compute_factor_scores(data, definitions)
    available_dates = sorted(pd.Timestamp(value) for value in data["Date"].unique())
    latest_date = available_dates[-1]
    selected_dates = available_dates if all_history else [latest_date]
    model_version = _model_version(model_config, use_frozen_model)
    rows: list[dict[str, Any]] = []
    factor_names = [definition.name for definition in definitions]

    for date, date_frame in data.groupby("Date", sort=True):
        date = pd.Timestamp(date)
        if date not in selected_dates:
            continue
        for region_key, spec in regions.items():
            history_start = _history_start(spec)
            if history_start is not None and date < history_start:
                continue
            selection = select_universe(
                date_frame,
                region_key,
                date=date,
                definitions=regions,
            ).frame
            if selection.empty:
                continue
            for definition in definitions:
                (
                    score,
                    covered,
                    universe_rows,
                    factor_coverage,
                    weight_coverage,
                    present_component_weight,
                ) = _aggregate_component_factor(selection, definition, spec)
                score_0_100 = score * 10.0 if score is not None else None
                factor_coverage_flag = bool(
                    score_0_100 is not None
                    and factor_coverage >= float(minimum_coverage)
                    and weight_coverage >= float(spec.minimum_weight_coverage)
                )
                region = _display_region(region_key)
                benchmark = (
                    spec.components[0].benchmark
                    if len(spec.components) == 1
                    else "ASIA_RESEARCH_UNION"
                )
                rows.append(
                    {
                        "Date": date,
                        "as_of_date": date,
                        "effective_date": date,
                        "horizon": "1M",
                        "region": region,
                        "region_key": region_key,
                        "factor": definition.name,
                        "factor_label": definition.label,
                        "factor_column": ", ".join(definition.source_columns),
                        "score_0_100": score_0_100,
                        "score": score_0_100,
                        "recommendation": _recommendation(score_0_100),
                        "covered": covered,
                        "universe": universe_rows,
                        "factor_coverage": factor_coverage,
                        "weight_coverage": weight_coverage,
                        "coverage": min(factor_coverage, weight_coverage),
                        "coverage_flag": factor_coverage_flag,
                        "component_aggregation_weight_sum": present_component_weight,
                        "n_components": int(selection["universe_component"].nunique()),
                        "benchmark": benchmark,
                        "currency_basis": spec.currency_basis,
                        "production_eligible": spec.production_eligible,
                        "benchmark_approved": spec.benchmark_approved,
                        "approval_status": spec.approval_status,
                        "approved": spec.benchmark_approved and spec.production_eligible,
                        "research_only": True,
                        "model_status": "research_only",
                        "model_version": model_version,
                        "prediction_semantics": "transparent_composite_score; no calibrated probability",
                        "prob_outperform": np.nan,
                        "confidence": (
                            min(factor_coverage, weight_coverage)
                            if score_0_100 is not None
                            else np.nan
                        ),
                    }
                )
    panel = pd.DataFrame(rows)
    if not panel.empty:
        panel = panel.sort_values(
            ["Date", "region", "factor"], kind="stable"
        ).reset_index(drop=True)
    details = {
        "factor_columns": {definition.name: list(definition.source_columns) for definition in definitions},
        "factor_names": factor_names,
        "regions": [_display_region(key) for key in regions],
        "approved_regions": [
            _display_region(key)
            for key, spec in regions.items()
            if spec.production_eligible and spec.benchmark_approved
        ],
        "latest_date": latest_date.date().isoformat(),
        "history_date_min": panel["Date"].min().date().isoformat() if not panel.empty else None,
        "history_date_max": panel["Date"].max().date().isoformat() if not panel.empty else None,
        "model_version": model_version,
        "research_only": True,
        "asia_approved": False,
        "production_effects": {
            "security_candidates": False,
            "optimizer": False,
            "export_signals": False,
        },
    }
    return panel, details


def _legacy_region_series(frame: pd.DataFrame) -> pd.Series:
    for column in (
        "region",
        "Region",
        "Exchange Country Region",
        "universe",
        "market",
    ):
        if column in frame.columns:
            return frame[column].map(_normalise_region)
    return pd.Series("UNKNOWN", index=frame.index, dtype="string")


def _build_legacy_panel(
    frame: pd.DataFrame,
    *,
    as_of: str | None,
    all_history: bool,
    universe_config: Mapping[str, Any],
    factor_config: Mapping[str, Any],
    model_config: Mapping[str, Any],
    use_frozen_model: bool,
    minimum_coverage: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """仅供旧测试配置使用；生产版本化配置不会进入此分支。"""

    data = frame.copy()
    if "Date" not in data.columns:
        raise ValueError("screen 缺少 Date 列")
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce").dt.normalize()
    data = data.dropna(subset=["Date"])
    if as_of:
        data = data.loc[data["Date"].le(pd.Timestamp(as_of).normalize())]
    columns = _factor_columns(factor_config, data)
    if data.empty or not columns:
        return pd.DataFrame(), {"reason": "legacy screen 没有可用日期或因子列"}
    data["_region"] = _legacy_region_series(data)
    approved = {
        _normalise_region(value)
        for value in _config_value(universe_config, "approved_regions", "regions", default=("US", "EU"))
        if value is not False
    }
    dates = sorted(pd.Timestamp(value) for value in data["Date"].unique())
    if not all_history:
        dates = dates[-1:]
    model_version = _model_version(model_config, use_frozen_model)
    rows: list[dict[str, Any]] = []
    for date in dates:
        date_frame = data.loc[data["Date"].eq(date)]
        for region in ("US", "EU", "ASIA"):
            region_frame = date_frame.loc[date_frame["_region"].eq(region)]
            if region_frame.empty:
                continue
            for factor_name, column in columns.items():
                numeric = pd.to_numeric(region_frame[column], errors="coerce")
                valid = numeric.dropna()
                score = _legacy_score_0_100(valid.mean()) if not valid.empty else None
                coverage = float(len(valid) / len(region_frame))
                rows.append(
                    {
                        "Date": date,
                        "as_of_date": date,
                        "effective_date": date,
                        "horizon": "1M",
                        "region": region,
                        "region_key": "EUROPE" if region == "EU" else region,
                        "factor": factor_name.lower(),
                        "factor_label": factor_name,
                        "factor_column": column,
                        "score_0_100": score,
                        "score": score,
                        "recommendation": _recommendation(score),
                        "covered": int(len(valid)),
                        "universe": int(len(region_frame)),
                        "factor_coverage": coverage,
                        "weight_coverage": coverage,
                        "coverage": coverage,
                        "coverage_flag": bool(score is not None and coverage >= minimum_coverage),
                        "component_aggregation_weight_sum": 1.0,
                        "n_components": 1,
                        "benchmark": region,
                        "currency_basis": "legacy_test_config",
                        "production_eligible": region in approved and region != "ASIA",
                        "benchmark_approved": region in approved and region != "ASIA",
                        "approval_status": "approved" if region in approved and region != "ASIA" else "research_only_benchmark_unapproved",
                        "approved": region in approved and region != "ASIA",
                        "research_only": True,
                        "model_status": "research_only",
                        "model_version": model_version,
                        "prediction_semantics": "legacy_test_composite; no calibrated probability",
                        "prob_outperform": np.nan,
                        "confidence": coverage if score is not None else np.nan,
                    }
                )
    panel = pd.DataFrame(rows)
    return panel, {
        "factor_columns": columns,
        "approved_regions": sorted(approved),
        "model_version": model_version,
        "latest_date": panel["Date"].max().date().isoformat() if not panel.empty else None,
        "research_only": True,
        "asia_approved": False,
    }


def _build_signal(panel: pd.DataFrame, minimum_coverage: float) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame(
            columns=[
                "Date",
                "signal_family",
                "signal_name",
                "scope",
                "score",
                "direction",
                "coverage_flag",
                "model_version",
                "source_project",
            ]
        )
    signal = pd.DataFrame(
        {
            "Date": panel["Date"],
            "signal_family": "FactorRecommendation",
            "signal_name": "factor_recommendation_" + panel["factor"].astype(str).str.lower(),
            "scope": "region",
            "score": pd.to_numeric(panel["score_0_100"], errors="coerce"),
            "direction": "higher_is_better",
            "coverage_flag": panel["coverage_flag"].astype(bool),
            "model_version": panel["model_version"],
            "source_project": "16_factor_recommendation_model",
            "region": panel["region"],
            "benchmark": panel["benchmark"],
            "universe": panel["region_key"],
            "score_pct": pd.to_numeric(panel["score_0_100"], errors="coerce") / 100.0,
            "raw_value": panel["recommendation"],
            "as_of_date": panel["as_of_date"],
            "effective_date": panel["effective_date"],
            "horizon": panel["horizon"],
            "confidence": pd.to_numeric(panel["confidence"], errors="coerce"),
            "signal_description": "research-only monthly factor recommendation; not connected to candidates or optimizer",
            "factor": panel["factor"],
            "factor_label": panel["factor_label"],
            "score_0_100": panel["score_0_100"],
            "factor_coverage": panel["factor_coverage"],
            "weight_coverage": panel["weight_coverage"],
            "production_eligible": panel["production_eligible"],
            "benchmark_approved": panel["benchmark_approved"],
            "approval_status": panel["approval_status"],
            "model_status": "research_only",
            "prob_outperform": np.nan,
            "prediction_semantics": panel["prediction_semantics"],
        }
    )
    # Keep the public contract explicit and reject duplicate region/factor rows.
    signal["coverage_flag"] = signal["coverage_flag"] & signal["factor_coverage"].ge(float(minimum_coverage))
    return signal


def _inspect_frame(path: Path) -> tuple[bool, str, int]:
    if not path.exists():
        return False, "missing", 0
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        return False, f"corrupt: {exc}", 0
    return not frame.empty, "ok" if not frame.empty else "empty", int(len(frame))


def _benchmark_definition(
    regions: Mapping[str, RegionUniverse] | None,
) -> dict[str, Any]:
    if not regions:
        return {"status": "legacy_test_config", "asia": "research_only_unapproved"}
    return {
        "status": "versioned_config",
        "regions": {
            _display_region(name): {
                "components": [component.benchmark for component in spec.components],
                "aggregation_weights": dict(spec.aggregation_weights),
                "production_eligible": spec.production_eligible,
                "approval_status": spec.approval_status,
                "currency_basis": spec.currency_basis,
            }
            for name, spec in regions.items()
        },
        "asia": {
            "components": ["JAPAN", "ASIA_EX_JAPAN"],
            "aggregation_weights": {"JAPAN": 0.5, "ASIA_EX_JAPAN": 0.5},
            "status": "research_only_benchmark_unapproved",
        },
    }


def run_refresh_factor_recommendation(args: RefreshFactorRecommendationConfig) -> Path:
    """运行或 inspect 隔离的 factor recommendation research artifact。"""

    parameters = vars(args).copy()
    parameters["research_only"] = True
    parameters["production_effects"] = {
        "security_candidates": False,
        "optimizer": False,
        "export_signals": False,
    }
    manifest = StepManifest("refresh_factor_recommendation", parameters)
    screen_path = Path(getattr(args, "screen", SCREEN_AGGREGATE_PATH))
    returns_path = Path(getattr(args, "returns", RETURNS_PATH))
    universe_config = Path(getattr(args, "universe_config", DEFAULT_UNIVERSE_CONFIG))
    factor_config = Path(getattr(args, "factor_config", DEFAULT_FACTOR_CONFIG))
    model_config = Path(getattr(args, "model_config", DEFAULT_MODEL_CONFIG))
    output_dir = Path(getattr(args, "output_dir", DEFAULT_OUTPUT_DIR))
    signal_output = Path(getattr(args, "signal_output", DEFAULT_SIGNAL_OUTPUT))
    panel_output = output_dir / DEFAULT_PANEL_OUTPUT.name
    history_output = output_dir / DEFAULT_HISTORY_OUTPUT.name
    summary_output = output_dir / DEFAULT_SUMMARY_OUTPUT.name
    validation_output = output_dir / DEFAULT_VALIDATION_OUTPUT.name
    project_manifest_output = output_dir / DEFAULT_PROJECT_MANIFEST_OUTPUT.name

    manifest.inputs = {
        "screen": path_profile(screen_path, parquet=True),
        "returns": path_profile(returns_path, parquet=True),
        "universe_config": path_profile(universe_config),
        "factor_config": path_profile(factor_config),
        "model_config": path_profile(model_config),
        "frozen_model_dir": path_profile(FROZEN_MODEL_DIR),
    }
    manifest.outputs = {
        "panel": path_profile(panel_output, parquet=True),
        "history": path_profile(history_output, parquet=True),
        "summary": path_profile(summary_output),
        "validation": path_profile(validation_output),
        "project_manifest": path_profile(project_manifest_output),
        "signal": path_profile(signal_output, parquet=True),
    }

    try:
        if getattr(args, "inspect_only", False):
            inspected = {}
            for name, path in (
                ("panel", panel_output),
                ("history", history_output),
                ("summary", summary_output),
                ("validation", validation_output),
                ("manifest", project_manifest_output),
                ("signal", signal_output),
            ):
                if path.suffix == ".parquet":
                    exists, state, rows = _inspect_frame(path)
                else:
                    exists, state, rows = path.exists(), "ok" if path.exists() else "missing", 0
                inspected[name] = {"state": state, "rows": rows, "path": str(path)}
                manifest.add_validation(
                    f"{name}_available",
                    exists,
                    f"factor recommendation {name}: {state}",
                    inspected[name],
                )
            manifest.details.update(
                {
                    "research_only": True,
                    "production_effects": parameters["production_effects"],
                    "inspect_only": True,
                    "outputs": inspected,
                    "asia_approved": False,
                }
            )
            return manifest.write("success")

        if not screen_path.exists():
            raise FileNotFoundError(f"screen 不存在: {screen_path}")
        if not returns_path.exists():
            raise FileNotFoundError(f"returns 不存在: {returns_path}")
        universe_payload = _read_json(universe_config)
        factor_payload = _read_json(factor_config)
        model_payload = _read_json(model_config)
        versioned = isinstance(universe_payload.get("regions"), Mapping) and "factor_columns" not in factor_payload
        regions: dict[str, RegionUniverse] | None = None
        if versioned:
            regions = load_region_universes(universe_config)
            definitions = tuple(load_factor_definitions(factor_config))
            screen = _load_versioned_screen(screen_path, definitions, regions)
            full_panel, build_details = _build_versioned_panel(
                screen,
                as_of=getattr(args, "as_of", None),
                all_history=bool(getattr(args, "all_history", False)),
                regions=regions,
                definitions=definitions,
                model_config=model_payload,
                use_frozen_model=bool(getattr(args, "use_frozen_model", False)),
                minimum_coverage=float(getattr(args, "minimum_coverage", 0.5)),
            )
        else:
            screen = pd.read_parquet(screen_path)
            full_panel, build_details = _build_legacy_panel(
                screen,
                as_of=getattr(args, "as_of", None),
                all_history=bool(getattr(args, "all_history", False)),
                universe_config=universe_payload,
                factor_config=factor_payload,
                model_config=model_payload,
                use_frozen_model=bool(getattr(args, "use_frozen_model", False)),
                minimum_coverage=float(getattr(args, "minimum_coverage", 0.5)),
            )
        if full_panel.empty:
            raise ValueError("没有生成任何区域/因子推荐行")

        latest_date = pd.to_datetime(full_panel["Date"], errors="coerce").max()
        history = full_panel.copy()
        # ``--all-history`` is used by research/backfill callers and keeps the
        # panel wide enough for every configured region; the default production
        # refresh exposes only the latest monthly panel.
        panel = (
            full_panel.copy()
            if bool(getattr(args, "all_history", False))
            else full_panel.loc[pd.to_datetime(full_panel["Date"]).eq(latest_date)].copy()
        )
        signal = _build_signal(history, float(getattr(args, "minimum_coverage", 0.5)))
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_parquet(panel, panel_output)
        _write_parquet(history, history_output)
        signal_output.parent.mkdir(parents=True, exist_ok=True)
        write_signal_frame(signal, signal_output, strict=True)

        validation = validate_signal_frame(pd.read_parquet(signal_output), strict=True)
        coverage = pd.to_numeric(history.get("coverage"), errors="coerce").dropna()
        summary = {
            "schema_version": "factor_recommendation.pipeline_outputs.v1",
            "project": "16_factor_recommendation_model",
            "latest_date": latest_date.date().isoformat(),
            "history_date_min": pd.to_datetime(history["Date"]).min().date().isoformat(),
            "history_date_max": pd.to_datetime(history["Date"]).max().date().isoformat(),
            "panel_rows": int(len(panel)),
            "history_rows": int(len(history)),
            "signal_rows": int(len(signal)),
            "regions": sorted(map(str, history["region"].dropna().unique())),
            "factors": sorted(map(str, history["factor"].dropna().unique())),
            "minimum_coverage": float(getattr(args, "minimum_coverage", 0.5)),
            "minimum_observed_coverage": float(coverage.min()) if not coverage.empty else None,
            "research_only": True,
            "production_eligible": False,
            "asia_approved": False,
            "benchmark_definition": _benchmark_definition(regions),
            "data_fingerprint": {
                "screen": _file_fingerprint(screen_path),
                "returns": _file_fingerprint(returns_path),
                "universe_config": _file_fingerprint(universe_config),
                "factor_config": _file_fingerprint(factor_config),
                "model_config": _file_fingerprint(model_config),
            },
        }
        validation_payload = {
            "signal_schema_valid": validation.is_valid,
            "signal_schema_errors": validation.errors,
            "signal_schema_warnings": validation.warnings,
            "duplicate_signal_keys": int(
                pd.read_parquet(signal_output).duplicated(
                    subset=["Date", "signal_family", "signal_name", "scope", "region", "benchmark", "universe", "model_version"],
                    keep=False,
                ).sum()
            ),
            "panel_rows": int(len(panel)),
            "history_rows": int(len(history)),
            "signal_rows": int(len(signal)),
        }
        _write_json(summary_output, summary)
        _write_json(validation_output, validation_payload)
        project_manifest = {
            **summary,
            "status": "success",
            "model_status": "research_only",
            "outputs": {
                "panel": str(panel_output),
                "history": str(history_output),
                "summary": str(summary_output),
                "validation": str(validation_output),
                "signal": str(signal_output),
            },
            "gates": {
                "promotion": "not_promoted",
                "asia_benchmark_approval": "not_approved",
                "forward_shadow": "pending",
            },
        }
        _write_json(project_manifest_output, project_manifest)
        manifest.outputs = {
            "panel": path_profile(panel_output, parquet=True),
            "history": path_profile(history_output, parquet=True),
            "summary": path_profile(summary_output),
            "validation": path_profile(validation_output),
            "project_manifest": path_profile(project_manifest_output),
            "signal": path_profile(signal_output, parquet=True),
        }
        manifest.details.update(
            {
                "research_only": True,
                "production_effects": parameters["production_effects"],
                "asia_approved": False,
                "model_status": "research_only",
                "build": build_details,
                "latest_date": summary["latest_date"],
                "rows": int(len(panel)),
                "history_rows": int(len(history)),
                "signal_rows": int(len(signal)),
                "approved_regions": build_details.get("approved_regions", ["US", "EU"]),
                "benchmark_definition": summary["benchmark_definition"],
                "summary_path": str(summary_output),
                "validation_path": str(validation_output),
                "project_manifest_path": str(project_manifest_output),
                "evidence": [
                    "canonical screen projection and versioned PIT benchmark universe",
                    "strict tp_core.signals.write_signal_frame validation",
                ],
                "backtest": [],
                "baselines": [],
                "gates": [
                    {"name": "production_promotion", "status": "not_promoted"},
                    {"name": "asia_benchmark_approval", "status": "not_approved"},
                    {"name": "forward_shadow_12m", "status": "pending"},
                ],
            }
        )
        manifest.add_validation(
            "panel_written",
            panel_output.exists(),
            "factor recommendation latest panel 已写出",
            {"rows": int(len(panel))},
        )
        manifest.add_validation(
            "history_written",
            history_output.exists(),
            "factor recommendation history 已写出",
            {"rows": int(len(history))},
        )
        manifest.add_validation(
            "strict_signal_schema",
            validation.is_valid and validation_payload["duplicate_signal_keys"] == 0,
            "统一 signal schema strict 校验通过"
            if validation.is_valid and validation_payload["duplicate_signal_keys"] == 0
            else "统一 signal schema strict 校验失败",
            validation_payload,
        )
        manifest.add_validation(
            "research_only_boundary",
            parameters["production_effects"] == {
                "security_candidates": False,
                "optimizer": False,
                "export_signals": False,
            },
            "research-only boundary remains isolated",
            parameters["production_effects"],
        )
        return manifest.write("success")
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新 research-only factor recommendation 产物")
    parser.add_argument("--inspect-only", action="store_true", help="只检查已有 panel/history/signal，不重算")
    parser.add_argument("--as-of", help="只使用该日期之前的 screen 日期")
    parser.add_argument("--screen", default=str(SCREEN_AGGREGATE_PATH))
    parser.add_argument("--returns", default=str(RETURNS_PATH))
    parser.add_argument("--universe-config", default=str(DEFAULT_UNIVERSE_CONFIG))
    parser.add_argument("--factor-config", default=str(DEFAULT_FACTOR_CONFIG))
    parser.add_argument("--model-config", default=str(DEFAULT_MODEL_CONFIG))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--signal-output", default=str(DEFAULT_SIGNAL_OUTPUT))
    parser.add_argument("--all-history", action="store_true", help="写出所有可用日期；默认只写最新日期")
    parser.add_argument("--use-frozen-model", action="store_true", help="使用登记的 frozen factor model 版本")
    parser.add_argument("--minimum-coverage", type=float, default=0.8)
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    manifest_path = run_refresh_factor_recommendation(
        RefreshFactorRecommendationConfig.from_namespace(args)
    )
    print(f"refresh_factor_recommendation manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_FACTOR_CONFIG",
    "DEFAULT_HISTORY_OUTPUT",
    "DEFAULT_MODEL_CONFIG",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_PANEL_OUTPUT",
    "DEFAULT_SIGNAL_OUTPUT",
    "DEFAULT_UNIVERSE_CONFIG",
    "RefreshFactorRecommendationConfig",
    "build_parser",
    "main",
    "run_refresh_factor_recommendation",
]

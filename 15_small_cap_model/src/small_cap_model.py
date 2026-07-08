"""Production model for the MSCI EUR SMALL defensive multifactor score."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

TP_ROOT = Path(__file__).resolve().parents[2]
if str(TP_ROOT) not in sys.path:
    sys.path.insert(0, str(TP_ROOT))

import sitecustomize  # noqa: F401,E402

from tp_core.data_sources import SCREEN_AGGREGATE_PATH  # noqa: E402
from tp_core.signals import standardize_signal_frame, validate_signal_frame, write_signal_frame  # noqa: E402


MODULE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = MODULE_ROOT / "config" / "eu_small_defensive_tilt.json"
DEFAULT_OUTPUT_DIR = MODULE_ROOT / "outputs"
DEFAULT_SIGNAL_OUTPUT = TP_ROOT / "04_signals" / "small_cap_model_signals.parquet"
DATE_COL = "Date"
ISIN_COL = "ISIN"
SEDOL_COL = "Company SEDOL"
NAME_COL = "Name"
MODEL_SCORE_COL = "eu_small_defensive_tilt_score"
MODEL_RANK_COL = "eu_small_defensive_tilt_rank"
MODEL_PCT_COL = "eu_small_defensive_tilt_pct"
MODEL_BUCKET_COL = "eu_small_defensive_tilt_bucket"


def _slugify(text: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]+", "_", text.strip())
    return re.sub(r"_+", "_", value).strip("_").lower() or "item"


def _available_columns(path: Path) -> set[str]:
    return set(pq.ParquetFile(path).schema_arrow.names)


def _load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _winsorize_by_date(values: pd.Series, dates: pd.Series, config: dict[str, Any]) -> pd.Series:
    lower = float(config.get("lower_quantile", 0.01))
    upper = float(config.get("upper_quantile", 0.99))
    min_obs = int(config.get("min_observations", 20))

    def clip_one(group: pd.Series) -> pd.Series:
        valid = group.dropna()
        if len(valid) < min_obs:
            return group
        return group.clip(valid.quantile(lower), valid.quantile(upper))

    return values.groupby(dates, group_keys=False).transform(clip_one)


def _sector_rank_score(values: pd.Series, dates: pd.Series, sectors: pd.Series, scale: float) -> pd.Series:
    frame = pd.DataFrame({"value": values, "Date": dates, "sector": sectors})
    ranked = frame.groupby(["Date", "sector"], observed=True)["value"].rank(pct=True)
    return ranked * scale


def _average_scores(frame: pd.DataFrame, columns: list[str], min_count: int) -> pd.Series:
    present = [column for column in columns if column in frame.columns]
    if not present:
        return pd.Series(np.nan, index=frame.index)
    data = frame[present].apply(pd.to_numeric, errors="coerce")
    return data.mean(axis=1, skipna=True).where(data.notna().sum(axis=1) >= min_count)


def _weighted_scores(frame: pd.DataFrame, weights: dict[str, float], min_count: int) -> pd.Series:
    columns = [column for column in weights if column in frame.columns]
    if not columns:
        return pd.Series(np.nan, index=frame.index)
    data = frame[columns].apply(pd.to_numeric, errors="coerce")
    weight = pd.Series({column: weights[column] for column in columns}, dtype=float)
    valid_weight_sum = data.notna().mul(weight, axis=1).sum(axis=1)
    score = data.mul(weight, axis=1).sum(axis=1) / valid_weight_sum.replace(0, np.nan)
    return score.where(data.notna().sum(axis=1) >= min_count)


def _read_screen(screen_path: Path, config: dict[str, Any]) -> pd.DataFrame:
    columns = _available_columns(screen_path)
    weight_col = str(config["weight_column"])
    sector_col = str(config["sector_column"])
    identity = [
        DATE_COL,
        ISIN_COL,
        SEDOL_COL,
        NAME_COL,
        sector_col,
        weight_col,
        "Benchmark Country English",
        "Exchange Country Region",
        "Benchmark Market Value Millions in EUR",
    ]
    raw_columns = [
        variable["column"]
        for spec in config["subfactors"].values()
        for variable in spec["variables"]
        if variable["column"] in columns
    ]
    read_columns = list(dict.fromkeys([column for column in identity if column in columns] + raw_columns))
    missing = [column for column in [DATE_COL, SEDOL_COL, sector_col, weight_col] if column not in read_columns]
    if missing:
        raise ValueError(f"screen_aggregate 缺少小盘模型必需列: {missing}")

    screen = pd.read_parquet(screen_path, columns=read_columns)
    if ISIN_COL not in screen.columns and screen.index.name == ISIN_COL:
        screen = screen.reset_index()
    if ISIN_COL not in screen.columns and "__index_level_0__" in screen.columns:
        screen = screen.rename(columns={"__index_level_0__": ISIN_COL})
    if ISIN_COL not in screen.columns:
        screen[ISIN_COL] = pd.NA

    screen[DATE_COL] = pd.to_datetime(screen[DATE_COL], errors="coerce")
    screen = screen[pd.to_numeric(screen[weight_col], errors="coerce").fillna(0.0) > 0].copy()
    screen = screen.dropna(subset=[DATE_COL, SEDOL_COL, sector_col]).sort_values([DATE_COL, SEDOL_COL])
    return screen.reset_index(drop=True)


def build_small_cap_scores(
    *,
    screen_path: Path = SCREEN_AGGREGATE_PATH,
    config_path: Path = DEFAULT_CONFIG,
    as_of: str | None = None,
    latest_only: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    config = _load_config(config_path)
    screen = _read_screen(screen_path, config)
    if as_of:
        screen = screen[screen[DATE_COL].le(pd.Timestamp(as_of))].copy()
    if screen.empty:
        raise ValueError("MSCI EUR SMALL universe is empty after filters")

    sector_col = str(config["sector_column"])
    scale = float(config.get("score_scale", 10.0))
    winsor_cfg = dict(config.get("winsorize") or {})
    available_raw: dict[str, list[str]] = {}
    variable_rows: list[dict[str, Any]] = []

    for family, family_spec in config["subfactors"].items():
        score_columns: list[str] = []
        for variable in family_spec["variables"]:
            column = str(variable["column"])
            if column not in screen.columns:
                continue
            direction = float(variable.get("direction", 1.0))
            score_col = f"eu_small_{family}_{_slugify(column)}_score"
            raw = (pd.to_numeric(screen[column], errors="coerce") * direction).replace([np.inf, -np.inf], np.nan)
            clipped = _winsorize_by_date(raw, screen[DATE_COL], winsor_cfg)
            screen[score_col] = _sector_rank_score(clipped, screen[DATE_COL], screen[sector_col], scale)
            score_columns.append(score_col)
            variable_rows.append(
                {
                    "family": family,
                    "column": column,
                    "direction": direction,
                    "score_column": score_col,
                    "coverage": float(screen[column].notna().mean()),
                }
            )
        available_raw[family] = score_columns
        subfactor_col = f"eu_small_{family}_score"
        screen[subfactor_col] = _average_scores(screen, score_columns, int(family_spec.get("min_count", 1)))
        screen[f"eu_small_{family}_valid_variables"] = screen[score_columns].notna().sum(axis=1) if score_columns else 0

    subfactor_weights = {f"eu_small_{family}_score": float(weight) for family, weight in config["final_weights"].items()}
    screen[MODEL_SCORE_COL] = _weighted_scores(screen, subfactor_weights, int(config.get("final_min_count", 1)))
    subfactor_cols = list(subfactor_weights)
    screen["eu_small_valid_subfactors"] = screen[subfactor_cols].notna().sum(axis=1)
    screen[MODEL_RANK_COL] = screen.groupby(DATE_COL, dropna=False)[MODEL_SCORE_COL].rank(ascending=False, method="min")
    screen[MODEL_PCT_COL] = screen.groupby(DATE_COL, dropna=False)[MODEL_SCORE_COL].rank(pct=True)
    coverage_by_date = screen.groupby(DATE_COL, dropna=False)[MODEL_SCORE_COL].transform("count")
    screen[MODEL_BUCKET_COL] = "middle"
    screen.loc[screen[MODEL_RANK_COL].le((coverage_by_date * 0.2).clip(lower=1)), MODEL_BUCKET_COL] = "top_20pct"
    screen.loc[screen[MODEL_PCT_COL].le(0.2), MODEL_BUCKET_COL] = "worst_20pct"

    if latest_only:
        latest_date = screen[DATE_COL].max()
        screen = screen[screen[DATE_COL].eq(latest_date)].copy()

    latest = screen[screen[DATE_COL].eq(screen[DATE_COL].max())].copy()
    diagnostics = {
        "model_version": config["model_version"],
        "benchmark": config["benchmark"],
        "latest_date": latest[DATE_COL].max().date().isoformat(),
        "rows": int(len(screen)),
        "latest_rows": int(len(latest)),
        "latest_coverage": float(latest[MODEL_SCORE_COL].notna().mean()) if len(latest) else 0.0,
        "final_weights": config["final_weights"],
        "available_variables": {family: len(columns) for family, columns in available_raw.items()},
        "variable_coverage": variable_rows,
    }
    return screen, diagnostics


def _make_signal_frame(panel: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    signal = pd.DataFrame(
        {
            "Date": panel[DATE_COL],
            "signal_family": "small_cap_model",
            "signal_name": "eu_small_defensive_tilt",
            "scope": "security",
            "score": panel[MODEL_SCORE_COL],
            "direction": "higher_is_better",
            "coverage_flag": panel[MODEL_SCORE_COL].notna(),
            "model_version": config["model_version"],
            "source_project": "15_small_cap_model",
            "Company SEDOL": panel[SEDOL_COL].astype("string"),
            "ISIN": panel[ISIN_COL].astype("string") if ISIN_COL in panel.columns else pd.NA,
            "region": panel.get("Exchange Country Region", "Europe"),
            "benchmark": config["benchmark"],
            "universe": config["benchmark"],
            "score_pct": panel[MODEL_PCT_COL],
            "raw_value": panel[MODEL_BUCKET_COL],
            "as_of_date": panel[DATE_COL],
            "effective_date": panel[DATE_COL],
            "horizon": "1M",
            "confidence": panel["eu_small_valid_subfactors"] / max(1, len(config["final_weights"])),
            "signal_description": "MSCI EUR SMALL defensive six-style rebuilt multifactor score.",
            "Name": panel.get(NAME_COL, pd.NA),
            "rank": panel[MODEL_RANK_COL],
            "bucket": panel[MODEL_BUCKET_COL],
            "growth_score": panel.get("eu_small_growth_score", pd.NA),
            "value_score": panel.get("eu_small_value_score", pd.NA),
            "quality_score": panel.get("eu_small_quality_score", pd.NA),
            "lowvol_score": panel.get("eu_small_lowvol_score", pd.NA),
            "momentum_score": panel.get("eu_small_momentum_score", pd.NA),
            "dividend_score": panel.get("eu_small_dividend_score", pd.NA),
            "valid_subfactors": panel["eu_small_valid_subfactors"],
            "weight_in_benchmark": panel[config["weight_column"]],
            "sector": panel[config["sector_column"]],
            "country": panel.get("Benchmark Country English", pd.NA),
            "market_value_eur_mn": panel.get("Benchmark Market Value Millions in EUR", pd.NA),
        }
    )
    return standardize_signal_frame(signal)


def _write_outputs(
    panel: pd.DataFrame,
    diagnostics: dict[str, Any],
    *,
    output_dir: Path,
    signal_output: Path,
    config_path: Path,
) -> dict[str, Path]:
    config = _load_config(config_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    panel_output = output_dir / "eu_small_model_scores_latest.parquet"
    summary_output = output_dir / "eu_small_model_summary.json"
    variables_output = output_dir / "eu_small_variable_coverage.csv"
    signal = _make_signal_frame(panel, config)
    validation = validate_signal_frame(signal)
    diagnostics["signal_validation"] = {
        "is_valid": validation.is_valid,
        "errors": validation.errors,
        "warnings": validation.warnings,
    }
    diagnostics["outputs"] = {
        "panel": str(panel_output),
        "summary": str(summary_output),
        "variable_coverage": str(variables_output),
        "signal": str(signal_output),
    }
    panel.to_parquet(panel_output, index=False)
    pd.DataFrame(diagnostics["variable_coverage"]).to_csv(variables_output, index=False, encoding="utf-8-sig")
    summary_output.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_signal_frame(signal, signal_output)
    return {
        "panel": panel_output,
        "summary": summary_output,
        "variable_coverage": variables_output,
        "signal": signal_output,
    }


def export_small_cap_model(
    *,
    screen_path: Path = SCREEN_AGGREGATE_PATH,
    config_path: Path = DEFAULT_CONFIG,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    signal_output: Path = DEFAULT_SIGNAL_OUTPUT,
    as_of: str | None = None,
    latest_only: bool = True,
) -> dict[str, Any]:
    panel, diagnostics = build_small_cap_scores(
        screen_path=screen_path,
        config_path=config_path,
        as_of=as_of,
        latest_only=latest_only,
    )
    outputs = _write_outputs(panel, diagnostics, output_dir=output_dir, signal_output=signal_output, config_path=config_path)
    return {**diagnostics, "output_paths": {name: str(path) for name, path in outputs.items()}}


def inspect_outputs(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    signal_output: Path = DEFAULT_SIGNAL_OUTPUT,
) -> dict[str, Any]:
    summary_path = output_dir / "eu_small_model_summary.json"
    payload: dict[str, Any] = {
        "output_dir": str(output_dir),
        "signal_output": str(signal_output),
        "summary_exists": summary_path.exists(),
        "signal_exists": signal_output.exists(),
    }
    if summary_path.exists():
        payload["summary"] = json.loads(summary_path.read_text(encoding="utf-8"))
    if signal_output.exists():
        signal = pd.read_parquet(signal_output)
        dates = pd.to_datetime(signal["Date"], errors="coerce").dropna()
        payload["signal_rows"] = int(len(signal))
        payload["signal_latest_date"] = dates.max().date().isoformat() if not dates.empty else None
        payload["signal_validation"] = validate_signal_frame(signal).__dict__
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build MSCI EUR SMALL defensive multifactor signal")
    parser.add_argument("--screen", default=str(SCREEN_AGGREGATE_PATH))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--signal-output", default=str(DEFAULT_SIGNAL_OUTPUT))
    parser.add_argument("--as-of")
    parser.add_argument("--all-history", action="store_true")
    parser.add_argument("--inspect-only", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.inspect_only:
        payload = inspect_outputs(output_dir=Path(args.output_dir), signal_output=Path(args.signal_output))
    else:
        payload = export_small_cap_model(
            screen_path=Path(args.screen),
            config_path=Path(args.config),
            output_dir=Path(args.output_dir),
            signal_output=Path(args.signal_output),
            as_of=args.as_of,
            latest_only=not args.all_history,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

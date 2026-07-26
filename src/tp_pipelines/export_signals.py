"""导出所有标准化信号表。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd

from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH, TP_ROOT
from tp_core.signals import validate_signal_frame
from tp_models import country, technical_signals
from tp_models.ml import signals as ml_signals
from tp_models.regime import export_risk_budget

from .common import StepManifest, path_profile, summarize_frame


ML_EXPORTER = Path(ml_signals.__file__)
TECHNICAL_EXPORTER = Path(technical_signals.__file__)
REGIME_EXPORTER = Path(export_risk_budget.__file__)
COUNTRY_EXPORTER = Path(country.__file__)
SIGNALS_DIR = TP_ROOT / "04_signals"


def _signal_details(path: Path) -> dict[str, object]:
    frame = pd.read_parquet(path)
    result = validate_signal_frame(frame)
    dates = pd.to_datetime(frame["Date"], errors="coerce").dropna()
    details = summarize_frame(frame)
    availability: dict[str, object] = {}
    if "technical_available_date" in frame.columns:
        available = pd.to_datetime(frame["technical_available_date"], errors="coerce")
        signal_dates = pd.to_datetime(frame["Date"], errors="coerce")
        availability["technical_available_date_min"] = available.min().date().isoformat() if available.notna().any() else None
        availability["technical_available_date_max"] = available.max().date().isoformat() if available.notna().any() else None
        availability["availability_after_signal_date_rows"] = int((available > signal_dates).sum())
    if "technical_period_end" in frame.columns:
        period_end = pd.to_datetime(frame["technical_period_end"], errors="coerce")
        signal_dates = pd.to_datetime(frame["Date"], errors="coerce")
        availability["technical_period_end_max"] = period_end.max().date().isoformat() if period_end.notna().any() else None
        availability["period_end_after_signal_date_rows"] = int((period_end > signal_dates).sum())
    if "technical_pattern_date" in frame.columns:
        pattern_date = pd.to_datetime(frame["technical_pattern_date"], errors="coerce")
        availability["technical_pattern_date_max"] = pattern_date.max().date().isoformat() if pattern_date.notna().any() else None
    details.update(
        {
            "signal_family": sorted(map(str, frame["signal_family"].dropna().unique())),
            "signal_name_count": int(frame["signal_name"].nunique(dropna=True)),
            "signal_name_sample": sorted(map(str, frame["signal_name"].dropna().unique()))[:30],
            "date_min": dates.min().date().isoformat() if not dates.empty else None,
            "date_max": dates.max().date().isoformat() if not dates.empty else None,
            "availability": availability,
            "validation": {
                "is_valid": result.is_valid,
                "errors": result.errors,
                "warnings": result.warnings,
            },
        }
    )
    return details


def run_export_signals(args: argparse.Namespace) -> Path:
    manifest = StepManifest("export_signals", vars(args).copy())
    manifest.inputs = {
        "screen_aggregate": path_profile(SCREEN_AGGREGATE_PATH, parquet=True),
        "returns": path_profile(Path(getattr(args, "returns", RETURNS_PATH)), parquet=True),
        "ml_exporter": path_profile(ML_EXPORTER),
        "technical_exporter": path_profile(TECHNICAL_EXPORTER),
        "regime_exporter": path_profile(REGIME_EXPORTER),
        "country_exporter": path_profile(COUNTRY_EXPORTER),
        "country_workbook": path_profile(Path(args.country_workbook)),
    }
    outputs: dict[str, Path] = {}
    try:
        if not args.skip_ml:
            outputs["ml_signals"] = ml_signals.export_ml_signals(
                output=Path(args.ml_output),
                latest_only=not args.all_history,
            )
        if not args.skip_technical:
            outputs["technical_signals"] = technical_signals.export_technical_signals(
                patterns_path=Path(args.patterns),
                output=Path(args.technical_output),
                returns_path=Path(getattr(args, "returns", RETURNS_PATH)),
                screen_path=SCREEN_AGGREGATE_PATH,
                latest_only=not args.all_history,
                as_of=args.as_of,
            )
        if not args.skip_regime:
            outputs["regime_risk_budget"] = export_risk_budget.export_risk_budget(
                output=Path(args.regime_output),
                oos=args.regime_oos,
                regions=args.region,
            )
        if not args.skip_country:
            outputs["country_model_signals"] = country.export_country_signals(
                output=Path(args.country_output),
                workbook=Path(args.country_workbook),
                database=Path(args.country_database),
                latest_only=not args.all_history,
            )

        manifest.outputs = {name: path_profile(path, parquet=True) for name, path in outputs.items()}
        for name, path in outputs.items():
            details = _signal_details(path)
            ok = bool(details["validation"]["is_valid"])
            manifest.add_validation(
                f"{name}_schema",
                ok,
                "信号表 schema 通过" if ok else "信号表 schema 失败",
                details,
            )
        manifest.add_validation("at_least_one_signal_output", bool(outputs), "至少生成一张信号表")
        return manifest.write("success")
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导出统一信号表并写 pipeline manifest")
    parser.add_argument("--as-of", help="记录目标日期；当前导出函数按源数据最新可用日期刷新")
    parser.add_argument("--all-history", action="store_true", help="导出全历史；默认每个来源导出最新日期")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    parser.add_argument("--skip-ml", action="store_true", help="跳过 ML 信号")
    parser.add_argument("--skip-technical", action="store_true", help="跳过技术信号")
    parser.add_argument("--skip-regime", action="store_true", help="跳过 Regime 风险预算信号")
    parser.add_argument("--skip-country", action="store_true", help="跳过国家模型信号")
    parser.add_argument("--regime-oos", action="store_true", help="使用 regime_oos 文件")
    parser.add_argument("--region", action="append", choices=["US", "EU"], help="Regime 区域，可重复传入")
    parser.add_argument("--patterns", default=str(TP_ROOT / "03_technical_analysis" / "output" / "patterns.parquet"))
    parser.add_argument("--returns", default=str(RETURNS_PATH))
    parser.add_argument("--ml-output", default=str(SIGNALS_DIR / "ml_signals.parquet"))
    parser.add_argument("--technical-output", default=str(SIGNALS_DIR / "technical_signals.parquet"))
    parser.add_argument("--regime-output", default=str(SIGNALS_DIR / "regime_risk_budget.parquet"))
    parser.add_argument("--country-output", default=str(SIGNALS_DIR / "country_model_signals.parquet"))
    parser.add_argument("--country-workbook", default=str(TP_ROOT / "00_screen" / "production_inputs" / "modele_pays.xlsb"))
    parser.add_argument(
        "--country-database",
        default=str(TP_ROOT / "14_country_model" / "data" / "country_model_database.parquet"),
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest_path = run_export_signals(args)
    print(f"export_signals manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

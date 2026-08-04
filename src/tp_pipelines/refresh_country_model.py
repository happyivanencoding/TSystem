"""重建国家模型数据库、评分面板和标准国家信号。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd

from tp_core.data_sources import TP_ROOT
from tp_core.workspace import SIGNALS_DIR
from tp_models import country

from .common import StepManifest, path_profile
from .configs import RefreshCountryConfig


DEFAULT_WORKBOOK = TP_ROOT / "00_screen" / "production_inputs" / "modele_pays.xlsb"
DEFAULT_DATABASE = TP_ROOT / "14_country_model" / "data" / "country_model_database.parquet"
DEFAULT_OUTPUT_DIR = TP_ROOT / "14_country_model" / "outputs"
DEFAULT_SIGNAL_OUTPUT = SIGNALS_DIR / "country_model_signals.parquet"


def _latest_date(path: Path, column: str = "Date") -> pd.Timestamp | None:
    if not path.exists():
        return None
    dates = pd.to_datetime(pd.read_parquet(path, columns=[column])[column], errors="coerce").dropna()
    return pd.Timestamp(dates.max()).normalize() if not dates.empty else None


def run_refresh_country_model(args: RefreshCountryConfig) -> Path:
    manifest = StepManifest("refresh_country_model", vars(args).copy())
    workbook = Path(args.workbook).resolve()
    database = Path(args.database_output).resolve()
    output_dir = Path(args.output_dir).resolve()
    signal_output = Path(args.signal_output).resolve()
    manifest.inputs = {
        "workbook": path_profile(workbook),
        "country_model": path_profile(Path(country.__file__)),
        "database_previous": path_profile(database, parquet=True),
    }
    try:
        latest_csv = output_dir / "country_model_latest.csv"
        if args.inspect_only:
            latest_dates = (
                pd.to_datetime(
                    pd.read_csv(latest_csv, usecols=["Date"])["Date"], errors="coerce"
                ).dropna()
                if latest_csv.exists()
                else pd.Series(dtype="datetime64[ns]")
            )
            latest = latest_dates.max() if not latest_dates.empty else None
            outputs_exist = latest is not None and signal_output.exists()
            manifest.add_validation(
                "country_outputs_exist",
                outputs_exist,
                "国家模型产物存在" if outputs_exist else "国家模型产物缺失",
                {"latest_date": latest.date().isoformat() if latest is not None else None},
            )
            result: dict[str, object] = {"latest_date": latest.date().isoformat() if latest is not None else None}
        else:
            result = country.run_model(
                workbook_path=workbook,
                database_output=database,
                output_dir=output_dir,
                signal_output=signal_output,
                latest_only=not args.all_history,
                rebuild_database=not args.use_existing_database,
            )
            latest_date = pd.to_datetime(result.get("latest_date"), errors="coerce")
            manifest.add_validation(
                "country_latest_date_available",
                pd.notna(latest_date),
                "国家模型已覆盖最新可用日期" if pd.notna(latest_date) else "国家模型没有可用日期",
                {"latest_date": result.get("latest_date")},
            )
            manifest.add_validation(
                "country_excel_replica_matches",
                result.get("rank_mismatch_count") == 0 and float(result.get("max_abs_score_diff_vs_excel") or 0.0) == 0.0,
                "国家模型与 Excel 结果一致" if result.get("rank_mismatch_count") == 0 else "国家模型与 Excel 结果存在差异",
                {
                    "rank_mismatch_count": result.get("rank_mismatch_count"),
                    "max_abs_score_diff_vs_excel": result.get("max_abs_score_diff_vs_excel"),
                },
            )
        manifest.details["result"] = result
        manifest.outputs = {
            "database": path_profile(database, parquet=True),
            "panel": path_profile(output_dir / "country_model_panel.parquet", parquet=True),
            "latest": path_profile(latest_csv),
            "single_country_latest": path_profile(output_dir / "country_model_single_country_latest.csv"),
            "validation": path_profile(output_dir / "country_model_validation.json"),
            "signal": path_profile(signal_output, parquet=True),
        }
        return manifest.write("success")
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新国家模型数据库和信号")
    parser.add_argument("--workbook", default=str(DEFAULT_WORKBOOK))
    parser.add_argument("--database-output", default=str(DEFAULT_DATABASE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--signal-output", default=str(DEFAULT_SIGNAL_OUTPUT))
    parser.add_argument("--all-history", action="store_true")
    parser.add_argument("--use-existing-database", action="store_true")
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    manifest_path = run_refresh_country_model(RefreshCountryConfig.from_namespace(args))
    print(f"refresh_country_model manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

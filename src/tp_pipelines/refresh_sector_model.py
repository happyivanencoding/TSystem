"""刷新 EU/US 行业评分模型并写 pipeline manifest。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd

from tp_core.data_sources import FACTSET_ICB_MAPPING_PATH, RETURNS_PATH, SCREEN_AGGREGATE_PATH, TP_ROOT
from tp_models.sector import model as sector_model

from .common import StepManifest, path_profile
from .configs import RefreshSectorConfig


DEFAULT_US_OUTPUT_DIR = TP_ROOT / "13_sector_score_model" / "outputs_fs_sector_default"
DEFAULT_EU_OUTPUT_DIR = TP_ROOT / "13_sector_score_model" / "outputs_eu"
DEFAULT_LEGACY_US_OUTPUT_DIR = TP_ROOT / "13_sector_score_model" / "outputs"


def _max_date(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    dates = pd.to_datetime(pd.read_parquet(path, columns=["Date"])["Date"], errors="coerce").dropna()
    return pd.Timestamp(dates.max()).normalize() if not dates.empty else None


def _latest_csv_date(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    dates = pd.to_datetime(pd.read_csv(path, usecols=["Date"])["Date"], errors="coerce").dropna()
    return pd.Timestamp(dates.max()).normalize() if not dates.empty else None


def run_refresh_sector_model(args: RefreshSectorConfig) -> Path:
    manifest = StepManifest("refresh_sector_model", vars(args).copy())
    screen = Path(args.screen).resolve()
    returns = Path(args.returns).resolve()
    mapping = Path(args.mapping).resolve()
    output_dirs = {
        "US": Path(args.us_output_dir).resolve(),
        "EU": Path(args.eu_output_dir).resolve(),
    }
    if args.legacy_us_output_dir:
        output_dirs["US_legacy"] = Path(args.legacy_us_output_dir).resolve()
    manifest.inputs = {
        "screen": path_profile(screen, parquet=True),
        "returns": path_profile(returns, parquet=True),
        "mapping": path_profile(mapping),
        "model": path_profile(Path(sector_model.__file__)),
    }
    try:
        anchor = _max_date(screen)
        results: dict[str, object] = {}
        if args.inspect_only:
            for label, output_dir in output_dirs.items():
                latest_path = output_dir / "sector_scores_latest.csv"
                latest = _latest_csv_date(latest_path)
                manifest.add_validation(
                    f"{label.lower()}_latest_exists",
                    latest is not None,
                    f"{label} 行业最新产物存在" if latest is not None else f"{label} 行业最新产物缺失",
                    {"path": str(latest_path), "latest_date": latest.date().isoformat() if latest is not None else None},
                )
        else:
            for market, output_dir in (("US", output_dirs["US"]), ("EU", output_dirs["EU"])):
                results[market] = sector_model.run_model(
                    screen_path=screen,
                    returns_path=returns,
                    mapping_path=mapping,
                    output_dir=output_dir,
                    start_date=args.start_date,
                    score_column=args.score_column,
                    top_n=args.top_n,
                    bottom_n=args.bottom_n,
                    market=market,
                )
            legacy_result = sector_model.run_model(
                screen_path=screen,
                returns_path=returns,
                mapping_path=mapping,
                output_dir=output_dirs["US_legacy"],
                start_date=args.start_date,
                score_column=args.score_column,
                top_n=args.top_n,
                bottom_n=args.bottom_n,
                market="US",
            ) if "US_legacy" in output_dirs else None
            results["US_legacy"] = legacy_result

        output_dates = {
            label: _latest_csv_date(output_dir / "sector_scores_latest.csv")
            for label, output_dir in output_dirs.items()
        }
        for label, latest in output_dates.items():
            ok = latest is not None and (anchor is None or latest == anchor)
            manifest.add_validation(
                f"{label.lower()}_fresh",
                ok,
                f"{label} 行业模型覆盖最新 Screen 日期" if ok else f"{label} 行业模型日期未覆盖最新 Screen",
                {
                    "anchor_date": anchor.date().isoformat() if anchor is not None else None,
                    "latest_date": latest.date().isoformat() if latest is not None else None,
                },
            )
        manifest.details["result"] = results
        manifest.outputs = {
            f"{label.lower()}_latest": path_profile(output_dir / "sector_scores_latest.csv")
            for label, output_dir in output_dirs.items()
        }
        return manifest.write("success")
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新 EU/US 行业评分模型")
    parser.add_argument("--screen", default=str(SCREEN_AGGREGATE_PATH))
    parser.add_argument("--returns", default=str(RETURNS_PATH))
    parser.add_argument("--mapping", default=str(FACTSET_ICB_MAPPING_PATH))
    parser.add_argument("--us-output-dir", default=str(DEFAULT_US_OUTPUT_DIR))
    parser.add_argument("--eu-output-dir", default=str(DEFAULT_EU_OUTPUT_DIR))
    parser.add_argument("--legacy-us-output-dir", default=str(DEFAULT_LEGACY_US_OUTPUT_DIR))
    parser.add_argument("--start-date", default="2010-01-01")
    parser.add_argument("--score-column", default="score_final")
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--bottom-n", type=int, default=3)
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    manifest_path = run_refresh_sector_model(RefreshSectorConfig.from_namespace(args))
    print(f"refresh_sector_model manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

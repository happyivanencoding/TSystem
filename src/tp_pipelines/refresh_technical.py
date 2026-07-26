"""刷新 technical patterns 生产产物并写 pipeline manifest。"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH, TP_ROOT
from tp_models.technical import Main as technical_main

from .common import StepManifest, path_profile


TECHNICAL_DIR = TP_ROOT / "03_technical_analysis"
TECHNICAL_MAIN = Path(technical_main.__file__)
DEFAULT_PATTERNS = TECHNICAL_DIR / "output" / "patterns.parquet"
TECHNICAL_AVAILABILITY_COLUMNS = [
    "technical_period_start",
    "technical_period_end",
    "technical_available_date",
]


def _max_parquet_date(path: Path, column: str) -> pd.Timestamp | None:
    if not path.exists():
        return None
    frame = pd.read_parquet(path, columns=[column])
    dates = pd.to_datetime(frame[column], errors="coerce").dropna()
    return pd.Timestamp(dates.max()).normalize() if not dates.empty else None


def _date_lag_days(source_date: pd.Timestamp | None, anchor_date: pd.Timestamp | None) -> int | None:
    if source_date is None or anchor_date is None:
        return None
    return int((anchor_date - source_date).days)


def _returns_index(returns_path: Path) -> pd.Index:
    return pd.read_parquet(returns_path, columns=[]).index


def _build_period_availability(returns_index: pd.Index) -> pd.DataFrame:
    dates = pd.DatetimeIndex(pd.to_datetime(returns_index, errors="coerce"))
    dates = pd.DatetimeIndex(dates[~dates.isna()]).sort_values().unique()
    dates = pd.DatetimeIndex(dates)
    if dates.empty:
        return pd.DataFrame(columns=["period_key", *TECHNICAL_AVAILABILITY_COLUMNS])
    calendar = pd.DataFrame({"return_date": dates})
    calendar["period_key"] = calendar["return_date"].dt.strftime("%G-W%V")
    availability = (
        calendar.groupby("period_key", as_index=False)["return_date"]
        .agg(technical_period_start="min", technical_period_end="max")
    )
    ordered_dates = pd.DatetimeIndex(calendar["return_date"])

    def next_trading_day(period_end: pd.Timestamp) -> pd.Timestamp | pd.NaT:
        candidates = ordered_dates[ordered_dates > pd.Timestamp(period_end)]
        return candidates[0] if len(candidates) else pd.NaT

    availability["technical_available_date"] = availability["technical_period_end"].map(next_trading_day)
    return availability


def _read_pattern_dates(path: Path) -> pd.DataFrame:
    try:
        import pyarrow.parquet as pq

        available_columns = set(pq.ParquetFile(path).schema_arrow.names)
    except Exception:
        available_columns = set()
    optional_columns = [column for column in TECHNICAL_AVAILABILITY_COLUMNS if column in available_columns]
    return pd.read_parquet(path, columns=["Date", *optional_columns])


def _availability_frame(path: Path, returns_path: Path) -> pd.DataFrame:
    frame = _read_pattern_dates(path)
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    missing_availability = any(column not in frame.columns for column in TECHNICAL_AVAILABILITY_COLUMNS)
    if missing_availability:
        frame["period_key"] = frame["Date"].dt.strftime("%G-W%V")
        frame = frame.merge(_build_period_availability(_returns_index(returns_path)), on="period_key", how="left")
        frame = frame.drop(columns=["period_key"])
    for column in ["Date", *TECHNICAL_AVAILABILITY_COLUMNS]:
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def _pattern_details(path: Path, *, returns_path: Path, anchor_date: pd.Timestamp | None, max_lag_days: int) -> dict[str, object]:
    pattern_date = _max_parquet_date(path, "Date")
    availability = _availability_frame(path, returns_path)
    available = pd.to_datetime(availability["technical_available_date"], errors="coerce")
    usable = availability[available.notna()].copy()
    if anchor_date is not None:
        usable = usable[pd.to_datetime(usable["technical_available_date"], errors="coerce").le(anchor_date)].copy()
    latest_usable_available = (
        pd.Timestamp(pd.to_datetime(usable["technical_available_date"], errors="coerce").max()).normalize()
        if not usable.empty
        else None
    )
    latest_usable_pattern = (
        pd.Timestamp(usable.loc[pd.to_datetime(usable["technical_available_date"], errors="coerce").eq(latest_usable_available), "Date"].max()).normalize()
        if latest_usable_available is not None
        else None
    )
    lag_days = _date_lag_days(latest_usable_available, anchor_date)
    future_available_rows = (
        int((available > anchor_date).sum())
        if anchor_date is not None and available.notna().any()
        else 0
    )
    return {
        "pattern_date": pattern_date.date().isoformat() if pattern_date is not None else None,
        "latest_usable_pattern_date": latest_usable_pattern.date().isoformat() if latest_usable_pattern is not None else None,
        "latest_usable_available_date": latest_usable_available.date().isoformat() if latest_usable_available is not None else None,
        "raw_available_date_max": available.max().date().isoformat() if available.notna().any() else None,
        "anchor_date": anchor_date.date().isoformat() if anchor_date is not None else None,
        "lag_days": lag_days,
        "max_lag_days": max_lag_days,
        "future_available_rows_vs_anchor": future_available_rows,
        "fresh": lag_days is not None and 0 <= lag_days <= max_lag_days,
    }


def run_refresh_technical(args: argparse.Namespace) -> Path:
    manifest = StepManifest("refresh_technical", vars(args).copy())
    output = Path(args.output)
    max_lag_days = int(args.max_lag_days)
    manifest.inputs = {
        "returns": path_profile(Path(args.returns), parquet=True),
        "screen": path_profile(Path(args.screen), parquet=True),
        "technical_main": path_profile(TECHNICAL_MAIN),
    }
    try:
        if not getattr(args, "inspect_only", False):
            env = os.environ.copy()
            env["TA_RETURNS_PATH"] = str(Path(args.returns))
            env["TA_SCREEN_PATH"] = str(Path(args.screen))
            env["TA_OUTPUT_PATH"] = str(output)
            completed = subprocess.run(
                [sys.executable, "-m", "tp_models.technical.Main"],
                cwd=TECHNICAL_DIR,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                timeout=int(args.timeout_seconds),
                env=env,
            )
            manifest.details["command"] = {
                "returncode": completed.returncode,
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
            }
            if completed.returncode != 0:
                raise RuntimeError(f"technical pattern refresh failed with exit code {completed.returncode}")
        else:
            manifest.add_validation("technical_refresh_skipped", True, "inspect-only 未重算 technical patterns")

        anchor_date = _max_parquet_date(Path(args.screen), "Date")
        details = _pattern_details(output, returns_path=Path(args.returns), anchor_date=anchor_date, max_lag_days=max_lag_days)
        manifest.outputs = {"patterns": path_profile(output, parquet=True)}
        manifest.details["pattern_freshness"] = details
        manifest.add_validation("patterns_exist", output.exists(), "technical patterns 已生成" if output.exists() else "technical patterns 缺失")
        manifest.add_validation(
            "patterns_fresh",
            bool(details["fresh"]),
            "technical patterns 日期在允许窗口内" if details["fresh"] else "technical patterns 日期过旧",
            details,
        )
        return manifest.write("success")
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新 technical patterns 并写 pipeline manifest")
    parser.add_argument("--returns", default=str(RETURNS_PATH), help="canonical returns parquet")
    parser.add_argument("--screen", default=str(SCREEN_AGGREGATE_PATH), help="canonical screen parquet")
    parser.add_argument("--output", default=str(DEFAULT_PATTERNS), help="patterns parquet 输出路径")
    parser.add_argument("--max-lag-days", type=int, default=31, help="patterns 相对 screen 最新月末允许滞后天数")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--inspect-only", action="store_true", help="只检查已有 patterns freshness")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest_path = run_refresh_technical(args)
    print(f"refresh_technical manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

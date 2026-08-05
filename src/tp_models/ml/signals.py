"""导出 ML_Enhanced 的统一信号表。"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from tp_core.data_sources import LAST_SCREEN_PATH, SCREEN_AGGREGATE_PATH
from tp_core.io import read_last_screen, read_screen_aggregate
from tp_core.signals import make_security_signal_frame, write_signal_frame
from tp_core.workspace import SIGNALS_DIR

DEFAULT_OUTPUT = SIGNALS_DIR / "ml_signals.parquet"
DEFAULT_SCORE_COLUMN = "Score ML"


def _read_screen_for_ml(*, latest_only: bool, engine: str | None = None) -> pd.DataFrame:
    columns = [
        "Date",
        "ISIN",
        "Company SEDOL",
        DEFAULT_SCORE_COLUMN,
        "Exchange Country Region",
        "Weight in STOXX EUROPE 600",
        "Weight in SP500",
        "Weight in MSCI WORLD",
    ]
    if latest_only:
        return read_last_screen(LAST_SCREEN_PATH, columns=columns, engine=engine)
    return read_screen_aggregate(SCREEN_AGGREGATE_PATH, columns=columns, engine=engine)


def export_ml_signals(
    *,
    output: Path = DEFAULT_OUTPUT,
    latest_only: bool = True,
    engine: str | None = None,
) -> Path:
    screen = _read_screen_for_ml(latest_only=latest_only, engine=engine)
    screen["Date"] = pd.to_datetime(screen["Date"], errors="coerce")
    scored = screen[screen[DEFAULT_SCORE_COLUMN].notna()].copy()
    if latest_only:
        max_scored_date = scored["Date"].max()
        scored = scored[scored["Date"].eq(max_scored_date)].copy()
    screen = scored

    signals = make_security_signal_frame(
        screen,
        score_column=DEFAULT_SCORE_COLUMN,
        signal_family="ML",
        signal_name="score_ml",
        model_version="ml_enhanced_current",
        source_project="ML_Enhanced",
        direction="higher_is_better",
        horizon="1M",
        signal_description="ML_Enhanced 当前 Score ML 分数",
    )
    if "Exchange Country Region" in screen.columns:
        signals["region"] = screen["Exchange Country Region"].values
    return write_signal_frame(signals, output)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出 ML_Enhanced 统一信号表")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出 parquet 路径")
    parser.add_argument("--all-history", action="store_true", help="导出全历史；默认只导出最新日期")
    args = parser.parse_args(list(argv) if argv is not None else None)
    output = export_ml_signals(output=Path(args.output), latest_only=not args.all_history)
    print(f"ML signals written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

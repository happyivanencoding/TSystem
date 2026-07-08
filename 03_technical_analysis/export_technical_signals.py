"""把 patterns.parquet 导出为统一 technical_signals。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Iterable

import pandas as pd

def _find_tp_root() -> Path:
    current = Path(__file__).resolve().parent
    for candidate in [current, *current.parents]:
        if (candidate / "01_tp_core").exists():
            return candidate
    return current.parent


TP_ROOT = _find_tp_root()
if str(TP_ROOT) not in sys.path:
    sys.path.insert(0, str(TP_ROOT))

import sitecustomize  # noqa: F401

from tp_core.data_sources import RETURNS_PATH as DEFAULT_RETURNS  # noqa: E402
from tp_core.data_sources import SCREEN_AGGREGATE_PATH as DEFAULT_SCREEN  # noqa: E402
from tp_core.signals import make_security_signal_frame, standardize_signal_frame, write_signal_frame  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_PATTERNS = PROJECT_DIR / "output" / "patterns.parquet"
DEFAULT_OUTPUT = TP_ROOT / "04_signals" / "technical_signals.parquet"
STRUCTURE_SCORE = {"HH": 1.0, "HL": 0.5, "LH": -0.5, "LL": -1.0}
BASE_PATTERN_COLUMNS = [
    "Date",
    "Company SEDOL",
    "signal",
    "rsi_14",
    "momentum_10",
    "MACDh_12_26_9",
    "triangle_pattern",
    "wedge_pattern",
    "double_pattern",
]
TECHNICAL_AVAILABILITY_COLUMNS = [
    "technical_period_start",
    "technical_period_end",
    "technical_available_date",
]


def _read_patterns(path: Path) -> pd.DataFrame:
    try:
        import pyarrow.parquet as pq

        available_columns = set(pq.ParquetFile(path).schema_arrow.names)
    except Exception:
        available_columns = set()
    optional_columns = [column for column in TECHNICAL_AVAILABILITY_COLUMNS if column in available_columns]
    return pd.read_parquet(path, columns=[*BASE_PATTERN_COLUMNS, *optional_columns])


def _max_parquet_date(path: Path, column: str) -> pd.Timestamp | None:
    if not path.exists():
        return None
    frame = pd.read_parquet(path, columns=[column])
    dates = pd.to_datetime(frame[column], errors="coerce").dropna()
    return pd.Timestamp(dates.max()).normalize() if not dates.empty else None


def _returns_index(returns_path: Path) -> pd.Index:
    if not returns_path.exists():
        raise FileNotFoundError(f"returns parquet missing: {returns_path}")
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


def _attach_availability(patterns: pd.DataFrame, returns_path: Path) -> pd.DataFrame:
    frame = patterns.copy()
    if "Company SEDOL" not in frame.columns and frame.index.name == "Company SEDOL":
        frame = frame.reset_index()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame["technical_pattern_date"] = frame["Date"]
    missing_availability = any(column not in frame.columns for column in TECHNICAL_AVAILABILITY_COLUMNS)
    if missing_availability:
        frame["period_key"] = frame["Date"].dt.strftime("%G-W%V")
        availability = _build_period_availability(_returns_index(returns_path))
        frame = frame.merge(availability, on="period_key", how="left").drop(columns=["period_key"])
    for column in ["technical_pattern_date", *TECHNICAL_AVAILABILITY_COLUMNS]:
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def _as_of_timestamp(as_of: str | None, screen_path: Path | None) -> pd.Timestamp | None:
    if as_of:
        value = pd.to_datetime(as_of, errors="coerce")
        if pd.isna(value):
            raise ValueError(f"Invalid as_of date: {as_of}")
        return pd.Timestamp(value).normalize()
    if screen_path is None:
        return None
    return _max_parquet_date(screen_path, "Date")


def _select_available_patterns(patterns: pd.DataFrame, *, latest_only: bool, as_of: pd.Timestamp | None) -> pd.DataFrame:
    available = pd.to_datetime(patterns["technical_available_date"], errors="coerce")
    mask = available.notna()
    if as_of is not None:
        mask &= available.le(as_of)
    selected = patterns[mask].copy()
    if selected.empty:
        return selected
    if latest_only:
        latest_available_date = pd.to_datetime(selected["technical_available_date"], errors="coerce").max()
        selected = selected[pd.to_datetime(selected["technical_available_date"], errors="coerce").eq(latest_available_date)].copy()
    return selected


def _with_availability_metadata(signals: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    result = signals.copy()
    result["as_of_date"] = source["technical_pattern_date"].to_numpy()
    result["effective_date"] = source["technical_available_date"].to_numpy()
    result["technical_pattern_date"] = source["technical_pattern_date"].to_numpy()
    result["technical_period_start"] = source["technical_period_start"].to_numpy()
    result["technical_period_end"] = source["technical_period_end"].to_numpy()
    result["technical_available_date"] = source["technical_available_date"].to_numpy()
    return result


def _structure_signal_frame(patterns: pd.DataFrame) -> pd.DataFrame:
    frame = patterns.copy()
    if "Company SEDOL" not in frame.columns and frame.index.name == "Company SEDOL":
        frame = frame.reset_index()
    frame["structure_score"] = frame["signal"].map(STRUCTURE_SCORE)
    frame = frame[frame["structure_score"].notna()].copy()
    result = make_security_signal_frame(
        frame,
        score_column="structure_score",
        raw_value_column="signal",
        signal_family="Technical",
        signal_name="structure_signal",
        model_version="technical_v2_patterns_availability_safe",
        source_project="technical_analysis",
        direction="higher_is_better",
        date_column="technical_available_date",
        horizon="1W",
        signal_description="HH/HL/LH/LL 价格结构标签映射分数",
    )
    return _with_availability_metadata(result, frame)


def _numeric_signal_frame(patterns: pd.DataFrame, column: str, direction: str, description: str) -> pd.DataFrame:
    frame = patterns.copy()
    if column not in frame.columns:
        return pd.DataFrame()
    frame = frame[frame[column].notna()].copy()
    if frame.empty:
        return pd.DataFrame()
    result = make_security_signal_frame(
        frame,
        score_column=column,
        raw_value_column=column,
        signal_family="Technical",
        signal_name=column,
        model_version="technical_v2_patterns_availability_safe",
        source_project="technical_analysis",
        direction=direction,
        date_column="technical_available_date",
        horizon="1W",
        signal_description=description,
    )
    return _with_availability_metadata(result, frame)


def _pattern_presence_frame(patterns: pd.DataFrame, column: str) -> pd.DataFrame:
    frame = patterns.copy()
    if column not in frame.columns:
        return pd.DataFrame()
    if "Company SEDOL" not in frame.columns and frame.index.name == "Company SEDOL":
        frame = frame.reset_index()
    frame = frame[frame[column].notna()].copy()
    if frame.empty:
        return pd.DataFrame()
    frame[f"{column}_presence"] = 1.0
    result = make_security_signal_frame(
        frame,
        score_column=f"{column}_presence",
        raw_value_column=column,
        signal_family="Technical",
        signal_name=column,
        model_version="technical_v2_patterns_availability_safe",
        source_project="technical_analysis",
        direction="binary_positive",
        date_column="technical_available_date",
        horizon="1W",
        signal_description=f"{column} 非空形态出现标记",
    )
    return _with_availability_metadata(result, frame)


def export_technical_signals(
    *,
    patterns_path: Path = DEFAULT_PATTERNS,
    output: Path = DEFAULT_OUTPUT,
    returns_path: Path = DEFAULT_RETURNS,
    screen_path: Path | None = DEFAULT_SCREEN,
    latest_only: bool = True,
    as_of: str | None = None,
) -> Path:
    patterns = _attach_availability(_read_patterns(patterns_path), returns_path)
    patterns = _select_available_patterns(
        patterns,
        latest_only=latest_only,
        as_of=_as_of_timestamp(as_of, screen_path),
    )
    if patterns.empty:
        raise ValueError("No availability-safe technical patterns are available for export")

    parts = [
        _structure_signal_frame(patterns),
        _numeric_signal_frame(patterns, "momentum_10", "higher_is_better", "10 日动量"),
        _numeric_signal_frame(patterns, "MACDh_12_26_9", "higher_is_better", "MACD histogram 12/26/9"),
        _numeric_signal_frame(patterns, "rsi_14", "neutral_midpoint", "RSI 14，50 附近为中性参考"),
        _pattern_presence_frame(patterns, "triangle_pattern"),
        _pattern_presence_frame(patterns, "wedge_pattern"),
        _pattern_presence_frame(patterns, "double_pattern"),
    ]
    signals = pd.concat([part for part in parts if not part.empty], ignore_index=True)
    signals = standardize_signal_frame(signals)
    return write_signal_frame(signals, output)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出技术分析统一信号表")
    parser.add_argument("--patterns", default=str(DEFAULT_PATTERNS), help="patterns.parquet 路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出 parquet 路径")
    parser.add_argument("--returns", default=str(DEFAULT_RETURNS), help="returns.parquet 路径，用于推断周频 availability")
    parser.add_argument("--screen", default=str(DEFAULT_SCREEN), help="screen_aggregate.parquet 路径；默认用最新 screen Date 限制可用信号")
    parser.add_argument("--as-of", help="只导出 technical_available_date <= as-of 的信号；默认用 screen 最新日期")
    parser.add_argument("--all-history", action="store_true", help="导出全历史；默认只导出最新日期")
    args = parser.parse_args(list(argv) if argv is not None else None)
    output = export_technical_signals(
        patterns_path=Path(args.patterns),
        output=Path(args.output),
        returns_path=Path(args.returns),
        screen_path=Path(args.screen) if args.screen else None,
        latest_only=not args.all_history,
        as_of=args.as_of,
    )
    print(f"Technical signals written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

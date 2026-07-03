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

from tp_core.signals import make_security_signal_frame, standardize_signal_frame, write_signal_frame  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_PATTERNS = PROJECT_DIR / "output" / "patterns.parquet"
DEFAULT_OUTPUT = TP_ROOT / "04_signals" / "technical_signals.parquet"
STRUCTURE_SCORE = {"HH": 1.0, "HL": 0.5, "LH": -0.5, "LL": -1.0}


def _read_patterns(path: Path) -> pd.DataFrame:
    columns = [
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
    return pd.read_parquet(path, columns=columns)


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
        model_version="technical_v2_patterns_current",
        source_project="technical_analysis",
        direction="higher_is_better",
        horizon="1W",
        signal_description="HH/HL/LH/LL 价格结构标签映射分数",
    )
    return result


def _numeric_signal_frame(patterns: pd.DataFrame, column: str, direction: str, description: str) -> pd.DataFrame:
    frame = patterns.copy()
    if column not in frame.columns:
        return pd.DataFrame()
    frame = frame[frame[column].notna()].copy()
    if frame.empty:
        return pd.DataFrame()
    return make_security_signal_frame(
        frame,
        score_column=column,
        raw_value_column=column,
        signal_family="Technical",
        signal_name=column,
        model_version="technical_v2_patterns_current",
        source_project="technical_analysis",
        direction=direction,
        horizon="1W",
        signal_description=description,
    )


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
    return make_security_signal_frame(
        frame,
        score_column=f"{column}_presence",
        raw_value_column=column,
        signal_family="Technical",
        signal_name=column,
        model_version="technical_v2_patterns_current",
        source_project="technical_analysis",
        direction="binary_positive",
        horizon="1W",
        signal_description=f"{column} 非空形态出现标记",
    )


def export_technical_signals(*, patterns_path: Path = DEFAULT_PATTERNS, output: Path = DEFAULT_OUTPUT, latest_only: bool = True) -> Path:
    patterns = _read_patterns(patterns_path)
    if latest_only:
        max_date = pd.to_datetime(patterns["Date"], errors="coerce").max()
        patterns = patterns[pd.to_datetime(patterns["Date"], errors="coerce").eq(max_date)].copy()

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
    parser.add_argument("--all-history", action="store_true", help="导出全历史；默认只导出最新日期")
    args = parser.parse_args(list(argv) if argv is not None else None)
    output = export_technical_signals(patterns_path=Path(args.patterns), output=Path(args.output), latest_only=not args.all_history)
    print(f"Technical signals written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

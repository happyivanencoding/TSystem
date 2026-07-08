"""CLI entrypoints for ML_Enhanced.

This file keeps the notebook-era implementation intact and exposes the stable
production actions as commands.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd


ML_ROOT = Path(__file__).resolve().parent
TP_ROOT = ML_ROOT.parent
if str(TP_ROOT) not in sys.path:
    sys.path.insert(0, str(TP_ROOT))
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

import sitecustomize  # noqa: F401,E402

from tp_core.data_sources import SCREEN_AGGREGATE_PATH  # noqa: E402

try:  # pragma: no cover - script fallback
    from .export_signals import DEFAULT_OUTPUT, export_ml_signals
    from .produce_score_ml import DEFAULT_UNIVERSES, produce_score_ml
except ImportError:  # pragma: no cover
    from export_signals import DEFAULT_OUTPUT, export_ml_signals
    from produce_score_ml import DEFAULT_UNIVERSES, produce_score_ml


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _score_ml_status() -> dict[str, object]:
    columns = ["Date", "Score ML"]
    try:
        screen = pd.read_parquet(SCREEN_AGGREGATE_PATH, columns=columns)
    except Exception:
        screen = pd.read_parquet(SCREEN_AGGREGATE_PATH)
        screen = screen[[col for col in columns if col in screen.columns]].copy()
    if "Date" not in screen.columns or "Score ML" not in screen.columns:
        raise KeyError("canonical screen must contain Date and Score ML")
    screen["Date"] = pd.to_datetime(screen["Date"], errors="coerce")
    by_date = screen.groupby("Date")["Score ML"].apply(lambda series: int(series.notna().sum())).sort_index()
    scored = by_date[by_date > 0]
    latest_screen_date = pd.Timestamp(screen["Date"].max()).normalize()
    latest_scored_date = pd.Timestamp(scored.index.max()).normalize() if not scored.empty else None
    missing_after_latest_score = []
    if latest_scored_date is not None:
        missing_after_latest_score = [
            pd.Timestamp(date).date().isoformat()
            for date, non_null in by_date.items()
            if pd.Timestamp(date).normalize() > latest_scored_date and int(non_null) == 0
        ]
    return {
        "screen_path": str(SCREEN_AGGREGATE_PATH),
        "latest_screen_date": latest_screen_date.date().isoformat(),
        "latest_scored_date": latest_scored_date.date().isoformat() if latest_scored_date is not None else None,
        "score_ml_non_null_rows": int(screen["Score ML"].notna().sum()),
        "date_count": int(screen["Date"].nunique(dropna=True)),
        "scored_date_count": int(len(scored)),
        "missing_after_latest_score": missing_after_latest_score,
        "is_current": latest_scored_date == latest_screen_date,
    }


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ML_Enhanced command line tools")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="检查 canonical screen 中 Score ML 覆盖情况")
    inspect.add_argument("--json", action="store_true", help="输出 JSON")

    export = sub.add_parser("export-signals", help="导出 ML 统一信号表")
    export.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出 parquet 路径")
    export.add_argument("--all-history", action="store_true", help="导出全历史；默认只导出最新日期")

    produce = sub.add_parser("produce-score-ml", help="生成并写入缺失的生产 Score ML")
    produce.add_argument("--date", action="append", help="目标月末日期，可重复")
    produce.add_argument("--from-date", help="只处理该日期之后的缺失月份")
    produce.add_argument("--to-date", help="只处理该日期之前的缺失月份")
    produce.add_argument("--universe", action="append", choices=DEFAULT_UNIVERSES, help="Universe，可重复")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "inspect":
        payload = _score_ml_status()
        if args.json:
            _print_json(payload)
        else:
            print(
                "Score ML latest_scored_date="
                f"{payload['latest_scored_date']} latest_screen_date={payload['latest_screen_date']} "
                f"is_current={payload['is_current']}"
            )
        return 0

    if args.command == "export-signals":
        output = export_ml_signals(output=Path(args.output), latest_only=not args.all_history)
        _print_json({"action": "exported", "output": output})
        return 0

    if args.command == "produce-score-ml":
        result = produce_score_ml(
            dates=args.date,
            from_date=args.from_date,
            to_date=args.to_date,
            universes=args.universe or DEFAULT_UNIVERSES,
        )
        _print_json(result)
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


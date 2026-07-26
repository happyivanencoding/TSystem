"""CLI for querying persistent TP experiment run cards."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from .recorder import ExperimentRecorder


def _summary(record: dict[str, object]) -> dict[str, object]:
    hypothesis = record.get("hypothesis") or {}
    run = record.get("run") or {}
    return {
        "hypothesis_id": hypothesis.get("hypothesis_id"),
        "name": hypothesis.get("name"),
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "record_path": record.get("record_path"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="查询 TP Experiment Recorder 的 run cards")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--hypothesis-id")
    parser.add_argument("--status")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--full", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    records = ExperimentRecorder(args.root).query_runs(
        hypothesis_id=args.hypothesis_id,
        status=args.status,
        tags=args.tag,
        limit=args.limit,
    )
    payload = records if args.full else [_summary(record) for record in records]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

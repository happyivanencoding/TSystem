"""CLI for querying persistent TP experiment run cards."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from .governance import PromotionDecisionStore
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
    parser.add_argument(
        "command",
        nargs="?",
        choices=("query", "decisions", "decide"),
        default="query",
        help="query 查询实验；decisions 查看独立决定；decide 创建决定",
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--hypothesis-id")
    parser.add_argument("--experiment-run-id")
    parser.add_argument("--status")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--decision", choices=("approved", "rejected", "revoked"))
    parser.add_argument("--reason")
    parser.add_argument("--decided-by", default="human")
    parser.add_argument("--required-gate", action="append", default=[])
    parser.add_argument("--gate-result", action="append", default=[])
    parser.add_argument("--applicable-scope", default="{}")
    parser.add_argument("--revokes-decision-id")
    return parser


def _gate_results(values: list[str]) -> dict[str, object]:
    results: dict[str, object] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--gate-result 必须使用 gate=value")
        name, result = value.split("=", 1)
        results[name] = result
    return results


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "query":
        records = ExperimentRecorder(args.root).query_runs(
            hypothesis_id=args.hypothesis_id,
            status=args.status,
            tags=args.tag,
            limit=args.limit,
        )
        payload = records if args.full else [_summary(record) for record in records]
    else:
        if not args.experiment_run_id:
            raise SystemExit("--experiment-run-id 是该命令必需的")
        store = PromotionDecisionStore(args.root)
        if args.command == "decisions":
            payload = store.list_decisions(args.experiment_run_id)
        else:
            if not args.decision or not args.reason:
                raise SystemExit("decide 命令需要 --decision 和 --reason")
            try:
                scope = json.loads(args.applicable_scope)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"--applicable-scope 必须是 JSON 对象：{exc}") from exc
            if not isinstance(scope, dict):
                raise SystemExit("--applicable-scope 必须是 JSON 对象")
            record = store.create(
                experiment_run_id=args.experiment_run_id,
                hypothesis_id=args.hypothesis_id,
                decision=args.decision,
                reason=args.reason,
                decided_by=args.decided_by,
                required_gates=args.required_gate,
                gate_results=_gate_results(args.gate_result),
                applicable_scope=scope,
                revokes_decision_id=args.revokes_decision_id,
            )
            payload = record.to_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

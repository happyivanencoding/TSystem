"""CLI for querying persistent TP experiment run cards."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from .governance import ModelReleaseStore, PromotionDecisionStore
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
        choices=(
            "query",
            "decisions",
            "decide",
            "release-create",
            "release-show",
            "release-activate",
            "release-retire",
            "release-revoke",
            "release-current",
        ),
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
    parser.add_argument("--release-root", type=Path)
    parser.add_argument("--model-release-id")
    parser.add_argument("--model-family")
    parser.add_argument("--source-experiment-run-id")
    parser.add_argument("--promotion-decision-id")
    parser.add_argument("--configuration-reference")
    parser.add_argument("--artifact-reference", action="append", default=[])
    parser.add_argument("--component-version", action="append", default=[])
    parser.add_argument("--market", action="append", default=[])
    parser.add_argument("--effective-from")
    parser.add_argument("--effective-to")
    parser.add_argument(
        "--deployment-status",
        choices=("shadow", "approved", "active", "retired", "revoked"),
        default="shadow",
    )
    parser.add_argument("--replacement-release-id")
    return parser


def _gate_results(values: list[str]) -> dict[str, object]:
    results: dict[str, object] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--gate-result 必须使用 gate=value")
        name, result = value.split("=", 1)
        results[name] = result
    return results


def _named_values(values: list[str], option: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option} 必须使用 name=value")
        name, item = value.split("=", 1)
        result[name] = item
    return result


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
    elif args.command in {"decisions", "decide"}:
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
    elif args.command == "release-create":
        required = {
            "--model-family": args.model_family,
            "--hypothesis-id": args.hypothesis_id,
            "--source-experiment-run-id": args.source_experiment_run_id,
            "--configuration-reference": args.configuration_reference,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise SystemExit(f"release-create 缺少参数：{missing}")
        store = ModelReleaseStore(args.root, release_root=args.release_root)
        try:
            release = store.create(
                model_family=args.model_family,
                hypothesis_id=args.hypothesis_id,
                source_experiment_run_id=args.source_experiment_run_id,
                configuration_reference=args.configuration_reference,
                artifact_references=_named_values(args.artifact_reference, "--artifact-reference"),
                component_versions=_named_values(args.component_version, "--component-version"),
                applicable_markets=args.market,
                effective_from=args.effective_from,
                effective_to=args.effective_to,
                deployment_status=args.deployment_status,
                created_by=args.decided_by,
                promotion_decision_id=args.promotion_decision_id,
                replacement_release_id=args.replacement_release_id,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        payload = release.to_dict()
    elif args.command == "release-show":
        if args.model_release_id:
            payload = ModelReleaseStore(args.root, release_root=args.release_root).get(
                args.model_release_id
            )
        else:
            payload = ModelReleaseStore(args.root, release_root=args.release_root).list(
                model_family=args.model_family
            )
    elif args.command in {"release-activate", "release-retire", "release-revoke"}:
        if not args.model_release_id:
            raise SystemExit("该 release 命令需要 --model-release-id")
        if not args.reason:
            raise SystemExit("该 release 命令需要 --reason")
        store = ModelReleaseStore(args.root, release_root=args.release_root)
        try:
            if args.command == "release-activate":
                payload = store.activate(
                    args.model_release_id,
                    changed_by=args.decided_by,
                    reason=args.reason,
                )
            elif args.command == "release-retire":
                payload = store.retire(
                    args.model_release_id,
                    changed_by=args.decided_by,
                    reason=args.reason,
                    replacement_release_id=args.replacement_release_id,
                )
            else:
                payload = store.revoke(
                    args.model_release_id,
                    changed_by=args.decided_by,
                    reason=args.reason,
                )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    elif args.command == "release-current":
        if not args.model_family:
            raise SystemExit("release-current 需要 --model-family")
        payload = ModelReleaseStore(args.root, release_root=args.release_root).current(
            model_family=args.model_family,
            market=args.market[0] if args.market else None,
            as_of=args.effective_from,
        )
    else:  # pragma: no cover - argparse constrains command values
        raise SystemExit(f"unsupported command: {args.command}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

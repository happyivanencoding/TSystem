"""Unified command line for registered TP research."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from tp_research.registry import HypothesisRegistry, run_definition


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="查询、校验并运行配置化 TP 研究")
    parser.add_argument("--registry-root", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="列出 Hypothesis Registry")
    show = subparsers.add_parser("show", help="显示研究定义")
    show.add_argument("hypothesis_id")
    subparsers.add_parser("validate", help="校验全部研究定义")

    run = subparsers.add_parser("run", help="运行一个已注册研究")
    run.add_argument("hypothesis_id")
    run.add_argument("--root", type=Path)
    run.add_argument("--parent-run-id")
    run.add_argument("arguments", nargs=argparse.REMAINDER)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    registry = HypothesisRegistry(args.registry_root)
    if args.command == "list":
        payload = [
            {
                "hypothesis_id": item.hypothesis_id,
                "name": item.payload["name"],
                "status": item.payload["status"],
                "statement": item.payload["statement"],
            }
            for item in registry.list()
        ]
    elif args.command == "show":
        payload = dict(registry.load(args.hypothesis_id).payload)
    elif args.command == "validate":
        definitions = registry.list()
        payload = {"status": "valid", "count": len(definitions)}
    else:
        definition = registry.load(args.hypothesis_id)
        options = {
            "arguments": args.arguments,
            "parent_run_id": args.parent_run_id,
        }
        if args.root is not None:
            options["root"] = args.root
        path = run_definition(definition, **options)
        payload = {"status": "complete", "run_card": str(path.resolve())}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

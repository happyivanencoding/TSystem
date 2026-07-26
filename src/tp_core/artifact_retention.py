"""TP 生成产物的保留策略与安全清理入口。"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import stat
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from tp_core.data_sources import TP_ROOT


@dataclass(frozen=True)
class RetentionRule:
    name: str
    root_pattern: str
    max_age_days: int
    keep_newest: int
    candidate_type: str = "all"
    protected_patterns: tuple[str, ...] = ("README*", "*_latest.*", "latest_*", ".gitkeep")


@dataclass(frozen=True)
class RetentionItem:
    rule: str
    path: str
    age_days: int


RETENTION_RULES = (
    RetentionRule(
        "notebook-executions",
        "artifacts/pipeline_runs/notebook_execution",
        max_age_days=14,
        keep_newest=3,
        candidate_type="directories",
    ),
    RetentionRule(
        "pipeline-manifests",
        "artifacts/pipeline_runs/manifests/*",
        max_age_days=365,
        keep_newest=50,
        candidate_type="files",
    ),
    RetentionRule(
        "experiment-run-cards",
        "artifacts/pipeline_runs/experiments/*",
        max_age_days=730,
        keep_newest=100,
        candidate_type="directories",
    ),
    RetentionRule(
        "screen-backups",
        "00_screen/backups/*",
        max_age_days=365,
        keep_newest=12,
        candidate_type="files",
    ),
    RetentionRule(
        "ad-hoc-backtests",
        "07_backtest_code/runs/ad_hoc",
        max_age_days=180,
        keep_newest=10,
        candidate_type="directories",
    ),
    RetentionRule(
        "news-runs",
        "16_news_market_signal/runs",
        max_age_days=90,
        keep_newest=10,
    ),
    RetentionRule(
        "dashboard-check-outputs",
        "artifacts/dashboard_work/system_checks/outputs",
        max_age_days=30,
        keep_newest=10,
    ),
    RetentionRule(
        "dashboard-launch-records",
        "artifacts/dashboard_work/launches",
        max_age_days=30,
        keep_newest=20,
        candidate_type="files",
    ),
    RetentionRule(
        "scratch-workspaces",
        "artifacts/scratch/codex_tmp",
        max_age_days=90,
        keep_newest=30,
        candidate_type="directories",
    ),
)


def _tracked_paths(workspace: Path) -> set[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=workspace,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return set()
    return {
        item.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        for item in completed.stdout.split(b"\0")
        if item
    }


def _is_tracked(relative_path: str, tracked: set[str]) -> bool:
    prefix = relative_path.rstrip("/") + "/"
    return relative_path in tracked or any(path.startswith(prefix) for path in tracked)


def _resolve_roots(workspace: Path, pattern: str) -> list[Path]:
    if any(char in pattern for char in "*?["):
        return sorted(path for path in workspace.glob(pattern) if path.is_dir())
    root = workspace / pattern
    return [root] if root.is_dir() else []


def _matches_type(path: Path, candidate_type: str) -> bool:
    if candidate_type == "directories":
        return path.is_dir()
    if candidate_type == "files":
        return path.is_file()
    return True


def build_retention_plan(
    workspace: Path = TP_ROOT,
    *,
    now: datetime | None = None,
    rules: Iterable[RetentionRule] = RETENTION_RULES,
    selected_rules: set[str] | None = None,
    tracked: set[str] | None = None,
) -> list[RetentionItem]:
    workspace = workspace.resolve()
    reference_time = now or datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    tracked_paths = tracked if tracked is not None else _tracked_paths(workspace)
    plan: list[RetentionItem] = []

    for rule in rules:
        if selected_rules and rule.name not in selected_rules:
            continue
        cutoff = reference_time - timedelta(days=rule.max_age_days)
        for root in _resolve_roots(workspace, rule.root_pattern):
            candidates = sorted(
                (path for path in root.iterdir() if _matches_type(path, rule.candidate_type)),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for path in candidates[rule.keep_newest:]:
                modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                relative_path = path.relative_to(workspace).as_posix()
                if modified_at >= cutoff:
                    continue
                if any(fnmatch.fnmatch(path.name, pattern) for pattern in rule.protected_patterns):
                    continue
                if _is_tracked(relative_path, tracked_paths):
                    continue
                plan.append(
                    RetentionItem(
                        rule=rule.name,
                        path=relative_path,
                        age_days=(reference_time - modified_at).days,
                    )
                )
    return plan


def apply_retention_plan(plan: Iterable[RetentionItem], workspace: Path = TP_ROOT) -> int:
    workspace = workspace.resolve()
    tracked = _tracked_paths(workspace)
    deleted = 0
    for item in plan:
        target = workspace / item.path
        resolved_target = target.resolve()
        if resolved_target == workspace or not resolved_target.is_relative_to(workspace):
            raise ValueError(f"拒绝删除工作区外路径：{resolved_target}")
        if _is_tracked(item.path, tracked):
            raise ValueError(f"拒绝删除 Git 跟踪路径：{item.path}")
        if not target.exists() and not target.is_symlink():
            continue
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target, onerror=_remove_readonly)
        else:
            try:
                target.unlink()
            except PermissionError:
                os.chmod(target, stat.S_IWRITE)
                target.unlink()
        deleted += 1
    return deleted


def _remove_readonly(function, path: str, _error_info) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按 TP 保留策略预览或清理生成产物")
    parser.add_argument("--apply", action="store_true", help="实际删除；默认仅预览")
    parser.add_argument(
        "--rule",
        action="append",
        choices=[rule.name for rule in RETENTION_RULES],
        help="只运行指定规则；可重复",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    plan = build_retention_plan(selected_rules=set(args.rule or ()))
    deleted = apply_retention_plan(plan) if args.apply else 0
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "eligible_count": len(plan),
                "deleted_count": deleted,
                "items": [asdict(item) for item in plan],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

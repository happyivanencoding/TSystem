from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tp_backtest.runner.artifacts import get_runs_dir
from tp_core.artifact_retention import (
    RetentionItem,
    RetentionRule,
    apply_retention_plan,
    build_retention_plan,
)
from tp_core.workspace import BACKTEST_OUTPUT_RUNS_DIR, HISTORICAL_RESEARCH_RUNS_DIR


def _set_age(path: Path, days: int, now: datetime) -> None:
    timestamp = now.timestamp() - days * 86400
    os.utime(path, (timestamp, timestamp))


def test_new_backtests_do_not_write_to_historical_store() -> None:
    assert get_runs_dir() == BACKTEST_OUTPUT_RUNS_DIR
    assert get_runs_dir() != HISTORICAL_RESEARCH_RUNS_DIR


def test_retention_keeps_newest_and_protects_tracked_paths(tmp_path: Path) -> None:
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    root = tmp_path / "runs"
    root.mkdir()
    for index in range(5):
        candidate = root / f"run_{index}"
        candidate.mkdir()
        _set_age(candidate, 20 + index, now)

    rule = RetentionRule("runs", "runs", max_age_days=14, keep_newest=2, candidate_type="directories")
    plan = build_retention_plan(
        tmp_path,
        now=now,
        rules=(rule,),
        tracked={"runs/run_3/evidence.json"},
    )

    assert [item.path for item in plan] == ["runs/run_2", "runs/run_4"]


def test_apply_retention_plan_deletes_only_planned_targets(tmp_path: Path) -> None:
    target = tmp_path / "runs" / "old"
    target.mkdir(parents=True)
    (target / "result.json").write_text("{}", encoding="utf-8")
    rule = RetentionRule("runs", "runs", max_age_days=0, keep_newest=0, candidate_type="directories")
    future = datetime(2030, 1, 1, tzinfo=timezone.utc)
    plan = build_retention_plan(tmp_path, now=future, rules=(rule,), tracked=set())

    assert apply_retention_plan(plan, tmp_path) == 1
    assert not target.exists()


def test_apply_retention_plan_rejects_paths_outside_workspace(tmp_path: Path) -> None:
    plan = [RetentionItem(rule="unsafe", path="../outside", age_days=999)]

    with pytest.raises(ValueError, match="工作区外"):
        apply_retention_plan(plan, tmp_path)

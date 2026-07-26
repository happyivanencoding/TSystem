from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from presentation_layer.apps.system_backtests import (
    BacktestDashboardContext,
    backtest_perf_metrics,
    backtest_rows,
    latest_backtest_perf_dirs,
    latest_backtest_summaries,
)
from presentation_layer.apps.system_checks import project_checks
from presentation_layer.apps.system_view_models import (
    format_int,
    format_pct,
    relative_path,
    status_label,
)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _format_float(value: Any, digits: int) -> str:
    if value in (None, ""):
        return ""
    return f"{float(value):.{digits}f}"


def _context(
    tmp_path: Path,
    *,
    manifests: dict[str, dict[str, Any]] | None = None,
) -> BacktestDashboardContext:
    manifest_payloads = manifests or {}
    return BacktestDashboardContext(
        run_roots=(tmp_path / "active", tmp_path / "historical"),
        validation_path=tmp_path / "validation.json",
        manifest_dir=tmp_path / "manifests",
        read_json=_read_json,
        latest_manifest=lambda step: manifest_payloads.get(step),
        read_frame=lambda path: pd.read_parquet(path) if path.exists() else None,
        relative_path=lambda path: str(path) if path else "",
        status_label=status_label,
        format_int=format_int,
        format_float=_format_float,
        format_pct=format_pct,
    )


def _write_perf_pair(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    pd.DataFrame(
        {"Date": dates, "Contrib": [100.0, 101.0, 103.0, 102.0]}
    ).to_parquet(run_dir / "perf_ptf.parquet")
    pd.DataFrame(
        {"Date": dates, "Contrib": [100.0, 100.5, 101.0, 101.5]}
    ).to_parquet(run_dir / "perf_bench.parquet")


def test_discovers_latest_summary_and_complete_perf_pair(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    older = context.run_roots[0] / "older" / "summary.json"
    newer = context.run_roots[1] / "newer" / "summary.json"
    for path in (older, newer):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    complete = context.run_roots[0] / "complete"
    incomplete = context.run_roots[1] / "incomplete"
    _write_perf_pair(complete)
    incomplete.mkdir(parents=True)
    pd.DataFrame({"Contrib": [100.0]}).to_parquet(
        incomplete / "perf_ptf.parquet"
    )

    assert latest_backtest_summaries(context, limit=1) == [newer]
    assert latest_backtest_perf_dirs(context) == [complete]


def test_builds_metrics_and_deduplicated_summary_row(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    run_dir = context.run_roots[0] / "run"
    _write_perf_pair(run_dir)
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "benchmark": "MSCI WORLD",
                "objective": "score_weight",
                "selected_names_sec_list": 20,
                "selected_weight_sum": 1.0,
                "top_holdings": [{"Name": "Example"}],
            }
        ),
        encoding="utf-8",
    )

    metrics = backtest_perf_metrics(context, run_dir)
    assert metrics["portfolio"]["date_min"] == "2026-01-01"
    assert metrics["portfolio"]["date_max"] == "2026-01-04"
    assert metrics["tracking_error"] is not None

    rows = backtest_rows(context)
    assert [row["来源"] for row in rows] == ["summary.json"]
    assert rows[0]["Benchmark"] == "MSCI WORLD"
    assert "Example" in rows[0]["报告/路径"]


def test_project_check_registry_uses_current_package_entries() -> None:
    checks = project_checks()
    project_ids = [check.project_id for check in checks]

    assert len(project_ids) == len(set(project_ids))
    assert {"00_screen", "tp_core", "pipelines", "backtests"} <= set(
        project_ids
    )
    command_text = "\n".join(" ".join(check.command) for check in checks)
    assert "07_backtest_code" not in command_text
    assert "01_tp_core" not in command_text
    assert "02_pipelines" not in command_text


def test_relative_path_normalizes_windows_long_path_prefix() -> None:
    root = Path("C:/GoogleDrive/TP")
    long_path = (
        r"\\?\C:\GoogleDrive\TP\artifacts\research\runs\historical"
        r"\summary.json"
    )

    assert relative_path(long_path, root=root) == (
        r"artifacts\research\runs\historical\summary.json"
    )

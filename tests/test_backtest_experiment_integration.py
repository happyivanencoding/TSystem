from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import yaml

from backtest_code.config.settings import AppSettings
from backtest_code.runner.service import BacktestService


def test_failed_backtest_writes_linked_failed_run_card(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "backtest-run"
    run_dir.mkdir()
    monkeypatch.setattr(
        "backtest_code.runner.service.create_run_directory",
        lambda _user, _label: run_dir,
    )
    settings = AppSettings()
    settings.paths.screen = str(tmp_path / "missing-screen.parquet")
    settings.paths.returns = str(tmp_path / "missing-returns.parquet")
    settings.run.bench = "TEST BENCH"
    settings.run.metrics = ["Score"]
    settings.experiment.enabled = True
    settings.experiment.hypothesis_id = "backtest-failure"
    settings.experiment.name = "Backtest failure audit"
    settings.experiment.parent_run_id = "pipeline-parent"
    settings.experiment.root = str(tmp_path / "experiments")

    result = BacktestService().run(settings)

    assert result.latest_run is not None
    assert result.latest_run.status == "failed"
    latest = json.loads(
        (tmp_path / "experiments" / "backtest-failure" / "latest.json").read_text(
            encoding="utf-8"
        )
    )
    record_path = (
        tmp_path
        / "experiments"
        / "backtest-failure"
        / latest["run_id"]
        / "run.json"
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert record["run"]["status"] == "failed"
    assert record["run"]["parent_run_id"] == "pipeline-parent"
    assert record["error"]["type"] == "FileNotFoundError"
    assert manifest["experiment_run_id"] == latest["run_id"]
    assert manifest["experiment_record"] == latest["record_path"]


def test_pipeline_backtest_inherits_parent_experiment_run_id(
    tmp_path, monkeypatch
) -> None:
    from tp_pipelines import orchestration

    captured: list[Namespace] = []
    monkeypatch.setattr(
        orchestration,
        "run_backtest_step",
        lambda args: captured.append(args) or Path(tmp_path / "manifest.json"),
    )
    args = Namespace(
        run_type="production",
        candidates_output="candidates.parquet",
        portfolio_output="weights.parquet",
        report_output="report.md",
        technical_patterns_output="patterns.parquet",
        backtest_profile="default",
        backtest_user=None,
        inspect_only_backtest=False,
        bench="TEST",
        metric=["Score"],
        start_date="2020-01-01",
        percentile=0.2,
        ptf_name="PTF",
        backtest_output_dir=None,
        backtest_max_weight=0.05,
        sector_neutral=True,
        top=True,
        bottom=False,
        batch=False,
        hypothesis_id="pipeline-hypothesis",
        experiment_name="Pipeline experiment",
        effective_trial_count=3,
        experiment_root=str(tmp_path / "experiments"),
    )
    context = orchestration.PipelineContext.from_args(args)
    context.experiment_parent_run_id = "pipeline-parent"

    orchestration._run_backtest(context)

    assert len(captured) == 1
    child = captured[0]
    assert child.record_experiment is True
    assert child.hypothesis_id == "pipeline-hypothesis-backtest"
    assert child.parent_run_id == "pipeline-parent"

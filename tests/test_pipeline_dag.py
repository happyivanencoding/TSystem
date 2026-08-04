from __future__ import annotations

import json
from pathlib import Path

import pytest

from tp_pipelines.common import StepManifest, path_profile
from tp_pipelines.configs import PipelineRunConfig, RefreshDataConfig
from tp_pipelines.dag import PipelineDAG, PipelineStep
from tp_pipelines.orchestration import pipeline_dag
from tp_pipelines.run_all import build_parser


def _noop(_context) -> Path:
    return Path("manifest.json")


def test_cli_namespace_is_adapted_to_typed_step_configs() -> None:
    config = PipelineRunConfig.from_namespace(build_parser().parse_args([]))

    assert isinstance(config.refresh_data, RefreshDataConfig)
    assert config.refresh_data.update_mode == "both"
    assert config.optimize_portfolio.candidates == config.build_candidates.output
    assert config.run_backtest.hypothesis_id == "production-pipeline-backtest"


def test_production_dag_exposes_cross_step_dependencies() -> None:
    dag = pipeline_dag()

    assert dag.dependencies_for("build_candidates") == (
        "export_signals",
        "refresh_small_cap",
        "refresh_sector_model",
    )
    assert dag.dependencies_for("optimize_portfolio") == ("build_candidates",)
    assert dag.names().index("export_signals") < dag.names().index("build_candidates")
    assert dag.names().index("run_backtest") < dag.names().index("generate_report")


def test_pipeline_dag_rejects_cycles() -> None:
    with pytest.raises(ValueError, match="cycle"):
        PipelineDAG(
            (
                PipelineStep("a", ("b",), lambda _context: True, _noop),
                PipelineStep("b", ("a",), lambda _context: True, _noop),
            )
        )


def test_independent_pipeline_step_writes_linked_experiment_card(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "input.parquet"
    source.write_bytes(b"fingerprint")
    output = tmp_path / "output.json"
    output.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "tp_pipelines.common.PIPELINE_MANIFESTS_DIR",
        tmp_path / "manifests",
    )
    experiment_root = tmp_path / "experiments"
    manifest = StepManifest(
        "typed_smoke",
        {
            "run_type": "smoke",
            "as_of": "2025-12-31",
            "experiment_root": str(experiment_root),
            "trial_family": "pipeline-smoke",
        },
    )
    manifest.inputs = {"canonical": path_profile(source)}
    manifest.outputs = {"result": path_profile(output)}

    manifest_path = manifest.write("success")

    latest = json.loads(
        (
            experiment_root
            / "pipeline-typed_smoke"
            / "latest.json"
        ).read_text(encoding="utf-8")
    )
    payload = json.loads(
        (
            experiment_root
            / "pipeline-typed_smoke"
            / latest["run_id"]
            / "run.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest_path.exists()
    assert payload["input_data_fingerprint"]
    assert payload["hypothesis"]["pit_cutoff"] == "2025-12-31"
    assert payload["hypothesis"]["trial_family"] == "pipeline-smoke"
    assert payload["decision"]["reason"]
    assert payload["artifacts"]["step_manifest"]["exists"] is True

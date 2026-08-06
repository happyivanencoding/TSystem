from __future__ import annotations

import json

from tp_experiments import ExperimentRecorder, ExperimentSpec


def test_research_run_has_review_state_and_promotion_lineage(tmp_path) -> None:
    recorder = ExperimentRecorder(tmp_path / "experiments", repo_root=tmp_path)
    run = recorder.start_run(
        ExperimentSpec(
            hypothesis_id="research-kind",
            name="Research kind",
            trial_family="factor-family",
            effective_trial_count=3,
        ),
        run_id="research-1",
        run_kind="research",
    )
    run.log_metrics({"rank_ic": 0.12})
    run.complete()

    payload = json.loads(run.path.read_text(encoding="utf-8"))
    assert payload["run_kind"] == "research"
    assert payload["research_run"]["review_state"] == "review_required"
    assert payload["research_run"]["research_metrics"]["rank_ic"] == 0.12
    assert payload["production_run"] is None
    assert payload["decision"]["status"] == "review_required"


def test_production_run_has_operational_success_not_promotion_wait(tmp_path) -> None:
    recorder = ExperimentRecorder(tmp_path / "experiments", repo_root=tmp_path)
    run = recorder.start_run(
        ExperimentSpec(hypothesis_id="production-kind", name="Production kind"),
        run_id="production-1",
        run_kind="production",
        production_run={
            "production_run_id": "prod-1",
            "data_release_id": "legacy-canonical",
            "model_release_ids": ["mr-approved"],
            "parent_step_manifests": ["refresh_data.json"],
            "write_approval": {"approved": True},
        },
    )
    run.complete()

    payload = json.loads(run.path.read_text(encoding="utf-8"))
    assert payload["run_kind"] == "production"
    assert payload["production_run"]["production_run_id"] == "prod-1"
    assert payload["production_run"]["operational_status"] == "operational_success"
    assert payload["decision"]["status"] == "operational_success"
    assert payload["research_run"] is None

from __future__ import annotations

import pytest

from tp_experiments import (
    ExperimentRecorder,
    ExperimentSpec,
    ModelReleaseStore,
    PromotionDecisionStore,
)


def _completed_run(tmp_path, run_id: str = "release-run") -> str:
    recorder = ExperimentRecorder(tmp_path / "experiments", repo_root=tmp_path)
    run = recorder.start_run(
        ExperimentSpec(hypothesis_id="release-hypothesis", name="Release test"),
        run_id=run_id,
    )
    run.complete()
    return run_id


def _approved_store(tmp_path) -> tuple[ModelReleaseStore, str, str]:
    run_id = _completed_run(tmp_path)
    decisions = PromotionDecisionStore(tmp_path / "experiments")
    decision = decisions.create(
        experiment_run_id=run_id,
        decision="approved",
        reason="registered gates passed",
        decided_by="reviewer",
    )
    store = ModelReleaseStore(
        tmp_path / "experiments",
        release_root=tmp_path / "releases",
    )
    return store, run_id, decision.decision_id


def test_production_release_requires_approved_decision(tmp_path) -> None:
    run_id = _completed_run(tmp_path, "no-approval")
    store = ModelReleaseStore(
        tmp_path / "experiments",
        release_root=tmp_path / "releases",
    )

    with pytest.raises(ValueError, match="promotion_decision_id"):
        store.create(
            model_family="risk-budget",
            hypothesis_id="release-hypothesis",
            source_experiment_run_id=run_id,
            configuration_reference="config/production/risk-budget.json",
            deployment_status="approved",
        )

    shadow = store.create(
        model_family="risk-budget",
        hypothesis_id="release-hypothesis",
        source_experiment_run_id=run_id,
        configuration_reference="config/research/model_candidates/shadow.json",
    )
    with pytest.raises(ValueError, match="not production-usable"):
        store.require_production(shadow.model_release_id)


def test_release_state_transitions_and_current_resolution(tmp_path) -> None:
    store, run_id, decision_id = _approved_store(tmp_path)
    release = store.create(
        model_family="risk-budget",
        hypothesis_id="release-hypothesis",
        source_experiment_run_id=run_id,
        promotion_decision_id=decision_id,
        configuration_reference="config/production/risk-budget.json",
        artifact_references={"model": "artifacts/models/risk-budget.bin"},
        component_versions={"engine": "risk-v1"},
        applicable_markets=("EU",),
        effective_from="2026-08-01",
        deployment_status="approved",
        created_by="reviewer",
    )

    active = store.activate(release.model_release_id, changed_by="ops", reason="deploy")
    assert active["deployment_status"] == "active"
    assert store.current(model_family="risk-budget", market="EU", as_of="2026-08-06")[
        "model_release_id"
    ] == release.model_release_id
    assert len(active["state_history"]) == 2

    retired = store.retire(
        release.model_release_id,
        changed_by="ops",
        reason="superseded",
        replacement_release_id="mr-next",
    )
    assert retired["deployment_status"] == "retired"
    assert store.current(model_family="risk-budget", market="EU") is None


def test_revoked_promotion_blocks_activation(tmp_path) -> None:
    store, run_id, decision_id = _approved_store(tmp_path)
    release = store.create(
        model_family="risk-budget",
        hypothesis_id="release-hypothesis",
        source_experiment_run_id=run_id,
        promotion_decision_id=decision_id,
        configuration_reference="config/production/risk-budget.json",
        deployment_status="approved",
        created_by="reviewer",
    )
    PromotionDecisionStore(tmp_path / "experiments").create(
        experiment_run_id=run_id,
        decision="revoked",
        reason="approval withdrawn",
        decided_by="reviewer",
        revokes_decision_id=decision_id,
    )

    with pytest.raises(ValueError, match="no longer valid"):
        store.activate(release.model_release_id, changed_by="ops", reason="deploy")

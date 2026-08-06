from __future__ import annotations

import json

import pytest

from tp_experiments import ExperimentRecorder, ExperimentSpec, PromotionDecisionStore, cli


def _run(tmp_path, *, run_id: str, status: str = "success") -> tuple[str, object]:
    recorder = ExperimentRecorder(tmp_path / "experiments", repo_root=tmp_path)
    spec = ExperimentSpec(hypothesis_id="promotion-hypothesis", name="Promotion test")
    run = recorder.start_run(spec, run_id=run_id)
    if status == "success":
        run.complete()
    else:
        run.complete(status=status)
    return run_id, run.path


def test_completed_experiment_gets_independent_append_only_approval(tmp_path) -> None:
    run_id, run_path = _run(tmp_path, run_id="run-approved")
    before = run_path.read_text(encoding="utf-8")
    store = PromotionDecisionStore(tmp_path / "experiments")

    decision = store.create(
        experiment_run_id=run_id,
        decision="approved",
        reason="all registered gates passed",
        decided_by="reviewer-1",
        required_gates=("parity", "freshness"),
        gate_results={"parity": True, "freshness": "passed"},
        applicable_scope={"market": "EU"},
    )

    assert decision.decision_id.startswith("pd-")
    assert run_path.read_text(encoding="utf-8") == before
    records = store.list_decisions(run_id)
    assert len(records) == 1
    assert store.resolve(run_id)["decision"] == "approved"


def test_failed_experiment_cannot_be_approved(tmp_path) -> None:
    run_id, _ = _run(tmp_path, run_id="run-failed", status="failed")
    store = PromotionDecisionStore(tmp_path / "experiments")

    with pytest.raises(ValueError, match="successful"):
        store.create(
            experiment_run_id=run_id,
            decision="approved",
            reason="should fail",
            decided_by="reviewer-1",
        )


def test_approval_can_be_revoked_without_mutating_original_decision(tmp_path) -> None:
    run_id, _ = _run(tmp_path, run_id="run-revoked")
    store = PromotionDecisionStore(tmp_path / "experiments")
    approved = store.create(
        experiment_run_id=run_id,
        decision="approved",
        reason="approved for the initial scope",
        decided_by="reviewer-1",
    )
    revoked = store.create(
        experiment_run_id=run_id,
        decision="revoked",
        reason="new evidence invalidated the approval",
        decided_by="reviewer-2",
        revokes_decision_id=approved.decision_id,
    )

    assert revoked.revokes_decision_id == approved.decision_id
    assert store.resolve(run_id)["decision"] == "revoked"
    assert len(store.list_decisions(run_id)) == 2
    original = json.loads(
        (tmp_path / "experiments" / "_governance" / "promotion_decisions" / f"{approved.decision_id}.json").read_text(encoding="utf-8")
    )
    assert original["decision"] == "approved"


def test_cli_creates_and_reads_decision(tmp_path, capsys) -> None:
    run_id, _ = _run(tmp_path, run_id="run-cli")
    exit_code = cli.main(
        [
            "decide",
            "--root",
            str(tmp_path / "experiments"),
            "--experiment-run-id",
            run_id,
            "--decision",
            "approved",
            "--reason",
            "cli approval",
            "--decided-by",
            "cli-user",
        ]
    )
    assert exit_code == 0
    created = json.loads(capsys.readouterr().out)
    assert created["decision"] == "approved"

    cli.main(
        [
            "decisions",
            "--root",
            str(tmp_path / "experiments"),
            "--experiment-run-id",
            run_id,
        ]
    )
    listed = json.loads(capsys.readouterr().out)
    assert [item["decision_id"] for item in listed] == [created["decision_id"]]

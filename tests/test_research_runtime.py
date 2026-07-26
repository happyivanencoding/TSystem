from __future__ import annotations

import json

from tp_research.runtime import recorded_workflow


@recorded_workflow
def _successful_workflow(argv=None) -> int:
    return 0


def test_recorded_workflow_writes_complete_auditable_run_card(
    tmp_path, monkeypatch
) -> None:
    experiment_root = tmp_path / "experiments"
    monkeypatch.setenv("TP_PARENT_EXPERIMENT_RUN_ID", "parent-run")

    result = _successful_workflow(
        [
            "--experiment-root",
            str(experiment_root),
            "--hypothesis-id",
            "runtime-smoke",
            "--trial-family",
            "runtime-family",
            "--effective-trial-count",
            "3",
        ]
    )

    assert result == 0
    latest = json.loads(
        (experiment_root / "runtime-smoke" / "latest.json").read_text(
            encoding="utf-8"
        )
    )
    payload = json.loads(
        (
            experiment_root
            / "runtime-smoke"
            / latest["run_id"]
            / "run.json"
        ).read_text(encoding="utf-8")
    )
    hypothesis = payload["hypothesis"]
    assert payload["run"]["parent_run_id"] == "parent-run"
    assert payload["run"]["status"] == "success"
    assert payload["input_data_fingerprint"]
    assert hypothesis["trial_family"] == "runtime-family"
    assert hypothesis["effective_trial_count"] == 3
    assert set(hypothesis["component_versions"]) == {
        "engine",
        "signal",
        "optimizer",
    }
    assert payload["decision"]["status"] == "review_required"
    assert payload["decision"]["reason"]
    assert payload["artifacts"]["workflow_source"]["exists"] is True

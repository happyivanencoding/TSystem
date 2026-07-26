from __future__ import annotations

import json

import pytest

from tp_experiments import ExperimentRecorder, ExperimentSpec, fingerprint_path


def test_recorder_persists_inputs_metrics_artifacts_and_lineage(tmp_path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("canonical", encoding="utf-8")
    artifact = tmp_path / "result.json"
    artifact.write_text('{"ok": true}', encoding="utf-8")
    recorder = ExperimentRecorder(tmp_path / "experiments", repo_root=tmp_path)
    spec = ExperimentSpec(
        hypothesis_id="raw-value-quality",
        name="Raw value quality gate",
        universe="EU",
        pit_cutoff="2024-12-31",
        effective_trial_count=4,
        component_versions={"engine": "security-nav-v2"},
    )

    with recorder.start_run(
        spec,
        parameters={"top_pct": 0.1},
        parent_run_id="parent-1",
        run_id="run-1",
        config={"metric": "value"},
    ) as run:
        run.log_inputs({"screen": source}, hash_content=True)
        run.log_metrics({"robust_score": 0.75})
        run.log_provenance({"provider": "canonical"})
        run.log_artifacts({"summary": artifact})
        run.set_decision("promote", reason="all gates passed")

    payload = json.loads(run.path.read_text(encoding="utf-8"))
    assert payload["run"]["status"] == "success"
    assert payload["run"]["parent_run_id"] == "parent-1"
    assert payload["inputs"]["screen"]["sha256"]
    assert payload["metrics"]["robust_score"] == pytest.approx(0.75)
    assert payload["artifacts"]["summary"]["exists"] is True
    assert payload["decision"]["status"] == "promote"
    assert payload["schema_version"] == 3
    assert payload["config"]["fingerprint"]
    assert payload["provenance"]["provider"] == "canonical"
    assert payload["record_fingerprint"]
    assert not run.path.with_suffix(".json.tmp").exists()


def test_recorder_context_captures_failure(tmp_path) -> None:
    recorder = ExperimentRecorder(tmp_path / "experiments", repo_root=tmp_path)
    spec = ExperimentSpec(hypothesis_id="failure-case", name="Failure capture")

    with pytest.raises(ValueError, match="broken"):
        with recorder.start_run(spec, run_id="run-failed") as run:
            raise ValueError("broken")

    payload = json.loads(run.path.read_text(encoding="utf-8"))
    assert payload["run"]["status"] == "failed"
    assert payload["error"] == {"type": "ValueError", "message": "broken"}


def test_fingerprint_changes_with_file_content(tmp_path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("first", encoding="utf-8")
    first = fingerprint_path(source, hash_content=True)
    source.write_text("second", encoding="utf-8")
    second = fingerprint_path(source, hash_content=True)

    assert first["sha256"] != second["sha256"]
    assert first["fingerprint"] != second["fingerprint"]


def test_hypothesis_id_cannot_escape_recorder_root() -> None:
    with pytest.raises(ValueError, match="hypothesis_id"):
        ExperimentSpec(hypothesis_id="../outside", name="Unsafe path")


def test_run_id_and_parent_id_cannot_escape_recorder_root(tmp_path) -> None:
    recorder = ExperimentRecorder(tmp_path / "experiments", repo_root=tmp_path)
    spec = ExperimentSpec(hypothesis_id="safe", name="Safe")

    with pytest.raises(ValueError, match="run_id"):
        recorder.start_run(spec, run_id="../outside")
    with pytest.raises(ValueError, match="parent_run_id"):
        recorder.start_run(spec, parent_run_id="../outside")


def test_recorder_queries_runs_and_writes_latest_pointer(tmp_path) -> None:
    recorder = ExperimentRecorder(tmp_path / "experiments", repo_root=tmp_path)
    spec = ExperimentSpec(
        hypothesis_id="queryable",
        name="Queryable",
        tags=("factor", "eu"),
    )
    recorder.start_run(spec, run_id="run-1").complete()
    failed = recorder.start_run(spec, run_id="run-2")
    failed.fail(RuntimeError("no data"))

    matches = recorder.query_runs(
        hypothesis_id="queryable",
        status="failed",
        tags=("factor",),
    )
    assert [record["run"]["run_id"] for record in matches] == ["run-2"]
    assert recorder.latest_run("queryable")["run"]["run_id"] == "run-2"
    latest = json.loads(
        (tmp_path / "experiments" / "queryable" / "latest.json").read_text(encoding="utf-8")
    )
    assert latest["run_id"] == "run-2"
    assert latest["status"] == "failed"

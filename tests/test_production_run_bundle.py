from __future__ import annotations

import json
from pathlib import Path

import pytest

from tp_pipelines import orchestration
from tp_pipelines.lineage import ProductionRunBundle
from tp_pipelines.run_all import build_parser


def _manifest(path: Path, *, production_run_id: str, as_of: str = "2026-08-01") -> None:
    path.write_text(
        json.dumps(
            {
                "step": path.stem,
                "run_type": "production",
                "production_run_id": production_run_id,
                "parameters": {"run_type": "production", "as_of": as_of},
                "outputs": {},
            }
        ),
        encoding="utf-8",
    )


def test_bundle_contains_releases_parents_outputs_and_step_states(tmp_path) -> None:
    child = tmp_path / "refresh_data.json"
    _manifest(child, production_run_id="prod-1")
    bundle = ProductionRunBundle.start(
        run_type="production",
        as_of_date="2026-08-01",
        input_month="202608",
        data_release_id="screen-v1|returns-v1",
        catalog_release_id="catalog-v1",
        model_release_ids=("mr-approved",),
        production_run_id="prod-1",
    )
    bundle.record_manifest("refresh_data", child)
    bundle.mark("build_candidates", "blocked_by_dependency")
    path = bundle.finish("failed", bundle_root=tmp_path / "bundles")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["production_run_id"] == "prod-1"
    assert payload["data_release_id"] == "screen-v1|returns-v1"
    assert payload["model_release_ids"] == ["mr-approved"]
    assert payload["child_manifests"]["refresh_data"] == str(child)
    assert payload["step_states"]["build_candidates"] == "blocked_by_dependency"
    assert payload["retention_class"] == "recent_operational"


def test_bundle_rejects_a_child_manifest_from_another_production_run(tmp_path) -> None:
    child = tmp_path / "refresh_data.json"
    _manifest(child, production_run_id="prod-other")
    bundle = ProductionRunBundle.start(
        run_type="production",
        as_of_date="2026-08-01",
        input_month="202608",
        data_release_id="screen-v1|returns-v1",
        catalog_release_id=None,
        production_run_id="prod-current",
    )

    with pytest.raises(ValueError, match="production_run_id mismatch"):
        bundle.record_manifest("refresh_data", child)


def test_failed_dependency_blocks_downstream(monkeypatch) -> None:
    args = build_parser().parse_args([])
    context = orchestration.PipelineContext.from_args(args)
    executed: list[str] = []

    def failed(_context):
        executed.append("refresh_data")
        raise RuntimeError("refresh failed")

    def should_not_run(_context):
        executed.append("refresh_sector_model")
        return Path("sector.json")

    monkeypatch.setattr(orchestration, "_refresh_data", failed)
    monkeypatch.setattr(orchestration, "_refresh_sector_model", should_not_run)
    monkeypatch.setattr(
        orchestration,
        "pipeline_dag",
        lambda: orchestration.PipelineDAG(
            (
                orchestration.PipelineStep(
                    "refresh_data", (), lambda _context: True, orchestration._refresh_data
                ),
                orchestration.PipelineStep(
                    "refresh_sector_model",
                    ("refresh_data",),
                    lambda _context: True,
                    orchestration._refresh_sector_model,
                ),
            )
        ),
    )

    with pytest.raises(RuntimeError, match="refresh failed"):
        orchestration.execute_pipeline_steps(context)

    assert executed == ["refresh_data"]
    assert context.step_states == {
        "refresh_data": "failed",
        "refresh_sector_model": "blocked_by_dependency",
    }


def test_skipped_dependency_requires_explicit_reuse(monkeypatch, tmp_path) -> None:
    reused_output = tmp_path / "reused.parquet"
    reused_output.write_bytes(b"fixture")
    old_manifest = tmp_path / "old_refresh_data.json"
    old_manifest.write_text(
        json.dumps(
            {
                "step": "refresh_data",
                "run_type": "production",
                "production_run_id": "prod-old",
                "parameters": {"run_type": "production", "as_of": "2026-08-01"},
                "outputs": {"canonical": {"path": str(reused_output)}},
            }
        ),
        encoding="utf-8",
    )
    reuse_map = tmp_path / "reuse.json"
    reuse_map.write_text(
        json.dumps({"refresh_data": {"manifest": str(old_manifest), "reason": "approved reuse"}}),
        encoding="utf-8",
    )
    args = build_parser().parse_args(
        [
            "--as-of",
            "2026-08-01",
            "--skip-refresh-data",
            "--reuse-manifest",
            str(reuse_map),
            "--skip-refresh-sector",
            "--skip-refresh-country-model",
            "--skip-refresh-technical",
            "--skip-export-signals",
            "--skip-refresh-small-cap",
            "--skip-build-candidates",
            "--skip-optimize-portfolio",
            "--skip-backtest",
            "--skip-report",
        ]
    )
    context = orchestration.PipelineContext.from_args(args)
    monkeypatch.setattr(
        orchestration,
        "pipeline_dag",
        lambda: orchestration.PipelineDAG(
            (
                orchestration.PipelineStep(
                    "refresh_data", (), lambda _context: False, orchestration._refresh_data
                ),
                orchestration.PipelineStep(
                    "refresh_sector_model",
                    ("refresh_data",),
                    lambda _context: False,
                    orchestration._refresh_sector_model,
                ),
            )
        ),
    )

    orchestration.execute_pipeline_steps(context)

    assert context.step_states["refresh_data"] == "explicitly_reused"
    assert context.step_manifests["refresh_data"] == str(old_manifest.resolve())
    assert context.step_states["refresh_sector_model"] == "disabled"

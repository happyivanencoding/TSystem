from __future__ import annotations

import json
from pathlib import Path

from test_io_engine import _fixture_release

from tp_core.analytics.authority import (
    activate_catalog_release,
    check_authority_readiness,
    rollback_catalog_release,
)
from tp_core.analytics.catalog import build_catalog_release
from tp_core.analytics.config import DuckDBConfig


def _authority_fixture(tmp_path: Path) -> tuple[Path, str, Path]:
    database, _, _ = _fixture_release(tmp_path)
    artifact_root = tmp_path / "artifacts"
    config = DuckDBConfig(
        database_path=database,
        temp_directory=artifact_root / "analytics" / "duckdb" / "temp-authority",
        data_root=tmp_path,
        artifact_root=artifact_root,
        latest_pointer=artifact_root / "analytics" / "duckdb" / "latest.json",
    )
    summary = build_catalog_release(
        config,
        release_id="authority-fixture",
        screen_manifest_path=tmp_path / "00_screen" / "datasets" / "manifests" / "screen" / "current.json",
        returns_manifest_path=tmp_path / "00_screen" / "datasets" / "manifests" / "returns_wide" / "current.json",
        refresh_marts=True,
    )
    evidence = artifact_root / "analytics" / "duckdb" / "authority_evidence.json"
    return Path(str(summary["database_path"])), "authority-fixture", evidence


def _write_evidence(path: Path, release_id: str, *, complete_chain: bool, cycles: list[dict[str, str]], approval: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "tp.duckdb-authority-evidence.v1",
                "release_id": release_id,
                "full_real_data_parity": True,
                "complete_production_chain_parity": complete_chain,
                "rollback_drill": True,
                "monthly_cycles": cycles,
                "external_approval": approval,
            }
        ),
        encoding="utf-8",
    )


def test_authority_switch_is_blocked_without_required_evidence(tmp_path: Path) -> None:
    database, release_id, evidence = _authority_fixture(tmp_path)
    _write_evidence(
        evidence,
        release_id,
        complete_chain=False,
        cycles=[{"cycle_id": "fixture-1", "status": "passed"}],
        approval=False,
    )
    readiness = check_authority_readiness(
        database_path=database,
        evidence_path=evidence,
        release_id=release_id,
    )
    assert readiness["status"] == "blocked"
    assert readiness["decision"] == "WRITER_CUTOVER_READY"
    assert readiness["conditions"]["two_independent_monthly_cycles"] is False
    pointer = tmp_path / "artifacts" / "analytics" / "duckdb" / "latest.json"
    result = activate_catalog_release(
        database_path=database,
        pointer_path=pointer,
        evidence_path=evidence,
        release_id=release_id,
        approve_authority_switch=False,
        apply=True,
    )
    assert result["status"] == "blocked"
    assert pointer.exists() is False


def test_authority_activation_and_rollback_preserve_previous_pointer(tmp_path: Path) -> None:
    database, release_id, evidence = _authority_fixture(tmp_path)
    _write_evidence(
        evidence,
        release_id,
        complete_chain=True,
        cycles=[
            {"cycle_id": "fixture-1", "status": "passed"},
            {"cycle_id": "fixture-2", "status": "completed"},
        ],
        approval=True,
    )
    pointer = tmp_path / "artifacts" / "analytics" / "duckdb" / "latest.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps({"release_id": "legacy-fixture"}), encoding="utf-8")
    activated = activate_catalog_release(
        database_path=database,
        pointer_path=pointer,
        evidence_path=evidence,
        release_id=release_id,
        approve_authority_switch=True,
        apply=True,
    )
    assert activated["status"] == "applied"
    assert json.loads(pointer.read_text(encoding="utf-8"))["authority_status"] == "CANONICAL_V2_ACTIVE"
    assert json.loads(pointer.with_name("latest.previous.json").read_text(encoding="utf-8"))["release_id"] == "legacy-fixture"

    rolled_back = rollback_catalog_release(
        database_path=database,
        pointer_path=pointer,
        release_id=release_id,
        apply=True,
    )
    assert rolled_back["status"] == "applied"
    assert json.loads(pointer.read_text(encoding="utf-8"))["authority_status"] == "ROLLBACK"

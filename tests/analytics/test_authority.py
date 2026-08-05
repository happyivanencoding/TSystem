from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
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


def _write_evidence(
    path: Path,
    database: Path,
    release_id: str,
    *,
    complete_chain: bool,
    cycles: list[dict[str, str]],
    approval: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database), read_only=True) as connection:
        versions = connection.execute(
            "SELECT screen_dataset_version, returns_dataset_version "
            "FROM meta.catalog_releases WHERE release_id = ?",
            [release_id],
        ).fetchone()
    assert versions is not None

    def reference(name: str, status: str = "passed") -> dict[str, object]:
        reference_path = path.parent / f"{name}.json"
        reference_path.write_text(
            json.dumps({"name": name, "release_id": release_id, "status": status}),
            encoding="utf-8",
        )
        digest = hashlib.sha256(reference_path.read_bytes()).hexdigest()
        payload: dict[str, object] = {
            "status": status,
            "path": str(reference_path),
            "sha256": digest,
            "commit_sha": "a" * 40,
            "release_id": release_id,
        }
        if name == "clean_ci":
            payload.update(
                {
                    "run_id": "fixture-ci",
                    "jobs": {"python-core": "passed", "duckdb-unit": "passed"},
                }
            )
        return payload

    path.write_text(
        json.dumps(
            {
                "schema_version": "tp.duckdb-authority-evidence.v2",
                "release_id": release_id,
                "authority_status": "not_active",
                "dataset_versions": {
                    "screen": versions[0],
                    "returns_wide": versions[1],
                },
                "clean_ci": reference("clean_ci"),
                "full_real_data_parity": reference("full_real_data_parity"),
                "complete_production_chain_parity": reference(
                    "complete_production_chain_parity",
                    "passed" if complete_chain else "blocked",
                ),
                "rollback_drill": reference("rollback_drill"),
                "deployment_smoke": reference("deployment_smoke"),
                "monthly_cycles": cycles,
                "external_approval": reference(
                    "external_approval",
                    "passed" if approval else "blocked",
                ),
                "compatibility_exports": {"default": "enabled", "retired": False},
            }
        ),
        encoding="utf-8",
    )


def test_authority_switch_is_blocked_without_required_evidence(tmp_path: Path) -> None:
    database, release_id, evidence = _authority_fixture(tmp_path)
    _write_evidence(
        evidence,
        database,
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
        database,
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

"""Guarded catalog authority switching and compatibility retirement status."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from .catalog import catalog_health
from .config import DuckDBConfig
from .connection import connect
from .locking import FileLock
from .manifests import write_json_atomic

AUTHORITY_EVIDENCE_SCHEMA = "tp.duckdb-authority-evidence.v2"
_PASSED_CYCLE_STATUSES = frozenset({"passed", "completed"})
_REFERENCE_NAMES = (
    "clean_ci",
    "full_real_data_parity",
    "complete_production_chain_parity",
    "rollback_drill",
    "deployment_smoke",
    "external_approval",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")


def check_authority_readiness(
    *,
    database_path: str | Path,
    evidence_path: str | Path,
    release_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate all conditions required before a canonical authority switch."""

    evidence_target = Path(evidence_path).resolve()
    evidence, evidence_errors = _load_evidence(evidence_target)
    evidence_release_id = str(evidence.get("release_id")) if evidence.get("release_id") else None
    target_release_id = release_id or evidence_release_id
    database_target = Path(database_path).resolve()
    release_snapshot, catalog_conditions, catalog_errors = _catalog_snapshot(
        database_target,
        release_id=target_release_id,
    )
    reference_conditions, reference_errors = _reference_conditions(
        evidence,
        evidence_target.parent,
        target_release_id=target_release_id,
        catalog_release=release_snapshot,
    )

    cycles = evidence.get("monthly_cycles")
    cycle_ids: list[str] = []
    passed_cycle_ids: list[str] = []
    if isinstance(cycles, list):
        for item in cycles:
            if not isinstance(item, Mapping):
                continue
            cycle_id = str(item.get("cycle_id") or item.get("id") or "")
            if cycle_id:
                cycle_ids.append(cycle_id)
                if str(item.get("status", "")).lower() in _PASSED_CYCLE_STATUSES:
                    passed_cycle_ids.append(cycle_id)

    conditions: dict[str, bool] = {
        "evidence_schema": evidence.get("schema_version") == AUTHORITY_EVIDENCE_SCHEMA,
        "clean_ci": reference_conditions["clean_ci"],
        "full_real_data_parity": reference_conditions["full_real_data_parity"],
        "complete_production_chain_parity": reference_conditions["complete_production_chain_parity"],
        "rollback_drill": reference_conditions["rollback_drill"],
        "deployment_smoke": reference_conditions["deployment_smoke"],
        "two_independent_monthly_cycles": len(set(passed_cycle_ids)) >= 2
        and len(passed_cycle_ids) == len(set(passed_cycle_ids)),
        "external_approval": reference_conditions["external_approval"],
        "authority_not_active": evidence.get("authority_status", "not_active") == "not_active",
        "compatibility_exports_enabled": _compatibility_exports_enabled(evidence),
        "catalog_health": catalog_conditions["catalog_health"],
        "release_present": catalog_conditions["release_present"],
        "release_marts_ready": catalog_conditions["release_marts_ready"],
        "evidence_release_matches": bool(target_release_id)
        and evidence_release_id == target_release_id,
    }
    blockers = [name for name, passed in conditions.items() if not passed]
    blockers.extend(evidence_errors)
    blockers.extend(reference_errors)
    blockers.extend(catalog_errors)
    ready = not blockers and all(conditions.values())
    quality_gate = "READY" if ready else "EVIDENCE_BLOCKED"
    if not conditions["clean_ci"]:
        quality_gate = "CI_BLOCKED"
    return {
        "status": "ready" if ready else "blocked",
        "decision": "CANONICAL_V2_ACTIVE" if ready else "WRITER_CUTOVER_READY",
        "database_path": str(database_target),
        "evidence_path": str(evidence_target),
        "release_id": target_release_id,
        "conditions": conditions,
        "blockers": sorted(set(blockers)),
        "quality_gate": quality_gate,
        "evidence_references": reference_conditions,
        "monthly_cycles": {
            "observed": cycle_ids,
            "passed": passed_cycle_ids,
        },
        "catalog_release": release_snapshot,
    }


def activate_catalog_release(
    *,
    database_path: str | Path,
    pointer_path: str | Path,
    evidence_path: str | Path,
    release_id: str,
    approve_authority_switch: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    """Atomically publish a catalog pointer only after every guard passes."""

    readiness = check_authority_readiness(
        database_path=database_path,
        evidence_path=evidence_path,
        release_id=release_id,
    )
    conditions = dict(readiness["conditions"])
    conditions["explicit_cli_approval"] = bool(approve_authority_switch)
    blockers = list(readiness["blockers"])
    if not approve_authority_switch:
        blockers.append("explicit_cli_approval")
    ready = readiness["status"] == "ready" and approve_authority_switch
    result = {
        **readiness,
        "conditions": conditions,
        "blockers": sorted(set(blockers)),
        "status": "ready" if ready else "blocked",
        "apply_requested": bool(apply),
        "applied": False,
        "pointer_path": str(Path(pointer_path).resolve()),
    }
    if not apply or not ready:
        return result

    pointer = Path(pointer_path).resolve()
    previous_path = pointer.with_name(f"{pointer.stem}.previous{pointer.suffix}")
    old_pointer = _read_json(pointer)
    with FileLock(pointer.with_suffix(pointer.suffix + ".lock")):
        if old_pointer:
            write_json_atomic(previous_path, old_pointer)
        release = readiness["catalog_release"] or {}
        write_json_atomic(
            pointer,
            {
                "schema_version": "tp.catalog-pointer.v2",
                "release_id": release_id,
                "database_path": str(Path(database_path).resolve()),
                "screen_dataset_version": release.get("screen_dataset_version"),
                "returns_dataset_version": release.get("returns_dataset_version"),
                "authority_status": "CANONICAL_V2_ACTIVE",
                "evidence_path": str(Path(evidence_path).resolve()),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
    result.update({"status": "applied", "applied": True, "previous_pointer": str(previous_path)})
    return result


def rollback_catalog_release(
    *,
    database_path: str | Path,
    pointer_path: str | Path,
    release_id: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Point the catalog back to a validated immutable release."""

    target_database = Path(database_path).resolve()
    release, catalog_conditions, errors = _catalog_snapshot(target_database, release_id=release_id)
    pointer = Path(pointer_path).resolve()
    result: dict[str, Any] = {
        "status": "dry_run" if not apply else "blocked",
        "apply_requested": bool(apply),
        "applied": False,
        "database_path": str(target_database),
        "pointer_path": str(pointer),
        "catalog_conditions": catalog_conditions,
        "catalog_release": release,
        "blockers": errors,
    }
    if errors or release is None:
        return result

    old_pointer = _read_json(pointer)
    previous_path = pointer.with_name(f"{pointer.stem}.previous{pointer.suffix}")
    if apply:
        with FileLock(pointer.with_suffix(pointer.suffix + ".lock")):
            if old_pointer:
                write_json_atomic(previous_path, old_pointer)
            write_json_atomic(
                pointer,
                {
                    "schema_version": "tp.catalog-pointer.v2",
                    "release_id": release["release_id"],
                    "database_path": str(target_database),
                    "screen_dataset_version": release.get("screen_dataset_version"),
                    "returns_dataset_version": release.get("returns_dataset_version"),
                    "authority_status": "ROLLBACK",
                    "rolled_back_at": datetime.now(UTC).isoformat(),
                },
            )
        result.update({"status": "applied", "applied": True, "previous_pointer": str(previous_path)})
    return result


def retirement_readiness(
    *,
    database_path: str | Path,
    evidence_path: str | Path,
    release_id: str | None = None,
) -> dict[str, Any]:
    """Report whether Phase 8 may disable compatibility export generation."""

    readiness = check_authority_readiness(
        database_path=database_path,
        evidence_path=evidence_path,
        release_id=release_id,
    )
    return {
        **readiness,
        "decision": "RETIREMENT_READY" if readiness["status"] == "ready" else "WRITER_CUTOVER_READY",
        "retirement": {
            "compatibility_exports_default": "enabled",
            "safe_to_disable": readiness["status"] == "ready",
            "switch": "TP_COMPAT_EXPORTS=false plus --no-compatibility-exports",
            "historical_run_cards_retained": True,
        },
    }


def _load_evidence(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"evidence_unreadable:{type(exc).__name__}"]
    if not isinstance(payload, dict):
        return {}, ["evidence_not_object"]
    return payload, []


def _reference_conditions(
    evidence: Mapping[str, Any],
    evidence_root: Path,
    *,
    target_release_id: str | None,
    catalog_release: Mapping[str, Any] | None,
) -> tuple[dict[str, bool], list[str]]:
    conditions = {name: False for name in _REFERENCE_NAMES}
    errors: list[str] = []
    expected_versions = evidence.get("dataset_versions")
    catalog_versions = {
        "screen": catalog_release.get("screen_dataset_version") if catalog_release else None,
        "returns_wide": catalog_release.get("returns_dataset_version") if catalog_release else None,
    }
    if not isinstance(expected_versions, Mapping):
        errors.append("evidence_dataset_versions_missing")
    elif catalog_release:
        for name, expected in catalog_versions.items():
            if expected and expected_versions.get(name) != expected:
                errors.append(f"evidence_dataset_version_mismatch:{name}")

    for name in _REFERENCE_NAMES:
        reference = evidence.get(name)
        if isinstance(reference, bool):
            errors.append(f"evidence_reference_required:{name}")
            continue
        if not isinstance(reference, Mapping):
            errors.append(f"evidence_reference_missing:{name}")
            continue
        status = str(reference.get("status", "")).lower()
        if status not in _PASSED_CYCLE_STATUSES:
            errors.append(f"evidence_reference_not_passed:{name}")
            continue
        errors.extend(
            _validate_reference(
                name,
                reference,
                evidence_root,
                target_release_id=target_release_id,
            )
        )
        if not _reference_has_valid_shape(
            reference,
            evidence_root,
            target_release_id=target_release_id,
        ):
            continue
        conditions[name] = True
        if name == "clean_ci" and not _clean_ci_green(reference):
            conditions[name] = False
            errors.append("clean_ci_not_green")
    return conditions, errors


def _validate_reference(
    name: str,
    reference: Mapping[str, Any],
    evidence_root: Path,
    *,
    target_release_id: str | None,
) -> list[str]:
    errors: list[str] = []
    path_value = reference.get("path")
    if not path_value:
        errors.append(f"evidence_reference_path_missing:{name}")
    else:
        target = Path(str(path_value))
        if not target.is_absolute():
            target = evidence_root / target
        if not target.exists():
            errors.append(f"evidence_reference_file_missing:{name}")
        else:
            expected_hash = str(reference.get("sha256") or "").lower()
            if not _SHA256_RE.fullmatch(expected_hash):
                errors.append(f"evidence_reference_sha256_missing:{name}")
            elif _sha256(target) != expected_hash:
                errors.append(f"evidence_reference_sha256_mismatch:{name}")
    commit_sha = str(reference.get("commit_sha") or "").lower()
    if not _COMMIT_RE.fullmatch(commit_sha):
        errors.append(f"evidence_reference_commit_missing:{name}")
    if target_release_id and reference.get("release_id") != target_release_id:
        errors.append(f"evidence_reference_release_mismatch:{name}")
    return errors


def _reference_has_valid_shape(
    reference: Mapping[str, Any],
    evidence_root: Path,
    *,
    target_release_id: str | None,
) -> bool:
    return not _validate_reference(
        "shape",
        reference,
        evidence_root,
        target_release_id=target_release_id,
    )


def _clean_ci_green(reference: Mapping[str, Any]) -> bool:
    jobs = reference.get("jobs")
    if not isinstance(jobs, Mapping) or not jobs:
        return False
    return bool(reference.get("run_id")) and all(
        str(status).lower() in _PASSED_CYCLE_STATUSES for status in jobs.values()
    )


def _compatibility_exports_enabled(evidence: Mapping[str, Any]) -> bool:
    value = evidence.get("compatibility_exports")
    if isinstance(value, Mapping):
        return (
            str(value.get("default", "enabled")).lower() == "enabled"
            and not bool(value.get("retired", False))
        )
    return value in (None, True, "enabled")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _catalog_snapshot(
    database_path: Path,
    *,
    release_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, bool], list[str]]:
    conditions = {
        "catalog_health": False,
        "release_present": False,
        "release_marts_ready": False,
    }
    if not database_path.exists():
        return None, conditions, ["catalog_database_missing"]
    config = DuckDBConfig(database_path=database_path, read_only=True)
    try:
        with connect(config) as connection:
            health = catalog_health(connection)
            conditions["catalog_health"] = health.ok
            if not health.ok:
                return None, conditions, ["catalog_health_failed"]
            if release_id:
                row = connection.execute(
                    "SELECT release_id, database_path, screen_dataset_version, "
                    "returns_dataset_version, validation_status, manifest_path "
                    "FROM meta.catalog_releases WHERE release_id = ?",
                    [release_id],
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT release_id, database_path, screen_dataset_version, "
                    "returns_dataset_version, validation_status, manifest_path "
                    "FROM meta.catalog_releases ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
            if row is None:
                return None, conditions, ["catalog_release_missing"]
            columns = [item[0] for item in connection.description]
            release = dict(zip(columns, row, strict=True))
            conditions["release_present"] = True
            conditions["release_marts_ready"] = release.get("validation_status") == "marts_ready"
            errors = [] if conditions["release_marts_ready"] else ["release_not_marts_ready"]
            return release, conditions, errors
    except (duckdb.Error, OSError, ValueError) as exc:
        return None, conditions, [f"catalog_unreadable:{type(exc).__name__}"]


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


__all__ = [
    "AUTHORITY_EVIDENCE_SCHEMA",
    "activate_catalog_release",
    "check_authority_readiness",
    "retirement_readiness",
    "rollback_catalog_release",
]

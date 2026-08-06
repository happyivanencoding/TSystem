"""Small production-run bundle and explicit manifest-reuse primitives."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from tp_core.data_sources import TP_ROOT
from tp_core.workspace import PIPELINE_RUNS_DIR

PRODUCTION_RUN_BUNDLES_DIR = PIPELINE_RUNS_DIR / "bundles"
STEP_STATES = {
    "produced_this_run",
    "explicitly_reused",
    "disabled",
    "failed",
    "blocked_by_dependency",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_production_run_id() -> str:
    return f"prod-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def _parse_date(value: Any) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return pd.Timestamp(parsed).normalize() if pd.notna(parsed) else None


def _manifest_date(payload: Mapping[str, Any]) -> pd.Timestamp | None:
    parameters = payload.get("parameters")
    details = payload.get("details")
    candidates: list[Any] = [
        payload.get("data_date"),
        payload.get("as_of"),
        parameters.get("as_of") if isinstance(parameters, Mapping) else None,
        parameters.get("to_date") if isinstance(parameters, Mapping) else None,
        details.get("data_date") if isinstance(details, Mapping) else None,
    ]
    if isinstance(parameters, Mapping) and parameters.get("input_month"):
        month = str(parameters["input_month"])
        if len(month) == 6 and month.isdigit():
            candidates.append(pd.Period(month, freq="M").end_time)
    for value in candidates:
        date = _parse_date(value)
        if date is not None:
            return date
    return None


def _output_paths(value: Any) -> list[Path]:
    paths: list[Path] = []
    if isinstance(value, Mapping):
        raw_path = value.get("path")
        if raw_path:
            paths.append(Path(str(raw_path)))
        for item in value.values():
            paths.extend(_output_paths(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            paths.extend(_output_paths(item))
    return paths


def load_reuse_mapping(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"reuse manifest mapping does not exist: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"reuse manifest mapping is unreadable: {source}") from exc
    mapping = payload.get("steps") if isinstance(payload, Mapping) else None
    if mapping is None:
        mapping = payload
    if not isinstance(mapping, Mapping):
        raise TypeError("reuse manifest mapping must be a JSON object")
    result: dict[str, dict[str, Any]] = {}
    for step, value in mapping.items():
        if isinstance(value, str):
            result[str(step)] = {"manifest": value, "reason": "explicit reuse"}
        elif isinstance(value, Mapping) and value.get("manifest"):
            result[str(step)] = {
                "manifest": str(value["manifest"]),
                "reason": str(value.get("reason") or "explicit reuse"),
            }
        else:
            raise ValueError(f"reuse entry for {step!r} must contain a manifest path")
    return result


def validate_reuse_manifest(
    path: str | Path,
    *,
    run_type: str,
    as_of: str | None,
    allowed_lag_days: int,
) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"explicit reuse manifest does not exist: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"explicit reuse manifest is unreadable: {source}") from exc
    if not isinstance(payload, Mapping):
        raise TypeError(f"explicit reuse manifest must be an object: {source}")
    manifest_run_type = payload.get("run_type") or (
        payload.get("parameters", {}).get("run_type")
        if isinstance(payload.get("parameters"), Mapping)
        else None
    )
    if str(manifest_run_type) != run_type:
        raise ValueError(
            f"reuse manifest run_type mismatch: expected {run_type}, got {manifest_run_type}"
        )
    artifact_paths = _output_paths(payload.get("outputs"))
    missing_artifacts = [str(item) for item in artifact_paths if not item.exists()]
    if missing_artifacts:
        raise ValueError(f"reuse manifest outputs are missing: {missing_artifacts}")
    artifact_date = _manifest_date(payload)
    as_of_date = _parse_date(as_of)
    if as_of_date is not None:
        if artifact_date is None:
            raise ValueError("reuse manifest has no verifiable data date")
        lag_days = int((as_of_date - artifact_date).days)
        if artifact_date > as_of_date or lag_days > allowed_lag_days:
            raise ValueError(
                "reuse manifest is incompatible with as-of: "
                f"artifact_date={artifact_date.date().isoformat()}, "
                f"as_of={as_of_date.date().isoformat()}, lag_days={lag_days}, "
                f"allowed_lag_days={allowed_lag_days}"
            )
    return {
        "manifest_path": str(source.resolve()),
        "run_type": str(manifest_run_type),
        "production_run_id": payload.get("production_run_id"),
        "data_date": artifact_date.date().isoformat() if artifact_date is not None else None,
        "payload": dict(payload),
    }


def _release_id_from_pointer(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for key in ("release_id", "dataset_version", "version"):
        if payload.get(key):
            return str(payload[key])
    return None


def resolve_data_release_id(root: str | Path = TP_ROOT) -> str:
    base = Path(root)
    values = [
        _release_id_from_pointer(
            base / "00_screen" / "datasets" / "manifests" / "screen" / "current.json"
        ),
        _release_id_from_pointer(
            base / "00_screen" / "datasets" / "manifests" / "returns_wide" / "current.json"
        ),
    ]
    values = [value for value in values if value]
    return "|".join(values) if values else "legacy-canonical"


def resolve_catalog_release_id(root: str | Path = TP_ROOT) -> str | None:
    pointer = Path(root) / "artifacts" / "analytics" / "duckdb" / "latest.json"
    return _release_id_from_pointer(pointer)


@dataclass
class ProductionRunBundle:
    production_run_id: str
    run_type: str
    started_at: str
    as_of_date: str | None
    input_month: str | None
    data_release_id: str
    catalog_release_id: str | None
    model_release_ids: tuple[str, ...] = field(default_factory=tuple)
    retention_class: str = "recent_operational"
    finished_at: str | None = None
    step_states: dict[str, str] = field(default_factory=dict)
    child_manifests: dict[str, str] = field(default_factory=dict)
    explicit_reuse_manifests: dict[str, dict[str, Any]] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    validations: list[dict[str, Any]] = field(default_factory=list)
    rollback_targets: list[str] = field(default_factory=list)
    status: str = "running"

    @classmethod
    def start(
        cls,
        *,
        run_type: str,
        as_of_date: str | None,
        input_month: str | None,
        data_release_id: str,
        catalog_release_id: str | None,
        model_release_ids: tuple[str, ...] = (),
        production_run_id: str | None = None,
    ) -> ProductionRunBundle:
        return cls(
            production_run_id=production_run_id or new_production_run_id(),
            run_type=run_type,
            started_at=utc_now(),
            as_of_date=as_of_date,
            input_month=input_month,
            data_release_id=data_release_id,
            catalog_release_id=catalog_release_id,
            model_release_ids=model_release_ids,
            retention_class=("disposable_smoke" if run_type in {"smoke", "inspect"} else "recent_operational"),
        )

    def mark(self, step: str, state: str, *, reason: str = "") -> None:
        if state not in STEP_STATES:
            raise ValueError(f"invalid pipeline step state: {state}")
        self.step_states[step] = state
        if reason:
            self.validations.append({"name": f"step:{step}", "status": state, "message": reason})

    def record_manifest(self, step: str, path: str | Path) -> None:
        source = Path(path)
        self.mark(step, "produced_this_run")
        self.child_manifests[step] = str(source)
        if not source.is_file():
            self.validations.append(
                {"name": f"manifest:{step}", "status": "missing", "path": str(source)}
            )
            return
        payload = json.loads(source.read_text(encoding="utf-8"))
        if payload.get("production_run_id") not in {None, self.production_run_id}:
            raise ValueError(
                f"child manifest production_run_id mismatch for {step}: "
                f"{payload.get('production_run_id')} != {self.production_run_id}"
            )
        self.outputs[step] = payload.get("outputs") or {}
        self.validations.append(
            {"name": f"manifest:{step}", "status": "passed", "path": str(source)}
        )

    def record_reuse(
        self,
        step: str,
        details: Mapping[str, Any],
        *,
        reason: str,
    ) -> None:
        self.mark(step, "explicitly_reused", reason=reason)
        self.explicit_reuse_manifests[step] = {
            "manifest_path": details.get("manifest_path"),
            "source_production_run_id": details.get("production_run_id"),
            "data_date": details.get("data_date"),
            "reason": reason,
        }
        self.outputs[step] = details.get("payload", {}).get("outputs", {})

    def finish(
        self,
        status: str,
        *,
        validations: list[Mapping[str, Any]] = (),
        rollback_targets: list[str] = (),
        bundle_root: str | Path | None = None,
    ) -> Path:
        self.status = status
        self.finished_at = utc_now()
        self.validations.extend(dict(item) for item in validations)
        self.rollback_targets = list(rollback_targets)
        root = Path(bundle_root or PRODUCTION_RUN_BUNDLES_DIR)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{self.production_run_id}.json"
        payload = {
            "production_run_id": self.production_run_id,
            "run_type": self.run_type,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "as_of_date": self.as_of_date,
            "input_month": self.input_month,
            "data_release_id": self.data_release_id,
            "catalog_release_id": self.catalog_release_id,
            "model_release_ids": list(self.model_release_ids),
            "step_states": self.step_states,
            "child_manifests": self.child_manifests,
            "explicit_reuse_manifests": self.explicit_reuse_manifests,
            "outputs": self.outputs,
            "validations": self.validations,
            "rollback_targets": self.rollback_targets,
            "retention_class": self.retention_class,
            "status": self.status,
        }
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        latest = root / "latest.json"
        latest.write_text(
            json.dumps(
                {"production_run_id": self.production_run_id, "bundle_path": str(path.resolve())},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path


__all__ = [
    "PRODUCTION_RUN_BUNDLES_DIR",
    "STEP_STATES",
    "ProductionRunBundle",
    "load_reuse_mapping",
    "new_production_run_id",
    "resolve_catalog_release_id",
    "resolve_data_release_id",
    "validate_reuse_manifest",
]

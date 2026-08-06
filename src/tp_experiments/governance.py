"""Append-only promotion decisions for experiment runs.

Run Cards describe what ran.  This module records the separate human or
control-plane decision that may follow a completed research run.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tp_core.workspace import EXPERIMENTS_DIR, PIPELINE_RUNS_DIR

from .recorder import ExperimentRecorder

PROMOTION_DECISIONS_DIRNAME = "promotion_decisions"
MODEL_RELEASES_DIR = PIPELINE_RUNS_DIR / "model_releases"
MODEL_RELEASE_STATUSES = {"shadow", "approved", "active", "retired", "revoked"}
PROMOTION_DECISIONS = {"approved", "rejected", "revoked"}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _gate_passed(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"passed", "approved", "true", "ok", "yes"}


def _decision_sort_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return (str(record.get("decided_at") or ""), str(record.get("decision_id") or ""))


@dataclass(frozen=True)
class PromotionDecision:
    """One immutable decision record stored independently from ``run.json``."""

    decision_id: str
    hypothesis_id: str
    experiment_run_id: str
    decision: str
    reason: str
    decided_by: str
    decided_at: str
    required_gates: tuple[str, ...] = field(default_factory=tuple)
    gate_results: Mapping[str, Any] = field(default_factory=dict)
    applicable_scope: Mapping[str, Any] = field(default_factory=dict)
    revokes_decision_id: str | None = None

    def __post_init__(self) -> None:
        if self.decision not in PROMOTION_DECISIONS:
            raise ValueError(f"invalid promotion decision: {self.decision}")
        if not self.reason.strip():
            raise ValueError("promotion decision reason must not be empty")
        if not self.decided_by.strip():
            raise ValueError("promotion decision decided_by must not be empty")
        if self.decision == "revoked" and not self.revokes_decision_id:
            raise ValueError("revoked decision must identify the decision it revokes")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_gates"] = list(self.required_gates)
        payload["gate_results"] = dict(self.gate_results)
        payload["applicable_scope"] = dict(self.applicable_scope)
        return payload


class PromotionDecisionStore:
    """Read and append promotion decisions for one experiment root."""

    def __init__(
        self,
        experiment_root: str | Path | None = None,
        *,
        decision_root: str | Path | None = None,
    ) -> None:
        self.experiment_root = Path(experiment_root or EXPERIMENTS_DIR)
        self.decision_root = Path(
            decision_root
            or self.experiment_root / "_governance" / PROMOTION_DECISIONS_DIRNAME
        )

    def find_experiment(
        self,
        experiment_run_id: str,
        *,
        hypothesis_id: str | None = None,
    ) -> dict[str, Any]:
        records = ExperimentRecorder(self.experiment_root).query_runs(
            hypothesis_id=hypothesis_id,
        )
        for record in records:
            if str((record.get("run") or {}).get("run_id")) == experiment_run_id:
                return record
        raise ValueError(f"experiment run does not exist: {experiment_run_id}")

    def list_decisions(self, experiment_run_id: str | None = None) -> list[dict[str, Any]]:
        paths = sorted(self.decision_root.glob("*.json")) if self.decision_root.exists() else []
        records: list[dict[str, Any]] = []
        for path in paths:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if experiment_run_id is not None and record.get("experiment_run_id") != experiment_run_id:
                continue
            record["record_path"] = str(path.resolve())
            records.append(record)
        records.sort(key=_decision_sort_key)
        return records

    def create(
        self,
        *,
        experiment_run_id: str,
        decision: str,
        reason: str,
        decided_by: str,
        required_gates: Sequence[str] = (),
        gate_results: Mapping[str, Any] | None = None,
        applicable_scope: Mapping[str, Any] | None = None,
        hypothesis_id: str | None = None,
        decided_at: str | None = None,
        revokes_decision_id: str | None = None,
    ) -> PromotionDecision:
        experiment = self.find_experiment(
            experiment_run_id,
            hypothesis_id=hypothesis_id,
        )
        run = experiment.get("run") or {}
        resolved_hypothesis_id = str(
            (experiment.get("hypothesis") or {}).get("hypothesis_id") or hypothesis_id or ""
        )
        if decision == "approved" and run.get("status") != "success":
            raise ValueError(
                "only a successful experiment run can receive an approved decision"
            )
        gates = tuple(str(gate) for gate in required_gates)
        results = dict(gate_results or {})
        if decision == "approved":
            missing = [gate for gate in gates if gate not in results]
            failed = [gate for gate in gates if gate in results and not _gate_passed(results[gate])]
            if missing or failed:
                raise ValueError(
                    f"approval gates not passed; missing={missing}, failed={failed}"
                )

        previous = self.list_decisions(experiment_run_id)
        if decision == "revoked":
            target = revokes_decision_id
            if target is None:
                approved = [item for item in previous if item.get("decision") == "approved"]
                target = approved[-1].get("decision_id") if approved else None
            if not target or not any(item.get("decision_id") == target for item in previous):
                raise ValueError("revoked decision must target an existing decision")
            revokes_decision_id = str(target)

        record = PromotionDecision(
            decision_id=f"pd-{uuid.uuid4().hex}",
            hypothesis_id=resolved_hypothesis_id,
            experiment_run_id=experiment_run_id,
            decision=decision,
            reason=reason,
            decided_by=decided_by,
            decided_at=decided_at or _utc_now(),
            required_gates=gates,
            gate_results=results,
            applicable_scope=dict(applicable_scope or {}),
            revokes_decision_id=revokes_decision_id,
        )
        self.decision_root.mkdir(parents=True, exist_ok=True)
        path = self.decision_root / f"{record.decision_id}.json"
        path.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return record

    def resolve(self, experiment_run_id: str) -> dict[str, Any] | None:
        """Resolve the effective decision without rewriting any prior record."""

        revoked: set[str] = set()
        effective: dict[str, Any] | None = None
        for record in self.list_decisions(experiment_run_id):
            decision_id = str(record.get("decision_id") or "")
            if record.get("decision") == "revoked":
                target = str(record.get("revokes_decision_id") or "")
                if target:
                    revoked.add(target)
                effective = record
            elif decision_id not in revoked:
                effective = record
        return effective

    def require_approved(self, experiment_run_id: str) -> dict[str, Any]:
        decision = self.resolve(experiment_run_id)
        if decision is None or decision.get("decision") != "approved":
            raise ValueError(f"experiment run has no effective approved decision: {experiment_run_id}")
        return decision


@dataclass(frozen=True)
class ModelRelease:
    """A production-addressable model release, separate from research output paths."""

    model_release_id: str
    model_family: str
    hypothesis_id: str
    source_experiment_run_id: str
    promotion_decision_id: str | None
    configuration_reference: str
    artifact_references: Mapping[str, Any] = field(default_factory=dict)
    component_versions: Mapping[str, str] = field(default_factory=dict)
    applicable_markets: tuple[str, ...] = field(default_factory=tuple)
    effective_from: str | None = None
    effective_to: str | None = None
    deployment_status: str = "shadow"
    created_by: str = "system"
    created_at: str = field(default_factory=_utc_now)
    retired_at: str | None = None
    replacement_release_id: str | None = None
    state_history: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.deployment_status not in MODEL_RELEASE_STATUSES:
            raise ValueError(f"invalid model release status: {self.deployment_status}")
        if not self.model_family.strip():
            raise ValueError("model_family must not be empty")
        if not self.configuration_reference.strip():
            raise ValueError("configuration_reference must not be empty")
        if not self.created_by.strip():
            raise ValueError("created_by must not be empty")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_references"] = dict(self.artifact_references)
        payload["component_versions"] = dict(self.component_versions)
        payload["applicable_markets"] = list(self.applicable_markets)
        payload["state_history"] = [dict(item) for item in self.state_history]
        return payload


class ModelReleaseStore:
    """Create and transition the single generic model-release record type."""

    def __init__(
        self,
        experiment_root: str | Path | None = None,
        *,
        release_root: str | Path | None = None,
        decision_root: str | Path | None = None,
    ) -> None:
        self.experiment_root = Path(experiment_root or EXPERIMENTS_DIR)
        self.release_root = Path(release_root or MODEL_RELEASES_DIR)
        self.decisions = PromotionDecisionStore(
            self.experiment_root,
            decision_root=decision_root,
        )

    def list(self, *, model_family: str | None = None) -> list[dict[str, Any]]:
        paths = sorted(self.release_root.glob("*.json")) if self.release_root.exists() else []
        records: list[dict[str, Any]] = []
        for path in paths:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if model_family is not None and record.get("model_family") != model_family:
                continue
            record["record_path"] = str(path.resolve())
            records.append(record)
        records.sort(
            key=lambda item: (
                str(item.get("created_at") or ""),
                str(item.get("model_release_id") or ""),
            ),
            reverse=True,
        )
        return records

    def get(self, model_release_id: str) -> dict[str, Any]:
        path = self.release_root / f"{model_release_id}.json"
        if not path.is_file():
            raise ValueError(f"model release does not exist: {model_release_id}")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"model release is unreadable: {path}") from exc
        record["record_path"] = str(path.resolve())
        return record

    def create(
        self,
        *,
        model_family: str,
        hypothesis_id: str,
        source_experiment_run_id: str,
        configuration_reference: str,
        artifact_references: Mapping[str, Any] | None = None,
        component_versions: Mapping[str, str] | None = None,
        applicable_markets: Sequence[str] = (),
        effective_from: str | None = None,
        effective_to: str | None = None,
        deployment_status: str = "shadow",
        created_by: str = "system",
        promotion_decision_id: str | None = None,
        replacement_release_id: str | None = None,
    ) -> ModelRelease:
        if deployment_status not in MODEL_RELEASE_STATUSES:
            raise ValueError(f"invalid model release status: {deployment_status}")
        if deployment_status != "shadow":
            if not promotion_decision_id:
                raise ValueError("a production-capable release requires promotion_decision_id")
            decision = self.decisions.require_approved(source_experiment_run_id)
            if decision.get("decision_id") != promotion_decision_id:
                raise ValueError("promotion_decision_id is not the effective approval")
        else:
            self.decisions.find_experiment(source_experiment_run_id, hypothesis_id=hypothesis_id)

        release = ModelRelease(
            model_release_id=f"mr-{uuid.uuid4().hex}",
            model_family=model_family,
            hypothesis_id=hypothesis_id,
            source_experiment_run_id=source_experiment_run_id,
            promotion_decision_id=promotion_decision_id,
            configuration_reference=configuration_reference,
            artifact_references=dict(artifact_references or {}),
            component_versions=dict(component_versions or {}),
            applicable_markets=tuple(str(market) for market in applicable_markets),
            effective_from=effective_from,
            effective_to=effective_to,
            deployment_status=deployment_status,
            created_by=created_by,
            replacement_release_id=replacement_release_id,
            state_history=(
                {
                    "status": deployment_status,
                    "changed_at": _utc_now(),
                    "changed_by": created_by,
                    "reason": "created",
                },
            ),
        )
        self.release_root.mkdir(parents=True, exist_ok=True)
        path = self.release_root / f"{release.model_release_id}.json"
        path.write_text(
            json.dumps(release.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return release

    def _transition(
        self,
        model_release_id: str,
        *,
        status: str,
        changed_by: str,
        reason: str,
        replacement_release_id: str | None = None,
    ) -> dict[str, Any]:
        record = self.get(model_release_id)
        if status not in MODEL_RELEASE_STATUSES:
            raise ValueError(f"invalid model release status: {status}")
        if record.get("deployment_status") in {"retired", "revoked"}:
            raise ValueError(f"model release is already terminal: {model_release_id}")
        if status == "active":
            if record.get("deployment_status") != "approved":
                raise ValueError("only an approved model release can be activated")
            try:
                decision = self.decisions.require_approved(str(record["source_experiment_run_id"]))
            except ValueError as exc:
                raise ValueError("model release approval is no longer valid") from exc
            if decision.get("decision_id") != record.get("promotion_decision_id"):
                raise ValueError("model release approval has been revoked or superseded")
        if status == "approved":
            try:
                decision = self.decisions.require_approved(str(record["source_experiment_run_id"]))
            except ValueError as exc:
                raise ValueError("model release approval is no longer valid") from exc
            if decision.get("decision_id") != record.get("promotion_decision_id"):
                raise ValueError("model release approval has been revoked or superseded")
        if not reason.strip() or not changed_by.strip():
            raise ValueError("state transition requires changed_by and reason")
        changed_at = _utc_now()
        history = list(record.get("state_history") or [])
        history.append(
            {
                "status": status,
                "changed_at": changed_at,
                "changed_by": changed_by,
                "reason": reason,
            }
        )
        record["deployment_status"] = status
        record["state_history"] = history
        if status == "retired":
            record["retired_at"] = changed_at
        if replacement_release_id is not None:
            record["replacement_release_id"] = replacement_release_id
        path = self.release_root / f"{model_release_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {key: value for key, value in record.items() if key != "record_path"},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
        return self.get(model_release_id)

    def activate(self, model_release_id: str, *, changed_by: str, reason: str) -> dict[str, Any]:
        return self._transition(
            model_release_id,
            status="active",
            changed_by=changed_by,
            reason=reason,
        )

    def retire(
        self,
        model_release_id: str,
        *,
        changed_by: str,
        reason: str,
        replacement_release_id: str | None = None,
    ) -> dict[str, Any]:
        return self._transition(
            model_release_id,
            status="retired",
            changed_by=changed_by,
            reason=reason,
            replacement_release_id=replacement_release_id,
        )

    def revoke(self, model_release_id: str, *, changed_by: str, reason: str) -> dict[str, Any]:
        record = self.get(model_release_id)
        decision_id = record.get("promotion_decision_id")
        if decision_id:
            self.decisions.create(
                experiment_run_id=str(record["source_experiment_run_id"]),
                decision="revoked",
                reason=reason,
                decided_by=changed_by,
                revokes_decision_id=str(decision_id),
            )
        return self._transition(
            model_release_id,
            status="revoked",
            changed_by=changed_by,
            reason=reason,
        )

    def require_production(self, model_release_id: str) -> dict[str, Any]:
        record = self.get(model_release_id)
        if record.get("deployment_status") not in {"approved", "active"}:
            raise ValueError(f"model release is not production-usable: {model_release_id}")
        decision = self.decisions.require_approved(str(record["source_experiment_run_id"]))
        if decision.get("decision_id") != record.get("promotion_decision_id"):
            raise ValueError(f"model release approval is no longer valid: {model_release_id}")
        return record

    def current(
        self,
        *,
        model_family: str,
        market: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        for record in self.list(model_family=model_family):
            if record.get("deployment_status") != "active":
                continue
            if market and record.get("applicable_markets") and market not in record["applicable_markets"]:
                continue
            if as_of:
                effective_from = record.get("effective_from")
                effective_to = record.get("effective_to")
                if effective_from and str(as_of) < str(effective_from):
                    continue
                if effective_to and str(as_of) > str(effective_to):
                    continue
            try:
                candidates.append(self.require_production(str(record["model_release_id"])))
            except ValueError:
                continue
        return candidates[0] if candidates else None


__all__ = [
    "MODEL_RELEASES_DIR",
    "MODEL_RELEASE_STATUSES",
    "PROMOTION_DECISIONS",
    "ModelRelease",
    "ModelReleaseStore",
    "PromotionDecision",
    "PromotionDecisionStore",
]

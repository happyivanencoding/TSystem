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

from tp_core.workspace import EXPERIMENTS_DIR

from .recorder import ExperimentRecorder

PROMOTION_DECISIONS_DIRNAME = "promotion_decisions"
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


__all__ = [
    "PROMOTION_DECISIONS",
    "PromotionDecision",
    "PromotionDecisionStore",
]

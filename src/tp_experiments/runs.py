"""Shared run-kind schemas used by research and production execution records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

RUN_KINDS = {"research", "production"}


@dataclass(frozen=True)
class ResearchRun:
    hypothesis: Mapping[str, Any]
    trial_family: str
    effective_trial_count: int | None
    research_metrics: Mapping[str, Any] = field(default_factory=dict)
    review_state: str = "running"
    promotion_lineage: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "hypothesis": dict(self.hypothesis),
            "research_metrics": dict(self.research_metrics),
            "promotion_lineage": dict(self.promotion_lineage),
        }


@dataclass(frozen=True)
class ProductionRun:
    production_run_id: str
    operational_status: str = "running"
    data_release_id: str | None = None
    model_release_ids: tuple[str, ...] = field(default_factory=tuple)
    parent_step_manifests: tuple[str, ...] = field(default_factory=tuple)
    reuse_decisions: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    write_approval: Mapping[str, Any] = field(default_factory=dict)
    rollback_target: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["model_release_ids"] = list(self.model_release_ids)
        payload["parent_step_manifests"] = list(self.parent_step_manifests)
        payload["reuse_decisions"] = [dict(item) for item in self.reuse_decisions]
        payload["write_approval"] = dict(self.write_approval)
        return payload


__all__ = ["RUN_KINDS", "ProductionRun", "ResearchRun"]

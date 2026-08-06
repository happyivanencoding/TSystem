"""Load and filter the versioned benchmark workload registry."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from .contracts import WorkloadDefinition


def default_registry_path(root: str | Path) -> Path:
    return Path(root) / "config" / "analytics" / "performance_workloads_v1.json"


def load_workloads(path: str | Path) -> list[WorkloadDefinition]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [WorkloadDefinition.from_dict(item) for item in payload.get("workloads", [])]


def select_workloads(
    workloads: Iterable[WorkloadDefinition],
    *,
    workload_ids: Iterable[str] = (),
    category: str | None = None,
) -> list[WorkloadDefinition]:
    requested = {str(value) for value in workload_ids if str(value)}
    selected = [
        item
        for item in workloads
        if (not requested or item.workload_id in requested)
        and (category is None or item.category == category)
    ]
    if requested:
        found = {item.workload_id for item in selected}
        missing = sorted(requested - found)
        if missing:
            raise ValueError(f"unknown workload(s): {', '.join(missing)}")
    return selected


__all__ = ["default_registry_path", "load_workloads", "select_workloads"]

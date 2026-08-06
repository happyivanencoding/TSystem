"""Small serializable contracts shared by the benchmark runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkloadDefinition:
    workload_id: str
    category: str
    description: str
    operation: str
    input_date: dict[str, Any]
    input_columns: tuple[str, ...]
    universe: dict[str, Any]
    result_schema: dict[str, Any]
    parity: dict[str, Any]
    repetitions: dict[str, int]
    hot_path: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WorkloadDefinition:
        return cls(
            workload_id=str(payload["workload_id"]),
            category=str(payload["category"]),
            description=str(payload["description"]),
            operation=str(payload["operation"]),
            input_date=dict(payload.get("input_date") or {}),
            input_columns=tuple(str(value) for value in payload.get("input_columns") or ()),
            universe=dict(payload.get("universe") or {}),
            result_schema=dict(payload.get("result_schema") or {}),
            parity=dict(payload.get("parity") or {}),
            repetitions={
                str(key): int(value)
                for key, value in dict(payload.get("repetitions") or {}).items()
            },
            hot_path=bool(payload.get("hot_path", False)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "workload_id": self.workload_id,
            "category": self.category,
            "description": self.description,
            "operation": self.operation,
            "input_date": self.input_date,
            "input_columns": list(self.input_columns),
            "universe": self.universe,
            "result_schema": self.result_schema,
            "parity": self.parity,
            "repetitions": self.repetitions,
            "hot_path": self.hot_path,
        }

    def repetitions_for(self, cache_mode: str, override: int | None = None) -> int:
        if override is not None:
            return max(1, int(override))
        return max(1, int(self.repetitions.get(cache_mode, 1)))


__all__ = ["WorkloadDefinition"]

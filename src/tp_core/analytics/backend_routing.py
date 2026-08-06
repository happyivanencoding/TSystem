"""Single production backend policy for workload-specific data reads."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROUTING_POLICY_PATH = Path(__file__).resolve().parents[3] / "config" / "data_backend_routing.json"

_BACKEND_TO_ENGINE = {
    "legacy_parquet": "legacy_parquet",
    "partitioned_parquet": "hybrid",
    "latest_snapshot": "legacy_parquet",
    "duckdb": "duckdb",
}
_EXPLICIT_ENGINES = {"legacy_parquet", "duckdb", "hybrid", "shadow_compare"}


@lru_cache(maxsize=1)
def routing_policy() -> dict[str, Any]:
    payload = json.loads(ROUTING_POLICY_PATH.read_text(encoding="utf-8"))
    routes = payload.get("routes")
    if not isinstance(routes, dict):
        raise TypeError(f"backend routing policy has no routes mapping: {ROUTING_POLICY_PATH}")
    return payload


def backend_for(query_type: str) -> str:
    """Return the declared production backend for one workload query type."""

    routes = routing_policy()["routes"]
    backend = routes.get(query_type)
    if backend not in _BACKEND_TO_ENGINE:
        raise ValueError(f"no backend route is declared for query type: {query_type!r}")
    return str(backend)


def reader_engine(query_type: str, *, explicit_engine: str | None = None) -> str:
    """Resolve a reader engine, allowing explicit diagnostic overrides only."""

    if explicit_engine is not None:
        if explicit_engine not in _EXPLICIT_ENGINES:
            raise ValueError(f"unsupported explicit reader engine: {explicit_engine!r}")
        return explicit_engine
    return _BACKEND_TO_ENGINE[backend_for(query_type)]


__all__ = ["ROUTING_POLICY_PATH", "backend_for", "reader_engine", "routing_policy"]

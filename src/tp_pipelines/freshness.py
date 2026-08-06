"""Point-in-time gates for market dates and run-generated timestamps."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    timestamp = pd.Timestamp(parsed)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def market_data_freshness(
    name: str,
    artifact_date: Any,
    *,
    as_of_date: Any,
    allowed_lag_days: int,
) -> dict[str, object]:
    """Require ``artifact_date <= as_of_date`` and a bounded non-negative lag."""

    artifact = _timestamp(artifact_date)
    as_of = _timestamp(as_of_date)
    base: dict[str, object] = {
        "name": name,
        "kind": "market_data_date",
        "artifact_date": artifact.date().isoformat() if artifact is not None else None,
        "as_of_date": as_of.date().isoformat() if as_of is not None else None,
        "allowed_lag_days": allowed_lag_days,
        "rule": "artifact_data_date <= as_of_date and as_of_date - artifact_data_date <= allowed_lag_days",
    }
    if artifact is None or as_of is None:
        return {
            **base,
            "lag_days": None,
            "ok": False,
            "message": "artifact date and as-of date are both required",
        }
    lag_days = int((as_of.normalize() - artifact.normalize()).days)
    if artifact.normalize() > as_of.normalize():
        message = "artifact data date is after the requested as-of date"
        ok = False
    elif lag_days > allowed_lag_days:
        message = "artifact data date is older than the allowed lag"
        ok = False
    else:
        message = "market data date is point-in-time compatible"
        ok = True
    return {**base, "lag_days": lag_days, "ok": ok, "message": message}


def generated_at_freshness(
    name: str,
    generated_at: Any,
    *,
    production_run_started_at: Any,
    reused: bool = False,
    reuse_source: str | None = None,
    reuse_reason: str | None = None,
) -> dict[str, object]:
    """Check execution time separately from the market data date."""

    generated = _timestamp(generated_at)
    started = _timestamp(production_run_started_at)
    base: dict[str, object] = {
        "name": name,
        "kind": "run_generation",
        "generated_at": generated.isoformat() if generated is not None else None,
        "production_run_started_at": started.isoformat() if started is not None else None,
        "rule": "generated_at >= production_run_started_at",
    }
    if reused:
        ok = bool(reuse_source and reuse_reason)
        return {
            **base,
            "ok": ok,
            "reused": True,
            "reuse_source": reuse_source,
            "reuse_reason": reuse_reason,
            "message": "explicit reuse recorded" if ok else "explicit reuse requires source and reason",
        }
    if generated is None or started is None:
        return {
            **base,
            "ok": False,
            "reused": False,
            "message": "generated_at and production_run_started_at are both required",
        }
    ok = generated >= started
    return {
        **base,
        "ok": ok,
        "reused": False,
        "message": "run artifact was generated during this production run"
        if ok
        else "run artifact was generated before this production run",
    }


__all__ = ["generated_at_freshness", "market_data_freshness"]

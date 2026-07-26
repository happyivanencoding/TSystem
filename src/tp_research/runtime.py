"""Common auditable runtime wrapper for research workflow entry points."""

from __future__ import annotations

import functools
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

import pandas as pd

from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH
from tp_core.security_nav_engine import NAV_ENGINE_ID, NAV_ENGINE_VERSION
from tp_experiments import ExperimentRecorder, ExperimentSpec
from tp_portfolio import OPTIMIZER_ID, OPTIMIZER_VERSION

P = ParamSpec("P")
R = TypeVar("R")
RESEARCH_SIGNAL_ID = "tp.research.factor-signal"
RESEARCH_SIGNAL_VERSION = "1.0.0"


def _argument_vector(args: tuple[Any, ...], kwargs: dict[str, Any]) -> list[str]:
    candidate = kwargs.get("argv")
    if candidate is None and args:
        candidate = args[0]
    if candidate is None:
        return list(sys.argv[1:])
    if isinstance(candidate, str):
        return [candidate]
    try:
        return list(candidate)
    except TypeError:
        return list(sys.argv[1:])


def _option(argv: list[str], name: str) -> str | None:
    prefix = f"{name}="
    for index, value in enumerate(argv):
        if value.startswith(prefix):
            return value[len(prefix) :]
        if value == name and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _infer_universe(workflow: str) -> str:
    lowered = workflow.lower()
    if "cross_market" in lowered:
        return "cross-market"
    if "stoxx600" in lowered:
        return "STOXX600"
    if "sp500" in lowered:
        return "SP500"
    if "nasdaq" in lowered:
        return "NASDAQ"
    if "eu_small" in lowered:
        return "EU-small-cap"
    return "all-supported"


def _canonical_sample_scope() -> tuple[str | None, str | None]:
    minima: list[pd.Timestamp] = []
    maxima: list[pd.Timestamp] = []
    try:
        screen = pd.read_parquet(SCREEN_AGGREGATE_PATH, columns=["Date"])
        dates = pd.to_datetime(screen["Date"], errors="coerce").dropna()
        if not dates.empty:
            minima.append(pd.Timestamp(dates.min()))
            maxima.append(pd.Timestamp(dates.max()))
    except Exception:
        pass
    try:
        returns = pd.read_parquet(RETURNS_PATH, columns=[])
        dates = pd.to_datetime(returns.index, errors="coerce")
        dates = dates[~pd.isna(dates)]
        if len(dates):
            minima.append(pd.Timestamp(dates.min()))
            maxima.append(pd.Timestamp(dates.max()))
    except Exception:
        pass
    sample_start = max(minima).date().isoformat() if minima else None
    pit_cutoff = min(maxima).date().isoformat() if maxima else None
    return sample_start, pit_cutoff


def _artifact_candidates(globals_: dict[str, Any]) -> dict[str, Path]:
    candidates: dict[str, Path] = {}
    markers = ("OUTPUT", "REPORT", "RESULT", "ARTIFACT", "HTML")
    for name, value in globals_.items():
        if not any(marker in name.upper() for marker in markers):
            continue
        if isinstance(value, Path):
            candidates[name.lower()] = value
        elif isinstance(value, str) and ("/" in value or "\\" in value):
            candidates[name.lower()] = Path(value)
    source = globals_.get("__file__")
    if source:
        candidates["workflow_source"] = Path(source)
    return candidates


def recorded_workflow(function: Callable[P, R]) -> Callable[P, R]:
    """Record config, lineage, data scope, artifacts, status, and decision."""

    @functools.wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        argv = _argument_vector(args, kwargs)
        if "-h" in argv or "--help" in argv:
            return function(*args, **kwargs)

        workflow = function.__module__.rsplit(".", 1)[-1]
        sample_start, canonical_cutoff = _canonical_sample_scope()
        explicit_end = (
            _option(argv, "--as-of")
            or _option(argv, "--to-date")
            or canonical_cutoff
            or "unresolved"
        )
        hypothesis_id = (
            _option(argv, "--hypothesis-id")
            or f"research-{workflow.replace('_', '-')}"
        )
        effective_trial_count = int(
            _option(argv, "--effective-trial-count") or 1
        )
        experiment = ExperimentRecorder(
            root=_option(argv, "--experiment-root")
        ).start_run(
            ExperimentSpec(
                hypothesis_id=hypothesis_id,
                name=f"Research workflow: {workflow}",
                universe=_infer_universe(workflow),
                sample_start=_option(argv, "--from-date")
                or _option(argv, "--start-date")
                or sample_start,
                sample_end=explicit_end,
                pit_cutoff=explicit_end,
                cost_assumptions={
                    "transaction_cost": float(
                        _option(argv, "--transaction-cost") or 0.0
                    ),
                    "slippage": float(_option(argv, "--slippage") or 0.0),
                },
                trial_family=_option(argv, "--trial-family") or workflow,
                effective_trial_count=effective_trial_count,
                component_versions={
                    "engine": f"{NAV_ENGINE_ID}:{NAV_ENGINE_VERSION}",
                    "signal": f"{RESEARCH_SIGNAL_ID}:{RESEARCH_SIGNAL_VERSION}",
                    "optimizer": f"{OPTIMIZER_ID}:{OPTIMIZER_VERSION}",
                },
                tags=("research", workflow),
            ),
            parameters={"workflow": workflow, "argv": argv},
            parent_run_id=os.environ.get("TP_PARENT_EXPERIMENT_RUN_ID"),
        )
        experiment.log_inputs(
            {
                "screen_aggregate": SCREEN_AGGREGATE_PATH,
                "returns": RETURNS_PATH,
            }
        )
        started = time.perf_counter()
        try:
            result = function(*args, **kwargs)
            experiment.log_metrics(
                {
                    "duration_seconds": round(time.perf_counter() - started, 3),
                    "exit_code": result if isinstance(result, int) else 0,
                }
            )
            experiment.log_artifacts(_artifact_candidates(function.__globals__))
            if isinstance(result, int) and result != 0:
                experiment.set_decision(
                    "reject",
                    reason=f"Workflow returned non-zero exit code {result}.",
                    decided_by="system",
                )
                experiment.complete(status="failed")
            else:
                experiment.set_decision(
                    "review_required",
                    reason="Research run completed; promotion requires gate review.",
                    decided_by="system",
                )
                experiment.complete()
            return result
        except BaseException as exc:
            if experiment.status == "running":
                experiment.log_artifacts(
                    _artifact_candidates(function.__globals__)
                )
                experiment.fail(exc)
            raise

    return wrapper


__all__ = ["recorded_workflow"]

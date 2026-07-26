"""Post-solve normalization, feasibility audit, and result construction."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tp_core.portfolio_weights import normalize_long_only_weights

from .contracts import (
    OPTIMIZER_ID,
    OPTIMIZER_VERSION,
    OptimizerConfig,
    PortfolioOptimizationResult,
)
from .inputs import PreparedInputs
from .problem import ProblemDefinition


def _constraint_rows(
    solved: np.ndarray,
    definition: ProblemDefinition,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    group_rows: list[dict[str, object]] = []
    for item in definition.group_audit_definitions:
        mask = np.asarray(item["mask"], dtype=bool)
        group_rows.append(
            {
                "name": item["name"],
                "key": str(item["key"]),
                "actual": float(solved[mask].sum()),
                "lower": item["lower"],
                "upper": item["upper"],
            }
        )

    linear_rows: list[dict[str, object]] = []
    for item in definition.linear_audit_definitions:
        coefficients = np.asarray(item["coefficients"], dtype=float)
        linear_rows.append(
            {
                "name": item["name"],
                "actual": float(coefficients @ solved),
                "lower": item["lower"],
                "upper": item["upper"],
            }
        )
    return group_rows, linear_rows


def _feasibility_violations(
    *,
    solved: np.ndarray,
    active_values: np.ndarray,
    tracking_error: float,
    portfolio_score: float,
    turnover: float,
    group_rows: list[dict[str, object]],
    linear_rows: list[dict[str, object]],
    inputs: PreparedInputs,
    config: OptimizerConfig,
) -> tuple[dict[str, float], int, float]:
    tolerance = max(1e-6, float(config.feasibility_tolerance) * 100.0)
    violations: dict[str, float] = {}

    def record_upper(name: str, actual: float, limit: float | int | None) -> None:
        if limit is not None and actual > float(limit) + tolerance:
            violations[name] = actual - float(limit)

    def record_lower(name: str, actual: float, limit: float | int | None) -> None:
        if limit is not None and actual < float(limit) - tolerance:
            violations[name] = float(limit) - actual

    record_upper(
        "security_upper_bound",
        float(np.maximum(solved - inputs.upper, 0.0).max()),
        0.0,
    )
    record_upper(
        "security_lower_bound",
        float(np.maximum(inputs.lower - solved, 0.0).max()),
        0.0,
    )
    record_upper(
        "max_active_weight",
        float(np.abs(active_values).max()),
        config.max_active_weight,
    )
    record_upper("max_turnover", turnover, config.max_turnover)
    record_upper("max_tracking_error", tracking_error, config.max_tracking_error)
    record_lower("min_score", portfolio_score, config.min_score)
    record_upper("max_score", portfolio_score, config.max_score)
    holdings = int((solved > config.feasibility_tolerance).sum())
    record_lower("min_holdings", float(holdings), config.min_holdings)
    record_upper("max_holdings", float(holdings), config.max_holdings)

    for row in group_rows:
        prefix = f"group:{row['name']}:{row['key']}"
        record_lower(prefix + ":lower", float(row["actual"]), row["lower"])
        record_upper(prefix + ":upper", float(row["actual"]), row["upper"])
    for row in linear_rows:
        prefix = f"linear:{row['name']}"
        record_lower(prefix + ":lower", float(row["actual"]), row["lower"])
        record_upper(prefix + ":upper", float(row["actual"]), row["upper"])
    if inputs.forced.any():
        record_lower(
            "forced_security_weight",
            float(solved[inputs.forced].min()),
            max(
                float(config.min_weight_if_selected),
                float(config.feasibility_tolerance) * 10.0,
            ),
        )
    if inputs.forbidden.any():
        record_upper(
            "forbidden_security_weight",
            float(solved[inputs.forbidden].max()),
            0.0,
        )
    return violations, holdings, tolerance


def build_result(
    candidates: pd.DataFrame,
    *,
    inputs: PreparedInputs,
    definition: ProblemDefinition,
    config: OptimizerConfig,
    solver: str,
    solver_errors: list[str],
) -> PortfolioOptimizationResult:
    """Normalize solver output, prove feasibility, and return the stable contract."""

    solved = np.asarray(definition.weights.value, dtype=float).reshape(-1)
    if config.long_only:
        solved = np.clip(solved, 0.0, None)
    weights = normalize_long_only_weights(pd.Series(solved, index=candidates.index))
    solved = weights.to_numpy(dtype=float)
    active_values = solved - inputs.benchmark
    tracking_error = float(
        np.sqrt(max(0.0, active_values @ inputs.covariance @ active_values))
    )
    portfolio_score = float(inputs.score @ solved)
    turnover = float(
        np.abs(solved - inputs.current).sum() + inputs.external_weight
    )
    group_rows, linear_rows = _constraint_rows(solved, definition)
    violations, holdings, tolerance = _feasibility_violations(
        solved=solved,
        active_values=active_values,
        tracking_error=tracking_error,
        portfolio_score=portfolio_score,
        turnover=turnover,
        group_rows=group_rows,
        linear_rows=linear_rows,
        inputs=inputs,
        config=config,
    )
    if violations:
        details = ", ".join(
            f"{name}={value:.3g}" for name, value in sorted(violations.items())
        )
        raise RuntimeError(
            "solver returned a post-processed portfolio outside constraints: "
            + details
        )

    audit = {
        "weight_sum": float(solved.sum()),
        "min_weight": float(solved.min()),
        "max_weight": float(solved.max()),
        "holdings": holdings,
        "tracking_error": tracking_error,
        "portfolio_score": portfolio_score,
        "two_way_turnover": turnover,
        "one_way_turnover": turnover / 2.0,
        "active_share": float(np.abs(active_values).sum() / 2.0),
        "max_abs_active_weight": float(np.abs(active_values).max()),
        "max_lower_bound_violation": float(
            np.maximum(inputs.lower - solved, 0.0).max()
        ),
        "max_upper_bound_violation": float(
            np.maximum(solved - inputs.upper, 0.0).max()
        ),
        "group_constraints": group_rows,
        "linear_constraints": linear_rows,
        "covariance_min_eigenvalue_before_projection": (
            inputs.covariance_min_eigenvalue
        ),
        "solver_attempt_errors": solver_errors,
        "feasibility_tolerance": tolerance,
        "constraint_violations": violations,
    }
    metadata = {
        "optimizer_id": OPTIMIZER_ID,
        "optimizer_version": OPTIMIZER_VERSION,
        "objective": definition.objective.value,
        "objective_policy": {
            "score_weight": float(config.score_weight),
            "tracking_error_weight": float(config.tracking_error_weight),
            "turnover_weight": float(config.turnover_weight),
            "active_weight_penalty": float(config.active_weight_penalty),
            "covariance_units": "caller_supplied",
        },
        "solver": solver,
        "status": str(definition.problem.status),
        "constraint_policy": {
            "long_only": config.long_only,
            "min_score": config.min_score,
            "max_score": config.max_score,
            "max_tracking_error": config.max_tracking_error,
            "max_turnover": config.max_turnover,
            "external_current_weight": inputs.external_weight,
            "max_active_weight": config.max_active_weight,
            "min_holdings": config.min_holdings,
            "max_holdings": config.max_holdings,
            "min_weight_if_selected": config.min_weight_if_selected,
            "forced_ids": [str(value) for value in config.forced_ids],
            "forbidden_ids": [str(value) for value in config.forbidden_ids],
            "group_constraint_count": len(definition.group_audit_definitions),
            "linear_constraint_count": len(definition.linear_audit_definitions),
        },
    }
    return PortfolioOptimizationResult(
        weights=weights,
        status=str(definition.problem.status),
        solver=solver,
        objective=definition.objective.value,
        objective_value=(
            float(definition.problem.value)
            if definition.problem.value is not None
            else None
        ),
        audit=audit,
        metadata=metadata,
    )

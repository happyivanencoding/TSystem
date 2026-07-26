"""cvxpy variables, constraints, and objective construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .contracts import (
    GroupConstraint,
    LinearConstraint,
    OptimizerConfig,
    OptimizerObjective,
)
from .inputs import PreparedInputs, candidate_vector
from .solver import require_cvxpy


@dataclass(frozen=True)
class ProblemDefinition:
    problem: Any
    weights: Any
    objective: OptimizerObjective
    group_audit_definitions: list[dict[str, object]]
    linear_audit_definitions: list[dict[str, object]]


def _cardinality_constraints(
    weights,
    inputs: PreparedInputs,
    config: OptimizerConfig,
) -> tuple[list[Any], Any | None]:
    cvxpy = require_cvxpy()
    if not inputs.uses_cardinality:
        return [weights >= inputs.lower, weights <= inputs.upper], None

    selected = cvxpy.Variable(len(inputs.benchmark), boolean=True)
    selected_floor = max(
        float(config.min_weight_if_selected),
        float(config.feasibility_tolerance) * 10.0,
    )
    selected_lower = np.maximum(inputs.lower, selected_floor)
    constraints = [
        weights >= cvxpy.multiply(selected_lower, selected),
        weights <= cvxpy.multiply(inputs.upper, selected),
    ]
    if config.min_holdings is not None:
        constraints.append(cvxpy.sum(selected) >= int(config.min_holdings))
    if config.max_holdings is not None:
        constraints.append(cvxpy.sum(selected) <= int(config.max_holdings))
    if inputs.forced.any():
        constraints.append(selected[np.flatnonzero(inputs.forced)] == 1)
    if inputs.forbidden.any():
        constraints.append(selected[np.flatnonzero(inputs.forbidden)] == 0)
    return constraints, selected


def _group_constraints(
    candidates: pd.DataFrame,
    weights,
    definitions: Sequence[GroupConstraint],
    config: OptimizerConfig,
) -> tuple[list[Any], list[dict[str, object]]]:
    cvxpy = require_cvxpy()
    constraints: list[Any] = []
    audit_definitions: list[dict[str, object]] = []
    for definition in definitions:
        if definition.group_col not in candidates.columns:
            raise KeyError(
                f"group constraint {definition.name} references missing column "
                f"{definition.group_col}"
            )
        groups = candidates[definition.group_col]
        all_keys = set(definition.lower_bounds) | set(definition.upper_bounds)
        for key in all_keys:
            mask = groups.eq(key).fillna(False).to_numpy(dtype=bool)
            lower_value = definition.lower_bounds.get(key)
            upper_value = definition.upper_bounds.get(key)
            if not mask.any():
                if (
                    lower_value is not None
                    and float(lower_value) > config.feasibility_tolerance
                ):
                    raise ValueError(
                        f"group constraint {definition.name}:{key} has a positive lower "
                        "bound but no eligible security"
                    )
                continue
            expression = cvxpy.sum(weights[np.flatnonzero(mask)])
            if lower_value is not None:
                constraints.append(expression >= float(lower_value))
            if upper_value is not None:
                constraints.append(expression <= float(upper_value))
            audit_definitions.append(
                {
                    "name": definition.name,
                    "key": key,
                    "mask": mask,
                    "lower": lower_value,
                    "upper": upper_value,
                }
            )
    return constraints, audit_definitions


def _linear_constraints(
    candidates: pd.DataFrame,
    weights,
    definitions: Sequence[LinearConstraint],
) -> tuple[list[Any], list[dict[str, object]]]:
    constraints: list[Any] = []
    audit_definitions: list[dict[str, object]] = []
    for definition in definitions:
        coefficients = candidate_vector(
            candidates,
            definition.coefficients,
            name=f"linear constraint {definition.name}",
            default=0.0,
        )
        expression = coefficients @ weights
        if definition.lower is not None:
            constraints.append(expression >= float(definition.lower))
        if definition.upper is not None:
            constraints.append(expression <= float(definition.upper))
        audit_definitions.append(
            {
                "name": definition.name,
                "coefficients": coefficients,
                "lower": definition.lower,
                "upper": definition.upper,
            }
        )
    return constraints, audit_definitions


def _objective_expression(
    *,
    objective: OptimizerObjective,
    tracking_error_variance,
    portfolio_variance,
    score_expression,
    turnover_expression,
    active_weight_l2,
    config: OptimizerConfig,
):
    if objective == OptimizerObjective.MIN_TRACKING_ERROR:
        expression = config.tracking_error_weight * tracking_error_variance
    elif objective == OptimizerObjective.MAX_SCORE:
        expression = -config.score_weight * score_expression
    elif objective == OptimizerObjective.MIN_TURNOVER:
        expression = config.turnover_weight * turnover_expression
        if config.turnover_weight == 0:
            expression = turnover_expression
    elif objective == OptimizerObjective.MIN_VARIANCE:
        expression = config.tracking_error_weight * portfolio_variance
    else:
        expression = (
            config.tracking_error_weight * tracking_error_variance
            - config.score_weight * score_expression
        )

    if objective != OptimizerObjective.MIN_TURNOVER and config.turnover_weight:
        expression += config.turnover_weight * turnover_expression
    if config.active_weight_penalty:
        expression += config.active_weight_penalty * active_weight_l2
    return expression


def build_problem(
    candidates: pd.DataFrame,
    *,
    inputs: PreparedInputs,
    group_constraints: Sequence[GroupConstraint],
    linear_constraints: Sequence[LinearConstraint],
    config: OptimizerConfig,
) -> ProblemDefinition:
    """Build the public optimization problem without solving or post-processing it."""

    cvxpy = require_cvxpy()
    objective = OptimizerObjective(config.objective)
    weights = cvxpy.Variable(len(candidates))
    constraints: list[Any] = [cvxpy.sum(weights) == 1.0]
    cardinality, _selected = _cardinality_constraints(weights, inputs, config)
    constraints.extend(cardinality)

    active = weights - inputs.benchmark
    tracking_error_variance = cvxpy.quad_form(active, inputs.covariance)
    portfolio_variance = cvxpy.quad_form(weights, inputs.covariance)
    score_expression = inputs.score @ weights
    turnover_expression = (
        cvxpy.norm1(weights - inputs.current) + inputs.external_weight
    )
    active_weight_l2 = cvxpy.sum_squares(active)

    if config.max_active_weight is not None:
        limit = float(config.max_active_weight)
        constraints.extend([active <= limit, active >= -limit])
    if config.max_turnover is not None:
        constraints.append(turnover_expression <= float(config.max_turnover))
    if config.max_tracking_error is not None:
        constraints.append(
            tracking_error_variance <= float(config.max_tracking_error) ** 2
        )
    if config.min_score is not None:
        constraints.append(score_expression >= float(config.min_score))
    if config.max_score is not None:
        constraints.append(score_expression <= float(config.max_score))

    group_rows, group_audit = _group_constraints(
        candidates,
        weights,
        group_constraints,
        config,
    )
    linear_rows, linear_audit = _linear_constraints(
        candidates,
        weights,
        linear_constraints,
    )
    constraints.extend(group_rows)
    constraints.extend(linear_rows)

    expression = _objective_expression(
        objective=objective,
        tracking_error_variance=tracking_error_variance,
        portfolio_variance=portfolio_variance,
        score_expression=score_expression,
        turnover_expression=turnover_expression,
        active_weight_l2=active_weight_l2,
        config=config,
    )
    problem = cvxpy.Problem(cvxpy.Minimize(expression), constraints)
    return ProblemDefinition(
        problem=problem,
        weights=weights,
        objective=objective,
        group_audit_definitions=group_audit,
        linear_audit_definitions=linear_audit,
    )

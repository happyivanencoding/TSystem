"""cvxpy variables, constraints, and objective construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import pandas as pd

from .contracts import (
    GroupConstraint,
    LinearConstraint,
    OptimizerConfig,
    OptimizerObjective,
)
from .constraints import (
    build_cardinality_constraints,
    build_group_constraints,
    build_linear_constraints,
)
from .inputs import PreparedInputs
from .objective import build_objective_expression
from .solver import require_cvxpy


@dataclass(frozen=True)
class ProblemDefinition:
    problem: Any
    weights: Any
    objective: OptimizerObjective
    group_audit_definitions: list[dict[str, object]]
    linear_audit_definitions: list[dict[str, object]]


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
    cardinality, _selected = build_cardinality_constraints(
        weights,
        inputs,
        config,
    )
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

    group_rows, group_audit = build_group_constraints(
        candidates,
        weights,
        group_constraints,
        config,
    )
    linear_rows, linear_audit = build_linear_constraints(
        candidates,
        weights,
        linear_constraints,
    )
    constraints.extend(group_rows)
    constraints.extend(linear_rows)

    expression = build_objective_expression(
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

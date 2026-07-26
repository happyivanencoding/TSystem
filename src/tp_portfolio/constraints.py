"""Constraint construction for the canonical portfolio optimizer."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd

from .contracts import GroupConstraint, LinearConstraint, OptimizerConfig
from .inputs import PreparedInputs, candidate_vector
from .solver import require_cvxpy


def build_cardinality_constraints(
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


def build_group_constraints(
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


def build_linear_constraints(
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


__all__ = [
    "build_cardinality_constraints",
    "build_group_constraints",
    "build_linear_constraints",
]

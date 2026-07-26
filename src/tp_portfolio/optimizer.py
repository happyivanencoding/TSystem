"""Sole TP portfolio optimizer API with explicit objectives and constraints."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from .audit import build_result
from .contracts import (
    OPTIMIZER_ID,
    OPTIMIZER_VERSION,
    GroupConstraint,
    LinearConstraint,
    OptimizerConfig,
    OptimizerObjective,
    PortfolioOptimizationResult,
)
from .inputs import prepare_inputs
from .problem import build_problem
from .solver import OPTIMAL_STATUSES, solve_problem


def optimize_portfolio(
    candidates: pd.DataFrame,
    *,
    id_col: str,
    benchmark_weights: str | Sequence[float] | pd.Series | np.ndarray,
    scores: str | Sequence[float] | pd.Series | np.ndarray | None = None,
    covariance: np.ndarray | pd.DataFrame | None = None,
    current_weights: str | Sequence[float] | pd.Series | np.ndarray | None = None,
    external_current_weight: float = 0.0,
    lower_bounds: str | Sequence[float] | pd.Series | np.ndarray | None = None,
    upper_bounds: str | Sequence[float] | pd.Series | np.ndarray | None = None,
    group_constraints: Sequence[GroupConstraint] = (),
    linear_constraints: Sequence[LinearConstraint] = (),
    config: OptimizerConfig = OptimizerConfig(),
) -> PortfolioOptimizationResult:
    """Optimize one portfolio under explicit objective and constraint settings."""

    inputs = prepare_inputs(
        candidates,
        id_col=id_col,
        benchmark_weights=benchmark_weights,
        scores=scores,
        covariance=covariance,
        current_weights=current_weights,
        external_current_weight=external_current_weight,
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        config=config,
    )
    definition = build_problem(
        candidates,
        inputs=inputs,
        group_constraints=group_constraints,
        linear_constraints=linear_constraints,
        config=config,
    )
    solver, solver_errors = solve_problem(
        definition.problem,
        config,
        mixed_integer=inputs.uses_cardinality,
    )
    return build_result(
        candidates,
        inputs=inputs,
        definition=definition,
        config=config,
        solver=solver,
        solver_errors=solver_errors,
    )


__all__ = [
    "OPTIMIZER_ID",
    "OPTIMIZER_VERSION",
    "GroupConstraint",
    "LinearConstraint",
    "OptimizerConfig",
    "OptimizerObjective",
    "PortfolioOptimizationResult",
    "optimize_portfolio",
]

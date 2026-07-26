"""Stable public optimizer contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


OPTIMIZER_ID = "tp.optimizer"
OPTIMIZER_VERSION = "3.0.0"


class OptimizerObjective(str, Enum):
    """Supported primary objectives."""

    MIN_TRACKING_ERROR = "min_tracking_error"
    MAX_SCORE = "max_score"
    MIN_TURNOVER = "min_turnover"
    MIN_VARIANCE = "min_variance"
    BLENDED = "blended"


@dataclass(frozen=True)
class LinearConstraint:
    """A generic linear exposure constraint: lower <= coefficients @ w <= upper."""

    name: str
    coefficients: Sequence[float] | pd.Series | np.ndarray
    lower: float | None = None
    upper: float | None = None


@dataclass(frozen=True)
class GroupConstraint:
    """Lower and upper portfolio-weight bounds for categories in one column."""

    name: str
    group_col: str
    lower_bounds: Mapping[object, float] = field(default_factory=dict)
    upper_bounds: Mapping[object, float] = field(default_factory=dict)

    @classmethod
    def around_targets(
        cls,
        *,
        name: str,
        group_col: str,
        targets: Mapping[object, float],
        margin: float,
    ) -> "GroupConstraint":
        lower = {
            key: max(0.0, float(value) - float(margin))
            for key, value in targets.items()
        }
        upper = {
            key: min(1.0, float(value) + float(margin))
            for key, value in targets.items()
        }
        return cls(
            name=name,
            group_col=group_col,
            lower_bounds=lower,
            upper_bounds=upper,
        )


@dataclass(frozen=True)
class OptimizerConfig:
    """Objective, solver and portfolio-wide constraint configuration."""

    objective: OptimizerObjective | str = OptimizerObjective.MIN_TRACKING_ERROR
    score_weight: float = 1.0
    tracking_error_weight: float = 1.0
    turnover_weight: float = 0.0
    active_weight_penalty: float = 0.0
    min_score: float | None = None
    max_score: float | None = None
    max_tracking_error: float | None = None
    max_turnover: float | None = None
    max_active_weight: float | None = None
    min_holdings: int | None = None
    max_holdings: int | None = None
    min_weight_if_selected: float = 0.0
    long_only: bool = True
    forced_ids: Sequence[object] = field(default_factory=tuple)
    forbidden_ids: Sequence[object] = field(default_factory=tuple)
    solver_order: Sequence[str] = field(default_factory=tuple)
    verbose: bool = False
    feasibility_tolerance: float = 1e-7


@dataclass
class PortfolioOptimizationResult:
    """Stable result contract for every TP optimization objective."""

    weights: pd.Series
    status: str
    solver: str
    objective: str
    objective_value: float | None
    audit: dict[str, object]
    metadata: dict[str, object]

    def to_frame(
        self,
        candidates: pd.DataFrame,
        *,
        weight_col: str = "target_weight",
    ) -> pd.DataFrame:
        result = candidates.copy()
        result[weight_col] = self.weights.reindex(result.index).to_numpy(dtype=float)
        result["optimizer_id"] = OPTIMIZER_ID
        result["optimizer_version"] = OPTIMIZER_VERSION
        result["optimizer_objective"] = self.objective
        result["optimizer_solver"] = self.solver
        result["optimizer_status"] = self.status
        return result

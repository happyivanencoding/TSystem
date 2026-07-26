"""Validation and normalization of optimizer inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from tp_core.portfolio_weights import normalize_long_only_weights

from .contracts import OptimizerConfig, OptimizerObjective


@dataclass(frozen=True)
class PreparedInputs:
    benchmark: np.ndarray
    score: np.ndarray
    current: np.ndarray
    external_weight: float
    lower: np.ndarray
    upper: np.ndarray
    covariance: np.ndarray
    covariance_min_eigenvalue: float | None
    forced: np.ndarray
    forbidden: np.ndarray
    uses_cardinality: bool


def candidate_vector(
    candidates: pd.DataFrame,
    values: str | Sequence[float] | pd.Series | np.ndarray | None,
    *,
    name: str,
    default: float,
) -> np.ndarray:
    if values is None:
        return np.full(len(candidates), float(default), dtype=float)
    if isinstance(values, str):
        if values not in candidates.columns:
            raise KeyError(f"candidate table is missing {name} column: {values}")
        source = candidates[values]
    elif isinstance(values, pd.Series):
        source = values.reindex(candidates.index)
    else:
        source = pd.Series(values, index=candidates.index)
    vector = pd.to_numeric(source, errors="coerce").to_numpy(dtype=float)
    if len(vector) != len(candidates):
        raise ValueError(f"{name} must have one value per candidate")
    if not np.isfinite(vector).all():
        raise ValueError(f"{name} contains NaN or infinite values")
    return vector


def positive_semidefinite(matrix: np.ndarray) -> tuple[np.ndarray, float]:
    covariance = np.asarray(matrix, dtype=float)
    if covariance.ndim != 2 or covariance.shape[0] != covariance.shape[1]:
        raise ValueError("covariance must be a square matrix")
    if not np.isfinite(covariance).all():
        raise ValueError("covariance contains NaN or infinite values")
    covariance = (covariance + covariance.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    minimum = float(eigenvalues.min())
    if minimum < 0:
        eigenvalues = np.clip(eigenvalues, 0.0, None)
        covariance = (eigenvectors * eigenvalues) @ eigenvectors.T
        covariance = (covariance + covariance.T) / 2.0
    return covariance, minimum


def prepare_inputs(
    candidates: pd.DataFrame,
    *,
    id_col: str,
    benchmark_weights: str | Sequence[float] | pd.Series | np.ndarray,
    scores: str | Sequence[float] | pd.Series | np.ndarray | None,
    covariance: np.ndarray | pd.DataFrame | None,
    current_weights: str | Sequence[float] | pd.Series | np.ndarray | None,
    external_current_weight: float,
    lower_bounds: str | Sequence[float] | pd.Series | np.ndarray | None,
    upper_bounds: str | Sequence[float] | pd.Series | np.ndarray | None,
    config: OptimizerConfig,
) -> PreparedInputs:
    """Validate caller data and resolve the vectors consumed by cvxpy."""

    if candidates.empty:
        raise ValueError("candidate table is empty")
    if not candidates.index.is_unique:
        raise ValueError("candidate table index must be unique")
    if id_col not in candidates.columns:
        raise KeyError(f"candidate table is missing id column: {id_col}")

    objective_kind = OptimizerObjective(config.objective)
    benchmark = candidate_vector(
        candidates,
        benchmark_weights,
        name="benchmark_weights",
        default=0.0,
    )
    benchmark = normalize_long_only_weights(
        pd.Series(benchmark, index=candidates.index),
        allow_equal_fallback=True,
    ).to_numpy(dtype=float)
    score = candidate_vector(candidates, scores, name="scores", default=0.0)
    current = candidate_vector(
        candidates,
        current_weights,
        name="current_weights",
        default=0.0,
    )
    external_weight = float(external_current_weight)
    if not np.isfinite(external_weight) or external_weight < 0:
        raise ValueError("external_current_weight must be finite and non-negative")
    if current_weights is None:
        if external_weight > config.feasibility_tolerance:
            raise ValueError("external_current_weight requires explicit current_weights")
        current = benchmark.copy()
    elif external_weight > 0:
        if config.long_only and (current < -config.feasibility_tolerance).any():
            raise ValueError("current_weights must be non-negative for long-only portfolios")
        total_current = float(current.sum()) + external_weight
        if abs(total_current - 1.0) > config.feasibility_tolerance:
            raise ValueError(
                "current_weights plus external_current_weight must sum to one"
            )
    elif current.sum() > 0:
        current = normalize_long_only_weights(
            pd.Series(current, index=candidates.index)
        ).to_numpy(dtype=float)

    lower = candidate_vector(candidates, lower_bounds, name="lower_bounds", default=0.0)
    upper = candidate_vector(candidates, upper_bounds, name="upper_bounds", default=1.0)
    if config.long_only:
        lower = np.maximum(lower, 0.0)
    if (lower > upper + config.feasibility_tolerance).any():
        raise ValueError("one or more lower bounds exceed upper bounds")
    if float(lower.sum()) > 1.0 + config.feasibility_tolerance:
        raise ValueError("security lower bounds sum to more than one")
    if float(upper.sum()) < 1.0 - config.feasibility_tolerance:
        raise ValueError("security upper bounds sum to less than one")

    covariance_min_eigenvalue = None
    if covariance is None:
        needs_covariance = (
            objective_kind
            in {
                OptimizerObjective.MIN_TRACKING_ERROR,
                OptimizerObjective.MIN_VARIANCE,
            }
            or config.max_tracking_error is not None
            or config.tracking_error_weight > 0
        )
        covariance_matrix = (
            np.eye(len(candidates), dtype=float)
            if needs_covariance
            else np.zeros((len(candidates), len(candidates)), dtype=float)
        )
    else:
        covariance_matrix, covariance_min_eigenvalue = positive_semidefinite(
            np.asarray(covariance, dtype=float)
        )
        if covariance_matrix.shape != (len(candidates), len(candidates)):
            raise ValueError("covariance dimensions must match the candidate count")

    ids = candidates[id_col].astype(str)
    forced = ids.isin({str(value) for value in config.forced_ids}).to_numpy()
    forbidden = ids.isin({str(value) for value in config.forbidden_ids}).to_numpy()
    if (forced & forbidden).any():
        raise ValueError("a security cannot be both forced and forbidden")
    upper = upper.copy()
    upper[forbidden] = 0.0
    uses_cardinality = (
        config.min_holdings is not None
        or config.max_holdings is not None
        or forced.any()
        or forbidden.any()
    )
    return PreparedInputs(
        benchmark=benchmark,
        score=score,
        current=current,
        external_weight=external_weight,
        lower=lower,
        upper=upper,
        covariance=covariance_matrix,
        covariance_min_eigenvalue=covariance_min_eigenvalue,
        forced=forced,
        forbidden=forbidden,
        uses_cardinality=uses_cardinality,
    )

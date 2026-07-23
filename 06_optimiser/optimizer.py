"""Sole TP portfolio optimizer API with explicit objectives and constraints."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

try:
    import cvxpy as cp
    _CVXPY_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - depends on local solver stack
    cp = None
    _CVXPY_IMPORT_ERROR = exc

from tp_core.portfolio_weights import normalize_long_only_weights


OPTIMIZER_ID = "tp.optimizer"
OPTIMIZER_VERSION = "3.0.0"
OPTIMAL_STATUSES = {"optimal", "optimal_inaccurate"}


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
        lower = {key: max(0.0, float(value) - float(margin)) for key, value in targets.items()}
        upper = {key: min(1.0, float(value) + float(margin)) for key, value in targets.items()}
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


def _require_cvxpy():
    """Return cvxpy or raise a clear environment error."""
    if cp is None:
        raise ImportError(
            "cvxpy is required for the download_09 optimizer engine, but it cannot be imported. "
            f"Original error: {_CVXPY_IMPORT_ERROR}"
        )
    return cp


def _candidate_vector(
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


def _positive_semidefinite(matrix: np.ndarray) -> tuple[np.ndarray, float]:
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


def _solve_public_problem(problem, config: OptimizerConfig, *, mixed_integer: bool) -> tuple[str, list[str]]:
    cvxpy = _require_cvxpy()
    installed = set(cvxpy.installed_solvers())
    if config.solver_order:
        order = list(config.solver_order)
    elif mixed_integer:
        order = ["ECOS_BB", "SCIP", "HIGHS", "SCIPY"]
    else:
        order = ["CLARABEL", "OSQP", "ECOS", "HIGHS", "SCS", "SCIPY"]

    errors: list[str] = []
    for solver in order:
        if solver not in installed:
            continue
        try:
            problem.solve(solver=solver, verbose=config.verbose, warm_start=True)
        except Exception as exc:
            errors.append(f"{solver}: {type(exc).__name__}: {exc}")
            continue
        if problem.status in OPTIMAL_STATUSES:
            return solver, errors
        errors.append(f"{solver}: status={problem.status}")
    raise RuntimeError(
        "portfolio optimization failed with every available solver"
        + (": " + " | ".join(errors) if errors else "")
    )


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

    cvxpy = _require_cvxpy()
    if candidates.empty:
        raise ValueError("candidate table is empty")
    if not candidates.index.is_unique:
        raise ValueError("candidate table index must be unique")
    if id_col not in candidates.columns:
        raise KeyError(f"candidate table is missing id column: {id_col}")

    objective_kind = OptimizerObjective(config.objective)
    benchmark = _candidate_vector(
        candidates,
        benchmark_weights,
        name="benchmark_weights",
        default=0.0,
    )
    benchmark = normalize_long_only_weights(
        pd.Series(benchmark, index=candidates.index),
        allow_equal_fallback=True,
    ).to_numpy(dtype=float)
    score = _candidate_vector(candidates, scores, name="scores", default=0.0)
    current = _candidate_vector(
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
            raise ValueError(
                "external_current_weight requires explicit current_weights"
            )
        current = benchmark.copy()
    elif external_weight > 0:
        if config.long_only and (current < -config.feasibility_tolerance).any():
            raise ValueError(
                "current_weights must be non-negative for long-only portfolios"
            )
        total_current = float(current.sum()) + external_weight
        if abs(total_current - 1.0) > config.feasibility_tolerance:
            raise ValueError(
                "current_weights plus external_current_weight must sum to one"
            )
    elif current.sum() > 0:
        current = normalize_long_only_weights(
            pd.Series(current, index=candidates.index)
        ).to_numpy(dtype=float)

    lower = _candidate_vector(
        candidates,
        lower_bounds,
        name="lower_bounds",
        default=0.0,
    )
    upper = _candidate_vector(
        candidates,
        upper_bounds,
        name="upper_bounds",
        default=1.0,
    )
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
        if objective_kind in {
            OptimizerObjective.MIN_TRACKING_ERROR,
            OptimizerObjective.MIN_VARIANCE,
        } or config.max_tracking_error is not None or config.tracking_error_weight > 0:
            covariance_matrix = np.eye(len(candidates), dtype=float)
        else:
            covariance_matrix = np.zeros((len(candidates), len(candidates)), dtype=float)
    else:
        covariance_matrix, covariance_min_eigenvalue = _positive_semidefinite(
            np.asarray(covariance, dtype=float)
        )
        if covariance_matrix.shape != (len(candidates), len(candidates)):
            raise ValueError("covariance dimensions must match the candidate count")

    forced = candidates[id_col].astype(str).isin({str(value) for value in config.forced_ids}).to_numpy()
    forbidden = candidates[id_col].astype(str).isin({str(value) for value in config.forbidden_ids}).to_numpy()
    if (forced & forbidden).any():
        raise ValueError("a security cannot be both forced and forbidden")
    upper = upper.copy()
    upper[forbidden] = 0.0

    uses_cardinality = any(
        value is not None
        for value in (config.min_holdings, config.max_holdings)
    ) or forced.any() or forbidden.any()
    w = cvxpy.Variable(len(candidates))
    selected = cvxpy.Variable(len(candidates), boolean=True) if uses_cardinality else None
    constraints = [cvxpy.sum(w) == 1.0]
    if selected is None:
        constraints.extend([w >= lower, w <= upper])
    else:
        effective_selected_floor = max(
            float(config.min_weight_if_selected),
            float(config.feasibility_tolerance) * 10.0,
        )
        selected_lower = np.maximum(lower, effective_selected_floor)
        constraints.extend(
            [
                w >= cvxpy.multiply(selected_lower, selected),
                w <= cvxpy.multiply(upper, selected),
            ]
        )
        if config.min_holdings is not None:
            constraints.append(cvxpy.sum(selected) >= int(config.min_holdings))
        if config.max_holdings is not None:
            constraints.append(cvxpy.sum(selected) <= int(config.max_holdings))
        if forced.any():
            constraints.append(selected[np.flatnonzero(forced)] == 1)
        if forbidden.any():
            constraints.append(selected[np.flatnonzero(forbidden)] == 0)

    active = w - benchmark
    tracking_error_variance = cvxpy.quad_form(active, covariance_matrix)
    portfolio_variance = cvxpy.quad_form(w, covariance_matrix)
    score_expression = score @ w
    turnover_expression = cvxpy.norm1(w - current) + external_weight
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

    group_audit_definitions: list[dict[str, object]] = []
    for definition in group_constraints:
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
                if lower_value is not None and float(lower_value) > config.feasibility_tolerance:
                    raise ValueError(
                        f"group constraint {definition.name}:{key} has a positive lower "
                        "bound but no eligible security"
                    )
                continue
            expression = cvxpy.sum(w[np.flatnonzero(mask)])
            if lower_value is not None:
                constraints.append(expression >= float(lower_value))
            if upper_value is not None:
                constraints.append(expression <= float(upper_value))
            group_audit_definitions.append(
                {
                    "name": definition.name,
                    "key": key,
                    "mask": mask,
                    "lower": lower_value,
                    "upper": upper_value,
                }
            )

    linear_audit_definitions: list[dict[str, object]] = []
    for definition in linear_constraints:
        coefficients = _candidate_vector(
            candidates,
            definition.coefficients,
            name=f"linear constraint {definition.name}",
            default=0.0,
        )
        expression = coefficients @ w
        if definition.lower is not None:
            constraints.append(expression >= float(definition.lower))
        if definition.upper is not None:
            constraints.append(expression <= float(definition.upper))
        linear_audit_definitions.append(
            {
                "name": definition.name,
                "coefficients": coefficients,
                "lower": definition.lower,
                "upper": definition.upper,
            }
        )

    if objective_kind == OptimizerObjective.MIN_TRACKING_ERROR:
        expression = config.tracking_error_weight * tracking_error_variance
    elif objective_kind == OptimizerObjective.MAX_SCORE:
        expression = -config.score_weight * score_expression
    elif objective_kind == OptimizerObjective.MIN_TURNOVER:
        expression = config.turnover_weight * turnover_expression
        if config.turnover_weight == 0:
            expression = turnover_expression
    elif objective_kind == OptimizerObjective.MIN_VARIANCE:
        expression = config.tracking_error_weight * portfolio_variance
    else:
        expression = (
            config.tracking_error_weight * tracking_error_variance
            - config.score_weight * score_expression
        )

    if objective_kind != OptimizerObjective.MIN_TURNOVER and config.turnover_weight:
        expression += config.turnover_weight * turnover_expression
    if config.active_weight_penalty:
        expression += config.active_weight_penalty * active_weight_l2

    problem = cvxpy.Problem(cvxpy.Minimize(expression), constraints)
    solver, solver_errors = _solve_public_problem(
        problem,
        config,
        mixed_integer=uses_cardinality,
    )
    solved = np.asarray(w.value, dtype=float).reshape(-1)
    if config.long_only:
        solved = np.clip(solved, 0.0, None)
    weights = normalize_long_only_weights(
        pd.Series(solved, index=candidates.index)
    )
    solved = weights.to_numpy(dtype=float)
    active_values = solved - benchmark
    tracking_error = float(
        np.sqrt(max(0.0, active_values @ covariance_matrix @ active_values))
    )
    portfolio_score = float(score @ solved)
    turnover = float(np.abs(solved - current).sum() + external_weight)

    group_rows = []
    for definition in group_audit_definitions:
        actual = float(solved[definition["mask"]].sum())
        group_rows.append(
            {
                "name": definition["name"],
                "key": str(definition["key"]),
                "actual": actual,
                "lower": definition["lower"],
                "upper": definition["upper"],
            }
        )
    linear_rows = []
    for definition in linear_audit_definitions:
        actual = float(definition["coefficients"] @ solved)
        linear_rows.append(
            {
                "name": definition["name"],
                "actual": actual,
                "lower": definition["lower"],
                "upper": definition["upper"],
            }
        )

    tolerance = max(1e-6, float(config.feasibility_tolerance) * 100.0)
    violations: dict[str, float] = {}

    def record_upper(name: str, actual: float, limit: float | None) -> None:
        if limit is not None and actual > float(limit) + tolerance:
            violations[name] = actual - float(limit)

    def record_lower(name: str, actual: float, limit: float | None) -> None:
        if limit is not None and actual < float(limit) - tolerance:
            violations[name] = float(limit) - actual

    record_upper(
        "security_upper_bound",
        float(np.maximum(solved - upper, 0.0).max()),
        0.0,
    )
    record_upper(
        "security_lower_bound",
        float(np.maximum(lower - solved, 0.0).max()),
        0.0,
    )
    record_upper(
        "max_active_weight",
        float(np.abs(active_values).max()),
        config.max_active_weight,
    )
    record_upper("max_turnover", turnover, config.max_turnover)
    record_upper(
        "max_tracking_error",
        tracking_error,
        config.max_tracking_error,
    )
    record_lower("min_score", portfolio_score, config.min_score)
    record_upper("max_score", portfolio_score, config.max_score)
    holdings = int((solved > config.feasibility_tolerance).sum())
    record_lower("min_holdings", float(holdings), config.min_holdings)
    record_upper("max_holdings", float(holdings), config.max_holdings)
    for row in group_rows:
        prefix = f"group:{row['name']}:{row['key']}"
        record_lower(prefix + ":lower", row["actual"], row["lower"])
        record_upper(prefix + ":upper", row["actual"], row["upper"])
    for row in linear_rows:
        prefix = f"linear:{row['name']}"
        record_lower(prefix + ":lower", row["actual"], row["lower"])
        record_upper(prefix + ":upper", row["actual"], row["upper"])
    if forced.any():
        record_lower(
            "forced_security_weight",
            float(solved[forced].min()),
            max(
                float(config.min_weight_if_selected),
                float(config.feasibility_tolerance) * 10.0,
            ),
        )
    if forbidden.any():
        record_upper(
            "forbidden_security_weight",
            float(solved[forbidden].max()),
            0.0,
        )
    if violations:
        details = ", ".join(
            f"{name}={value:.3g}"
            for name, value in sorted(violations.items())
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
        "max_lower_bound_violation": float(np.maximum(lower - solved, 0.0).max()),
        "max_upper_bound_violation": float(np.maximum(solved - upper, 0.0).max()),
        "group_constraints": group_rows,
        "linear_constraints": linear_rows,
        "covariance_min_eigenvalue_before_projection": covariance_min_eigenvalue,
        "solver_attempt_errors": solver_errors,
        "feasibility_tolerance": tolerance,
        "constraint_violations": violations,
    }
    metadata = {
        "optimizer_id": OPTIMIZER_ID,
        "optimizer_version": OPTIMIZER_VERSION,
        "objective": objective_kind.value,
        "objective_policy": {
            "score_weight": float(config.score_weight),
            "tracking_error_weight": float(config.tracking_error_weight),
            "turnover_weight": float(config.turnover_weight),
            "active_weight_penalty": float(config.active_weight_penalty),
            "covariance_units": "caller_supplied",
        },
        "solver": solver,
        "status": str(problem.status),
        "constraint_policy": {
            "long_only": config.long_only,
            "min_score": config.min_score,
            "max_score": config.max_score,
            "max_tracking_error": config.max_tracking_error,
            "max_turnover": config.max_turnover,
            "external_current_weight": external_weight,
            "max_active_weight": config.max_active_weight,
            "min_holdings": config.min_holdings,
            "max_holdings": config.max_holdings,
            "min_weight_if_selected": config.min_weight_if_selected,
            "forced_ids": [str(value) for value in config.forced_ids],
            "forbidden_ids": [str(value) for value in config.forbidden_ids],
            "group_constraint_count": len(group_audit_definitions),
            "linear_constraint_count": len(linear_audit_definitions),
        },
    }
    return PortfolioOptimizationResult(
        weights=weights,
        status=str(problem.status),
        solver=solver,
        objective=objective_kind.value,
        objective_value=float(problem.value) if problem.value is not None else None,
        audit=audit,
        metadata=metadata,
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





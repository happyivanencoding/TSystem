"""cvxpy loading and deterministic solver fallback."""

from __future__ import annotations

from .contracts import OptimizerConfig


try:
    import cvxpy as cp

    _CVXPY_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - depends on local solver stack
    cp = None
    _CVXPY_IMPORT_ERROR = exc


OPTIMAL_STATUSES = {"optimal", "optimal_inaccurate"}


def require_cvxpy():
    """Return cvxpy or raise a clear environment error."""

    if cp is None:
        raise ImportError(
            "cvxpy is required for the TP optimizer engine, but it cannot be imported. "
            f"Original error: {_CVXPY_IMPORT_ERROR}"
        )
    return cp


def solve_problem(
    problem,
    config: OptimizerConfig,
    *,
    mixed_integer: bool,
) -> tuple[str, list[str]]:
    cvxpy = require_cvxpy()
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

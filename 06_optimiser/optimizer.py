"""兼容入口；规范实现位于 :mod:`tp_portfolio`。"""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_portfolio import (
    GroupConstraint,
    LinearConstraint,
    OptimizerConfig,
    OptimizerObjective,
    PortfolioOptimizationResult,
    optimize_portfolio,
)

warn_legacy_entrypoint("from optimizer import ...", "from tp_portfolio import ...")

OptimizationResult = PortfolioOptimizationResult

__all__ = [
    "GroupConstraint",
    "LinearConstraint",
    "OptimizerConfig",
    "OptimizerObjective",
    "OptimizationResult",
    "PortfolioOptimizationResult",
    "optimize_portfolio",
]

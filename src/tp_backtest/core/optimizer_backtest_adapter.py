"""Adapter from optimizer output to the canonical TP backtest weight contract."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from tp_core.security_nav_engine import (
    TargetWeightSchema,
    SecurityNavEngine,
    SecurityNavResult,
)
from tp_backtest.core.weight_table_adapter import optimizer_result_to_weight_table
from tp_backtest.execution import (
    ExecutionAssumptions,
    WeightExecutionResult,
    simulate_weight_execution,
)


class OptimizerBacktestAdapter:
    """Convert optimizer output and delegate calculation to ``SecurityNavEngine``."""

    def __init__(
        self,
        returns: pd.DataFrame,
        execution_assumptions: ExecutionAssumptions | None = None,
    ):
        self.nav_engine = SecurityNavEngine(returns=returns)
        self.execution_assumptions = execution_assumptions or ExecutionAssumptions()
        self.last_optimized_weights: Optional[pd.DataFrame] = None
        self.last_nav_result: Optional[SecurityNavResult | WeightExecutionResult] = None
        self.perf_ptf: Optional[pd.Series] = None

    def calculate_optimizer_nav(
        self,
        optimizer_result: pd.DataFrame,
        weight_col: str = "target_weight",
        schema: TargetWeightSchema = TargetWeightSchema(),
        **backtest_kwargs,
    ) -> SecurityNavResult:
        """Calculate NAV for a table returned by ``optimize_portfolio``."""

        weights = optimizer_result_to_weight_table(
            optimizer_result,
            weight_col=weight_col,
        )
        return self.calculate_standard_weight_nav(
            weights,
            schema=schema,
            **backtest_kwargs,
        )

    def calculate_standard_weight_nav(
        self,
        weights: pd.DataFrame,
        schema: TargetWeightSchema = TargetWeightSchema(),
        **backtest_kwargs,
    ) -> SecurityNavResult:
        """Backtest an already-standard optimized target-weight table."""

        if self.execution_assumptions.mode == "fast_nav":
            result = self.nav_engine.run_weights(
                weights,
                schema=schema,
                **backtest_kwargs,
            )
        else:
            result = simulate_weight_execution(
                weights,
                self.nav_engine.returns,
                assumptions=self.execution_assumptions,
                schema=schema,
                **backtest_kwargs,
            )
        self.last_optimized_weights = result.rebalance_weights
        self.last_nav_result = result
        self.perf_ptf = result.nav
        return result


__all__ = ["OptimizerBacktestAdapter"]

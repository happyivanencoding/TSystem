"""Adapter from optimizer output to the canonical TP backtest weight contract."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pandas as pd

from tp_core.general_backtest import (
    BacktestSchema,
    GeneralBacktestEngine,
    GeneralBacktestResult,
)

TP_ROOT = Path(__file__).resolve().parents[2]
OPTIMISER_ROOT = TP_ROOT / "06_optimiser"
if str(OPTIMISER_ROOT) not in sys.path:
    sys.path.insert(0, str(OPTIMISER_ROOT))

from optimizer_engine import to_standard_weight_table  # noqa: E402


class OptimizerBacktestAdapter(GeneralBacktestEngine):
    """Convert optimizer output and delegate NAV calculation to the sole kernel."""

    def __init__(self, returns: pd.DataFrame):
        super().__init__(returns=returns)
        self.last_optimized_weights: Optional[pd.DataFrame] = None
        self.last_optimized_backtest: Optional[GeneralBacktestResult] = None
        self.perf_ptf: Optional[pd.Series] = None

    def backtest_optimizer_result(
        self,
        optimizer_result: pd.DataFrame,
        weight_col: str = "Wopt",
        schema: BacktestSchema = BacktestSchema(),
        **backtest_kwargs,
    ) -> GeneralBacktestResult:
        """Backtest a dataframe returned by optimizer_engine.optimize()."""

        weights = to_standard_weight_table(
            optimizer_result,
            weight_col=weight_col,
        )
        return self.backtest_weight_table_optimized(
            weights,
            schema=schema,
            **backtest_kwargs,
        )

    def backtest_weight_table_optimized(
        self,
        weights: pd.DataFrame,
        schema: BacktestSchema = BacktestSchema(),
        **backtest_kwargs,
    ) -> GeneralBacktestResult:
        """Backtest an already-standard optimized target-weight table."""

        result = self.run_weights(
            weights,
            schema=schema,
            **backtest_kwargs,
        )
        self.last_optimized_weights = result.rebalance_weights
        self.last_optimized_backtest = result
        self.perf_ptf = result.nav
        return result


__all__ = ["OptimizerBacktestAdapter"]

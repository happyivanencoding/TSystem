"""Optimized backtest engine connected to the download_09 optimizer standard."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pandas as pd

from core.backtest_engine import BacktestEngine
from tp_core.general_backtest import BacktestSchema, GeneralBacktestResult
from utils.constants import COL_DATE, COL_PORTFOLIO_WEIGHT, COL_SEDOL

TP_ROOT = Path(__file__).resolve().parents[2]
OPTIMISER_ROOT = TP_ROOT / "06_optimiser"
if str(OPTIMISER_ROOT) not in sys.path:
    sys.path.insert(0, str(OPTIMISER_ROOT))

from optimizer_engine import to_standard_weight_table  # noqa: E402


class BacktestEngineOptimized(BacktestEngine):
    """Backtest engine for portfolios produced by the download_09 optimizer."""

    def __init__(self, returns: pd.DataFrame):
        super().__init__(returns=returns)
        self.last_optimized_weights: Optional[pd.DataFrame] = None
        self.last_optimized_backtest: Optional[GeneralBacktestResult] = None

    @staticmethod
    def calculate_portfolio_returns_vectorized(
        df_rebal: pd.DataFrame,
        df_returns: pd.DataFrame,
        col_weight: str = COL_PORTFOLIO_WEIGHT,
        col_date: str = COL_DATE,
        col_id: str = COL_SEDOL,
    ) -> pd.Series:
        return BacktestEngine.calculate_portfolio_returns(
            df_rebal=df_rebal,
            df_returns=df_returns,
            col_weight=col_weight,
            col_date=col_date,
            col_id=col_id,
        )

    def backtest_optimizer_result(
        self,
        optimizer_result: pd.DataFrame,
        weight_col: str = "Wopt",
        schema: BacktestSchema = BacktestSchema(),
        **backtest_kwargs,
    ) -> GeneralBacktestResult:
        """Backtest a dataframe returned by optimizer_engine.optimize()."""
        weights = to_standard_weight_table(optimizer_result, weight_col=weight_col)
        result = self.run_weights(weights, schema=schema, **backtest_kwargs)
        self.last_optimized_weights = weights
        self.last_optimized_backtest = result
        self.perf_ptf = result.nav
        return result

    def backtest_weight_table_optimized(
        self,
        weights: pd.DataFrame,
        schema: BacktestSchema = BacktestSchema(),
        **backtest_kwargs,
    ) -> GeneralBacktestResult:
        """Backtest an already-standard optimized target-weight table."""
        result = self.run_weights(weights, schema=schema, **backtest_kwargs)
        self.last_optimized_weights = result.rebalance_weights
        self.last_optimized_backtest = result
        self.perf_ptf = result.nav
        return result

    def backtest_optimized(
        self,
        sec_list: pd.DataFrame,
        screen: pd.DataFrame,
        indice_name: str,
        method: str,
        max_weight: float,
        sec_list_: bool = True,
    ):
        """Legacy compatibility: delegate to the canonical security-list backtest."""
        return self.backtest(
            sec_list=sec_list,
            screen=screen,
            indice_name=indice_name,
            method=method,
            max_weight=max_weight,
            sec_list_=sec_list_,
        )


__all__ = ["BacktestEngineOptimized"]

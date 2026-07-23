"""Single public API for TP portfolio construction and backtesting."""

from __future__ import annotations

import sys

from .data_sources import TP_ROOT
from .general_backtest import (
    ENGINE_ID,
    ENGINE_VERSION,
    BacktestSchema,
    GeneralBacktestEngine,
    GeneralBacktestResult,
    ReturnSeriesBacktestResult,
    backtest_return_series,
    backtest_weight_table,
    engine_metadata,
)

_ACTIVE_BACKTEST_APP = TP_ROOT / "07_backtest_code"


def _ensure_backtest_app_on_path() -> None:
    app_path = str(_ACTIVE_BACKTEST_APP)
    if app_path not in sys.path:
        sys.path.insert(0, app_path)


_ensure_backtest_app_on_path()

from core.attribution import AttributionAnalysis  # noqa: E402
from core.factor_analysis import FactorAnalyzer  # noqa: E402
from core.financial_filter import FinancialFilter  # noqa: E402
from core.metrics import PerformanceMetrics  # noqa: E402
from core.optimizer_backtest_adapter import OptimizerBacktestAdapter  # noqa: E402
from core.portfolio_builder import PortfolioBuilder  # noqa: E402
from core.ptf_builder import PtfBuilder  # noqa: E402
from core.weight_manager import WeightManager  # noqa: E402
from core.weight_table_adapter import (  # noqa: E402
    benchmark_reference_list,
    benchmark_to_weight_table,
    plot_tracking_error,
    rolling_tracking_error,
    security_list_to_weight_table,
)


def build_backtest_engine(returns) -> GeneralBacktestEngine:
    """Create the sole TP security-level NAV engine."""

    return GeneralBacktestEngine(returns)


__all__ = [
    "ENGINE_ID",
    "ENGINE_VERSION",
    "AttributionAnalysis",
    "BacktestSchema",
    "FactorAnalyzer",
    "FinancialFilter",
    "GeneralBacktestEngine",
    "GeneralBacktestResult",
    "OptimizerBacktestAdapter",
    "PerformanceMetrics",
    "PortfolioBuilder",
    "PtfBuilder",
    "ReturnSeriesBacktestResult",
    "WeightManager",
    "backtest_return_series",
    "backtest_weight_table",
    "benchmark_reference_list",
    "benchmark_to_weight_table",
    "build_backtest_engine",
    "engine_metadata",
    "plot_tracking_error",
    "rolling_tracking_error",
    "security_list_to_weight_table",
]

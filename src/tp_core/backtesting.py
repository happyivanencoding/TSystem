"""Single public API for TP portfolio construction and backtesting."""

from __future__ import annotations

from importlib import import_module

from .security_nav_engine import (
    NAV_ENGINE_ID,
    NAV_ENGINE_VERSION,
    ReturnSeriesNavResult,
    SecurityNavEngine,
    SecurityNavResult,
    TargetWeightSchema,
    calculate_return_series_nav,
    calculate_security_nav,
    nav_engine_metadata,
)

_LAZY_EXPORTS = {
    "AttributionAnalysis": ("tp_backtest.core.attribution", "AttributionAnalysis"),
    "FactorAnalyzer": ("tp_backtest.core.factor_analysis", "FactorAnalyzer"),
    "FinancialFilter": ("tp_backtest.core.financial_filter", "FinancialFilter"),
    "PerformanceMetrics": ("tp_backtest.core.metrics", "PerformanceMetrics"),
    "OptimizerBacktestAdapter": (
        "tp_backtest.core.optimizer_backtest_adapter",
        "OptimizerBacktestAdapter",
    ),
    "OfficialPortfolioBacktest": (
        "tp_backtest.core.official_portfolio_backtest",
        "OfficialPortfolioBacktest",
    ),
    "SecurityListConstructor": (
        "tp_backtest.core.security_list_constructor",
        "SecurityListConstructor",
    ),
    "benchmark_reference_list": (
        "tp_backtest.core.weight_table_adapter",
        "benchmark_reference_list",
    ),
    "benchmark_to_weight_table": (
        "tp_backtest.core.weight_table_adapter",
        "benchmark_to_weight_table",
    ),
    "optimizer_result_to_weight_table": (
        "tp_backtest.core.weight_table_adapter",
        "optimizer_result_to_weight_table",
    ),
    "plot_tracking_error": (
        "tp_backtest.core.weight_table_adapter",
        "plot_tracking_error",
    ),
    "rolling_tracking_error": (
        "tp_backtest.core.weight_table_adapter",
        "rolling_tracking_error",
    ),
    "security_list_to_weight_table": (
        "tp_backtest.core.weight_table_adapter",
        "security_list_to_weight_table",
    ),
}


def __getattr__(name: str):
    """Load application-level backtest components only when requested."""

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()).union(_LAZY_EXPORTS))


def build_security_nav_engine(returns) -> SecurityNavEngine:
    """Create the sole TP security-level NAV engine."""

    return SecurityNavEngine(returns)


__all__ = [
    "NAV_ENGINE_ID",
    "NAV_ENGINE_VERSION",
    "AttributionAnalysis",
    "FactorAnalyzer",
    "FinancialFilter",
    "OfficialPortfolioBacktest",
    "OptimizerBacktestAdapter",
    "PerformanceMetrics",
    "ReturnSeriesNavResult",
    "SecurityListConstructor",
    "SecurityNavEngine",
    "SecurityNavResult",
    "TargetWeightSchema",
    "benchmark_reference_list",
    "benchmark_to_weight_table",
    "build_security_nav_engine",
    "calculate_return_series_nav",
    "calculate_security_nav",
    "nav_engine_metadata",
    "optimizer_result_to_weight_table",
    "plot_tracking_error",
    "rolling_tracking_error",
    "security_list_to_weight_table",
]

"""共享回测入口，当前指向传统代码版 backtest_code。"""

from __future__ import annotations

import importlib
import sys
from typing import Any

from .data_sources import TP_ROOT
from .general_backtest import BacktestSchema, GeneralBacktestEngine, GeneralBacktestResult, backtest_weight_table

_ACTIVE_BACKTEST_APP = TP_ROOT / "07_backtest_code"
_ACTIVE_ENGINE_MODULE = "BacktestEngine"


def _ensure_backtest_app_on_path() -> None:
    app_path = str(_ACTIVE_BACKTEST_APP)
    while app_path in sys.path:
        sys.path.remove(app_path)
    sys.path.insert(0, app_path)

def _import_from_active(module_name: str) -> Any:
    _ensure_backtest_app_on_path()
    return importlib.import_module(module_name)


def get_ptf_builder() -> type[Any]:
    """Return the active PtfBuilder class from the code-first backtest mainline."""
    module = _import_from_active(_ACTIVE_ENGINE_MODULE)
    return module.PtfBuilder


def get_backtest_engine_module() -> Any:
    """Return the active BacktestEngine module for advanced legacy callers."""
    return _import_from_active(_ACTIVE_ENGINE_MODULE)


def get_core_class(module_name: str, class_name: str) -> type[Any]:
    """从 backtest_code/core 暴露可复用核心类。"""
    module = _import_from_active(f"core.{module_name}")
    return getattr(module, class_name)


PtfBuilder = get_ptf_builder()
BacktestEngine = get_core_class("backtest_engine", "BacktestEngine")
PortfolioBuilder = get_core_class("portfolio_builder", "PortfolioBuilder")
PerformanceMetrics = get_core_class("metrics", "PerformanceMetrics")
WeightManager = get_core_class("weight_manager", "WeightManager")
AttributionAnalysis = get_core_class("attribution", "AttributionAnalysis")
FactorAnalyzer = get_core_class("factor_analysis", "FactorAnalyzer")
FinancialFilter = get_core_class("financial_filter", "FinancialFilter")


def calculate_portfolio_returns(*args, **kwargs):
    """兼容旧 API：调用当前主线 BacktestEngine.calculate_portfolio_returns。"""

    return BacktestEngine.calculate_portfolio_returns(*args, **kwargs)


def create_ptf_weight(*args, **kwargs):
    """兼容旧 API：调用当前主线 BacktestEngine.create_ptf_weight。"""

    return BacktestEngine.create_ptf_weight(*args, **kwargs)


def build_backtest_engine(returns) -> Any:
    """创建当前主线 BacktestEngine 实例。"""

    return BacktestEngine(returns)

__all__ = [
    "PtfBuilder",
    "BacktestEngine",
    "PortfolioBuilder",
    "PerformanceMetrics",
    "WeightManager",
    "AttributionAnalysis",
    "FactorAnalyzer",
    "FinancialFilter",
    "BacktestSchema",
    "GeneralBacktestEngine",
    "GeneralBacktestResult",
    "backtest_weight_table",
    "build_backtest_engine",
    "create_ptf_weight",
    "calculate_portfolio_returns",
    "get_ptf_builder",
    "get_backtest_engine_module",
    "get_core_class",
]


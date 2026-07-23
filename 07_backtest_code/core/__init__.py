"""
Core modules for the backtesting system.
"""

from .data_loader import DataLoader
from .portfolio_builder import PortfolioBuilder
from .optimizer_backtest_adapter import OptimizerBacktestAdapter
from .ptf_builder import PtfBuilder
from .factor_pipeline import (
    backtest_factors,
    build_factor_component,
    calculate_quality_score,
    handle_missing_values,
    neutralize_score,
    run_factor_pipeline,
    run_growth_factor_pipeline,
    test_unitary_factors,
    transform_absolute_values,
)
from .weight_manager import WeightManager
from .metrics import PerformanceMetrics

__all__ = [
    'DataLoader',
    'PortfolioBuilder',
    'OptimizerBacktestAdapter',
    'PtfBuilder',
    'backtest_factors',
    'build_factor_component',
    'calculate_quality_score',
    'handle_missing_values',
    'neutralize_score',
    'run_factor_pipeline',
    'run_growth_factor_pipeline',
    'test_unitary_factors',
    'transform_absolute_values',
    'WeightManager',
    'PerformanceMetrics',
]

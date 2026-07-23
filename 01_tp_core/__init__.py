"""Shared TP project utilities."""

import sys

sys.modules.setdefault("tp_core", sys.modules[__name__])

from .data_sources import SCREEN_AGGREGATE_PATH, RETURNS_PATH, LAST_SCREEN_PATH, PRODUCTION_INPUTS_DIR
from .data_contract import data_contract, validate_returns_contract, validate_screen_contract
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
from .optimisation import optimizer, turnover
from .presentation import add_icb_supersector_names, region_bucket_value

__all__ = [
    "SCREEN_AGGREGATE_PATH",
    "RETURNS_PATH",
    "LAST_SCREEN_PATH",
    "PRODUCTION_INPUTS_DIR",
    "data_contract",
    "validate_returns_contract",
    "validate_screen_contract",
    "BacktestSchema",
    "ENGINE_ID",
    "ENGINE_VERSION",
    "GeneralBacktestEngine",
    "GeneralBacktestResult",
    "ReturnSeriesBacktestResult",
    "backtest_return_series",
    "backtest_weight_table",
    "engine_metadata",
    "region_bucket_value",
    "add_icb_supersector_names",
    "turnover",
    "optimizer",
]

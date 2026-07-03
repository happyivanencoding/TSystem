"""Logical ``tp_core`` package exposed from the numbered ``01_tp_core`` folder."""

from __future__ import annotations

from pathlib import Path

_REAL_PACKAGE = Path(__file__).resolve().parents[1]
__path__ = [str(_REAL_PACKAGE)]

from .data_contract import data_contract, validate_returns_contract, validate_screen_contract
from .data_sources import LAST_SCREEN_PATH, PRODUCTION_INPUTS_DIR, RETURNS_PATH, SCREEN_AGGREGATE_PATH
from .general_backtest import BacktestSchema, GeneralBacktestEngine, GeneralBacktestResult, backtest_weight_table
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
    "GeneralBacktestEngine",
    "GeneralBacktestResult",
    "backtest_weight_table",
    "region_bucket_value",
    "add_icb_supersector_names",
    "turnover",
    "optimizer",
]

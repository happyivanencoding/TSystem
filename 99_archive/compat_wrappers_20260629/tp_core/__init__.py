"""兼容包：真实共享代码位于 `01_tp_core/`。"""

from pathlib import Path

_REAL_PACKAGE = Path(__file__).resolve().parents[1] / "01_tp_core"
__path__ = [str(_REAL_PACKAGE)]

from .data_contract import data_contract, validate_returns_contract, validate_screen_contract
from .general_backtest import BacktestSchema, GeneralBacktestEngine, GeneralBacktestResult, backtest_weight_table
from .data_sources import LAST_SCREEN_PATH, PRODUCTION_INPUTS_DIR, RETURNS_PATH, SCREEN_AGGREGATE_PATH

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
]

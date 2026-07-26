"""无界面回测编排、校验和产物保存。"""

from .input_loader import load_pruned_backtest_inputs
from .service import BacktestService, ServiceResult, SingleRunResult

__all__ = [
    "BacktestService",
    "ServiceResult",
    "SingleRunResult",
    "load_pruned_backtest_inputs",
]

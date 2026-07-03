"""无界面回测编排、校验和产物保存。"""

from .service import BacktestService, ServiceResult, SingleRunResult

__all__ = ["BacktestService", "ServiceResult", "SingleRunResult"]

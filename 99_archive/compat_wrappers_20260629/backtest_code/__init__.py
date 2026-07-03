"""兼容包：真实传统代码版回测位于 `07_backtest_code/`。"""

from pathlib import Path

_REAL_PACKAGE = Path(__file__).resolve().parents[1] / "07_backtest_code" / "src" / "backtest_code"
__path__ = [str(_REAL_PACKAGE)]

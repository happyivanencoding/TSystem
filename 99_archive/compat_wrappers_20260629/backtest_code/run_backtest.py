"""兼容 CLI：转发到 `07_backtest_code/run_backtest.py`。"""

from pathlib import Path
import runpy
import sys

_REAL_ROOT = Path(__file__).resolve().parents[1] / "07_backtest_code"
_REAL_SRC = _REAL_ROOT / "src"
for _path in (_REAL_SRC, _REAL_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

runpy.run_path(str(_REAL_ROOT / "run_backtest.py"), run_name="__main__")

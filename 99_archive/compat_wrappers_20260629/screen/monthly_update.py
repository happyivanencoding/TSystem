"""兼容 CLI：转发到 `00_screen/monthly_update.py`。"""

from pathlib import Path
import runpy
import sys

_REAL_DIR = Path(__file__).resolve().parents[1] / "00_screen"
if str(_REAL_DIR) not in sys.path:
    sys.path.insert(0, str(_REAL_DIR))

runpy.run_path(str(_REAL_DIR / "monthly_update.py"), run_name="__main__")

"""兼容 CLI：转发到 `03_technical_analysis/export_technical_signals.py`。"""

from pathlib import Path
import runpy
import sys

_REAL_DIR = Path(__file__).resolve().parents[1] / "03_technical_analysis"
if str(_REAL_DIR) not in sys.path:
    sys.path.insert(0, str(_REAL_DIR))

runpy.run_path(str(_REAL_DIR / "export_technical_signals.py"), run_name="__main__")

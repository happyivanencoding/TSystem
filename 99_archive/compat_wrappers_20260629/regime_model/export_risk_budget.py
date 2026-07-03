"""兼容 CLI：转发到 `03_regime_model/export_risk_budget.py`。"""

from pathlib import Path
import runpy
import sys

_REAL_DIR = Path(__file__).resolve().parents[1] / "03_regime_model"
if str(_REAL_DIR) not in sys.path:
    sys.path.insert(0, str(_REAL_DIR))

runpy.run_path(str(_REAL_DIR / "export_risk_budget.py"), run_name="__main__")

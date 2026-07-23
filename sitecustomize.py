"""Runtime aliases for TP numbered project directories.

The root workspace keeps physical project directories numbered, while Python
code still needs valid import names such as ``tp_core``.  Python imports this
file automatically when the TP root is on ``sys.path``.
"""

from __future__ import annotations

import sys
from pathlib import Path


TP_ROOT = Path(__file__).resolve().parent

for path in [
    TP_ROOT,
    TP_ROOT / "01_tp_core",
    TP_ROOT / "06_optimiser",
    TP_ROOT / "08_presentation_layer",
    TP_ROOT / "07_backtest_code" / "src",
    TP_ROOT / "07_backtest_code",
]:
    path_text = str(path)
    if path.exists() and path_text not in sys.path:
        sys.path.insert(0, path_text)

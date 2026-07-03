"""TP production pipeline entrypoints."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

TP_ROOT = Path(__file__).resolve().parents[1]
for _path in [
    TP_ROOT / "01_tp_core",
    TP_ROOT / "06_optimiser",
    TP_ROOT / "08_presentation_layer",
    TP_ROOT / "07_backtest_code" / "src",
]:
    _path_text = str(_path)
    if _path.exists() and _path_text not in sys.path:
        sys.path.insert(0, _path_text)

for _package in ["tp_core", "optimiser", "presentation_layer"]:
    if _package not in sys.modules:
        importlib.import_module(_package)

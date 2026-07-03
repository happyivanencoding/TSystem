from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
TP_ROOT = ROOT.parent
for path in (SRC, TP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import sitecustomize  # noqa: F401

from backtest_code.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

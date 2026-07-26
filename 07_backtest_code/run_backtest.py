from __future__ import annotations

from backtest_code.cli import main
from tp_core.deprecation import warn_legacy_entrypoint

if __name__ == "__main__":
    warn_legacy_entrypoint("07_backtest_code/run_backtest.py", "python -m backtest_code.cli")
    raise SystemExit(main())

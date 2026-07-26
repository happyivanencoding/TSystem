"""Compatibility entrypoint; use :mod:`tp_pipelines.run_backtest`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_pipelines.run_backtest import *  # noqa: F403
from tp_pipelines.run_backtest import main


if __name__ == "__main__":
    warn_legacy_entrypoint("02_pipelines/run_backtest.py", "python -m tp_pipelines.run_backtest")
    raise SystemExit(main())

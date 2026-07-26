"""Compatibility entrypoint; use :mod:`tp_pipelines.run_backtest`."""

from tp_pipelines.run_backtest import *  # noqa: F403
from tp_pipelines.run_backtest import main


if __name__ == "__main__":
    raise SystemExit(main())

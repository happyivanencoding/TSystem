"""Compatibility entrypoint; use :mod:`tp_pipelines.optimize_portfolio`."""

from tp_pipelines.optimize_portfolio import *  # noqa: F403
from tp_pipelines.optimize_portfolio import main


if __name__ == "__main__":
    raise SystemExit(main())

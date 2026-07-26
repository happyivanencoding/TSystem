"""Compatibility entrypoint; use :mod:`tp_pipelines.optimize_portfolio`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_pipelines.optimize_portfolio import *  # noqa: F403
from tp_pipelines.optimize_portfolio import main


if __name__ == "__main__":
    warn_legacy_entrypoint("02_pipelines/optimize_portfolio.py", "python -m tp_pipelines.optimize_portfolio")
    raise SystemExit(main())

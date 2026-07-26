"""Deprecated launcher for :mod:	p_research.workflows.run_nasdaq_relative_variable_parallel."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.run_nasdaq_relative_variable_parallel import *  # noqa: F403
from tp_research.workflows.run_nasdaq_relative_variable_parallel import main

warn_legacy_entrypoint(
    "07_backtest_code/scripts/run_nasdaq_relative_variable_parallel.py",
    "python -m tp_research.workflows.run_nasdaq_relative_variable_parallel",
)

if __name__ == "__main__":
    raise SystemExit(main())
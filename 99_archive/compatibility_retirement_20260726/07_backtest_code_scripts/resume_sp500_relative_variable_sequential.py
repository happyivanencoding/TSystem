"""Deprecated launcher for :mod:	p_research.workflows.resume_sp500_relative_variable_sequential."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.resume_sp500_relative_variable_sequential import *  # noqa: F403
from tp_research.workflows.resume_sp500_relative_variable_sequential import main

warn_legacy_entrypoint(
    "07_backtest_code/scripts/resume_sp500_relative_variable_sequential.py",
    "python -m tp_research.workflows.resume_sp500_relative_variable_sequential",
)

if __name__ == "__main__":
    raise SystemExit(main())
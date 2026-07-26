"""Deprecated launcher for :mod:	p_research.workflows.analyze_sp500_raw_variable_synergy."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.analyze_sp500_raw_variable_synergy import *  # noqa: F403
from tp_research.workflows.analyze_sp500_raw_variable_synergy import main

warn_legacy_entrypoint(
    "07_backtest_code/scripts/analyze_sp500_raw_variable_synergy.py",
    "python -m tp_research.workflows.analyze_sp500_raw_variable_synergy",
)

if __name__ == "__main__":
    raise SystemExit(main())
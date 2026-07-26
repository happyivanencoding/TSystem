"""Deprecated launcher for :mod:	p_research.workflows.analyze_nasdaq_extended_factor_research."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.analyze_nasdaq_extended_factor_research import *  # noqa: F403
from tp_research.workflows.analyze_nasdaq_extended_factor_research import main

warn_legacy_entrypoint(
    "07_backtest_code/scripts/analyze_nasdaq_extended_factor_research.py",
    "python -m tp_research.workflows.analyze_nasdaq_extended_factor_research",
)

if __name__ == "__main__":
    raise SystemExit(main())
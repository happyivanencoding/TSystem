"""Deprecated launcher for :mod:	p_research.workflows.resume_sp500_relative_synergy_full_loop."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.resume_sp500_relative_synergy_full_loop import *  # noqa: F403
from tp_research.workflows.resume_sp500_relative_synergy_full_loop import main

warn_legacy_entrypoint(
    "07_backtest_code/scripts/resume_sp500_relative_synergy_full_loop.py",
    "python -m tp_research.workflows.resume_sp500_relative_synergy_full_loop",
)

if __name__ == "__main__":
    raise SystemExit(main())
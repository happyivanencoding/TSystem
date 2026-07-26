"""Deprecated launcher for :mod:	p_research.workflows.resume_stoxx600_relative_synergy_isolated."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.resume_stoxx600_relative_synergy_isolated import *  # noqa: F403
from tp_research.workflows.resume_stoxx600_relative_synergy_isolated import main

warn_legacy_entrypoint(
    "07_backtest_code/scripts/resume_stoxx600_relative_synergy_isolated.py",
    "python -m tp_research.workflows.resume_stoxx600_relative_synergy_isolated",
)

if __name__ == "__main__":
    raise SystemExit(main())
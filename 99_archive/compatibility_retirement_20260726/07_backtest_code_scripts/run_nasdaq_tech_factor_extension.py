"""Deprecated launcher for :mod:	p_research.workflows.run_nasdaq_tech_factor_extension."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.run_nasdaq_tech_factor_extension import *  # noqa: F403
from tp_research.workflows.run_nasdaq_tech_factor_extension import main

warn_legacy_entrypoint(
    "07_backtest_code/scripts/run_nasdaq_tech_factor_extension.py",
    "python -m tp_research.workflows.run_nasdaq_tech_factor_extension",
)

if __name__ == "__main__":
    raise SystemExit(main())
"""Deprecated launcher for the packaged cross-market LOPO workflow."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.analyze_cross_market_leave_one_period_out import *  # noqa: F403
from tp_research.workflows.analyze_cross_market_leave_one_period_out import main

warn_legacy_entrypoint(
    legacy_path="07_backtest_code/scripts/analyze_cross_market_leave_one_period_out.py",
    replacement="python -m tp_research.workflows.analyze_cross_market_leave_one_period_out",
)

if __name__ == "__main__":
    raise SystemExit(main())

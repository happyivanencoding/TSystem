"""Deprecated launcher for the packaged cross-market lag-6 workflow."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.run_cross_market_lag6_relative_research import *  # noqa: F403
from tp_research.workflows.run_cross_market_lag6_relative_research import main

warn_legacy_entrypoint(
    legacy_path="07_backtest_code/scripts/run_cross_market_lag6_relative_research.py",
    replacement="python -m tp_research.workflows.run_cross_market_lag6_relative_research",
)

if __name__ == "__main__":
    raise SystemExit(main())

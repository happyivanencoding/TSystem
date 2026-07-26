"""Deprecated launcher for the packaged cross-market synergy workflow."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.run_cross_market_lag6_anchor_synergy import *  # noqa: F403
from tp_research.workflows.run_cross_market_lag6_anchor_synergy import main

warn_legacy_entrypoint(
    legacy_path="07_backtest_code/scripts/run_cross_market_lag6_anchor_synergy.py",
    replacement="python -m tp_research.workflows.run_cross_market_lag6_anchor_synergy",
)

if __name__ == "__main__":
    raise SystemExit(main())

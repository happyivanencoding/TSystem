"""Deprecated launcher for :mod:	p_research.workflows.analyze_stoxx600_lag_extension_robustness."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.analyze_stoxx600_lag_extension_robustness import *  # noqa: F403
from tp_research.workflows.analyze_stoxx600_lag_extension_robustness import main

warn_legacy_entrypoint(
    "07_backtest_code/scripts/analyze_stoxx600_lag_extension_robustness.py",
    "python -m tp_research.workflows.analyze_stoxx600_lag_extension_robustness",
)

if __name__ == "__main__":
    raise SystemExit(main())
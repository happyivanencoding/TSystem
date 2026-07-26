"""Deprecated launcher for :mod:	p_research.workflows.dispatch_stoxx600_synergy_metrics."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.dispatch_stoxx600_synergy_metrics import *  # noqa: F403
from tp_research.workflows.dispatch_stoxx600_synergy_metrics import main

warn_legacy_entrypoint(
    "07_backtest_code/scripts/dispatch_stoxx600_synergy_metrics.py",
    "python -m tp_research.workflows.dispatch_stoxx600_synergy_metrics",
)

if __name__ == "__main__":
    raise SystemExit(main())
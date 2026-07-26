"""Deprecated launcher for :mod:	p_research.workflows.analyze_stoxx600_leave_one_regime_out."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.analyze_stoxx600_leave_one_regime_out import *  # noqa: F403
from tp_research.workflows.analyze_stoxx600_leave_one_regime_out import main

warn_legacy_entrypoint(
    "07_backtest_code/scripts/analyze_stoxx600_leave_one_regime_out.py",
    "python -m tp_research.workflows.analyze_stoxx600_leave_one_regime_out",
)

if __name__ == "__main__":
    raise SystemExit(main())
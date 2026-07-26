"""Deprecated launcher for :mod:	p_research.workflows.analyze_stoxx600_2020_regime_break."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.analyze_stoxx600_2020_regime_break import *  # noqa: F403
from tp_research.workflows.analyze_stoxx600_2020_regime_break import main

warn_legacy_entrypoint(
    "07_backtest_code/scripts/analyze_stoxx600_2020_regime_break.py",
    "python -m tp_research.workflows.analyze_stoxx600_2020_regime_break",
)

if __name__ == "__main__":
    raise SystemExit(main())
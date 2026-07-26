"""Deprecated launcher for :mod:	p_research.workflows.build_stoxx600_factor_explorer."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.build_stoxx600_factor_explorer import *  # noqa: F403
from tp_research.workflows.build_stoxx600_factor_explorer import main

warn_legacy_entrypoint(
    "07_backtest_code/scripts/build_stoxx600_factor_explorer.py",
    "python -m tp_research.workflows.build_stoxx600_factor_explorer",
)

if __name__ == "__main__":
    raise SystemExit(main())
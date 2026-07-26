"""Deprecated launcher for :mod:	p_research.workflows.analyze_eu_small_variable_rotation."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.analyze_eu_small_variable_rotation import *  # noqa: F403
from tp_research.workflows.analyze_eu_small_variable_rotation import main

warn_legacy_entrypoint(
    "07_backtest_code/scripts/analyze_eu_small_variable_rotation.py",
    "python -m tp_research.workflows.analyze_eu_small_variable_rotation",
)

if __name__ == "__main__":
    raise SystemExit(main())
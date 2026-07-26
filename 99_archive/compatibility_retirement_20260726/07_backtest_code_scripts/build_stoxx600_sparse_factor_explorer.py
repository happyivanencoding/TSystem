"""Deprecated launcher for the packaged STOXX 600 factor explorer."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.build_stoxx600_sparse_factor_explorer import *  # noqa: F403
from tp_research.workflows.build_stoxx600_sparse_factor_explorer import main

warn_legacy_entrypoint(
    legacy_path="07_backtest_code/scripts/build_stoxx600_sparse_factor_explorer.py",
    replacement="python -m tp_research.workflows.build_stoxx600_sparse_factor_explorer",
)

if __name__ == "__main__":
    raise SystemExit(main())

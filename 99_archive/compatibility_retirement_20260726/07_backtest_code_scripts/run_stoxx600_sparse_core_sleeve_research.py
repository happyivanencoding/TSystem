"""Deprecated launcher for the packaged STOXX 600 sparse-core workflow."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.run_stoxx600_sparse_core_sleeve_research import *  # noqa: F403
from tp_research.workflows.run_stoxx600_sparse_core_sleeve_research import main

warn_legacy_entrypoint(
    legacy_path="07_backtest_code/scripts/run_stoxx600_sparse_core_sleeve_research.py",
    replacement="python -m tp_research.workflows.run_stoxx600_sparse_core_sleeve_research",
)

if __name__ == "__main__":
    raise SystemExit(main())

"""Deprecated launcher for the packaged residual-volatility workflow."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.run_lowvol_resvol_research import *  # noqa: F403
from tp_research.workflows.run_lowvol_resvol_research import main

warn_legacy_entrypoint(
    legacy_path="07_backtest_code/scripts/run_lowvol_resvol_research.py",
    replacement="python -m tp_research.workflows.run_lowvol_resvol_research",
)

if __name__ == "__main__":
    raise SystemExit(main())

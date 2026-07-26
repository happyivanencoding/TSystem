"""Deprecated launcher for :mod:	p_research.workflows.write_sp500_factor_research_vault_report."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research.workflows.write_sp500_factor_research_vault_report import *  # noqa: F403
from tp_research.workflows.write_sp500_factor_research_vault_report import main

warn_legacy_entrypoint(
    "07_backtest_code/scripts/write_sp500_factor_research_vault_report.py",
    "python -m tp_research.workflows.write_sp500_factor_research_vault_report",
)

if __name__ == "__main__":
    raise SystemExit(main())
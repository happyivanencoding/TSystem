"""Stable workspace paths used by research workflows and thin legacy launchers."""

from pathlib import Path

from tp_core.data_sources import TP_ROOT
from tp_core.workspace import BACKTEST_RUNS_DIR, REPORTS_DIR

BACKTEST_ROOT = BACKTEST_RUNS_DIR.parent
SCRIPT_DIR = Path(__file__).resolve().parent / "workflows"
AD_HOC_ROOT = BACKTEST_RUNS_DIR / "ad_hoc"
REPORT_ROOT = REPORTS_DIR

__all__ = [
    "AD_HOC_ROOT",
    "BACKTEST_ROOT",
    "REPORT_ROOT",
    "SCRIPT_DIR",
    "TP_ROOT",
]

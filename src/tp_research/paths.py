"""Stable workspace paths used by research workflows and thin legacy launchers."""

from pathlib import Path

from tp_core.data_sources import TP_ROOT
from tp_core.workspace import (
    HISTORICAL_RESEARCH_RUNS_DIR,
    REPORTS_DIR,
    RESEARCH_ARTIFACTS_DIR,
    RESEARCH_RUNS_DIR,
)

BACKTEST_ROOT = RESEARCH_ARTIFACTS_DIR
SCRIPT_DIR = Path(__file__).resolve().parent / "workflows"
AD_HOC_ROOT = RESEARCH_RUNS_DIR / "ad_hoc"
HISTORICAL_AD_HOC_ROOT = HISTORICAL_RESEARCH_RUNS_DIR / "ad_hoc"
REPORT_ROOT = REPORTS_DIR

__all__ = [
    "AD_HOC_ROOT",
    "BACKTEST_ROOT",
    "HISTORICAL_AD_HOC_ROOT",
    "REPORT_ROOT",
    "SCRIPT_DIR",
    "TP_ROOT",
]

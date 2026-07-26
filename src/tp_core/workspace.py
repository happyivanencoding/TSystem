"""Canonical non-source paths for the TP workspace."""

from __future__ import annotations

from .data_sources import TP_ROOT

ARTIFACTS_ROOT = TP_ROOT / "artifacts"
SIGNALS_DIR = ARTIFACTS_ROOT / "signals"
CANDIDATES_DIR = ARTIFACTS_ROOT / "candidates"
PORTFOLIOS_DIR = ARTIFACTS_ROOT / "portfolios"
REPORTS_DIR = ARTIFACTS_ROOT / "reports"
PIPELINE_RUNS_DIR = ARTIFACTS_ROOT / "pipeline_runs"
PIPELINE_MANIFESTS_DIR = PIPELINE_RUNS_DIR / "manifests"
EXPERIMENTS_DIR = PIPELINE_RUNS_DIR / "experiments"
BACKTEST_ARTIFACTS_DIR = ARTIFACTS_ROOT / "backtests"
DASHBOARD_WORK_DIR = ARTIFACTS_ROOT / "dashboard_work"
SCRATCH_DIR = ARTIFACTS_ROOT / "scratch"

# The 74 GB historical run store is intentionally not moved until its Google
# Drive synchronization impact has been approved separately.
BACKTEST_RUNS_DIR = TP_ROOT / "07_backtest_code" / "runs"

CONFIG_ROOT = TP_ROOT / "config"
BACKTEST_CONFIG_DIR = CONFIG_ROOT / "backtest"
LOGS_DIR = ARTIFACTS_ROOT / "logs"

__all__ = [
    "ARTIFACTS_ROOT",
    "BACKTEST_ARTIFACTS_DIR",
    "BACKTEST_CONFIG_DIR",
    "BACKTEST_RUNS_DIR",
    "CANDIDATES_DIR",
    "CONFIG_ROOT",
    "DASHBOARD_WORK_DIR",
    "EXPERIMENTS_DIR",
    "LOGS_DIR",
    "PIPELINE_MANIFESTS_DIR",
    "PIPELINE_RUNS_DIR",
    "PORTFOLIOS_DIR",
    "REPORTS_DIR",
    "SCRATCH_DIR",
    "SIGNALS_DIR",
]

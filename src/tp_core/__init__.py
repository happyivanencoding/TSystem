"""TP shared data contracts, paths, and deterministic utilities."""

from .data_contract import data_contract, validate_returns_contract, validate_screen_contract
from .data_sources import (
    LAST_SCREEN_PATH,
    PRODUCTION_INPUTS_DIR,
    RETURNS_PATH,
    SCREEN_AGGREGATE_PATH,
)
from .presentation import add_icb_supersector_names, region_bucket_value
from .workspace import (
    ARTIFACTS_ROOT,
    BACKTEST_CONFIG_DIR,
    BACKTEST_OUTPUT_RUNS_DIR,
    CANDIDATES_DIR,
    DASHBOARD_WORK_DIR,
    HISTORICAL_RESEARCH_RUNS_DIR,
    PIPELINE_MANIFESTS_DIR,
    PIPELINE_RUNS_DIR,
    PORTFOLIOS_DIR,
    REPORTS_DIR,
    RESEARCH_ARTIFACTS_DIR,
    RESEARCH_FEATURES_DIR,
    RESEARCH_MIGRATIONS_DIR,
    RESEARCH_RUNS_DIR,
    SCRATCH_DIR,
    SIGNALS_DIR,
)

__all__ = [
    "SCREEN_AGGREGATE_PATH",
    "RETURNS_PATH",
    "LAST_SCREEN_PATH",
    "PRODUCTION_INPUTS_DIR",
    "ARTIFACTS_ROOT",
    "BACKTEST_CONFIG_DIR",
    "BACKTEST_OUTPUT_RUNS_DIR",
    "CANDIDATES_DIR",
    "DASHBOARD_WORK_DIR",
    "HISTORICAL_RESEARCH_RUNS_DIR",
    "PIPELINE_MANIFESTS_DIR",
    "PIPELINE_RUNS_DIR",
    "PORTFOLIOS_DIR",
    "REPORTS_DIR",
    "RESEARCH_ARTIFACTS_DIR",
    "RESEARCH_FEATURES_DIR",
    "RESEARCH_MIGRATIONS_DIR",
    "RESEARCH_RUNS_DIR",
    "SCRATCH_DIR",
    "SIGNALS_DIR",
    "data_contract",
    "validate_returns_contract",
    "validate_screen_contract",
    "region_bucket_value",
    "add_icb_supersector_names",
]

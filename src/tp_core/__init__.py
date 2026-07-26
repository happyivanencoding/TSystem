"""TP shared data contracts, paths, and deterministic utilities."""

from .data_contract import data_contract, validate_returns_contract, validate_screen_contract
from .data_sources import (
    LAST_SCREEN_PATH,
    PRODUCTION_INPUTS_DIR,
    RETURNS_PATH,
    SCREEN_AGGREGATE_PATH,
)
from .presentation import add_icb_supersector_names, region_bucket_value

__all__ = [
    "SCREEN_AGGREGATE_PATH",
    "RETURNS_PATH",
    "LAST_SCREEN_PATH",
    "PRODUCTION_INPUTS_DIR",
    "data_contract",
    "validate_returns_contract",
    "validate_screen_contract",
    "region_bucket_value",
    "add_icb_supersector_names",
]

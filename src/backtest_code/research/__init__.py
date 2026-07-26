"""Deprecated compatibility facade for :mod:`tp_research`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_research import (
    GateThresholds,
    RelativeLevelSpec,
    build_same_security_relative_variables,
    build_synergy_candidate_matrix,
    dedupe_official_results,
    evaluate_official_top_worst_gate,
    incomplete_official_metrics,
    new_wave_id,
    read_official_results,
    shard_metric_names,
    shard_result_path,
)

warn_legacy_entrypoint(
    legacy="backtest_code.research",
    replacement="tp_research",
)

__all__ = [
    "GateThresholds",
    "RelativeLevelSpec",
    "build_same_security_relative_variables",
    "build_synergy_candidate_matrix",
    "dedupe_official_results",
    "evaluate_official_top_worst_gate",
    "incomplete_official_metrics",
    "new_wave_id",
    "read_official_results",
    "shard_metric_names",
    "shard_result_path",
]

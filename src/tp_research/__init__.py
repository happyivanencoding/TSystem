"""Public API for TP factor-research execution primitives."""

from .executor import (
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

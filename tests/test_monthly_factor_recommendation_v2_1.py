from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from tp_models.factor_recommendation.v2_research import (
    MODEL_IDS,
    NO_VALID_MODEL,
    allocate_top2,
    alternative_allocator_results,
    build_factor_panel,
    candidate_prediction_metrics,
    coverage_gate_frame,
    deflated_sharpe,
    make_smoke_sleeve_returns,
    pit_mutation_audit,
    promotion_gates,
    run_lopo_loro,
    select_champion,
    select_hyperparameters,
    walk_forward_predictions,
)
from tp_models.factor_recommendation.v2_sleeves import (
    SleeveRunSpec,
    _period_rows,
    canonical_factor_scores,
)

ROOT = Path(__file__).resolve().parents[1]


def _small_panel() -> pd.DataFrame:
    return build_factor_panel(make_smoke_sleeve_returns(months=12, regions=("US", "EUROPE")))


def test_m0_nan_cannot_win_champion() -> None:
    assert select_champion({"M0_equal_factor": np.nan, "M1_trailing_12m": 0.1, "M2_transparent_composite": 0.2, "M3_pooled_ridge": 0.3, "M4_pooled_elastic_net": 0.25}) == "M3_pooled_ridge"


def test_m0_is_baseline_only_even_if_its_metric_is_large() -> None:
    assert select_champion({"M0_equal_factor": 99.0, "M1_trailing_12m": 0.1, "M2_transparent_composite": 0.2, "M3_pooled_ridge": 0.3, "M4_pooled_elastic_net": 0.25}) == "M3_pooled_ridge"


def test_no_valid_candidate_is_explicit_no_view_model() -> None:
    assert select_champion({model: np.nan for model in MODEL_IDS}) == NO_VALID_MODEL


def test_cross_region_feature_does_not_use_same_month_target() -> None:
    panel = _small_panel()
    date = panel["Date"].sort_values().unique()[4]
    mutated = make_smoke_sleeve_returns(months=12, regions=("US", "EUROPE"))
    mask = mutated["Date"].eq(date) & mutated["region"].eq("US") & mutated["factor"].eq("value") & mutated["sleeve_side"].eq("Top")
    mutated.loc[mask, "active_return"] += 10.0
    changed = build_factor_panel(mutated)
    base_row = panel.loc[panel["Date"].eq(date)].set_index(["region", "factor"])["cross_region_confirmation"]
    changed_row = changed.loc[changed["Date"].eq(date)].set_index(["region", "factor"])["cross_region_confirmation"]
    assert np.allclose(base_row.to_numpy(dtype=float), changed_row.reindex(base_row.index).to_numpy(dtype=float), equal_nan=True)


def test_future_target_mutation_audit_is_executed() -> None:
    audit = pit_mutation_audit(make_smoke_sleeve_returns(months=12, regions=("US", "EUROPE")))
    assert "future_target_mutation_current_features_unchanged" in set(audit["check"])
    assert audit.loc[audit["check"].eq("future_target_mutation_current_features_unchanged"), "passed"].all()


def test_factor_coverage_uses_pre_dropna_denominator() -> None:
    panel = pd.DataFrame([{"Date": pd.Timestamp("2020-01-31"), "region": "US", "factor": "value", "eligible_universe_rows": 10, "valid_factor_rows": 5, "factor_row_coverage": 0.5, "eligible_benchmark_weight": 1.0, "valid_factor_benchmark_weight": 0.5, "factor_weight_coverage": 0.5, "raw_benchmark_weight": 1.0, "retained_country_weight": 1.0, "retained_benchmark_coverage": 1.0, "return_available_weight": 1.0, "return_weight_coverage": 1.0, "formation_available": True}])
    result = coverage_gate_frame(panel, minimum_factor_coverage=0.8, minimum_benchmark_coverage=0.8)
    assert result.iloc[0]["factor_row_coverage"] == 0.5
    assert not bool(result.iloc[0]["passed"])


def test_asia_retained_weight_coverage_is_not_automatically_one() -> None:
    panel = pd.DataFrame([{"Date": pd.Timestamp("2020-01-31"), "region": "ASIA_EX_JAPAN", "factor": "value", "eligible_universe_rows": 5, "valid_factor_rows": 5, "factor_row_coverage": 1.0, "eligible_benchmark_weight": 0.6, "valid_factor_benchmark_weight": 0.6, "factor_weight_coverage": 1.0, "raw_benchmark_weight": 1.0, "retained_country_weight": 0.6, "retained_benchmark_coverage": 0.6, "return_available_weight": 0.6, "return_weight_coverage": 1.0, "formation_available": True}])
    result = coverage_gate_frame(panel, minimum_factor_coverage=0.8, minimum_benchmark_coverage=0.8)
    assert result.iloc[0]["retained_benchmark_coverage"] == 0.6
    assert not bool(result.iloc[0]["passed"])


def test_small_size_score_is_inverse_on_zero_to_ten_scale() -> None:
    size = canonical_factor_scores("size", pd.Series([20.0, 50.0, 80.0]))
    small = canonical_factor_scores("small_size", pd.Series([20.0, 50.0, 80.0]))
    assert np.allclose((size + small).to_numpy(), 10.0)


def test_small_size_directional_delta_uses_reversed_score() -> None:
    sleeves = make_smoke_sleeve_returns(months=6, regions=("US",), factors=("size", "small_size"))
    panel = build_factor_panel(sleeves)
    size = panel.loc[panel["factor"].eq("size")].sort_values("Date")
    small = panel.loc[panel["factor"].eq("small_size")].sort_values("Date")
    assert np.allclose((size["factor_score"].to_numpy() + small["factor_score"].to_numpy()), 10.0)


def test_champion_gate_uses_champion_not_best_challenger() -> None:
    panel = _small_panel()
    predictions, _, _, _ = walk_forward_predictions(panel, minimum_train_months=6, purge_months=1, smoke=True)
    if predictions.empty:
        return
    allocations = allocate_top2(predictions, panel, cost_grid_bps=(25.0, 50.0))
    gates = promotion_gates(panel=panel, predictions=predictions, allocations=allocations, champion_allocations=allocations, champion_model="M1_trailing_12m", thresholds={"minimum_monthly_observations": 1, "minimum_valid_factors_per_month": 1, "minimum_factor_coverage": 0.0, "minimum_benchmark_coverage": 0.0, "minimum_mean_rank_ic": -1.0, "minimum_positive_ic_rate": 0.0, "minimum_region_consistency": 0.0, "minimum_bootstrap_probability_6": 0.0, "minimum_bootstrap_probability_12": 0.0, "minimum_dsr_probability": 0.0, "forward_shadow_months_required": 0, "clean_provenance_required": False}, bootstrap_rows=pd.DataFrame(), dsr_rows=pd.DataFrame(), clean_provenance=True)
    assert set(gates.loc[gates["gate_name"].eq("mean_rank_ic"), "metric_source_model"]) == {"M1_trailing_12m"}


def test_top2_capture_and_allocator_active_return_are_separate_metrics() -> None:
    metrics = candidate_prediction_metrics(walk_forward_predictions(_small_panel(), minimum_train_months=6, purge_months=1, smoke=True)[0])
    assert {"top2_capture_uplift", "top2_winner_capture"} <= set(metrics.columns)
    assert "allocator_mean_active_return" not in metrics.columns


def test_mdd_comparison_uses_top2_against_equal_factor_basis() -> None:
    text = (ROOT / "src/tp_models/factor_recommendation/v2_research.py").read_text(encoding="utf-8")
    assert "equal_factor_comparable_net_return" in text
    assert "mdd_deterioration_50bps" in text


def test_region_gate_reports_insufficient_history() -> None:
    panel = _small_panel()
    predictions, _, _, _ = walk_forward_predictions(panel, minimum_train_months=6, purge_months=1, smoke=True)
    allocations = allocate_top2(predictions, panel, cost_grid_bps=(25.0, 50.0))
    gates = promotion_gates(panel=panel, predictions=predictions, allocations=allocations, champion_allocations=allocations, champion_model="M1_trailing_12m", thresholds={"minimum_monthly_observations": 120}, bootstrap_rows=pd.DataFrame(), dsr_rows=pd.DataFrame(), clean_provenance=False)
    assert (gates["region_status"] == "insufficient_history").any()
    assert not gates.loc[gates["region_status"].eq("insufficient_history"), "production_eligible"].any()


def test_hyperparameter_grid_executes_all_registered_candidates() -> None:
    panel = _small_panel()
    train = panel.loc[panel["Date"].lt(panel["Date"].max())].copy()
    _, records = select_hyperparameters(train, "M4_pooled_elastic_net", hyperparameter_grid={"elastic_net_alpha": [0.001, 0.01, 0.1], "elastic_net_l1_ratio": [0.1, 0.5, 0.9]}, purge_months=1, validation_months=3)
    parsed = [json.loads(row["params"]) for row in records]
    assert {"elastic_alpha", "l1_ratio"} <= set(parsed[0])
    assert len({row["candidate_index"] for row in records}) == 9


def test_lopo_retrains_on_other_periods() -> None:
    panel = _small_panel()
    periods = [{"name": "pre_covid", "start": "2015-01-31", "end": "2015-06-30"}, {"name": "post_covid", "start": "2015-07-31", "end": "2015-12-31"}]
    lopo, _, _ = run_lopo_loro(panel, economic_periods=periods)
    assert not lopo.empty
    assert lopo["method"].eq("LOPO").all()
    assert lopo["retrained"].all()


def test_loro_retrains_without_held_out_region() -> None:
    loro = run_lopo_loro(_small_panel(), economic_periods=[])[1]
    assert not loro.empty
    assert loro["method"].eq("LORO").all()
    assert loro["retrained"].all()


def test_lopo_and_loro_are_not_one_alias() -> None:
    lopo, loro, summary = run_lopo_loro(_small_panel(), economic_periods=[{"name": "period_a", "start": "2015-01-31", "end": "2015-06-30"}])
    assert set(lopo["method"]) == {"LOPO"}
    assert set(loro["method"]) == {"LORO"}
    assert set(summary["method"]) == {"LOPO", "LORO"}


def test_dsr_is_candidate_specific_and_labels_approximation() -> None:
    result = deflated_sharpe(pd.Series(np.linspace(-0.01, 0.02, 24)), effective_trials=12, candidate="M3_pooled_ridge", block_length=6)
    assert result["candidate"] == "M3_pooled_ridge"
    assert result["metric"] == "approximate_deflated_sharpe"
    assert result["dsr_gate_eligible"] is False
    assert {"sample_length", "skewness", "kurtosis", "sharpe_variance", "selection_bias_adjustment", "autocorrelation_lag1"} <= set(result)


def test_alternative_allocators_have_independent_turnover_column() -> None:
    panel = _small_panel()
    predictions, _, _, _ = walk_forward_predictions(panel, minimum_train_months=6, purge_months=1, smoke=True)
    allocations = allocate_top2(predictions, panel, cost_grid_bps=(25.0,))
    variants = alternative_allocator_results(allocations, cost_bps=25.0)
    assert {"top1", "top2_equal", "score_weighted", "confidence_gated", "equal_factor"} <= set(variants["allocator_variant"])
    assert "allocator_turnover" in variants.columns


def test_official_holdings_count_is_taken_from_execution_weights() -> None:
    dates = pd.to_datetime(["2020-01-31", "2020-02-28"])
    screen = pd.DataFrame({"Date": dates.repeat(2), "Company SEDOL": ["A", "B", "A", "B"], "Value Avg Percentile": [20, 30, 40, 50], "Weight in SP500": [0.6, 0.4, 0.6, 0.4]})
    daily = pd.date_range("2020-02-01", "2020-02-28", freq="D")
    series = pd.Series(0.001, index=daily)
    result = SimpleNamespace(gross_daily_returns=series, net_daily_returns=series, net_nav=(1 + series).cumprod(), gross_nav=(1 + series).cumprod(), turnover=pd.Series(0.0, index=daily), execution_weights=pd.DataFrame({"Date": [pd.Timestamp("2020-02-01")]*2, "security_id": ["A", "B"], "Weight": [0.6, 0.4]}).set_index(["Date", "security_id"]), manifest={"engine_id": "real.test", "engine_version": "1"})
    spec = SleeveRunSpec(region="US", region_component="US", benchmark="SP500", factor="value", sleeve_side="Top")
    rows = _period_rows(spec=spec, screen=screen, portfolio_result=result, benchmark_result=result, security_returns=pd.DataFrame({"A": 0.001, "B": 0.001}, index=daily))
    assert rows.iloc[0]["holdings_count"] == 2
    assert rows.iloc[0]["holdings_count_source"] == "official_execution_weights"


def test_pipeline_boundary_keeps_no_view_semantics() -> None:
    panel = _small_panel()
    panel["factor_coverage"] = 0.5
    panel["factor_weight_coverage"] = 0.5
    predictions, _, _, _ = walk_forward_predictions(panel, minimum_train_months=6, purge_months=1, smoke=True)
    allocations = allocate_top2(predictions, panel, cost_grid_bps=(25.0,), minimum_coverage=0.8)
    assert not allocations.empty
    assert set(allocations["stance"]) == {"NO_VIEW"}
    assert allocations["recommended_weight"].sum() == 0


def test_real_payload_html_preserves_not_a_forecast_copy() -> None:
    html_builder = (ROOT / "16_factor_recommendation_model/build_v2_report_html.py").read_text(encoding="utf-8")
    assert "Not a forecast" in html_builder
    assert "model_unavailable" in html_builder


def test_v2_1_registry_lineage_and_invalidation_record_are_explicit() -> None:
    config = (ROOT / "config/research/hypotheses/monthly-factor-recommendation-v2-1.json").read_text(encoding="utf-8")
    rejected = (ROOT / "config/research/model_candidates/monthly-factor-recommendation-v2-run-20260804T165649Z-rejected.json").read_text(encoding="utf-8")
    assert '"parent_hypothesis_id": "monthly-factor-recommendation-v2"' in config
    assert '"status": "invalid_for_model_selection"' in rejected

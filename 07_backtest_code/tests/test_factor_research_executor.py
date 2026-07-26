import numpy as np
import pandas as pd
import pytest

from backtest_code.research.executor import (
    GateThresholds,
    RelativeLevelSpec,
    build_same_security_relative_variables,
    build_synergy_candidate_matrix,
    dedupe_official_results,
    evaluate_official_top_worst_gate,
    incomplete_official_metrics,
    shard_metric_names,
)


def test_resume_requires_both_official_sides():
    completed = pd.DataFrame(
        {
            "metric": ["a", "a", "b"],
            "side": ["Top", "Worst", "Top"],
            "status": ["success", "success", "success"],
        }
    )

    assert incomplete_official_metrics(["a", "b"], completed) == ["b"]


def test_dedupe_prefers_success_over_failed():
    results = pd.DataFrame(
        {
            "metric": ["a", "a"],
            "side": ["Top", "Top"],
            "status": ["failed", "success"],
            "value": [1, 2],
        }
    )

    output = dedupe_official_results(results)

    assert output.iloc[0]["status"] == "success"
    assert output.iloc[0]["value"] == 2


def test_gate_requires_worst_and_all_thresholds():
    summary = pd.DataFrame(
        {
            "metric": ["good", "good", "missing_worst"],
            "side": ["Top", "Worst", "Top"],
            "status": ["success", "success", "success"],
            "coverage": [np.nan, np.nan, np.nan],
            "ratio_cagr": [0.02, np.nan, 0.03],
            "top_worst_ratio_return": [0.04, np.nan, 0.05],
            "robust_score": [1.0, np.nan, 1.2],
        }
    )
    diagnostics = pd.DataFrame(
        {"metric": ["good", "missing_worst"], "coverage": [0.9, 0.9]}
    )

    gate = evaluate_official_top_worst_gate(
        summary,
        diagnostics,
        thresholds=GateThresholds(min_coverage=0.75),
    ).set_index("metric")

    assert bool(gate.loc["good", "pass_gate"])
    assert not bool(gate.loc["missing_worst", "pass_gate"])
    assert "official_worst_incomplete" in gate.loc[
        "missing_worst", "fail_reasons"
    ]


def test_gate_ignores_source_and_diagnostic_labels():
    summary = pd.DataFrame(
        {
            "metric": ["ciq_pass", "ciq_pass", "core_fail", "core_fail"],
            "side": ["Top", "Worst", "Top", "Worst"],
            "status": ["success", "success", "success", "success"],
            "ratio_cagr": [0.02, np.nan, -0.01, np.nan],
            "top_worst_ratio_return": [0.04, np.nan, -0.02, np.nan],
            "robust_score": [1.0, np.nan, -0.5, np.nan],
        }
    )
    diagnostics = pd.DataFrame(
        {
            "metric": ["ciq_pass", "core_fail"],
            "coverage": [0.9, 0.9],
        }
    )
    metadata = pd.DataFrame(
        {
            "metric": ["ciq_pass", "core_fail"],
            "source": ["CIQ", "local"],
            "diagnostic_label": ["supplement", "core"],
        }
    )

    gate = evaluate_official_top_worst_gate(
        summary,
        diagnostics,
        thresholds=GateThresholds(min_coverage=0.75),
        metadata=metadata,
    ).set_index("metric")

    assert bool(gate.loc["ciq_pass", "pass_gate"])
    assert not bool(gate.loc["core_fail", "pass_gate"])


def test_gate_keeps_requested_metrics_with_no_result_rows():
    summary = pd.DataFrame(
        columns=[
            "metric",
            "side",
            "status",
            "ratio_cagr",
            "top_worst_ratio_return",
            "robust_score",
        ]
    )
    diagnostics = pd.DataFrame(
        {"metric": ["missing"], "coverage": [0.9]}
    )

    gate = evaluate_official_top_worst_gate(
        summary,
        diagnostics,
        thresholds=GateThresholds(),
        metrics=["missing"],
    ).set_index("metric")

    assert not bool(gate.loc["missing", "pass_gate"])
    assert "official_top_incomplete" in gate.loc["missing", "fail_reasons"]
    assert "official_worst_incomplete" in gate.loc["missing", "fail_reasons"]


def test_relative_builder_uses_same_security_observation_lag():
    screen = pd.DataFrame(
        {
            "Date": pd.to_datetime(
                ["2024-01-31", "2024-02-29", "2024-01-31", "2024-02-29"]
            ),
            "ISIN": ["A", "A", "B", "B"],
            "Sector": [1, 1, 1, 1],
            "level": [1.0, 3.0, 5.0, 4.0],
            "level_score": [0.2, 0.8, 0.9, 0.4],
        }
    )
    specs = [
        RelativeLevelSpec(
            raw_column="level",
            score_column="level_score",
            family="growth",
        )
    ]

    output, definitions = build_same_security_relative_variables(
        screen,
        specs,
        lags=[1],
        transforms=["directional_delta", "score_delta"],
        date_col="Date",
        security_col="ISIN",
        sector_col="Sector",
        raw_score=lambda frame, spec: frame[spec.score_column],
        winsorize=lambda values, dates: values,
        sector_score=lambda values, dates, sectors: values,
        column_name=lambda spec, transform, lag: f"{transform}_{lag}",
    )

    latest = output[output["Date"].eq(pd.Timestamp("2024-02-29"))].set_index(
        "ISIN"
    )
    assert latest.loc["A", "directional_delta_1"] == 2.0
    assert latest.loc["B", "directional_delta_1"] == -1.0
    assert latest.loc["A", "score_delta_1"] == pytest.approx(0.6)
    assert definitions["metric"].tolist() == [
        "directional_delta_1",
        "score_delta_1",
    ]


def test_synergy_builder_emits_pair_subset_and_leave_one_out():
    screen = pd.DataFrame(
        {
            "a": [0.1, 0.2],
            "b": [0.3, 0.4],
            "c": [0.5, 0.6],
        }
    )
    legs = pd.DataFrame(
        {
            "metric": ["a", "b", "c"],
            "bucket": ["revision", "momentum", "growth"],
        }
    )

    def weighted(frame, components, min_count):
        values = frame[list(components)].mul(pd.Series(components), axis=1)
        return values.sum(axis=1, min_count=min_count)

    def averaged(frame, columns, min_count):
        values = frame[list(columns)]
        return values.mean(axis=1).where(values.notna().sum(axis=1) >= min_count)

    output, candidates = build_synergy_candidate_matrix(
        screen,
        legs,
        bucket_order=["revision", "momentum", "growth"],
        prefix="test",
        weighted_scores=weighted,
        average_scores=averaged,
        subset_sizes=[2],
        include_individual_leave_one_out=True,
    )

    types = set(candidates["candidate_type"])
    assert {"pair", "family_subset", "full_model", "leave_one_out"}.issubset(types)
    assert "leave_one_variable_out" in types
    assert set(candidates["metric"]).issubset(output.columns)


def test_metric_shards_are_disjoint_and_complete():
    shards = shard_metric_names(["a", "b", "c", "d"], 3)

    assert sorted(metric for shard in shards for metric in shard) == [
        "a",
        "b",
        "c",
        "d",
    ]
    assert len({metric for shard in shards for metric in shard}) == 4

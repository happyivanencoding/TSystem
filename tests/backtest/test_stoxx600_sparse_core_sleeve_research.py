import numpy as np
import pandas as pd

from tp_research.workflows import build_stoxx600_sparse_factor_explorer as explorer
from tp_research.workflows import (
    run_stoxx600_sparse_core_sleeve_research as research,
)


def test_candidate_registry_is_frozen_and_propagates_missing_values():
    screen = pd.DataFrame(
        {
            spec.metric: [1.0, np.nan, 3.0]
            for spec in research.SIGNALS
        }
    )

    output, registry = research.build_candidate_registry(screen)

    assert len(registry) == 39
    assert registry["metric"].nunique() == 39
    assert int(registry["deployable_architecture"].sum()) == 5
    assert int(registry["candidate_type"].eq("leave_one_out").sum()) == 12
    assert np.isnan(output.loc[1, "stoxx600_sparse_core3_equal"])


def test_small_valid_universe_blocks_overlapping_top_and_worst():
    dates = [pd.Timestamp("2020-01-31")] * 10 + [
        pd.Timestamp("2020-02-29")
    ] * 10
    screen = pd.DataFrame(
        {
            research.DATE_COL: dates,
            "test_metric": [
                1.0,
                2.0,
                3.0,
                *([np.nan] * 7),
                *range(10),
            ],
        }
    )

    monthly, summary = research.metric_monthly_diagnostics(
        screen,
        ["test_metric"],
    )

    first = monthly.loc[
        monthly["date"].eq(pd.Timestamp("2020-01-31"))
    ].iloc[0]
    second = monthly.loc[
        monthly["date"].eq(pd.Timestamp("2020-02-29"))
    ].iloc[0]
    assert first["target_count_per_side"] == 2
    assert not bool(first["top_worst_disjoint_possible"])
    assert not bool(first["eligible_month"])
    assert bool(second["top_worst_disjoint_possible"])
    assert int(summary.iloc[0]["months_disjoint_impossible"]) == 1


def test_synergy_stays_incomplete_without_pair_and_leave_one_out_evidence():
    summary = pd.DataFrame(
        {
            "metric": ["stoxx600_sparse_core3_equal"],
            "side": ["Top"],
            "status": ["success"],
        }
    )
    gate = pd.DataFrame(
        {
            "metric": ["stoxx600_sparse_core3_equal"],
            "pass_gate": [True],
        }
    )
    _, registry = research.build_candidate_registry(
        pd.DataFrame(
            {
                spec.metric: [1.0]
                for spec in research.SIGNALS
            }
        )
    )

    evidence = research.build_synergy_evidence(summary, gate, registry)

    assert len(evidence) == len(research.SLEEVE_KEYS)
    assert evidence["classification"].eq("incomplete").all()
    assert not evidence["evidence_complete"].any()


def test_missing_benchmark_month_keeps_holdings_and_drifts_weights(tmp_path):
    security_list = tmp_path / "sec_list.parquet"
    pd.DataFrame(
        {
            research.DATE_COL: [
                pd.Timestamp("2009-11-01"),
                pd.Timestamp("2009-11-01"),
                pd.Timestamp("2009-12-01"),
                pd.Timestamp("2009-12-01"),
            ],
            research.ISIN_COL: ["A", "B", "A", "B"],
            "Weight": [0.5, 0.5, 0.6, 0.4],
        }
    ).to_parquet(security_list, index=False)
    results = pd.DataFrame(
        {
            "metric": [
                research.SIGNAL_BY_KEY["revision"].metric,
            ],
            "side": ["Top"],
            "status": ["success"],
            "sec_list": [str(security_list)],
        }
    )

    check = research.verify_missing_month_drift(results).iloc[0]

    assert bool(check["verified"])
    assert bool(check["same_security_set"])
    assert int(check["changed_weight_count"]) == 2
    assert bool(check["weights_normalized"])


def test_explorer_chart_has_static_no_javascript_fallback():
    markup = explorer.build_chart_markup(
        [
            {
                "date": "2020-01-31",
                "top": 100.0,
                "worst": 100.0,
                "benchmark": 100.0,
            },
            {
                "date": "2020-02-29",
                "top": 104.0,
                "worst": 98.0,
                "benchmark": 101.0,
            },
        ]
    )

    assert markup.count("<polyline") == 3
    assert 'data-series="top"' in markup
    assert 'data-series="worst"' in markup
    assert 'data-series="benchmark"' in markup

from __future__ import annotations

import numpy as np
import pandas as pd

from tp_research.workflows.run_regime_direct_risk_challengers import (
    _current_hmm_predictions,
    _risk_percentile,
    _uniform_metrics,
)
from tp_research.workflows.run_regime_direct_risk_challengers_v2 import (
    _causal_stack_features,
    _fit_stacked_meta_model,
    _joint_summary_strict,
)


def test_risk_percentile_uses_only_supplied_history() -> None:
    history = pd.Series([1.0, 2.0, 3.0, 4.0])

    assert _risk_percentile(2.5, history) == 0.5


def test_uniform_metrics_rank_higher_predictions_as_higher_risk() -> None:
    dates = pd.date_range("2020-01-31", periods=12, freq="ME")
    actual = pd.Series(np.arange(1, 13), index=dates, dtype=float)
    prediction = actual.copy()

    metrics = _uniform_metrics(actual, prediction)

    assert metrics["months"] == 12
    assert metrics["spearman"] == 1.0
    assert metrics["high_risk_auc"] == 1.0
    assert metrics["recall"] == 1.0


def test_current_hmm_prediction_does_not_use_current_target(
    monkeypatch,
    tmp_path,
) -> None:
    dates = pd.date_range("2020-01-31", periods=4, freq="ME")
    states = pd.DataFrame({"state": [0, 0, 1, 0]}, index=dates)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    states.to_parquet(output_dir / "regime_oos_US.parquet")
    monkeypatch.setattr(
        "tp_research.workflows.run_regime_direct_risk_challengers."
        "regime_config.OUTPUT_DIR",
        output_dir,
    )
    original = pd.Series([1.0, 3.0, 100.0, 999.0], index=dates)
    changed = original.copy()
    changed.iloc[-1] = -999.0

    first = _current_hmm_predictions("US", original, dates)
    second = _current_hmm_predictions("US", changed, dates)

    assert first.loc[3, "prediction"] == second.loc[3, "prediction"]
    assert first.loc[3, "prediction"] == 2.0


def test_joint_summary_does_not_skip_missing_target() -> None:
    rows = []
    for target, months, spearman, auc in [
        ("fwd_vol", 36, 0.5, 0.8),
        ("fwd_mdd", 0, np.nan, np.nan),
    ]:
        rows.append(
            {
                "region": "US",
                "target": target,
                "period": "common_validation_2018_2021",
                "model": "ridge",
                "months": months,
                "spearman": spearman,
                "high_risk_auc": auc,
                "precision": 0.5,
                "recall": 0.5,
                "false_positive_rate": 0.2,
            }
        )

    summary = _joint_summary_strict(pd.DataFrame(rows)).iloc[0]

    assert not summary["target_metrics_complete"]
    assert np.isnan(summary["joint_score"])


def test_stacked_meta_model_does_not_use_current_target() -> None:
    dates = pd.date_range("2018-01-31", periods=36, freq="ME")
    rows = []
    model_names = [
        "volatility_persistence",
        "current_hmm",
        "ridge",
        "elastic_net",
        "logistic",
        "markov_switching_ar",
        "ridge_logistic_ensemble",
    ]
    for offset, date in enumerate(dates):
        for model_position, model_name in enumerate(model_names):
            rows.append(
                {
                    "Date": date,
                    "model": model_name,
                    "prediction": float(offset + model_position + 1),
                }
            )
    base_predictions = pd.DataFrame(rows)
    original = pd.Series(np.arange(1, 37), index=dates, dtype=float)
    changed = original.copy()
    changed.iloc[-1] = 1_000_000.0

    first = _fit_stacked_meta_model(
        base_predictions,
        original,
        min_meta_train=24,
    )
    second = _fit_stacked_meta_model(
        base_predictions,
        changed,
        min_meta_train=24,
    )

    assert first.iloc[-1]["Date"] == dates[-1]
    assert first.iloc[-1]["prediction"] == second.iloc[-1]["prediction"]


def test_stack_masks_non_converged_base_prediction() -> None:
    dates = pd.date_range("2020-01-31", periods=8, freq="ME")
    rows = []
    for date in dates:
        for model_name in [
            "volatility_persistence",
            "current_hmm",
            "ridge",
            "elastic_net",
            "logistic",
            "markov_switching_ar",
            "ridge_logistic_ensemble",
        ]:
            rows.append(
                {
                    "Date": date,
                    "model": model_name,
                    "prediction": 1.0,
                    "fit_success": True,
                    "fit_converged": model_name
                    != "markov_switching_ar",
                }
            )

    features = _causal_stack_features(pd.DataFrame(rows))

    assert (
        features.iloc[-1]["markov_switching_ar__available"] == 0.0
    )
    assert features.iloc[-1]["markov_switching_ar__score"] == 0.5

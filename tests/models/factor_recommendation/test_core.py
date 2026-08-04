from __future__ import annotations

import numpy as np
import pandas as pd
import builtins

from tp_models.factor_recommendation.evaluation import (
    evaluate_factor_models,
    same_month_grouped_folds,
)
from tp_models.factor_recommendation.factor_definitions import FactorDefinition
from tp_models.factor_recommendation.features import build_monthly_features, build_security_feature_panel
from tp_models.factor_recommendation.models import fit_factor_models, fit_model, predict_factor_recommendations
from tp_models.factor_recommendation.persistence import upsert_frame
from tp_models.factor_recommendation.targets import build_next_month_targets
from tp_models.factor_recommendation.universe import load_region_universes, select_universe


def _screen() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for date_index, date in enumerate(pd.date_range("2020-01-31", periods=5, freq="ME")):
        rows.extend(
            [
                {
                    "ISIN": f"J{date_index}",
                    "Company SEDOL": f"J{date_index}",
                    "Date": date,
                    "Exchange Country Iso2": "JP",
                    "Weight in NIKKEI": 1.0,
                    "Weight in MSCI EM": 0.0,
                    "Value": 2.0 + date_index,
                    "Size": 8.0 - date_index,
                },
                {
                    "ISIN": f"C{date_index}",
                    "Company SEDOL": f"C{date_index}",
                    "Date": date,
                    "Exchange Country Iso2": "CN",
                    "Weight in NIKKEI": 0.0,
                    "Weight in MSCI EM": 0.4,
                    "Value": 8.0 - date_index,
                    "Size": 2.0 + date_index,
                },
                {
                    "ISIN": f"U{date_index}",
                    "Company SEDOL": f"U{date_index}",
                    "Date": date,
                    "Exchange Country Iso2": "US",
                    "Weight in NIKKEI": 0.0,
                    "Weight in MSCI EM": 0.3,
                    "Value": 5.0,
                    "Size": 5.0,
                },
            ]
        )
    return pd.DataFrame(rows)


def _definitions() -> tuple[FactorDefinition, ...]:
    return (
        FactorDefinition("value", "Value", ("Value",)),
        FactorDefinition("size", "Large Size", ("Size",)),
        FactorDefinition("small_size", "Small Size", ("Size",), direction=-1, transform="reverse_score"),
    )


def test_asia_is_fixed_dual_component_research_union() -> None:
    screen = _screen()
    selection = select_universe(screen, "ASIA")
    assert selection.research_only is True
    assert selection.benchmark_approved is False
    assert set(selection.frame["universe_component"]) == {"JAPAN", "ASIA_EX_JAPAN"}
    assert not selection.frame["Exchange Country Iso2"].eq("US").any()
    assert set(selection.frame["component_aggregation_weight"]) == {0.5}
    spec = load_region_universes()["ASIA"]
    assert dict(spec.aggregation_weights) == {"JAPAN": 0.5, "ASIA_EX_JAPAN": 0.5}
    assert spec.production_eligible is False


def test_features_have_pit_lag_and_small_size_is_inverse() -> None:
    panel = build_security_feature_panel(_screen(), "ASIA", definitions=_definitions())
    assert panel["Date"].min() == pd.Timestamp("2020-02-29")
    assert (panel["feature_as_of_date"] < panel["Date"]).all()
    assert (panel["target_date"] > panel["Date"]).all()
    j0 = panel.loc[panel["ISIN"].eq("J0")].iloc[0]
    assert j0["size"] == 8.0
    assert j0["small_size"] == 2.0

    monthly = build_monthly_features(_screen(), "ASIA", definitions=_definitions())
    first = monthly.iloc[0]
    assert first["value"] == 5.0  # fixed 0.5 / 0.5 component aggregation
    assert first["component_aggregation_weight_sum"] == 1.0


def test_next_month_targets_and_grouped_folds_are_temporal() -> None:
    dates = pd.date_range("2020-01-31", periods=6, freq="ME")
    frame = pd.DataFrame({"Date": dates, "feature": range(6), "value": np.arange(6) / 100})
    targets = build_next_month_targets(frame, ["value"])
    assert targets.loc[0, "target_date"] == dates[1]
    assert targets.loc[0, "target_value"] == 0.01
    assert pd.isna(targets.iloc[-1]["target_value"])
    folds = same_month_grouped_folds(dates, n_splits=3)
    for train, test in folds:
        assert set(train).isdisjoint(set(test))
        assert max(dates[train]) < min(dates[test])


def test_models_evaluation_probability_and_idempotent_persistence(tmp_path) -> None:
    dates = pd.date_range("2020-01-31", periods=10, freq="ME")
    frame = pd.DataFrame(
        {
            "Date": dates,
            "feature": np.arange(10, dtype=float),
            "target_value": np.arange(10, dtype=float) / 100,
        }
    )
    models = fit_factor_models(frame, ["value"], feature_columns=["feature"])
    recommendation = predict_factor_recommendations(models, frame.tail(1), region="US")
    assert recommendation["probability_available"].eq(False).all()
    assert recommendation["probability"].isna().all()
    evaluation = evaluate_factor_models(
        frame, ["value"], feature_columns=["feature"], n_splits=3
    )
    assert evaluation.probability_available is False
    assert evaluation.predictions["probability"].isna().all()

    records = recommendation.assign(region="US", model_version="v1")
    path = tmp_path / "recommendations.parquet"
    first = upsert_frame(path, records)
    second = upsert_frame(path, records)
    assert len(first) == len(second) == 1


def test_optional_sklearn_missing_has_transparent_ridge_fallback(monkeypatch) -> None:
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "sklearn.linear_model" or name.startswith("sklearn.linear_model."):
            raise ImportError("blocked by unit test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    model = fit_model(
        pd.DataFrame({"feature": [1.0, 2.0, 3.0]}),
        pd.Series([0.1, 0.2, 0.3]),
        model_type="elasticnet",
        feature_names=["feature"],
    )
    assert model.backend == "numpy_ridge_fallback"
    assert "scikit-learn unavailable" in (model.fallback_reason or "")

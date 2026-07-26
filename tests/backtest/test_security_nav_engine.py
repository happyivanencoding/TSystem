import numpy as np
import pandas as pd
import pytest

from tp_backtest.runner.artifacts import read_manifest, save_manifest
from tp_core.backtesting import build_security_nav_engine
from tp_core.security_nav_engine import (
    NAV_ENGINE_ID,
    NAV_ENGINE_VERSION,
    TargetWeightSchema,
    SecurityNavEngine,
    calculate_return_series_nav,
    calculate_security_nav,
    load_returns,
    map_rebalance_to_execution_dates,
    normalize_rebalance_weights,
)


def _sample_returns():
    return pd.DataFrame(
        {
            "A": [0.10, 0.00, 0.00],
            "B": [0.00, 0.20, 0.00],
        },
        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
    )


def _sample_weights():
    return pd.DataFrame(
        [
            {"Date": "2024-01-01", "Company SEDOL": "A", "Portfolio weight": 2.0},
            {"Date": "2024-01-01", "Company SEDOL": "B", "Portfolio weight": 1.0},
            {"Date": "2024-01-01", "Company SEDOL": "C", "Portfolio weight": 1.0},
        ]
    )


def test_security_nav_engine_filters_normalizes_and_drifts_weights():
    result = calculate_security_nav(weights=_sample_weights(), returns=_sample_returns())

    assert result.manifest["dropped_not_in_returns_rows"] == 1
    assert result.manifest["rebalance_date_count"] == 1
    assert result.manifest["execution_date_count"] == 1
    assert result.nav.index[0] == pd.Timestamp("2024-01-02")
    assert np.isclose(result.daily_returns.loc["2024-01-02"], 0.0)
    assert np.isclose(result.daily_returns.loc["2024-01-03"], 1.0 / 3.0 * 0.20)
    assert np.isclose(result.nav.loc["2024-01-03"], 100.0 * (1.0 + 1.0 / 3.0 * 0.20))


def test_active_backtest_engine_exposes_general_run_weights():
    engine = build_security_nav_engine(_sample_returns())

    assert isinstance(engine, SecurityNavEngine)
    result = engine.run_weights(
        _sample_weights(),
        schema=TargetWeightSchema(date_col="Date", id_col="Company SEDOL", weight_col="Portfolio weight"),
    )

    assert engine.last_result is result
    assert result.execution_weights.index.names == ["Date", "Company SEDOL"]


def _legacy_iterrows_daily_returns(
    weights,
    returns,
    *,
    apply_weights_at_close,
):
    schema = TargetWeightSchema()
    normalized, _ = normalize_rebalance_weights(
        weights,
        returns_columns=returns.columns,
        schema=schema,
    )
    execution_weights, _ = map_rebalance_to_execution_dates(
        normalized,
        returns_index=returns.index,
        schema=schema,
    )
    target_by_date = {
        pd.Timestamp(date): group.set_index(schema.id_col)[schema.weight_col].astype(float)
        for date, group in execution_weights.groupby(schema.date_col)
    }
    current_weights = None
    values = []
    dates = []
    for date, row in load_returns(returns).loc[
        lambda frame: frame.index >= execution_weights[schema.date_col].min()
    ].iterrows():
        date = pd.Timestamp(date)
        if not apply_weights_at_close and date in target_by_date:
            current_weights = target_by_date[date].copy()
        if current_weights is None:
            portfolio_return = 0.0
        else:
            asset_returns = row.reindex(current_weights.index).fillna(0.0).astype(float)
            portfolio_return = float((current_weights * asset_returns).sum())
            current_weights = current_weights * (1.0 + asset_returns)
            total_weight = float(current_weights.sum())
            if total_weight != 0:
                current_weights = current_weights / total_weight
        dates.append(date)
        values.append(portfolio_return)
        if apply_weights_at_close and date in target_by_date:
            current_weights = target_by_date[date].copy()
    return pd.Series(values, index=pd.DatetimeIndex(dates), name="daily_return")


@pytest.mark.parametrize("apply_weights_at_close", [True, False])
def test_vectorized_loop_is_exactly_equal_to_frozen_iterrows_reference(
    apply_weights_at_close,
):
    rng = np.random.default_rng(73)
    dates = pd.bdate_range("2021-01-04", periods=80)
    returns = pd.DataFrame(
        rng.normal(0.0002, 0.015, size=(len(dates), 8)),
        index=dates,
        columns=[f"S{i}" for i in range(8)],
    )
    returns.iloc[7, 2] = np.nan
    weights = pd.DataFrame(
        [
            {
                "Date": rebalance_date,
                "Company SEDOL": security,
                "Portfolio weight": float(weight),
            }
            for rebalance_date in dates[[0, 19, 41, 63]]
            for security, weight in zip(
                returns.columns,
                rng.uniform(0.01, 1.0, size=len(returns.columns)),
            )
        ]
    )
    expected = _legacy_iterrows_daily_returns(
        weights,
        returns,
        apply_weights_at_close=apply_weights_at_close,
    )
    result = calculate_security_nav(
        weights,
        returns,
        apply_weights_at_close=apply_weights_at_close,
    )

    pd.testing.assert_series_equal(result.daily_returns, expected, check_exact=True)
    expected_nav = (1.0 + expected).cumprod() * 100.0
    expected_nav.name = "nav"
    pd.testing.assert_series_equal(result.nav, expected_nav, check_exact=True)


def test_results_record_engine_identity_and_execution_policy():
    result = calculate_security_nav(_sample_weights(), _sample_returns())

    assert result.manifest["engine_id"] == NAV_ENGINE_ID
    assert result.manifest["engine_version"] == NAV_ENGINE_VERSION
    assert result.manifest["execution_policy"] == {
        "strictly_after_rebalance": True,
        "apply_weights_at_close": True,
        "rebalance_mapping": "first_returns_date_strictly_after_rebalance",
        "weight_application": "after_close_return",
    }


def test_aggregated_return_series_helper_preserves_exact_cumprod_semantics():
    returns = pd.Series(
        [0.10, -0.05, np.nan, 0.02],
        index=pd.to_datetime(
            ["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30"]
        ),
        name="sector_strategy",
    )
    result = calculate_return_series_nav(
        returns,
        initial_nav=1.0,
        periods_per_year=12,
        name="sector_strategy",
    )
    expected_returns = returns.fillna(0.0)
    expected_nav = (1.0 + expected_returns).cumprod()
    expected_nav.name = "sector_strategy_nav"

    pd.testing.assert_series_equal(result.returns, expected_returns, check_exact=True)
    pd.testing.assert_series_equal(result.nav, expected_nav, check_exact=True)
    assert result.manifest["engine_id"] == NAV_ENGINE_ID
    assert result.manifest["periods_per_year"] == 12


def test_official_artifact_manifest_always_records_engine_provenance(tmp_path):
    save_manifest(tmp_path, {"status": "success", "research": "unit-test"})
    manifest = read_manifest(tmp_path)

    assert manifest["engine_id"] == NAV_ENGINE_ID
    assert manifest["engine_version"] == NAV_ENGINE_VERSION
    assert manifest["execution_policy"]["rebalance_mapping"] == (
        "first_returns_date_strictly_after_rebalance"
    )
    assert manifest["execution_policy"]["weight_application"] == (
        "after_close_return"
    )

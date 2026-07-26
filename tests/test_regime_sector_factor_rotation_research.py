from __future__ import annotations

import pandas as pd
from pandas.testing import assert_frame_equal

from tp_research.workflows.run_regime_sector_factor_rotation_research import (
    _exact_lag_delta,
    _factor_regime_diagnostics,
    _safe_auc,
    build_market_signals,
)


def _screen_frame() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2020-01-31", periods=8, freq="ME")
    for entity_index in range(40):
        for date_index, date in enumerate(dates):
            rows.append(
                {
                    "Date": date,
                    "ISIN": f"ISIN{entity_index:03d}",
                    "Total Return": (entity_index - 20) / 1000,
                    " Benchmark ICB Supersector ": 1 + entity_index % 4,
                    "Weight in SP500": 1.0,
                    "Oper Margin": entity_index + date_index,
                    "ROE avg FY0": entity_index + 2 * date_index,
                    "NetDebt to EBITDA exFIN": entity_index - date_index,
                    "Earns Yield FY1": entity_index + date_index / 2,
                    "EPS Revision Ratio": entity_index - 10,
                    "EPS NTM 3M Growth": entity_index - 15,
                }
            )
    return pd.DataFrame(rows)


def test_exact_lag_delta_rejects_non_exact_month_gap() -> None:
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(
                ["2020-01-31", "2020-02-29", "2020-04-30"]
            ),
            "ISIN": ["A", "A", "A"],
        }
    )
    values = pd.Series([1.0, 2.0, 4.0])

    result = _exact_lag_delta(frame, values, lag=1)

    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == 1.0
    assert pd.isna(result.iloc[2])


def test_market_features_do_not_change_before_future_observation() -> None:
    original = _screen_frame()
    changed = original.copy()
    final_date = changed["Date"].max()
    changed.loc[changed["Date"].eq(final_date), "Oper Margin"] += 1000

    original_market, original_sectors = build_market_signals(
        original,
        weight_column="Weight in SP500",
        lag=3,
        sample_start=pd.Timestamp("2020-04-30"),
    )
    changed_market, changed_sectors = build_market_signals(
        changed,
        weight_column="Weight in SP500",
        lag=3,
        sample_start=pd.Timestamp("2020-04-30"),
    )

    prior_market = original_market.index < final_date
    assert_frame_equal(
        original_market.loc[prior_market],
        changed_market.loc[prior_market],
    )
    prior_sector = original_sectors["Date"] < final_date
    assert_frame_equal(
        original_sectors.loc[prior_sector].reset_index(drop=True),
        changed_sectors.loc[prior_sector].reset_index(drop=True),
    )


def test_safe_auc_accepts_nullable_boolean_target() -> None:
    target = pd.Series(
        [True, False] * 6 + [pd.NA],
        dtype="boolean",
    )
    score = pd.Series(range(len(target)), dtype=float)

    result = _safe_auc(target, score)

    assert 0 <= result <= 1


def test_factor_regime_diagnostics_join_on_date_contract() -> None:
    dates = pd.date_range("2022-01-31", periods=2, freq="ME")
    states = pd.DataFrame(
        {
            "Date": dates,
            "region": ["US", "US"],
            "enhanced_state": [0, 1],
        }
    )
    market = pd.DataFrame(
        {
            "Date": dates,
            "region": ["US", "US"],
            "core_factor_return_quality": [0.01, -0.01],
            "core_factor_return_deleveraging": [0.02, -0.02],
            "core_factor_return_earnings_yield": [0.03, -0.03],
            "core_factor_return_revision": [0.04, -0.04],
            "core_transition_breadth_ewma3": [0.6, 0.4],
            "core_revision_breadth_ewma3": [0.7, 0.3],
            "core_rotation_dispersion_ewma3": [0.1, 0.2],
            "confirmation_transition_breadth_ewma3": [0.55, 0.45],
        }
    )

    result = _factor_regime_diagnostics(market, states)

    assert len(result) == 2
    assert result.columns.is_unique
    assert "core_factor_return_quality_mean" in result

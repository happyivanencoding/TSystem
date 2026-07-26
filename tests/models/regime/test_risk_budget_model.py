from __future__ import annotations

import pandas as pd
import pytest

from tp_models.regime import risk_budget_model


def test_eu_persistence_budget_is_causal() -> None:
    dates = pd.date_range("2020-01-31", periods=7, freq="ME")
    features = pd.DataFrame({"rvol_ann": [2.0] * 7}, index=dates)
    forward_vol = pd.Series([1.0, 2.0, 3.0, 100.0, 100.0, 100.0], index=dates[:6])

    result = risk_budget_model.eu_persistence_risk_budget(features, forward_vol, min_history=3)

    assert result.loc[dates[3], "target_vol"] == pytest.approx(2.0)
    assert result.loc[dates[3], "risk_budget_multiplier"] == pytest.approx(1.0)


def test_eu_persistence_budget_respects_bounds() -> None:
    dates = pd.date_range("2020-01-31", periods=6, freq="ME")
    features = pd.DataFrame({"rvol_ann": [1.0, 1.0, 1.0, 0.1, 10.0, 1.0]}, index=dates)
    forward_vol = pd.Series([1.0] * 5, index=dates[:5])

    result = risk_budget_model.eu_persistence_risk_budget(features, forward_vol, min_history=3)

    assert result.loc[dates[3], "risk_budget_multiplier"] == pytest.approx(1.30)
    assert result.loc[dates[4], "risk_budget_multiplier"] == pytest.approx(0.70)

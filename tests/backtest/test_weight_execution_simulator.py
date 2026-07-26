from __future__ import annotations

import pandas as pd
import pytest

from tp_backtest.execution import (
    ExecutionAssumptions,
    WeightExecutionResult,
    run_weight_backtest,
    simulate_weight_execution,
)
from tp_core.security_nav_engine import SecurityNavResult, calculate_security_nav


def _returns() -> pd.DataFrame:
    return pd.DataFrame(
        {"A": [0.01, 0.02, -0.01, 0.03], "B": [0.0, 0.01, 0.02, -0.02]},
        index=pd.bdate_range("2024-01-02", periods=4),
    )


def _weights() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Date": "2024-01-01", "Company SEDOL": "A", "Portfolio weight": 0.6},
            {"Date": "2024-01-01", "Company SEDOL": "B", "Portfolio weight": 0.4},
            {"Date": "2024-01-03", "Company SEDOL": "A", "Portfolio weight": 0.2},
            {"Date": "2024-01-03", "Company SEDOL": "B", "Portfolio weight": 0.8},
        ]
    )


def test_zero_cost_unlimited_simulation_is_exactly_equal_to_fast_gross_nav() -> None:
    fast = calculate_security_nav(_weights(), _returns())
    simulated = simulate_weight_execution(
        _weights(),
        _returns(),
        assumptions=ExecutionAssumptions(mode="weight_simulated"),
    )

    pd.testing.assert_series_equal(
        simulated.gross_daily_returns,
        fast.daily_returns.rename("gross_daily_return"),
        check_exact=True,
    )
    pd.testing.assert_series_equal(
        simulated.gross_nav,
        fast.nav.rename("gross_nav"),
        check_exact=True,
    )
    pd.testing.assert_series_equal(
        simulated.net_nav,
        simulated.gross_nav.rename("net_nav"),
        check_exact=True,
    )


def test_turnover_cap_carries_residual_and_costs_reduce_nav() -> None:
    result = simulate_weight_execution(
        _weights(),
        _returns(),
        assumptions=ExecutionAssumptions(
            mode="weight_simulated",
            commission_bps=10,
            slippage_bps=5,
            max_one_way_turnover_per_day=0.1,
        ),
    )

    assert result.turnover.max() == pytest.approx(0.1)
    assert not result.residuals.empty
    assert result.net_nav.iloc[-1] < result.gross_nav.iloc[-1]
    assert result.manifest["commission_cost_total"] > 0


def test_fast_nav_remains_default_public_mode() -> None:
    fast = run_weight_backtest(_weights(), _returns())
    simulated = run_weight_backtest(
        _weights(),
        _returns(),
        assumptions=ExecutionAssumptions(mode="weight_simulated"),
    )

    assert isinstance(fast, SecurityNavResult)
    assert isinstance(simulated, WeightExecutionResult)

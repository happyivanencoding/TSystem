import numpy as np
import pandas as pd

from tp_core.backtesting import BacktestEngine
from tp_core.general_backtest import BacktestSchema, GeneralBacktestEngine, backtest_weight_table


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


def test_general_backtest_filters_normalizes_and_drifts_weights():
    result = backtest_weight_table(weights=_sample_weights(), returns=_sample_returns())

    assert result.manifest["dropped_not_in_returns_rows"] == 1
    assert result.manifest["rebalance_date_count"] == 1
    assert result.manifest["execution_date_count"] == 1
    assert result.nav.index[0] == pd.Timestamp("2024-01-02")
    assert np.isclose(result.daily_returns.loc["2024-01-02"], 0.0)
    assert np.isclose(result.daily_returns.loc["2024-01-03"], 1.0 / 3.0 * 0.20)
    assert np.isclose(result.nav.loc["2024-01-03"], 100.0 * (1.0 + 1.0 / 3.0 * 0.20))


def test_active_backtest_engine_exposes_general_run_weights():
    engine = BacktestEngine(_sample_returns())

    assert isinstance(engine, GeneralBacktestEngine)
    result = engine.run_weights(
        _sample_weights(),
        schema=BacktestSchema(date_col="Date", id_col="Company SEDOL", weight_col="Portfolio weight"),
    )

    assert engine.last_result is result
    assert result.execution_weights.index.names == ["Date", "Company SEDOL"]

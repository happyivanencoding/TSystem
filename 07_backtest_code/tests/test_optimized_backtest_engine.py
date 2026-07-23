import sys
from pathlib import Path

import pandas as pd

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.optimizer_backtest_adapter import OptimizerBacktestAdapter


def test_optimized_backtest_engine_runs_optimizer_result_wopt():
    returns = pd.DataFrame(
        {
            "A": [0.01, 0.02, 0.00],
            "B": [0.00, 0.01, -0.01],
        },
        index=pd.to_datetime(["2024-02-01", "2024-02-02", "2024-02-05"]),
    )
    optimizer_result = pd.DataFrame(
        {
            "Date": ["2024-01-31", "2024-01-31"],
            "Company SEDOL": ["A", "B"],
            "Wopt": [0.6, 0.4],
        }
    )
    engine = OptimizerBacktestAdapter(returns)

    result = engine.backtest_optimizer_result(optimizer_result)

    assert result.nav.index[0] == pd.Timestamp("2024-02-01")
    assert not result.nav.empty
    assert engine.perf_ptf is result.nav
    assert engine.last_optimized_weights["Portfolio weight"].sum() == 1.0

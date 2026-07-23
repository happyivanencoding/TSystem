import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

OPT_ROOT = Path(__file__).resolve().parent
if str(OPT_ROOT) not in sys.path:
    sys.path.insert(0, str(OPT_ROOT))

import optimizer


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": ["A", "B", "C", "D"],
            "benchmark": [0.25, 0.25, 0.25, 0.25],
            "score": [1.0, 0.7, 0.2, 0.0],
            "current": [0.20, 0.30, 0.30, 0.20],
            "lower": [0.0, 0.0, 0.0, 0.0],
            "upper": [0.60, 0.60, 0.60, 0.60],
            "sector": ["X", "X", "Y", "Y"],
            "beta": [1.2, 1.0, 0.8, 0.6],
        }
    )


def test_optimizer_exposes_one_public_entry_point():
    assert optimizer.OPTIMIZER_ID == "tp.optimizer"
    assert callable(optimizer.optimize_portfolio)
    assert "optimize" not in optimizer.__all__


def test_min_tracking_error_recovers_benchmark():
    result = optimizer.optimize_portfolio(
        _candidates(),
        id_col="id",
        benchmark_weights="benchmark",
        scores="score",
        covariance=np.eye(4),
        lower_bounds="lower",
        upper_bounds="upper",
        config=optimizer.OptimizerConfig(
            objective=optimizer.OptimizerObjective.MIN_TRACKING_ERROR,
        ),
    )

    assert result.status in optimizer.OPTIMAL_STATUSES
    np.testing.assert_allclose(result.weights.to_numpy(), 0.25, atol=1e-6)
    assert result.audit["tracking_error"] == pytest.approx(0.0, abs=1e-6)


def test_max_score_supports_te_turnover_group_and_linear_constraints():
    candidates = _candidates()
    result = optimizer.optimize_portfolio(
        candidates,
        id_col="id",
        benchmark_weights="benchmark",
        scores="score",
        covariance=np.eye(4) * 0.04,
        current_weights="current",
        lower_bounds="lower",
        upper_bounds="upper",
        group_constraints=[
            optimizer.GroupConstraint(
                name="sector",
                group_col="sector",
                lower_bounds={"X": 0.45, "Y": 0.35},
                upper_bounds={"X": 0.65, "Y": 0.55},
            )
        ],
        linear_constraints=[
            optimizer.LinearConstraint(
                name="beta",
                coefficients=candidates["beta"],
                lower=0.85,
                upper=1.05,
            )
        ],
        config=optimizer.OptimizerConfig(
            objective=optimizer.OptimizerObjective.MAX_SCORE,
            max_tracking_error=0.08,
            max_turnover=0.50,
            max_active_weight=0.25,
            min_holdings=2,
            max_holdings=4,
            min_weight_if_selected=0.01,
        ),
    )

    weights = result.weights.to_numpy()
    assert weights.sum() == pytest.approx(1.0)
    assert result.audit["tracking_error"] <= 0.08 + 1e-6
    assert result.audit["two_way_turnover"] <= 0.50 + 1e-6
    assert 0.45 - 1e-6 <= weights[:2].sum() <= 0.65 + 1e-6
    beta = float(candidates["beta"].to_numpy() @ weights)
    assert 0.85 - 1e-6 <= beta <= 1.05 + 1e-6


def test_blended_result_carries_optimizer_metadata():
    result = optimizer.optimize_portfolio(
        _candidates(),
        id_col="id",
        benchmark_weights="benchmark",
        scores="score",
        covariance=np.eye(4),
        current_weights="current",
        config=optimizer.OptimizerConfig(
            objective=optimizer.OptimizerObjective.BLENDED,
            score_weight=1.0,
            tracking_error_weight=3.0,
            turnover_weight=0.1,
            active_weight_penalty=2.0,
        ),
    )
    frame = result.to_frame(_candidates())

    assert frame["optimizer_id"].unique().tolist() == ["tp.optimizer"]
    assert frame["optimizer_version"].unique().tolist() == [
        optimizer.OPTIMIZER_VERSION
    ]
    assert frame["optimizer_objective"].unique().tolist() == ["blended"]
    assert result.metadata["constraint_policy"]["long_only"] is True


def test_external_current_weight_counts_for_turnover():
    candidates = _candidates().iloc[:2].copy()
    result = optimizer.optimize_portfolio(
        candidates,
        id_col="id",
        benchmark_weights=[0.5, 0.5],
        current_weights=[0.4, 0.4],
        external_current_weight=0.2,
        config=optimizer.OptimizerConfig(
            objective=optimizer.OptimizerObjective.MIN_TURNOVER,
            turnover_weight=1.0,
        ),
    )

    assert result.audit["two_way_turnover"] == pytest.approx(0.4)
    assert result.metadata["constraint_policy"]["external_current_weight"] == 0.2

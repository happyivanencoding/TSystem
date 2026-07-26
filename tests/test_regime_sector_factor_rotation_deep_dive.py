from __future__ import annotations

import numpy as np
import pandas as pd

from tp_models.sector.model import run_sector_tilt_backtest
from tp_research.workflows.run_regime_sector_factor_rotation_deep_dive import (
    _monthly_from_details,
    add_eu_diagnostic_candidates,
    build_tilt_weight_details,
)


def test_eu_conditional_candidate_uses_low_and_high_confirmation_weights() -> None:
    frame = pd.DataFrame(
        {
            "baseline_rank": [8.0, 8.0],
            "diffusion_score": [4.0, 4.0],
            "confirmation_transition_breadth": [0.49, 0.50],
            "quality_breadth": [1.0, 1.0],
            "deleveraging_breadth": [2.0, 2.0],
            "earnings_yield_breadth": [3.0, 3.0],
            "revision_breadth": [4.0, 4.0],
        }
    )

    result = add_eu_diagnostic_candidates(frame)

    assert np.isclose(result.loc[0, "conditional_15_35"], 7.4)
    assert np.isclose(result.loc[1, "conditional_15_35"], 6.6)


def test_tilt_weight_details_reproduce_canonical_active_return() -> None:
    rows = []
    for date_index, date in enumerate(
        pd.date_range("2022-01-31", periods=3, freq="ME")
    ):
        for sector_code in range(1, 11):
            rows.append(
                {
                    "Date": date,
                    "next_date": date + pd.offsets.MonthEnd(1),
                    "sector_code": sector_code,
                    "sector_name": f"S{sector_code}",
                    "score": sector_code + date_index / 10,
                    "sector_forward_return": (
                        sector_code - 5 + date_index
                    )
                    / 100,
                    "sector_weight": sector_code,
                }
            )
    panel = pd.DataFrame(rows)

    canonical = run_sector_tilt_backtest(panel, score_column="score")
    details = build_tilt_weight_details(panel, score_column="score")
    monthly = _monthly_from_details(details)
    joined = canonical[["Date", "active_return"]].merge(
        monthly[["Date", "active_return"]],
        on="Date",
        suffixes=("_canonical", "_detail"),
    )

    assert np.allclose(
        joined["active_return_canonical"],
        joined["active_return_detail"],
        atol=1e-12,
    )
    weight_sums = details.groupby("Date")["tilted_weight"].sum()
    assert np.allclose(weight_sums, 1.0)

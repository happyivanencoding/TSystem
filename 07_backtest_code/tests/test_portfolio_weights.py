import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


TP_CORE_ROOT = Path(__file__).resolve().parents[2] / "01_tp_core"
if str(TP_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(TP_CORE_ROOT))

from tp_core.portfolio_weights import (
    cap_and_redistribute_weights,
    cap_weights_preserving_group_totals,
    match_group_weight_targets,
    normalize_weight_table,
)


def test_hard_cap_survives_redistribution():
    result = cap_and_redistribute_weights(pd.Series([0.9, 0.1]), 0.6)

    np.testing.assert_allclose(result.to_numpy(), [0.6, 0.4])
    assert result.sum() == pytest.approx(1.0)
    assert result.max() <= 0.6


def test_infeasible_hard_cap_is_rejected():
    with pytest.raises(ValueError, match="infeasible"):
        cap_and_redistribute_weights(pd.Series([0.5, 0.5]), 0.4)


def test_normalize_weight_table_applies_cap_per_date():
    frame = pd.DataFrame(
        {
            "Date": ["2024-01-31"] * 2 + ["2024-02-29"] * 2,
            "Weight": [9.0, 1.0, 1.0, 3.0],
        }
    )

    result = normalize_weight_table(
        frame,
        weight_col="Weight",
        group_cols="Date",
        max_weight=0.6,
    )

    sums = result.groupby("Date")["Weight"].sum()
    assert sums.eq(1.0).all()
    assert result.groupby("Date")["Weight"].max().le(0.6).all()


def test_sector_neutral_cap_preserves_sector_targets():
    frame = pd.DataFrame(
        {
            "Date": ["2024-01-31"] * 5,
            "Sector": ["A", "A", "A", "B", "B"],
            "Weight": [0.9, 0.05, 0.05, 0.8, 0.2],
        }
    )
    targets = pd.Series({"A": 0.6, "B": 0.4})

    neutral = match_group_weight_targets(
        frame,
        targets,
        weight_col="Weight",
        group_cols="Sector",
    )
    capped = cap_weights_preserving_group_totals(
        neutral,
        weight_col="Weight",
        max_weight=0.3,
        group_cols=["Date", "Sector"],
    )

    actual = capped.groupby("Sector")["Weight"].sum()
    np.testing.assert_allclose(actual.reindex(targets.index), targets)
    assert capped["Weight"].max() <= 0.3
    assert capped["Weight"].sum() == pytest.approx(1.0)

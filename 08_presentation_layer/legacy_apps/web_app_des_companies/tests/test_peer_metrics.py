"""Unit tests for peer_metrics (pure functions, no Dash/file I/O)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.schemas_ciq import (
    CIQ_COL_DATE,
    CIQ_COL_ICB_SUPERSECTOR,
    CIQ_COL_ISIN,
    CIQ_COL_NAME,
)
from src.services.peer_metrics import (
    peer_set_for_spot,
    spot_compare_metric,
    trend_series_anchor_vs_industry,
)


@pytest.fixture
def spot_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            CIQ_COL_ISIN: ["A", "B", "C", "D"],
            CIQ_COL_NAME: ["AlphaCo", "BetaCo", "GammaCo", "DeltaCo"],
            CIQ_COL_ICB_SUPERSECTOR: ["Tech", "Tech", "Tech", "Banks"],
            "PE NTM": [10.0, 20.0, 30.0, 8.0],
            "Weight in X": [0.1, 0.2, 0.3, 0.4],
        }
    )


def test_peer_set_for_spot_same_industry(spot_df):
    out = peer_set_for_spot(spot_df, "A", CIQ_COL_ICB_SUPERSECTOR)
    assert set(out[CIQ_COL_ISIN]) == {"A", "B", "C"}


def test_peer_set_for_spot_missing_anchor(spot_df):
    out = peer_set_for_spot(spot_df, "ZZZ", CIQ_COL_ICB_SUPERSECTOR)
    assert out.empty


def test_spot_compare_metric_stats_and_rank(spot_df):
    peers = peer_set_for_spot(spot_df, "B", CIQ_COL_ICB_SUPERSECTOR)
    result = spot_compare_metric(peers, "B", "PE NTM")
    assert result.peer_count == 3
    assert result.anchor_value == pytest.approx(20.0)
    assert result.median == pytest.approx(20.0)
    assert result.rank == 2
    assert result.percentile == pytest.approx((2 - 0.5) / 3 * 100)
    assert list(result.peer_df[CIQ_COL_ISIN]) == ["A", "B", "C"]


def test_spot_compare_metric_nan_metric(spot_df):
    df = spot_df.copy()
    df.loc[df[CIQ_COL_ISIN] == "A", "PE NTM"] = np.nan
    peers = peer_set_for_spot(df, "A", CIQ_COL_ICB_SUPERSECTOR)
    result = spot_compare_metric(peers, "A", "PE NTM")
    assert result.peer_count == 2
    assert result.anchor_value is None
    assert result.rank is None


def test_spot_compare_metric_empty_peer():
    empty = pd.DataFrame(
        {CIQ_COL_ISIN: [], CIQ_COL_NAME: [], "x": []}
    )
    r = spot_compare_metric(empty, "A", "x")
    assert r.peer_count == 0
    assert r.anchor_value is None


@pytest.fixture
def hist_df() -> pd.DataFrame:
    dates = pd.to_datetime(["2023-01-31", "2023-02-28", "2023-03-31"])
    rows = []
    for d in dates:
        rows.extend(
            [
                {CIQ_COL_DATE: d, CIQ_COL_ISIN: "A", CIQ_COL_ICB_SUPERSECTOR: "Tech", "PE NTM": 10.0 + dates.get_loc(d)},
                {CIQ_COL_DATE: d, CIQ_COL_ISIN: "B", CIQ_COL_ICB_SUPERSECTOR: "Tech", "PE NTM": 20.0 + dates.get_loc(d)},
                {CIQ_COL_DATE: d, CIQ_COL_ISIN: "C", CIQ_COL_ICB_SUPERSECTOR: "Tech", "PE NTM": 30.0 + dates.get_loc(d)},
                {CIQ_COL_DATE: d, CIQ_COL_ISIN: "D", CIQ_COL_ICB_SUPERSECTOR: "Banks", "PE NTM": 8.0},
            ]
        )
    return pd.DataFrame(rows)


def test_trend_series_anchor_vs_industry_median(hist_df):
    out = trend_series_anchor_vs_industry(
        hist_df, anchor_isin="B", metric_col="PE NTM",
        industry_col=CIQ_COL_ICB_SUPERSECTOR, baseline="median",
    )
    assert list(out.columns) == ["anchor", "industry"]
    assert len(out) == 3
    assert out.loc[pd.Timestamp("2023-01-31"), "anchor"] == pytest.approx(20.0)
    assert out.loc[pd.Timestamp("2023-01-31"), "industry"] == pytest.approx(20.0)


def test_trend_series_mean_excludes_other_industries(hist_df):
    out = trend_series_anchor_vs_industry(
        hist_df, anchor_isin="B", metric_col="PE NTM",
        industry_col=CIQ_COL_ICB_SUPERSECTOR, baseline="mean",
    )
    assert out.loc[pd.Timestamp("2023-03-31"), "industry"] == pytest.approx(
        (12.0 + 22.0 + 32.0) / 3
    )


def test_trend_series_missing_anchor(hist_df):
    out = trend_series_anchor_vs_industry(
        hist_df, anchor_isin="ZZZ", metric_col="PE NTM",
        industry_col=CIQ_COL_ICB_SUPERSECTOR,
    )
    assert out.empty

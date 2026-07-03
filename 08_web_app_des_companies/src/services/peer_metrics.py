"""Pure peer-comparison helpers (no Dash, no file I/O).

All functions operate on plain DataFrames so they can be unit-tested with
tiny in-memory fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from src.data.schemas_ciq import (
    CIQ_COL_DATE,
    CIQ_COL_ISIN,
    CIQ_COL_NAME,
)


@dataclass(frozen=True)
class SpotCompareResult:
    """Spot comparison summary for an anchor vs peers on one metric."""

    anchor_value: Optional[float]
    peer_count: int
    median: Optional[float]
    mean: Optional[float]
    p25: Optional[float]
    p75: Optional[float]
    min_value: Optional[float]
    max_value: Optional[float]
    rank: Optional[int]  # 1-based, ascending
    percentile: Optional[float]  # 0..100 (ascending)
    peer_df: pd.DataFrame


def peer_set_for_spot(
    constituents: pd.DataFrame,
    anchor_isin: str,
    industry_col: str,
) -> pd.DataFrame:
    """Return the subset of constituents sharing the anchor's industry.

    Includes the anchor itself. Empty DataFrame if the anchor or its industry
    is missing.
    """
    if constituents.empty or industry_col not in constituents.columns:
        return constituents.iloc[0:0].copy()
    row = constituents.loc[constituents[CIQ_COL_ISIN] == anchor_isin]
    if row.empty:
        return constituents.iloc[0:0].copy()
    industry = row.iloc[0][industry_col]
    if pd.isna(industry):
        return constituents.iloc[0:0].copy()
    return constituents.loc[constituents[industry_col] == industry].copy()


def spot_compare_metric(
    peers_df: pd.DataFrame,
    anchor_isin: str,
    metric_col: str,
) -> SpotCompareResult:
    """Compute anchor value, peer distribution stats, rank and percentile."""
    empty = SpotCompareResult(
        anchor_value=None,
        peer_count=0,
        median=None,
        mean=None,
        p25=None,
        p75=None,
        min_value=None,
        max_value=None,
        rank=None,
        percentile=None,
        peer_df=peers_df.iloc[0:0].copy()
        if peers_df is not None
        else pd.DataFrame(),
    )
    if peers_df is None or peers_df.empty:
        return empty
    if metric_col not in peers_df.columns:
        return empty
    sub = peers_df[[CIQ_COL_ISIN, CIQ_COL_NAME, metric_col]].copy()
    sub = sub.dropna(subset=[metric_col])
    if sub.empty:
        return empty
    sub = sub.sort_values(metric_col, ascending=True).reset_index(drop=True)
    values = sub[metric_col].astype(float)

    anchor_row = sub.loc[sub[CIQ_COL_ISIN] == anchor_isin]
    anchor_value: Optional[float] = None
    rank_: Optional[int] = None
    percentile: Optional[float] = None
    if not anchor_row.empty:
        anchor_value = float(anchor_row.iloc[0][metric_col])
        rank_ = int(anchor_row.index[0]) + 1
        n = len(sub)
        percentile = (rank_ - 0.5) / n * 100.0 if n > 0 else None

    return SpotCompareResult(
        anchor_value=anchor_value,
        peer_count=int(len(sub)),
        median=float(values.median()),
        mean=float(values.mean()),
        p25=float(values.quantile(0.25)),
        p75=float(values.quantile(0.75)),
        min_value=float(values.min()),
        max_value=float(values.max()),
        rank=rank_,
        percentile=percentile,
        peer_df=sub,
    )


def trend_series_anchor_vs_industry(
    index_history: pd.DataFrame,
    anchor_isin: str,
    metric_col: str,
    industry_col: str,
    baseline: str = "median",
) -> pd.DataFrame:
    """Build a Date-indexed frame with columns ``anchor`` and ``industry``.

    ``baseline`` is ``"median"`` (default) or ``"mean"``; computed **each period**
    on the subset of ``index_history`` that shares the anchor's industry (as of
    the same period, to honor sector migrations over time).
    """
    if index_history is None or index_history.empty:
        return pd.DataFrame(columns=["anchor", "industry"])
    needed = {CIQ_COL_DATE, CIQ_COL_ISIN, industry_col, metric_col}
    if not needed.issubset(index_history.columns):
        return pd.DataFrame(columns=["anchor", "industry"])

    anchor_rows = index_history.loc[
        index_history[CIQ_COL_ISIN] == anchor_isin,
        [CIQ_COL_DATE, metric_col, industry_col],
    ].copy()
    if anchor_rows.empty:
        return pd.DataFrame(columns=["anchor", "industry"])

    anchor_ts = (
        anchor_rows.dropna(subset=[metric_col])
        .drop_duplicates(subset=[CIQ_COL_DATE])
        .set_index(CIQ_COL_DATE)[metric_col]
        .astype(float)
        .sort_index()
    )
    anchor_ts.name = "anchor"

    industry_per_date = anchor_rows.set_index(CIQ_COL_DATE)[industry_col]
    df = index_history[[CIQ_COL_DATE, industry_col, metric_col]].copy()
    df = df.dropna(subset=[metric_col])
    df["_ind_anchor"] = df[CIQ_COL_DATE].map(industry_per_date)
    df = df.dropna(subset=["_ind_anchor"])
    df = df.loc[df[industry_col] == df["_ind_anchor"]]
    if df.empty:
        return pd.DataFrame({"anchor": anchor_ts, "industry": np.nan})

    agg = "median" if baseline == "median" else "mean"
    industry_ts = (
        df.groupby(CIQ_COL_DATE)[metric_col].agg(agg).astype(float).sort_index()
    )
    industry_ts.name = "industry"

    out = pd.concat([anchor_ts, industry_ts], axis=1).sort_index()
    return out

"""Semantic access layer over the ``screen_aggregateCIQ`` panel.

Separate from ``CompanyRepository`` because this dataset has a very different
shape (Date x ISIN panel with many numeric metrics + per-index weight columns).
Upper layers (services, callbacks, UI) should only talk to this repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import pandas as pd

from src.data import loaders
from src.data.schemas_ciq import (
    CIQ_COL_DATE,
    CIQ_COL_ICB_SUPERSECTOR,
    CIQ_COL_ISIN,
    CIQ_COL_NAME,
    CIQ_COL_REGION,
    CIQ_NON_METRIC_COLS,
    WEIGHT_IN_PREFIX,
)


@dataclass(frozen=True)
class IndexChoice:
    """One selectable index, derived from a ``Weight in <label>`` column."""

    column: str  # full column name, e.g. "Weight in MSCI WORLD"
    label: str   # human label, e.g. "MSCI WORLD"


class IndexScreenRepository:
    """High-level API backed by the screen_aggregateCIQ panel."""

    def __init__(self) -> None:
        self._df: pd.DataFrame = loaders.load_screen_aggregate_ciq()
        # Cache CPU : historique bench par colonne de poids (données immuables en mémoire)
        @lru_cache(maxsize=64)
        def _memo_history(wcol: str) -> pd.DataFrame:
            if wcol not in self._df.columns:
                return self._df.iloc[0:0].copy()
            mask = self._df[wcol].fillna(0) > 0
            return self._df.loc[mask].copy()

        self._history_for_index_memo = _memo_history

    @property
    def df(self) -> pd.DataFrame:
        return self._df

    # --- Reference lists -------------------------------------------------

    def list_indices(self) -> list[IndexChoice]:
        """Columns matching ``Weight in …`` are candidate indices."""
        items: list[IndexChoice] = []
        for col in self._df.columns:
            if isinstance(col, str) and col.startswith(WEIGHT_IN_PREFIX):
                label = col[len(WEIGHT_IN_PREFIX):].strip() or col
                items.append(IndexChoice(column=col, label=label))
        items.sort(key=lambda x: x.label.lower())
        return items

    def available_dates_for_index(self, weight_col: str) -> list[pd.Timestamp]:
        """Sorted list of dates where at least one constituent has weight > 0."""
        if weight_col not in self._df.columns:
            return []
        mask = self._df[weight_col].fillna(0) > 0
        dates = pd.to_datetime(self._df.loc[mask, CIQ_COL_DATE].unique())
        return sorted(pd.DatetimeIndex(dates).tolist())

    def numeric_metric_columns(self) -> list[str]:
        """All numeric columns that are not IDs, weights, or region/industry labels."""
        cols: list[str] = []
        for c in self._df.columns:
            if c in CIQ_NON_METRIC_COLS:
                continue
            if isinstance(c, str) and c.startswith(WEIGHT_IN_PREFIX):
                continue
            if pd.api.types.is_numeric_dtype(self._df[c]):
                cols.append(c)
        cols.sort(key=str.lower)
        return cols

    # --- Cross-sectional / historical slices -----------------------------

    def constituents_asof(
        self, asof: pd.Timestamp, weight_col: str
    ) -> pd.DataFrame:
        """Return all rows on ``asof`` with ``weight_col > 0``."""
        if weight_col not in self._df.columns:
            return self._df.iloc[0:0].copy()
        mask_date = self._df[CIQ_COL_DATE] == pd.Timestamp(asof)
        mask_w = self._df[weight_col].fillna(0) > 0
        return self._df.loc[mask_date & mask_w].copy()

    def history_for_index(self, weight_col: str) -> pd.DataFrame:
        """All rows where the given index weight > 0 (all dates)."""
        return self._history_for_index_memo(weight_col)

    def get_identity(self, isin: str) -> Optional[pd.Series]:
        """Latest row for a given ISIN (for labels)."""
        rows = self._df[self._df[CIQ_COL_ISIN] == isin]
        if rows.empty:
            return None
        return rows.sort_values(CIQ_COL_DATE, ascending=False).iloc[0]


_repo: Optional[IndexScreenRepository] = None


def get_index_screen_repository() -> IndexScreenRepository:
    global _repo
    if _repo is None:
        _repo = IndexScreenRepository()
    return _repo


# Re-exported for callers that only need column constants
__all__ = [
    "IndexChoice",
    "IndexScreenRepository",
    "get_index_screen_repository",
    "CIQ_COL_ICB_SUPERSECTOR",
    "CIQ_COL_NAME",
    "CIQ_COL_REGION",
]

"""Integration smoke test for IndexScreenRepository (skipped if no parquet)."""
from __future__ import annotations

import pandas as pd
import pytest

from config import settings
from src.data.index_screen_repository import IndexScreenRepository
from src.data.schemas_ciq import CIQ_COL_ISIN


pytestmark = pytest.mark.skipif(
    not settings.SCREEN_AGG_CIQ_PARQUET.exists(),
    reason="canonical screen_aggregate.parquet not present locally",
)


@pytest.fixture(scope="module")
def repo() -> IndexScreenRepository:
    return IndexScreenRepository()


def test_indices_contains_weight_in(repo):
    items = repo.list_indices()
    assert items
    assert any(ic.column.startswith("Weight in ") for ic in items)


def test_metrics_non_empty(repo):
    metrics = repo.numeric_metric_columns()
    assert len(metrics) > 20


def test_constituents_asof_positive(repo):
    items = repo.list_indices()
    assert items
    col = items[0].column
    dates = repo.available_dates_for_index(col)
    assert dates
    sub = repo.constituents_asof(dates[-1], col)
    assert not sub.empty
    assert (sub[col] > 0).all()
    assert CIQ_COL_ISIN in sub.columns


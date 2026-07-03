"""Integration-style tests for CompanyRepository against real parquet files."""
from __future__ import annotations

import pandas as pd
import pytest

from src.data.repository import get_repository
from src.data.schemas import COL_ISIN, COL_NAME


@pytest.fixture(scope="module")
def repo():
    return get_repository()


def test_companies_df_unique_isin(repo):
    df = repo.companies_df()
    assert not df.empty
    assert df[COL_ISIN].is_unique


def test_reference_lists_non_empty(repo):
    assert len(repo.list_countries()) > 0
    assert len(repo.list_sectors()) > 0


def test_get_identity_roundtrip(repo):
    catalog = repo.companies_df()
    sample_isin = catalog.iloc[0][COL_ISIN]
    identity = repo.get_identity(sample_isin)
    assert identity is not None
    assert identity.isin == sample_isin


def test_get_identity_unknown_returns_none(repo):
    assert repo.get_identity("INVALID_ISIN_XXX") is None


def test_get_news_for_known_isin_returns_dataframe(repo):
    catalog = repo.companies_df()
    # Pick an ISIN that likely has news (scan until one is found)
    for isin in catalog[COL_ISIN].tolist():
        news = repo.get_news(isin)
        if not news.empty:
            assert isinstance(news, pd.DataFrame)
            return
    pytest.skip("No company with news found in sample data.")

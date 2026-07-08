"""Unit tests for the filter service (pure functions, no Dash needed)."""
from __future__ import annotations

import pandas as pd
import pytest

from src.data.schemas import COL_COUNTRY, COL_ISIN, COL_NAME, COL_SECTOR
from src.services.filters import apply_filters, paginate, total_pages


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            COL_ISIN: ["US0001", "FR0002", "DE0003", "US0004"],
            COL_NAME: ["Alpha Corp", "Beta SA", "Gamma AG", "Delta Inc"],
            COL_COUNTRY: ["UNITED STATES", "FRANCE", "GERMANY", "UNITED STATES"],
            COL_SECTOR: ["Tech", "Banks", "Auto", "Tech"],
        }
    )


def test_apply_filters_no_filter_returns_all(sample_df):
    assert len(apply_filters(sample_df)) == 4


def test_apply_filters_by_country(sample_df):
    out = apply_filters(sample_df, countries=["UNITED STATES"])
    assert len(out) == 2
    assert set(out[COL_ISIN]) == {"US0001", "US0004"}


def test_apply_filters_by_sector(sample_df):
    out = apply_filters(sample_df, sectors=["Tech"])
    assert len(out) == 2


def test_apply_filters_query_matches_name_case_insensitive(sample_df):
    out = apply_filters(sample_df, query="beta")
    assert len(out) == 1
    assert out.iloc[0][COL_ISIN] == "FR0002"


def test_apply_filters_query_matches_isin(sample_df):
    out = apply_filters(sample_df, query="DE0003")
    assert len(out) == 1


def test_apply_filters_combined(sample_df):
    out = apply_filters(
        sample_df,
        countries=["UNITED STATES"],
        sectors=["Tech"],
        query="alpha",
    )
    assert len(out) == 1
    assert out.iloc[0][COL_NAME] == "Alpha Corp"


def test_paginate_basic(sample_df):
    page1 = paginate(sample_df, page=1, page_size=2)
    page2 = paginate(sample_df, page=2, page_size=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1.iloc[0][COL_ISIN] == "US0001"
    assert page2.iloc[0][COL_ISIN] == "DE0003"


def test_total_pages():
    assert total_pages(0, 10) == 1
    assert total_pages(10, 10) == 1
    assert total_pages(11, 10) == 2
    assert total_pages(25, 10) == 3

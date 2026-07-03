"""Fumée PtfRepository (skip si ptf manquant)."""
from __future__ import annotations

import pytest

from config import settings
from src.data.ptf_repository import PtfRepository
from src.data.schemas_ptf import PTF_COL_ISIN, PTF_COL_PTF

pytestmark = pytest.mark.skipif(
    not settings.PTF_XLSX.exists(),
    reason="PTF_IA_WORLD.xlsx absent",
)


@pytest.fixture(scope="module")
def repo() -> PtfRepository:
    return PtfRepository()


def test_list_ptf(repo):
    assert repo.list_ptf_names()


def test_holdings_asof_one_snapshot_per_ptf(repo):
    names = repo.list_ptf_names()
    if not names:
        return
    import pandas as pd

    d = _pick_common_date(repo, names[0])
    h = repo.holdings_asof(names[0], pd.Timestamp(d))
    if h.empty:
        return
    u = h[PTF_COL_ISIN].nunique()
    assert len(h) == u
    dts = (
        repo.df[repo.df[PTF_COL_PTF] == names[0]]["Date"].dropna()
        if "Date" in repo.df.columns
        else None
    )
    assert dts is None or dts.nunique() >= 1


def _pick_common_date(repo, ptf) -> str:
    import pandas as pd

    sub = repo.df[repo.df[PTF_COL_PTF] == ptf]
    if "Date" not in sub.columns or sub.empty:
        return "2020-01-01"
    return str(sub["Date"].max().date())

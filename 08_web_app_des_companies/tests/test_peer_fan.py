import pandas as pd

from src.data.schemas_ciq import (
    CIQ_COL_DATE,
    CIQ_COL_ICB_SUPERSECTOR,
    CIQ_COL_ISIN,
    CIQ_COL_REGION,
)
from src.services.peer_fan import peer_fan_timeseries


def _mk_hist() -> pd.DataFrame:
    rows = []
    d1 = pd.Timestamp("2023-01-31")
    d2 = pd.Timestamp("2023-02-28")
    # bench A et pairs Tech / West Europe
    for d in (d1, d2):
        rows.append(
            {
                CIQ_COL_DATE: d,
                CIQ_COL_ISIN: "A",
                "M": 1.0,
                CIQ_COL_ICB_SUPERSECTOR: "Tech",
                CIQ_COL_REGION: "West Europe",
            }
        )
        rows.append(
            {
                CIQ_COL_DATE: d,
                CIQ_COL_ISIN: "B",
                "M": 2.0,
                CIQ_COL_ICB_SUPERSECTOR: "Tech",
                CIQ_COL_REGION: "West Europe",
            }
        )
        rows.append(
            {
                CIQ_COL_DATE: d,
                CIQ_COL_ISIN: "C",
                "M": 3.0,
                CIQ_COL_ICB_SUPERSECTOR: "Banks",
                CIQ_COL_REGION: "West Europe",
            }
        )
    return pd.DataFrame(rows)


def test_peer_fan_anchor_and_peer():
    H = _mk_hist()
    anc, peers, err = peer_fan_timeseries(H, "A", "M", seed=1)
    assert err is None
    assert anc is not None
    assert len(anc) == 2
    assert "B" in peers
    assert err is None


def test_peer_fan_empty_bench():
    H = pd.DataFrame(
        {
            CIQ_COL_DATE: [],
            CIQ_COL_ISIN: [],
            "M": [],
            CIQ_COL_ICB_SUPERSECTOR: [],
            CIQ_COL_REGION: [],
        }
    )
    a, p, e = peer_fan_timeseries(H, "A", "M")
    assert a is None and p == {}
    assert e is not None


def test_peer_fan_fallback_factset_when_icb_null():
    """Comme le CIQ réel : ICB souvent NaN, repli sur FactSet Ind."""
    d1 = pd.Timestamp("2023-01-31")
    rows = [
        {
            CIQ_COL_DATE: d1,
            CIQ_COL_ISIN: "A",
            "M": 1.0,
            CIQ_COL_ICB_SUPERSECTOR: None,
            "FactSet Ind": "Widgets",
            CIQ_COL_REGION: "North America",
        },
        {
            CIQ_COL_DATE: d1,
            CIQ_COL_ISIN: "B",
            "M": 2.0,
            CIQ_COL_ICB_SUPERSECTOR: None,
            "FactSet Ind": "Widgets",
            CIQ_COL_REGION: "North America",
        },
    ]
    H = pd.DataFrame(rows)
    _a, peers, err = peer_fan_timeseries(H, "A", "M")
    assert err is None
    assert "B" in peers

import sys
from pathlib import Path

import pandas as pd

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.esg_pivot import resolve_esg_pivot_score
from core.portfolio_builder import PortfolioBuilder
from utils.constants import (
    COL_DATE,
    COL_ISIN,
    COL_SEDOL,
    COL_MKT_CAP,
    COL_ESG_SCORE,
    COL_SECTOR_ICB11,
    COL_SECTOR_ICB19,
    ISIN_PAIRS,
)
from utils.data_utils import merge_ticker_secondaire
from utils.plotting import PlotlyVisualizer


def test_merge_ticker_secondaire_uses_current_benchmark_weight():
    keep_isin, drop_isin = ISIN_PAIRS[:2]
    screen = pd.DataFrame(
        {
            COL_ISIN: [keep_isin, drop_isin],
            "Weight in STOXX EUROPE 600": [0.25, 0.10],
            "Weight in MSCI WORLD": [9.0, 7.0],
        }
    ).set_index(COL_ISIN)

    merged = merge_ticker_secondaire(screen, "STOXX EUROPE 600")

    assert keep_isin in merged.index
    assert drop_isin not in merged.index
    assert merged.loc[keep_isin, "Weight in STOXX EUROPE 600"] == 0.35
    assert merged.loc[keep_isin, "Weight in MSCI WORLD"] == 9.0


def test_update_ptf_with_monthly_drift_is_idempotent_for_existing_months():
    screen = pd.DataFrame(
        {
            COL_ISIN: ["AAA"],
            COL_SEDOL: ["SED1"],
            COL_DATE: [pd.Timestamp("2024-01-31")],
            "Weight in TEST": [1.0],
            COL_MKT_CAP: [100.0],
            COL_SECTOR_ICB11: [1],
            COL_SECTOR_ICB19: [1],
            "score": [1.0],
        }
    ).set_index(COL_ISIN)
    builder = PortfolioBuilder(
        screen=screen,
        bench="TEST",
        percentile=0.2,
        metrics="score",
    )
    builder.returns = pd.DataFrame(
        {"SED1": [0.0, 0.10]},
        index=[pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-29")],
    )
    sec_list = pd.DataFrame(
        {
            "PTF": ["PTF TEST"],
            COL_ISIN: ["AAA"],
            "Weight": [1.0],
            COL_DATE: [pd.Timestamp("2024-01-31")],
            "Secto": [1],
            "Score": [1.0],
        }
    )

    filled = builder.update_ptf_with_monthly_drift(sec_list, today=pd.Timestamp("2024-02-29"))
    filled_again = builder.update_ptf_with_monthly_drift(filled, today=pd.Timestamp("2024-02-29"))

    assert sorted(pd.to_datetime(filled[COL_DATE]).dt.strftime("%Y-%m-%d").unique().tolist()) == [
        "2024-01-31",
        "2024-02-29",
    ]
    assert len(filled_again) == len(filled)
    assert filled_again.groupby(COL_DATE)["Weight"].sum().round(10).eq(1.0).all()


def test_plot_top_bottom_vs_benchmark_returns_ratio_figure():
    index = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"])
    top = pd.Series([100, 104, 108], index=index)
    bottom = pd.Series([100, 98, 95], index=index)
    bench = pd.Series([100, 102, 103], index=index)

    fig = PlotlyVisualizer.plot_top_bottom_vs_benchmark(
        top,
        bottom,
        bench,
        save_path=None,
        show_plot=False,
    )

    assert len(fig.data) == 6
    assert [trace.name for trace in fig.data] == [
        "Top",
        "Bottom",
        "Benchmark",
        "Top / Benchmark",
        "Bottom / Benchmark",
        "Top / Bottom",
    ]


def test_resolve_esg_pivot_score_uses_latest_dated_folder_and_file(tmp_path):
    old_dir = tmp_path / "20240131_old"
    new_dir = tmp_path / "20240531_new"
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / "20240131_pivot.csv").write_text(
        "sec_id|note_pivot\nINDEX TEST|10.0\n",
        encoding="cp1252",
    )
    (new_dir / "20240531_pivot.csv").write_text(
        "sec_id|note_pivot\nINDEX TEST|42.5\n",
        encoding="cp1252",
    )

    score = resolve_esg_pivot_score(tmp_path, "INDEX TEST")

    assert score == 42.5


def test_portfolio_builder_applies_numeric_esg_pivot_threshold():
    screen = pd.DataFrame(
        {
            COL_ISIN: ["AAA", "BBB"],
            COL_SEDOL: ["SED1", "SED2"],
            COL_DATE: [pd.Timestamp("2024-01-31"), pd.Timestamp("2024-01-31")],
            "Weight in TEST": [0.5, 0.5],
            COL_MKT_CAP: [100.0, 200.0],
            COL_SECTOR_ICB11: [1, 1],
            COL_SECTOR_ICB19: [1, 1],
            COL_ESG_SCORE: [45.0, 60.0],
            "score": [1.0, 2.0],
        }
    ).set_index(COL_ISIN)
    builder = PortfolioBuilder(
        screen=screen,
        bench="TEST",
        percentile=0.5,
        metrics="score",
        score_pivot_esg=50.0,
        esg_exclusion=0.0,
    )

    filtered, excluded = builder.filtrage_esg_liste_noire(screen.copy(), pd.Timestamp("2024-01-31"))

    assert filtered.index.tolist() == ["BBB"]
    assert excluded.index.tolist() == ["AAA"]
    assert excluded.loc["AAA", "Raison Exclusion"] == "ESG Reason"


def test_portfolio_builder_resolves_text_esg_pivot_threshold(tmp_path):
    pivot_dir = tmp_path / "20240531_new"
    pivot_dir.mkdir()
    (pivot_dir / "20240531_pivot.csv").write_text(
        "sec_id|note_pivot\nINDEX TEST|55.0\n",
        encoding="cp1252",
    )
    screen = pd.DataFrame(
        {
            COL_ISIN: ["AAA"],
            COL_SEDOL: ["SED1"],
            COL_DATE: [pd.Timestamp("2024-01-31")],
            "Weight in TEST": [1.0],
            COL_MKT_CAP: [100.0],
            COL_SECTOR_ICB11: [1],
            COL_SECTOR_ICB19: [1],
            COL_ESG_SCORE: [60.0],
            "score": [1.0],
        }
    ).set_index(COL_ISIN)

    builder = PortfolioBuilder(
        screen=screen,
        bench="TEST",
        percentile=0.5,
        metrics="score",
        score_pivot_esg="INDEX TEST",
        score_pivot_esg_path=str(tmp_path),
    )

    assert builder.score_pivot_esg == 55.0

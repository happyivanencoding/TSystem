import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.esg_pivot import resolve_esg_pivot_score
from core.portfolio_builder import PortfolioBuilder
from backtest_code.runner.input_loader import (
    MULTI_AVG_SOURCE_COLUMNS,
    load_pruned_backtest_inputs,
)
from backtest_code.config.settings import AppSettings
from backtest_code.runner.service import BacktestService
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


def test_vectorized_sector_neutralization_matches_legacy_algorithm():
    sectors = np.repeat(np.arange(1, 20), 3)
    screen = pd.DataFrame(
        {
            COL_ISIN: [f"ISIN{i:03d}" for i in range(len(sectors))],
            COL_SEDOL: [f"SED{i:03d}" for i in range(len(sectors))],
            COL_DATE: pd.Timestamp("2013-01-31"),
            "Weight in TEST": 1.0 / len(sectors),
            COL_MKT_CAP: np.arange(100.0, 100.0 + len(sectors)),
            COL_SECTOR_ICB11: sectors,
            COL_SECTOR_ICB19: sectors,
            COL_ESG_SCORE: 75.0,
            "score_a": np.sin(np.arange(len(sectors))) + np.arange(len(sectors)) / 100,
            "score_b": np.cos(np.arange(len(sectors))) - np.arange(len(sectors)) / 200,
        }
    ).set_index(COL_ISIN)
    builder = PortfolioBuilder(
        screen=screen,
        bench="TEST",
        percentile=0.2,
        metrics=["score_a", "score_b"],
        copy_inputs=False,
    )

    expected = screen.copy()
    score_columns = ["score_a", "score_b"]
    scores = expected[score_columns].astype(float).rank(pct=True)
    scores = (scores - scores.min()) / (scores.max() - scores.min())
    for sector in expected[COL_SECTOR_ICB19].unique():
        mask = expected[COL_SECTOR_ICB19] == sector
        sector_scores = scores.loc[mask, score_columns].rank(pct=True)
        sector_scores = (
            sector_scores - sector_scores.min()
        ) / (sector_scores.max() - sector_scores.min())
        scores.loc[mask, score_columns] = sector_scores
    expected.loc[:, score_columns] = scores

    actual = builder.neutralise_score_by_secteur(screen, score_columns)

    assert_frame_equal(actual, expected, check_exact=True)


def test_monthly_base_cache_is_exact_across_scores_and_sides():
    sectors = np.repeat(np.arange(1, 20), 3)
    screen = pd.DataFrame(
        {
            COL_ISIN: [f"ISIN{i:03d}" for i in range(len(sectors))],
            COL_SEDOL: [f"SED{i:03d}" for i in range(len(sectors))],
            COL_DATE: pd.Timestamp("2013-01-31"),
            "Weight in TEST": 1.0 / len(sectors),
            COL_MKT_CAP: np.arange(100.0, 100.0 + len(sectors)),
            COL_SECTOR_ICB11: sectors,
            COL_SECTOR_ICB19: sectors,
            COL_ESG_SCORE: 75.0,
            "score_a": np.arange(len(sectors), dtype=float),
            "score_b": np.sin(np.arange(len(sectors))) + np.arange(len(sectors)) / 100,
        }
    ).set_index(COL_ISIN)
    cache = {}

    warm_builder = PortfolioBuilder(
        screen=screen,
        bench="TEST",
        percentile=0.2,
        metrics="score_a",
        ponderation="Market cap",
        copy_inputs=False,
        monthly_base_cache=cache,
    )
    warm_builder.sec_list_spot(screen)

    for top, ptf_name in ((True, "TOP"), (False, "WORST")):
        uncached_builder = PortfolioBuilder(
            screen=screen,
            bench="TEST",
            percentile=0.2,
            metrics="score_b",
            ptf_name=ptf_name,
            ponderation="Market cap",
            Top=top,
            copy_inputs=False,
        )
        cached_builder = PortfolioBuilder(
            screen=screen,
            bench="TEST",
            percentile=0.2,
            metrics="score_b",
            ptf_name=ptf_name,
            ponderation="Market cap",
            Top=top,
            copy_inputs=False,
            monthly_base_cache=cache,
        )

        uncached_selection, uncached_exclusions = uncached_builder.sec_list_spot(screen)
        cached_selection, cached_exclusions = cached_builder.sec_list_spot(screen)

        assert_frame_equal(cached_selection, uncached_selection, check_exact=True)
        assert_frame_equal(cached_exclusions, uncached_exclusions, check_exact=True)


def test_official_worker_inputs_are_pruned_to_shard_universe(tmp_path):
    screen_path = tmp_path / "screen.parquet"
    returns_path = tmp_path / "returns.parquet"
    screen = pd.DataFrame(
        {
            COL_DATE: [pd.Timestamp("2024-02-29")] * 4,
            COL_ISIN: ["AAA", "BBB", "CCC", ISIN_PAIRS[0]],
            COL_SEDOL: ["SED1", "SED2", "NON_MEMBER", "PAIR_SEDOL"],
            COL_SECTOR_ICB19: [1, 2, 3, 4],
            COL_MKT_CAP: [100.0, 200.0, 300.0, 400.0],
            "Weight in STOXX EUROPE 600": [0.4, 0.6, 0.0, 0.0],
            "score": [1.0, 2.0, 3.0, 4.0],
            "unused_score": [3.0, 4.0, 5.0, 6.0],
        }
    )
    returns = pd.DataFrame(
        {
            "SED1": [0.01, 0.02],
            "SED2": [0.03, 0.04],
            "NON_MEMBER": [0.05, 0.06],
            "PAIR_SEDOL": [0.07, 0.08],
            "UNUSED": [0.05, 0.06],
        },
        index=pd.to_datetime(["2024-02-01", "2024-02-02"]),
    )
    screen.to_parquet(screen_path, index=False)
    returns.to_parquet(returns_path)

    loaded_screen, loaded_returns = load_pruned_backtest_inputs(
        screen_path,
        returns_path,
        metrics=["score"],
        benchmarks=["STOXX EUROPE 600"],
        start_date="2024-02-01",
    )

    assert "score" in loaded_screen.columns
    assert "unused_score" not in loaded_screen.columns
    assert loaded_returns.columns.tolist() == ["SED1", "SED2", "PAIR_SEDOL"]
    assert isinstance(loaded_returns.index, pd.DatetimeIndex)
    assert loaded_returns.index.min() == pd.Timestamp("2024-02-01")


def test_pruned_input_loader_expands_multi_avg_dependencies(tmp_path):
    screen_path = tmp_path / "screen.parquet"
    returns_path = tmp_path / "returns.parquet"
    screen = pd.DataFrame(
        {
            COL_DATE: [pd.Timestamp("2024-01-31")],
            COL_ISIN: ["AAA"],
            COL_SEDOL: ["SED1"],
            COL_SECTOR_ICB19: [1],
            COL_MKT_CAP: [100.0],
            "Weight in TEST": [1.0],
            **{column: [0.5] for column in MULTI_AVG_SOURCE_COLUMNS},
            "unused_score": [1.0],
        }
    )
    returns = pd.DataFrame(
        {"SED1": [0.01]},
        index=pd.to_datetime(["2024-02-01"]),
    )
    screen.to_parquet(screen_path, index=False)
    returns.to_parquet(returns_path)

    loaded_screen, _ = load_pruned_backtest_inputs(
        screen_path,
        returns_path,
        metrics=["Multi Avg Percentile"],
        benchmarks=["TEST"],
    )

    assert set(MULTI_AVG_SOURCE_COLUMNS).issubset(loaded_screen.columns)
    assert "Multi Avg Percentile" not in loaded_screen.columns
    assert "unused_score" not in loaded_screen.columns


def test_portfolio_builder_default_shares_inputs_without_mutating_them():
    screen = pd.DataFrame(
        {
            COL_ISIN: ["AAA", "BBB"],
            COL_SEDOL: ["SED1", "SED2"],
            COL_DATE: [pd.Timestamp("2024-01-31")] * 2,
            "Weight in TEST": [0.5, 0.5],
            COL_MKT_CAP: [100.0, 200.0],
            COL_SECTOR_ICB11: [1, 1],
            COL_SECTOR_ICB19: [1, 1],
            COL_ESG_SCORE: [75.0, 80.0],
            "score": [1.0, 2.0],
        }
    ).set_index(COL_ISIN)
    original = screen.copy(deep=True)
    builder = PortfolioBuilder(
        screen=screen,
        bench="TEST",
        percentile=0.5,
        metrics="score",
        esg_exclusion=0.0,
    )

    assert builder.screen is screen
    builder.sec_list_spot(screen)
    assert_frame_equal(screen, original, check_exact=True)


def test_service_batch_input_plan_uses_metric_union_and_earliest_date(tmp_path):
    screen_path = tmp_path / "screen.parquet"
    returns_path = tmp_path / "returns.parquet"
    screen = pd.DataFrame(
        {
            COL_DATE: [
                pd.Timestamp("2023-01-31"),
                pd.Timestamp("2024-01-31"),
            ],
            COL_ISIN: ["AAA", "AAA"],
            COL_SEDOL: ["SED1", "SED1"],
            COL_SECTOR_ICB19: [1, 1],
            COL_MKT_CAP: [100.0, 110.0],
            "Weight in TEST": [1.0, 1.0],
            "score_a": [0.1, 0.2],
            "score_b": [0.3, 0.4],
            "unused_score": [0.5, 0.6],
        }
    )
    returns = pd.DataFrame(
        {"SED1": [0.01, 0.02, 0.03]},
        index=pd.to_datetime(["2022-12-30", "2023-02-01", "2024-02-01"]),
    )
    screen.to_parquet(screen_path, index=False)
    returns.to_parquet(returns_path)

    settings_a = AppSettings()
    settings_a.paths.screen = str(screen_path)
    settings_a.paths.returns = str(returns_path)
    settings_a.run.bench = "TEST"
    settings_a.run.metrics = ["score_a"]
    settings_a.run.start_date = "2024-01-01"
    settings_a.run.esg_exclusion = 0.0
    settings_b = settings_a.copy()
    settings_b.run.metrics = ["score_b"]
    settings_b.run.start_date = "2023-01-01"

    loaded_screen, loaded_returns = BacktestService()._load_inputs_for_settings(  # noqa: SLF001
        [settings_a, settings_b]
    )

    assert {"score_a", "score_b"}.issubset(loaded_screen.columns)
    assert "unused_score" not in loaded_screen.columns
    assert loaded_screen[COL_DATE].min() == pd.Timestamp("2023-01-31")
    assert loaded_returns.index.min() == pd.Timestamp("2023-02-01")

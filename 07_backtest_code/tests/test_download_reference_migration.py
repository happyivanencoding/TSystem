import sys
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tp_core.backtesting import (
    BacktestSchema,
    PtfBuilder,
    backtest_weight_table,
    benchmark_to_weight_table,
)
from core.factor_pipeline import (
    build_factor_component,
    handle_missing_values,
    neutralize_score,
    run_growth_factor_pipeline,
    transform_absolute_values,
)
from utils.constants import (
    COL_DATE,
    COL_ISIN,
    COL_MKT_CAP,
    COL_SECTOR_ICB11,
    COL_SECTOR_ICB19,
    COL_SEDOL,
)


def _sample_screen():
    return pd.DataFrame(
        {
            COL_ISIN: ["AAA", "BBB", "AAA", "BBB"],
            COL_SEDOL: ["S1", "S2", "S1", "S2"],
            COL_DATE: pd.to_datetime(["2024-01-31", "2024-01-31", "2024-02-29", "2024-02-29"]),
            "Weight in TEST": [0.5, 0.5, 0.5, 0.5],
            COL_MKT_CAP: [100.0, 400.0, 121.0, 441.0],
            COL_SECTOR_ICB11: [1, 1, 1, 1],
            COL_SECTOR_ICB19: [1, 1, 1, 1],
            "Exchange Country Region": ["EU", "EU", "EU", "EU"],
            "score": [1.0, 2.0, 1.2, 2.2],
            "Sales": [10.0, 20.0, 11.0, 22.0],
            "R&D Expense CIQ": [1.0, 2.0, 1.2, 2.4],
        }
    )


def test_factor_pipeline_neutralizes_so_higher_values_get_higher_scores():
    df = _sample_screen()
    scored = neutralize_score(df, "score", higher_is_better=True)

    date_mask = scored[COL_DATE] == pd.Timestamp("2024-01-31")
    assert scored.loc[date_mask & (scored[COL_ISIN] == "BBB"), "score"].iloc[0] > scored.loc[
        date_mask & (scored[COL_ISIN] == "AAA"), "score"
    ].iloc[0]


def test_factor_pipeline_handles_missing_and_absolute_transforms():
    df = _sample_screen()
    df.loc[0, "score"] = np.nan
    filled = handle_missing_values(df, ["score"])
    assert filled["score"].notna().all()

    transformed, new_cols = transform_absolute_values(df, ["R&D Expense CIQ"])
    assert new_cols == ["R&D Expense CIQ_Intensity"]
    assert "R&D Expense CIQ_Intensity" in transformed.columns

    growth = run_growth_factor_pipeline(df, abs_vars=["R&D Expense CIQ"], ratio_vars=["score"])
    assert "R&D Expense CIQ_Intensity" in growth.columns
    assert growth["R&D Expense CIQ_Intensity"].notna().any()


def test_build_factor_component_combines_level_and_change_scores():
    df = _sample_screen()
    config = {
        "use_level": True,
        "weight_level": 0.7,
        "use_diff": True,
        "weight_diff": 0.3,
        "higher_is_better": True,
    }

    out, contribution = build_factor_component(df, "score", config)

    assert "score_diff" in out.columns
    assert isinstance(contribution, pd.Series)
    assert contribution.notna().any()


def test_ptfbuilder_download_reference_compatibility_methods():
    screen = _sample_screen().set_index(COL_ISIN, drop=False)
    returns = pd.DataFrame(
        {
            "S1": [0.0, 0.01, 0.02],
            "S2": [0.0, -0.01, 0.01],
        },
        index=pd.to_datetime(["2024-02-01", "2024-02-02", "2024-03-01"]),
    )
    builder = PtfBuilder(
        screen=screen,
        returns=returns,
        bench="TEST",
        percentile=0.5,
        metrics="score",
        ponderation="Racine carrée",
    )

    adjusted = builder.adjust_companies_ponderation(screen)
    assert adjusted.loc["AAA", COL_MKT_CAP].iloc[0] == 10.0

    sec_list = pd.DataFrame(
        {
            COL_DATE: [pd.Timestamp("2024-02-01"), pd.Timestamp("2024-02-01")],
            COL_ISIN: ["AAA", "BBB"],
        }
    )
    weights = benchmark_to_weight_table(
        sec_list,
        "TEST",
        screen.reset_index(drop=True),
        1.0,
        method="EW",
    )
    assert not weights.empty
    assert weights.groupby(level=0)["Portfolio weight"].sum().round(10).eq(1.0).all()

    nav = backtest_weight_table(
        weights.reset_index(),
        returns,
        schema=BacktestSchema(),
    ).nav
    assert nav.iloc[0] == 100.0

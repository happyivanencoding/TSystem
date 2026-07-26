import pandas as pd
import pytest


def test_lowvol_consumer_uses_exact_sector_targets():
    from tp_research.workflows import run_lowvol_resvol_research as module
    date = pd.Timestamp("2024-01-31")
    screen = pd.DataFrame(
        {
            module.COL_DATE: [date] * 5,
            module.COL_ISIN: list("ABCDE"),
            module.COL_SEDOL: list("ABCDE"),
            module.COL_SECTOR_ICB19: ["S1", "S1", "S1", "S2", "S2"],
            module.COL_MKT_CAP: [5.0, 4.0, 3.0, 2.0, 1.0],
            module.WEIGHT_COL: [0.3, 0.2, 0.1, 0.3, 0.1],
            "score": [5.0, 4.0, 3.0, 2.0, 1.0],
        }
    )

    weights = module.select_weights(screen, "score", True)

    assert weights[module.COL_PORTFOLIO_WEIGHT].sum() == pytest.approx(1.0)
    assert weights.groupby(module.COL_SECTOR_ICB19)[
        module.COL_PORTFOLIO_WEIGHT
    ].sum().to_dict() == pytest.approx({"S1": 0.6, "S2": 0.4})
    assert weights[module.COL_PORTFOLIO_WEIGHT].max() <= module.MAX_WEIGHT


def test_technical_consumer_preserves_sector_targets_and_cap():
    from tp_models.technical import pattern_backtest_engine as module
    group = pd.DataFrame(
        {
            "Company SEDOL": list("ABCDEF"),
            "Sector": ["S1", "S1", "S1", "S2", "S2", "S2"],
            "Benchmark Weight": [0.3, 0.2, 0.1, 0.2, 0.1, 0.1],
            module.CANONICAL_MKT_CAP_COL: [6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
            "Total Score": [6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
        }
    )

    selected = module._select_group_members(
        group,
        target_count=4,
        sector_neutral=True,
        max_weight=0.4,
    )
    weights = module._assign_strategy_weights(
        selected,
        group,
        sector_neutral=True,
        max_weight=0.4,
    )

    assert weights["Portfolio weight"].sum() == pytest.approx(1.0)
    assert weights.groupby("Sector")["Portfolio weight"].sum().to_dict() == (
        pytest.approx({"S1": 0.6, "S2": 0.4})
    )
    assert weights["Portfolio weight"].max() <= 0.4

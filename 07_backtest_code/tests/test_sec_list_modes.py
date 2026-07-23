import sys
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).resolve().parents[1]
opt_root = project_root.parent / "06_optimiser"
for path in [project_root, opt_root]:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tp_core.backtesting import PtfBuilder
import optimizer_engine


def _screen():
    isins = [f"ISIN{i}" for i in range(6)]
    return pd.DataFrame(
        {
            "Date": [pd.Timestamp("2024-01-31")] * 6,
            "Name": [f"Company {i}" for i in range(6)],
            "Company SEDOL": [f"SED{i}" for i in range(6)],
            "Weight in TEST": [0.22, 0.20, 0.18, 0.16, 0.14, 0.10],
            "Weight in MSCI WORLD": [0.22, 0.20, 0.18, 0.16, 0.14, 0.10],
            "Benchmark Market Value Millions in EUR": [100, 90, 80, 70, 60, 50],
            " Benchmark ICB Supersector ": [1, 1, 2, 2, 3, 3],
            " Benchmark ICB Industry ": [1, 1, 2, 2, 3, 3],
            "Exchange Country Region": ["West Europe", "West Europe", "North America", "North America", "Others", "Others"],
            "ESG_ANALYST_SCORE": [80, 75, 70, 65, 60, 55],
            "Score ML": [9, 8, 7, 6, 5, 4],
        },
        index=pd.Index(isins, name="ISIN"),
    )


def _returns():
    dates = pd.to_datetime(["2024-01-02", "2024-01-10", "2024-01-20", "2024-01-31"])
    data = {f"SED{i}": np.repeat(0.001 * (i + 1), len(dates)) for i in range(6)}
    return pd.DataFrame(data, index=dates)


def test_normal_and_optimized_sec_list_modes_are_separate(monkeypatch):
    def fake_optimize(result_df, *args, **kwargs):
        weights = pd.to_numeric(result_df["Score ML"], errors="coerce").fillna(0).clip(lower=0)
        result_df = result_df.copy()
        result_df["Wopt"] = weights / weights.sum()
        return result_df, "optimal"

    monkeypatch.setattr(optimizer_engine, "optimize", fake_optimize)

    builder = PtfBuilder(
        screen=_screen(),
        returns=_returns(),
        bench="TEST",
        percentile=0.5,
        metrics="Score ML",
        ponderation="Equalweight",
        ptf_name="TEST PTF",
        optimizer_config={
            "current_params": {
                "margin_title": 0.0,
                "margin_country": 1.0,
                "margin_sector": 1.0,
                "nb_max_titres": 6,
                "nb_min_titres": 1,
                "max_turnover": 1.0,
                "min_score_target": 0.0,
                "te_max": 1.0,
            },
            "lb_title": {"North America": 0.0, "West Europe": 0.0, "Others": 0.0},
            "config_ub": {
                "North America": {"bins": [0, 1], "values": [1.0]},
                "West Europe": {"bins": [0, 1], "values": [1.0]},
                "Others": {"bins": [0, 1], "values": [1.0]},
            },
            "top_mandatory": 1,
        },
    )

    normal_sec_list, _ = builder.sec_list_spot()
    normal_weights = normal_sec_list.set_index("ISIN")["Weight"].copy()

    optimized_sec_list = builder.sec_list_spot_optim(init=True, drift=False)

    assert builder.sec_list_monthly is not None
    assert builder.sec_list_optimized_monthly is not None
    assert normal_weights.equals(builder.sec_list_monthly.set_index("ISIN")["Weight"])
    assert optimized_sec_list["Weight"].sum() == 1.0
    assert not optimized_sec_list.set_index("ISIN")["Weight"].equals(normal_weights.reindex(optimized_sec_list["ISIN"]))
    assert builder.optimizer_result_monthly is not None

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "sector_score_model.py"
SPEC = importlib.util.spec_from_file_location("sector_score_model_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
sector_score_model = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sector_score_model
SPEC.loader.exec_module(sector_score_model)


def test_latest_recommendations_use_current_sector_scores(tmp_path: Path) -> None:
    sectors = list(range(1, 9))
    panel = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-05-31"] * len(sectors)),
            "next_date": pd.to_datetime(["2026-06-30"] * len(sectors)),
            "sector_code": sectors,
            "sector_name": [f"Sector {sector}" for sector in sectors],
            "score_final": [float(sector) for sector in sectors],
            "sector_weight": [1 / len(sectors)] * len(sectors),
            "sector_forward_return": [sector / 100 for sector in sectors],
            "return_coverage_n": [10] * len(sectors),
        }
    )
    latest_scores = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-06-30"] * len(sectors)),
            "sector_code": sectors,
            "sector_name": [f"Sector {sector}" for sector in sectors],
            "score_final": [float(9 - sector) for sector in sectors],
            "sector_weight": [1 / len(sectors)] * len(sectors),
        }
    )

    sector_score_model.write_outputs(
        panel,
        tmp_path,
        "score_final",
        top_n=1,
        bottom_n=1,
        latest_scores=latest_scores,
    )

    latest = pd.read_csv(tmp_path / "sector_scores_latest.csv", encoding="utf-8-sig")
    assert pd.to_datetime(latest["Date"]).max() == pd.Timestamp("2026-06-30")
    assert latest.loc[latest["rank"].eq(1), "sector_name"].item() == "Sector 1"

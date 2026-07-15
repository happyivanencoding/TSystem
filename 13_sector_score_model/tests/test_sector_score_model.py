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


def test_trailing_sector_mean_never_uses_future_scores() -> None:
    dates = pd.date_range("2025-01-31", periods=7, freq="ME")
    frame = pd.DataFrame(
        {
            "Date": list(dates) * 2,
            "sector_code": [1] * 7 + [2] * 7,
            "score": list(range(1, 8)) + list(range(11, 18)),
        }
    )

    original = sector_score_model._trailing_sector_mean(frame, "score", months=6)
    changed = frame.copy()
    changed.loc[changed["Date"].eq(dates[-1]), "score"] = 10_000
    revised = sector_score_model._trailing_sector_mean(changed, "score", months=6)

    earlier = frame["Date"].lt(dates[-1])
    pd.testing.assert_series_equal(original[earlier], revised[earlier])
    assert original.iloc[5] == 3.5


def test_sector_tilt_tie_break_is_independent_of_row_order() -> None:
    panel = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-01-31"] * 8),
            "next_date": pd.to_datetime(["2026-02-28"] * 8),
            "sector_code": list(range(1, 9)),
            "sector_name": [f"Sector {sector}" for sector in range(1, 9)],
            "score": [10, 10, 9, 8, 3, 2, 1, 1],
            "sector_weight": [0.125] * 8,
            "sector_forward_return": [sector / 100 for sector in range(1, 9)],
        }
    )
    original = sector_score_model.run_sector_tilt_backtest(panel, score_column="score")
    shuffled = sector_score_model.run_sector_tilt_backtest(
        panel.sample(frac=1, random_state=7), score_column="score"
    )

    assert original.loc[0, "model_return"] == shuffled.loc[0, "model_return"]
    assert original.loc[0, "top_sectors"] == shuffled.loc[0, "top_sectors"]
    assert original.loc[0, "bottom_sectors"] == shuffled.loc[0, "bottom_sectors"]

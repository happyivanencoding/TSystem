from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pandas as pd


build_candidates = import_module("02_pipelines.build_candidates")


def test_sector_component_uses_latest_recommendation_csv(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "sector_scores_latest.csv"
    pd.DataFrame(
        {
            "Date": ["2026-06-30", "2026-06-30"],
            "sector_code": [1, 2],
            "sector_name": ["A", "B"],
            "score_final": [7.0, 3.0],
            "recommendation": ["Positive", "Negative"],
        }
    ).to_csv(path, index=False, encoding="utf-8-sig")
    monkeypatch.setattr(build_candidates, "SECTOR_OUTPUTS", [("US", path)])

    frame, date = build_candidates._sector_component(as_of=None)

    assert date == pd.Timestamp("2026-06-30")
    assert frame["signal_date_sector"].max() == pd.Timestamp("2026-06-30")
    assert frame.loc[frame["sector_code"].eq(1), "sector_recommendation"].item() == "Positive"

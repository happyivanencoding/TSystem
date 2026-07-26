from __future__ import annotations

from argparse import Namespace
from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest


build_candidates = import_module("02_pipelines.build_candidates")


class FakeRepository:
    def __init__(self, signals: pd.DataFrame, screen_date: str | list[str]) -> None:
        self._signals = signals
        screen_dates = [screen_date] if isinstance(screen_date, str) else screen_date
        self._screen = pd.DataFrame(
            {
                "Date": [pd.Timestamp(value) for value in screen_dates],
                "Company SEDOL": ["ABC1234"] * len(screen_dates),
                "Exchange Country Region": ["North America"] * len(screen_dates),
                "Exchange Country Name": ["UNITED STATES"] * len(screen_dates),
                " Benchmark ICB Supersector ": [1] * len(screen_dates),
            }
        )

    def signals(self) -> pd.DataFrame:
        return self._signals.copy()

    def screen(self, *, last_only: bool = False) -> pd.DataFrame:
        screen = self._screen.copy()
        if last_only:
            screen = screen[screen["Date"].eq(screen["Date"].max())]
        return screen


def _signals(ml_date: str, technical_dates: list[str]) -> pd.DataFrame:
    rows = [
        {
            "Date": pd.Timestamp(ml_date),
            "scope": "security",
            "signal_family": "ML",
            "signal_name": "score_ml",
            "Company SEDOL": "ABC1234",
            "score": 0.8,
            "score_pct": 0.8,
            "region": "North America",
            "raw_value": 0.8,
        }
    ]
    rows.extend(
        {
            "Date": pd.Timestamp(date),
            "scope": "security",
            "signal_family": "Technical",
            "signal_name": "momentum",
            "Company SEDOL": "ABC1234",
            "score": 0.9,
            "score_pct": 0.9,
            "region": "North America",
            "raw_value": 0.9,
        }
        for date in technical_dates
    )
    return pd.DataFrame(rows)


def _run_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    signals: pd.DataFrame,
    screen_date: str,
    policy: str,
) -> pd.DataFrame:
    repo = FakeRepository(signals, screen_date)
    monkeypatch.setattr(build_candidates, "PresentationDataRepository", lambda: repo)
    monkeypatch.setattr(
        build_candidates,
        "_sector_component",
        lambda as_of: (
            pd.DataFrame(
                columns=[
                    "sector_region_key",
                    "sector_code",
                    "sector_score",
                    "sector_score_pct",
                    "sector_name",
                    "sector_recommendation",
                    "signal_date_sector",
                ]
            ),
            None,
        ),
    )
    return build_candidates.build_candidates(
        as_of=None,
        output=tmp_path / "candidates.parquet",
        top_n=1,
        top_pct=0.1,
        ml_weight=0.7,
        technical_weight=0.3,
        allocation_weight=0.2,
        candidate_date_policy=policy,
        max_component_lag_days=31,
        allow_stale_technical=False,
        by_region=False,
    )


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


def test_screen_snapshot_uses_history_without_future_data() -> None:
    repo = FakeRepository(
        pd.DataFrame(),
        ["2026-01-31", "2026-06-30"],
    )

    frame, snapshot_date = build_candidates._screen_snapshot(
        repo,
        pd.Timestamp("2026-01-31"),
    )

    assert snapshot_date == pd.Timestamp("2026-01-31")
    assert len(frame) == 1


def test_min_component_reselects_signals_without_lookahead(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _run_candidates(
        tmp_path,
        monkeypatch,
        signals=_signals("2026-01-31", ["2026-01-31", "2026-06-30"]),
        screen_date="2026-01-31",
        policy="min_component",
    )

    assert frame["candidate_date"].max() == pd.Timestamp("2026-01-31")
    assert frame["signal_date_technical"].max() == pd.Timestamp("2026-01-31")


def test_max_component_rejects_candidate_after_screen_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="Screen snapshot"):
        _run_candidates(
            tmp_path,
            monkeypatch,
            signals=_signals("2026-06-30", ["2026-06-30"]),
            screen_date="2026-01-31",
            policy="max_component",
        )


def test_max_component_rejects_stale_nontechnical_component(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="组件过旧"):
        _run_candidates(
            tmp_path,
            monkeypatch,
            signals=_signals("2025-01-31", ["2026-06-30"]),
            screen_date="2026-06-30",
            policy="max_component",
        )


def test_run_build_candidates_records_causal_freshness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeManifest:
        def __init__(self, step: str, parameters: dict[str, object]) -> None:
            self.inputs: dict[str, object] = {}
            self.outputs: dict[str, object] = {}
            self.details: dict[str, object] = {}
            self.validations: list[dict[str, object]] = []
            captured["manifest"] = self

        def add_validation(self, name, ok, message="", details=None) -> None:
            self.validations.append({"name": name, "ok": ok, "details": details})

        def write(self, status: str, *, error=None) -> Path:
            captured["status"] = status
            return tmp_path / "build_candidates_manifest.json"

    candidate_date = pd.Timestamp("2026-06-30")
    frame = pd.DataFrame(
        {
            "candidate_date": [candidate_date],
            "screen_snapshot_date": [candidate_date],
            "Company SEDOL": ["ABC1234"],
            "selected": [True],
            "signal_date_ml": [candidate_date],
            "signal_date_technical": [candidate_date],
            "signal_date_regime": [candidate_date],
            "signal_date_country": [candidate_date],
            "signal_date_sector": [candidate_date],
        }
    )
    monkeypatch.setattr(build_candidates, "StepManifest", FakeManifest)
    monkeypatch.setattr(build_candidates, "build_candidates", lambda **kwargs: frame)

    manifest_path = build_candidates.run_build_candidates(
        Namespace(
            as_of=None,
            output=str(tmp_path / "candidates.parquet"),
            top_n=1,
            top_pct=0.1,
            ml_weight=0.7,
            technical_weight=0.3,
            allocation_weight=0.2,
            candidate_date_policy="max_component",
            max_component_lag_days=31,
            allow_stale_technical=False,
            by_region=False,
            signals_dir=str(tmp_path / "signals"),
            last_screen=str(tmp_path / "last_screen.parquet"),
        )
    )

    manifest = captured["manifest"]
    validation_by_name = {item["name"]: item["ok"] for item in manifest.validations}
    assert manifest_path.name == "build_candidates_manifest.json"
    assert captured["status"] == "success"
    assert validation_by_name["candidate_date_fresh"] is True
    assert validation_by_name["component_dates_causal_and_fresh"] is True
    assert manifest.details["component_freshness"]["component_lag_days"] == {
        "ml": 0,
        "technical": 0,
        "regime": 0,
        "country": 0,
        "sector": 0,
    }

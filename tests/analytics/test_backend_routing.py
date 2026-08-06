from __future__ import annotations

import pandas as pd

from presentation_layer import data_repository
from presentation_layer.data_repository import PresentationDataRepository
from tp_core.analytics.backend_routing import backend_for, reader_engine


def test_selective_backend_policy_is_single_and_explicit() -> None:
    expected = {
        "screen_latest_selected": "partitioned_parquet",
        "company_latest": "latest_snapshot",
        "company_history": "legacy_parquet",
        "returns_matrix": "legacy_parquet",
        "official_backtest_input": "legacy_parquet",
        "screen_full": "legacy_parquet",
        "returns_full": "legacy_parquet",
        "dashboard_marts": "duckdb",
        "catalog": "duckdb",
        "monthly_writer": "partitioned_parquet",
    }

    assert {key: backend_for(key) for key in expected} == expected
    assert reader_engine("screen_latest_selected") == "hybrid"
    assert reader_engine("company_history") == "legacy_parquet"
    assert reader_engine("dashboard_marts") == "duckdb"


def test_repository_policy_wins_over_global_engine_for_production_routes(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("TP_DATA_ENGINE", "duckdb")
    calls: list[tuple[str, str]] = []

    def fake_last_screen(path, *, columns=None, engine=None, **kwargs):
        calls.append(("latest", str(engine)))
        return pd.DataFrame({"Date": pd.to_datetime(["2026-02-28"]), "ISIN": ["ISIN1"]})

    def fake_screen(path, *, columns=None, engine=None, **kwargs):
        calls.append(("screen", str(engine)))
        return pd.DataFrame({"ISIN": ["ISIN1"], "Date": pd.to_datetime(["2026-02-28"])})

    def fake_returns(path, *, columns=None, engine=None, **kwargs):
        calls.append(("returns", str(engine)))
        return pd.DataFrame(
            {"SED1": [0.1]},
            index=pd.DatetimeIndex(["2026-02-28"], name="Date"),
        )

    monkeypatch.setattr(data_repository, "read_last_screen", fake_last_screen)
    monkeypatch.setattr(data_repository, "read_screen_aggregate", fake_screen)
    monkeypatch.setattr(data_repository, "read_returns", fake_returns)

    repository = PresentationDataRepository(root=tmp_path)
    repository.screen(last_only=True, columns=("Date", "ISIN"))
    repository.screen(last_only=False)
    repository.latest_company_snapshot(isin="ISIN1")
    repository.company_history("ISIN1")
    repository.returns(columns=("SED1",))

    assert calls == [
        ("latest", "hybrid"),
        ("screen", "legacy_parquet"),
        ("latest", "legacy_parquet"),
        ("screen", "legacy_parquet"),
        ("returns", "legacy_parquet"),
    ]

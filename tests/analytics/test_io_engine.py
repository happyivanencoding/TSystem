from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from presentation_layer.data_repository import PresentationDataRepository
from tp_backtest.runner.input_loader import load_pruned_backtest_inputs
from tp_core.analytics import partition_readers
from tp_core.analytics.catalog import build_catalog_release
from tp_core.analytics.config import DuckDBConfig
from tp_core.analytics.partitioning import migrate_dataset
from tp_core.io import read_last_screen, read_returns, read_screen_aggregate


def _fixture_release(tmp_path: Path) -> tuple[Path, Path, Path]:
    screen_path = tmp_path / "00_screen" / "screen_aggregate.parquet"
    returns_path = tmp_path / "00_screen" / "returns.parquet"
    screen_path.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-01-31", "2026-01-31", "2026-02-28"]),
            "Company SEDOL": ["SED1", "SED2", "SED1"],
            "Benchmark Market Value Millions in EUR": [100.0, 200.0, 110.0],
            "Weight in TEST": [0.5, 0.5, 0.6],
            "score": [1.0, 2.0, 3.0],
            "value": [1.0, 2.0, 3.0],
        },
        index=pd.Index(["ISIN1", "ISIN2", "ISIN1"], name="ISIN"),
    ).to_parquet(screen_path)
    pd.DataFrame(
        {"SED1": [0.1, 0.2], "SED2": [0.3, 0.4]},
        index=pd.DatetimeIndex(["2025-12-31", "2026-01-02"], name="Date"),
    ).to_parquet(returns_path)
    screen = migrate_dataset(screen_path, dataset_name="screen", root=tmp_path, apply=True)
    returns = migrate_dataset(returns_path, dataset_name="returns_wide", root=tmp_path, apply=True)
    config = DuckDBConfig(
        database_path=tmp_path / "artifacts" / "analytics" / "duckdb" / "tp_analytics.duckdb",
        temp_directory=tmp_path / "artifacts" / "analytics" / "duckdb" / "temp",
        data_root=tmp_path,
        artifact_root=tmp_path / "artifacts",
        latest_pointer=tmp_path / "artifacts" / "analytics" / "duckdb" / "latest.json",
    )
    summary = build_catalog_release(
        config,
        release_id="io-engine-test",
        screen_manifest_path=screen.current_pointer or "",
        returns_manifest_path=returns.current_pointer or "",
    )
    return Path(str(summary["database_path"])), screen_path, returns_path


def test_io_reads_duckdb_and_shadow_engines_without_changing_default_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database, screen_path, returns_path = _fixture_release(tmp_path)
    monkeypatch.setenv("TP_DUCKDB_PATH", str(database))
    monkeypatch.setenv("TP_DATA_ENGINE", "duckdb")

    screen = read_screen_aggregate(
        screen_path,
        columns=("Date", "ISIN", "Company SEDOL", "value"),
        date_from=date(2026, 1, 31),
        date_to=date(2026, 2, 28),
        engine="duckdb",
    )
    latest = read_last_screen(
        screen_path,
        columns=("Date", "ISIN", "value"),
        engine="duckdb",
    )
    returns = read_returns(
        returns_path,
        columns=("SED1",),
        date_from=date(2025, 12, 31),
        date_to=date(2026, 1, 2),
        engine="duckdb",
    )
    assert len(screen) == 3
    assert len(latest) == 1
    assert latest.iloc[0]["ISIN"] == "ISIN1"
    assert returns.index.name == "Date"
    assert returns["SED1"].tolist() == [0.1, 0.2]

    shadow_screen = read_screen_aggregate(
        screen_path,
        columns=("Date", "ISIN", "Company SEDOL", "value"),
        date_from=date(2026, 1, 31),
        date_to=date(2026, 2, 28),
        engine="shadow_compare",
    )
    legacy_screen = read_screen_aggregate(
        screen_path,
        columns=("Date", "ISIN", "Company SEDOL", "value"),
        date_from=date(2026, 1, 31),
        date_to=date(2026, 2, 28),
        engine="legacy_parquet",
    )
    shadow_returns = read_returns(
        returns_path,
        columns=("SED1",),
        date_from=date(2025, 12, 31),
        date_to=date(2026, 1, 2),
        engine="shadow_compare",
    )
    legacy_returns = read_returns(
        returns_path,
        columns=("SED1",),
        date_from=date(2025, 12, 31),
        date_to=date(2026, 1, 2),
        engine="legacy_parquet",
    )
    pd.testing.assert_frame_equal(shadow_screen, legacy_screen)
    pd.testing.assert_frame_equal(shadow_returns, legacy_returns)

    presentation = PresentationDataRepository(root=tmp_path, engine="duckdb", run_type="benchmark")
    presentation_latest = presentation.screen(last_only=True, columns=("Date", "ISIN", "value"))
    presentation_returns = presentation.returns(columns=("SED1",), date_from=date(2025, 12, 31), date_to=date(2026, 1, 2))
    assert len(presentation_latest) == 1
    assert presentation_latest.iloc[0]["ISIN"] == "ISIN1"
    pd.testing.assert_frame_equal(presentation_returns, returns)

    loaded_screen, loaded_returns = load_pruned_backtest_inputs(
        screen_path,
        returns_path,
        metrics=("score",),
        benchmarks=("TEST",),
        start_date=date(2026, 1, 1),
        engine="duckdb",
        run_type="benchmark",
    )
    assert loaded_screen["score"].tolist() == [1.0, 2.0, 3.0]
    assert loaded_returns.columns.tolist() == ["SED1", "SED2"]


def test_hybrid_engine_reads_partitioned_screen_returns_and_company_history(tmp_path: Path) -> None:
    _, screen_path, returns_path = _fixture_release(tmp_path)

    screen = read_screen_aggregate(
        screen_path,
        columns=("Date", "ISIN", "Company SEDOL", "value"),
        date_from=date(2026, 1, 31),
        date_to=date(2026, 2, 28),
        engine="hybrid",
    )
    latest = read_last_screen(
        screen_path,
        columns=("Date", "ISIN", "value"),
        engine="hybrid",
    )
    returns = read_returns(
        returns_path,
        columns=("SED1",),
        date_from=date(2025, 12, 31),
        date_to=date(2026, 1, 2),
        engine="hybrid",
    )
    history = PresentationDataRepository(root=tmp_path, engine="hybrid", run_type="benchmark").company_history(
        "ISIN1",
        columns=("Date", "ISIN", "value"),
    )

    assert screen.shape == (3, 4)
    assert latest["Date"].nunique() == 1
    assert latest.iloc[0]["ISIN"] == "ISIN1"
    assert returns["SED1"].tolist() == [0.1, 0.2]
    assert history["ISIN"].tolist() == ["ISIN1", "ISIN1"]


def test_hybrid_latest_reads_only_the_latest_screen_partition(tmp_path: Path, monkeypatch) -> None:
    _, screen_path, _ = _fixture_release(tmp_path)
    read_paths: list[Path] = []
    original_read_table = partition_readers.pq.read_table

    def tracking_read_table(path, *args, **kwargs):
        read_paths.append(Path(path).resolve())
        return original_read_table(path, *args, **kwargs)

    monkeypatch.setattr(partition_readers.pq, "read_table", tracking_read_table)

    latest = read_last_screen(
        screen_path,
        columns=("Date", "ISIN", "value"),
        engine="hybrid",
    )

    assert len(set(read_paths)) == 1
    assert latest["Date"].max() == pd.Timestamp("2026-02-28")


def test_r03_and_r05_legacy_routes_preserve_full_numeric_matrix(tmp_path: Path, monkeypatch) -> None:
    database, screen_path, returns_path = _fixture_release(tmp_path)
    monkeypatch.setenv("TP_DUCKDB_PATH", str(database))
    expected_full = pd.read_parquet(returns_path)
    expected_full.index = pd.DatetimeIndex(expected_full.index).astype("datetime64[ns]")

    r03 = read_returns(
        returns_path,
        columns=("SED1", "SED2"),
        engine="legacy_parquet",
    )
    pd.testing.assert_frame_equal(r03, expected_full)

    _, r05 = load_pruned_backtest_inputs(
        screen_path,
        returns_path,
        metrics=("score",),
        benchmarks=("TEST",),
        start_date=date(2026, 1, 1),
        engine="duckdb",
        run_type="benchmark",
    )
    expected_r05 = expected_full.loc[expected_full.index >= pd.Timestamp("2026-01-01")]
    pd.testing.assert_frame_equal(r05, expected_r05)

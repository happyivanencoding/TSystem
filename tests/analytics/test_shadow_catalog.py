from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from tp_core.analytics.catalog import build_catalog_release, catalog_health
from tp_core.analytics.config import DuckDBConfig
from tp_core.analytics.connection import connect
from tp_core.analytics.partitioning import load_current_manifest, migrate_dataset
from tp_core.analytics.queries import ReturnsQuery, ScreenQuery
from tp_core.analytics.repositories import ReturnsRepository, ScreenRepository
from tp_core.analytics.shadow import (
    shadow_compare_returns,
    shadow_compare_returns_partitions,
    shadow_compare_screen,
)


def _build_release(tmp_path: Path) -> tuple[Path, Path, Path]:
    screen_path = tmp_path / "00_screen" / "screen_aggregate.parquet"
    returns_path = tmp_path / "00_screen" / "returns.parquet"
    screen_path.parent.mkdir(parents=True)
    screen = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-01-31", "2026-01-31", "2026-02-28"]),
            "Company SEDOL": ["SED1", "SED2", "SED1"],
            "value": [1.0, 2.0, 3.0],
        },
        index=pd.Index(["ISIN1", "ISIN2", "ISIN1"], name="ISIN"),
    )
    returns = pd.DataFrame(
        {"SED1": [0.1, 0.2], "SED2": [0.3, 0.4]},
        index=pd.DatetimeIndex(["2025-12-31", "2026-01-02"], name="Date"),
    )
    screen.to_parquet(screen_path)
    returns.to_parquet(returns_path)
    screen_result = migrate_dataset(screen_path, dataset_name="screen", root=tmp_path, apply=True)
    returns_result = migrate_dataset(returns_path, dataset_name="returns_wide", root=tmp_path, apply=True)
    config = DuckDBConfig(
        database_path=tmp_path / "artifacts" / "analytics" / "duckdb" / "tp_analytics.duckdb",
        temp_directory=tmp_path / "artifacts" / "analytics" / "duckdb" / "temp",
        data_root=tmp_path,
        artifact_root=tmp_path / "artifacts",
        latest_pointer=tmp_path / "artifacts" / "analytics" / "duckdb" / "latest.json",
    )
    summary = build_catalog_release(
        config,
        release_id="shadow-test",
        screen_manifest_path=screen_result.current_pointer or "",
        returns_manifest_path=returns_result.current_pointer or "",
    )
    return Path(str(summary["database_path"])), screen_path, returns_path


def test_catalog_release_is_readable_and_repositories_use_canonical_views(tmp_path: Path) -> None:
    database, screen_path, returns_path = _build_release(tmp_path)
    config = DuckDBConfig(database_path=database, read_only=True, data_root=tmp_path)
    with connect(config) as connection:
        health = catalog_health(connection)
        assert health.ok is True
        assert connection.execute("SELECT COUNT(*) FROM canonical.screen").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM canonical.returns_wide").fetchone()[0] == 2
        screen = ScreenRepository(connection).latest(columns=("Date", "ISIN", "value"))
        returns = ReturnsRepository(connection).matrix(ReturnsQuery(securities=("SED1",)))
        assert len(screen) == 1
        assert screen.iloc[0]["ISIN"] == "ISIN1"
        assert returns.index.name == "Date"
        assert returns["SED1"].tolist() == [0.1, 0.2]

        screen_shadow = shadow_compare_screen(
            connection,
            screen_path,
            ScreenQuery(
                columns=("Date", "ISIN", "Company SEDOL", "value"),
                date_from=date(2026, 1, 31),
                date_to=date(2026, 2, 28),
            ),
            surface="dashboard",
        )
        returns_shadow = shadow_compare_returns(
            connection,
            returns_path,
            ReturnsQuery(securities=("SED1", "SED2")),
            surface="backtest",
        )
        returns_manifest = load_current_manifest(
            tmp_path / "00_screen" / "datasets" / "manifests" / "returns_wide" / "current.json",
            root=tmp_path,
        )
        returns_partition_shadow = shadow_compare_returns_partitions(
            connection,
            returns_path,
            returns_manifest.path,
            ReturnsQuery(securities=("SED1",), date_from=date(2026, 1, 1), date_to=date(2026, 1, 2)),
            root=tmp_path,
            surface="backtest_partition",
        )
        assert screen_shadow.status == "passed"
        assert returns_shadow.status == "passed"
        assert returns_partition_shadow.status == "passed"

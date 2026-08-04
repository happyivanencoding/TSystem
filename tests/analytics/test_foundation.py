from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from tp_core.analytics.catalog import catalog_health, initialize_catalog, initialize_database
from tp_core.analytics.cli import build_catalog_main, validate_release_main
from tp_core.analytics.config import DuckDBConfig
from tp_core.analytics.connection import connect, connection_info
from tp_core.analytics.locking import FileLock
from tp_core.analytics.manifests import (
    MANIFEST_SCHEMA_VERSION,
    ManifestError,
    load_manifest,
    validate_manifest,
    write_json_atomic,
)
from tp_core.analytics.materializations import MaterializationSpec, materialize
from tp_core.analytics.parity import compare_frames
from tp_core.analytics.queries import (
    QuerySpecError,
    ReturnsQuery,
    ScreenQuery,
    SignalQuery,
    quote_identifier,
)
from tp_core.analytics.repositories import ReturnsRepository, ScreenRepository, SignalRepository


def test_config_reads_typed_environment_overrides(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TP_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("TP_DUCKDB_PATH", str(tmp_path / "catalog.duckdb"))
    monkeypatch.setenv("TP_DUCKDB_THREADS", "2")
    monkeypatch.setenv("TP_DATA_ENGINE", "shadow_compare")
    config = DuckDBConfig.from_env()

    assert config.database_path == tmp_path / "catalog.duckdb"
    assert config.data_root == tmp_path
    assert config.threads == 2
    assert config.data_engine == "shadow_compare"


def test_connection_is_explicit_and_records_settings(tmp_path: Path) -> None:
    config = DuckDBConfig.from_env(database_path=tmp_path / "catalog.duckdb")
    with connect(config) as connection:
        connection.execute("CREATE TABLE smoke(value INTEGER)")
        info = connection_info(connection, config)
        assert info["read_only"] is False
    with connect(config.with_database(tmp_path / "catalog.duckdb", read_only=True)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM smoke").fetchone()[0] == 0


def test_catalog_initialization_is_idempotent(tmp_path: Path) -> None:
    config = DuckDBConfig.from_env(database_path=tmp_path / "catalog.duckdb")
    first = initialize_database(config, release_id="release-1")
    second = initialize_database(config, release_id="release-1")

    assert first.ok and second.ok
    with connect(config.with_database(config.database_path, read_only=True)) as connection:
        health = catalog_health(connection)
        assert health.schema_version == "tp.catalog.v1"
        assert health.table_rows["meta.catalog_releases"] == 1


def test_catalog_cli_apply_and_validate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = tmp_path / "catalog.duckdb"
    assert build_catalog_main(["--database", str(database), "--apply", "--release-id", "cli-release"]) == 0
    assert validate_release_main(["--database", str(database)]) == 0
    output = capsys.readouterr().out
    assert '"status": "passed"' in output


def test_repositories_validate_columns_and_preserve_returns_wide() -> None:
    connection = duckdb.connect(":memory:")
    try:
        initialize_catalog(connection)
        connection.execute('CREATE TABLE "canonical"."screen" ("ISIN" VARCHAR, "Date" DATE, "Company SEDOL" VARCHAR, "Weight in MSCI WORLD" DOUBLE)')
        connection.execute("INSERT INTO canonical.screen VALUES ('A', '2026-01-31', 'SED1', 0.5), ('B', '2026-01-31', 'SED2', 0.0)")
        screen = ScreenRepository(connection).query(ScreenQuery(columns=("ISIN",), positive_weight_only=True))
        assert screen["ISIN"].tolist() == ["A"]

        connection.execute('CREATE TABLE "canonical"."returns_wide" ("Date" DATE, "SED1" DOUBLE, "SED2" DOUBLE)')
        connection.execute("INSERT INTO canonical.returns_wide VALUES ('2026-01-30', 0.1, 0.2), ('2026-01-31', 0.3, 0.4)")
        returns = ReturnsRepository(connection).matrix(ReturnsQuery(securities=("SED1",), date_from=date(2026, 1, 31)))
        assert returns.index.tolist() == [pd.Timestamp("2026-01-31")]
        assert returns.columns.tolist() == ["SED1"]
        with pytest.raises(QuerySpecError):
            ScreenRepository(connection).query(ScreenQuery(columns=("missing",)))

        connection.execute('CREATE TABLE "signals"."all_signals" (signal_family VARCHAR, signal_name VARCHAR, scope VARCHAR, as_of DATE, value DOUBLE)')
        connection.execute("INSERT INTO signals.all_signals VALUES ('family', 'signal', 'global', '2026-01-01', 1), ('family', 'signal', 'global', '2026-02-01', 2)")
        latest = SignalRepository(connection).query(SignalQuery(latest_only=True))
        assert latest["value"].tolist() == [2.0]
        assert "__tp_rn" not in latest.columns
    finally:
        connection.close()


def test_manifest_and_parity_contracts() -> None:
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_name": "screen",
        "dataset_version": "screen-v1",
        "partitions": [{"path": "part.parquet", "sha256": "abc", "row_count": 1}],
        "validation_status": "passed",
    }
    validate_manifest(payload)
    with pytest.raises(ManifestError):
        validate_manifest({"dataset_name": "screen"})
    result = compare_frames(pd.DataFrame({"id": [1], "value": [2]}), pd.DataFrame({"id": [1], "value": [2]}), key_columns=("id",))
    assert result.equal
    assert quote_identifier('column "quoted"') == '"column ""quoted"""'


def test_manifest_atomic_write_and_file_lock(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_name": "returns_wide",
        "dataset_version": "returns-v1",
        "partitions": [],
        "validation_status": "passed",
    }
    write_json_atomic(manifest_path, payload)
    assert load_manifest(manifest_path).dataset_version == "returns-v1"

    lock_path = tmp_path / "catalog.duckdb.lock"
    with FileLock(lock_path):
        assert lock_path.exists()
    with FileLock(lock_path):
        assert lock_path.exists()


def test_materialization_is_limited_to_allowlisted_sources() -> None:
    connection = duckdb.connect(":memory:")
    try:
        initialize_catalog(connection)
        connection.execute('CREATE TABLE "canonical"."screen" (value INTEGER)')
        connection.execute("INSERT INTO canonical.screen VALUES (1), (2)")
        assert materialize(connection, MaterializationSpec("latest_screen_summary", "canonical.screen")) == 2
        with pytest.raises(QuerySpecError):
            MaterializationSpec("unsafe", "main.secret_table")
    finally:
        connection.close()

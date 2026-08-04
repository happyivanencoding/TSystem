"""DuckDB catalog schemas and release registration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .config import DuckDBConfig
from .connection import connect
from .contracts import CATALOG_SCHEMA_VERSION, CATALOG_SCHEMAS, CatalogHealth, CatalogRelease
from .locking import FileLock

CATALOG_TABLES: tuple[str, ...] = (
    "meta.schema_migrations",
    "meta.dataset_registry",
    "meta.dataset_versions",
    "meta.partition_registry",
    "meta.schema_registry",
    "meta.data_quality_results",
    "meta.catalog_releases",
    "meta.artifact_registry",
    "meta.run_registry",
    "meta.pipeline_manifest_registry",
    "meta.benchmark_registry",
    "meta.query_benchmark_results",
    "meta.materialization_registry",
)


def initialize_catalog(connection: Any) -> None:
    """Create the foundation schemas/tables idempotently."""

    for schema in CATALOG_SCHEMAS:
        connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    for statement in _TABLE_DDL:
        connection.execute(statement)
    existing = connection.execute(
        "SELECT COUNT(*) FROM meta.schema_migrations WHERE version = ?",
        [CATALOG_SCHEMA_VERSION],
    ).fetchone()[0]
    if not existing:
        connection.execute(
            "INSERT INTO meta.schema_migrations(version, applied_at, checksum) VALUES (?, ?, ?)",
            [CATALOG_SCHEMA_VERSION, datetime.now(UTC), CATALOG_SCHEMA_VERSION],
        )


def catalog_health(connection: Any) -> CatalogHealth:
    schemas = tuple(
        row[0]
        for row in connection.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ("
            + ",".join("?" for _ in CATALOG_SCHEMAS)
            + ") ORDER BY schema_name",
            list(CATALOG_SCHEMAS),
        ).fetchall()
    )
    tables: list[str] = []
    table_rows: dict[str, int] = {}
    for relation in CATALOG_TABLES:
        schema, table = relation.split(".", 1)
        count = connection.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"').fetchone()[0]
        tables.append(relation)
        table_rows[relation] = int(count)
    version_rows = connection.execute(
        "SELECT version FROM meta.schema_migrations ORDER BY applied_at"
    ).fetchall()
    versions = tuple(row[0] for row in version_rows)
    return CatalogHealth(
        ok=set(CATALOG_SCHEMAS).issubset(schemas) and set(CATALOG_TABLES).issubset(tables),
        schemas=schemas,
        tables=tuple(tables),
        table_rows=table_rows,
        schema_version=versions[-1] if versions else "unknown",
    )


def register_release(connection: Any, release: CatalogRelease) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO meta.catalog_releases "
        "(release_id, created_at, database_path, screen_dataset_version, "
        "returns_dataset_version, validation_status, manifest_path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            release.release_id,
            release.created_at,
            release.database_path,
            release.screen_dataset_version,
            release.returns_dataset_version,
            release.validation_status,
            release.manifest_path,
        ],
    )


def latest_release(connection: Any) -> dict[str, Any] | None:
    rows = connection.execute(
        "SELECT release_id, created_at, database_path, screen_dataset_version, "
        "returns_dataset_version, validation_status, manifest_path "
        "FROM meta.catalog_releases ORDER BY created_at DESC LIMIT 1"
    ).fetchall()
    if not rows:
        return None
    columns = [item[0] for item in connection.description]
    return dict(zip(columns, rows[0], strict=True))


def initialize_database(
    config: DuckDBConfig,
    *,
    release_id: str | None = None,
    screen_dataset_version: str | None = None,
    returns_dataset_version: str | None = None,
) -> CatalogHealth:
    """Initialize a database under the single-writer lock."""

    if config.read_only:
        raise ValueError("initialize_database requires read_only=False")
    lock_path = config.database_path.with_suffix(config.database_path.suffix + ".lock")
    with FileLock(lock_path), connect(config) as connection:
        initialize_catalog(connection)
        if release_id is not None:
            register_release(
                connection,
                CatalogRelease(
                    release_id=release_id,
                    database_path=str(config.database_path),
                    screen_dataset_version=screen_dataset_version,
                    returns_dataset_version=returns_dataset_version,
                ),
            )
        return catalog_health(connection)


_TABLE_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS meta.schema_migrations (
        version VARCHAR PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL,
        checksum VARCHAR NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS meta.dataset_registry (
        dataset_name VARCHAR PRIMARY KEY,
        current_dataset_version VARCHAR,
        current_manifest_path VARCHAR,
        updated_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS meta.dataset_versions (
        dataset_name VARCHAR,
        dataset_version VARCHAR,
        manifest_path VARCHAR,
        schema_fingerprint VARCHAR,
        row_count BIGINT,
        validation_status VARCHAR,
        created_at TIMESTAMPTZ,
        PRIMARY KEY(dataset_name, dataset_version)
    )""",
    """CREATE TABLE IF NOT EXISTS meta.partition_registry (
        dataset_name VARCHAR,
        dataset_version VARCHAR,
        partition_key VARCHAR,
        path VARCHAR,
        sha256 VARCHAR,
        row_count BIGINT,
        bytes BIGINT,
        created_at TIMESTAMPTZ,
        PRIMARY KEY(dataset_name, dataset_version, partition_key, path)
    )""",
    """CREATE TABLE IF NOT EXISTS meta.schema_registry (
        schema_name VARCHAR,
        object_name VARCHAR,
        object_type VARCHAR,
        schema_fingerprint VARCHAR,
        registered_at TIMESTAMPTZ,
        PRIMARY KEY(schema_name, object_name, object_type)
    )""",
    """CREATE TABLE IF NOT EXISTS meta.data_quality_results (
        dataset_name VARCHAR,
        dataset_version VARCHAR,
        check_name VARCHAR,
        status VARCHAR,
        details_json VARCHAR,
        checked_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS meta.catalog_releases (
        release_id VARCHAR PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL,
        database_path VARCHAR NOT NULL,
        screen_dataset_version VARCHAR,
        returns_dataset_version VARCHAR,
        validation_status VARCHAR NOT NULL,
        manifest_path VARCHAR
    )""",
    """CREATE TABLE IF NOT EXISTS meta.artifact_registry (
        artifact_id VARCHAR,
        artifact_type VARCHAR,
        path VARCHAR,
        sha256 VARCHAR,
        run_id VARCHAR,
        catalog_release_id VARCHAR,
        created_at TIMESTAMPTZ,
        PRIMARY KEY(artifact_id)
    )""",
    """CREATE TABLE IF NOT EXISTS meta.run_registry (
        run_id VARCHAR PRIMARY KEY,
        run_type VARCHAR,
        status VARCHAR,
        dataset_version VARCHAR,
        catalog_release_id VARCHAR,
        query_hash VARCHAR,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS meta.pipeline_manifest_registry (
        manifest_id VARCHAR PRIMARY KEY,
        step_name VARCHAR,
        path VARCHAR,
        status VARCHAR,
        run_id VARCHAR,
        created_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS meta.benchmark_registry (
        benchmark_id VARCHAR PRIMARY KEY,
        workload VARCHAR,
        engine VARCHAR,
        result_fingerprint VARCHAR,
        elapsed_seconds DOUBLE,
        peak_memory_bytes BIGINT,
        bytes_read BIGINT,
        created_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS meta.query_benchmark_results (
        benchmark_id VARCHAR,
        query_hash VARCHAR,
        cold_or_warm VARCHAR,
        elapsed_seconds DOUBLE,
        result_fingerprint VARCHAR,
        created_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS meta.materialization_registry (
        materialization_name VARCHAR PRIMARY KEY,
        source_relation VARCHAR,
        row_count BIGINT,
        catalog_release_id VARCHAR,
        refreshed_at TIMESTAMPTZ
    )""",
)


__all__ = [
    "CATALOG_TABLES",
    "catalog_health",
    "initialize_catalog",
    "initialize_database",
    "latest_release",
    "register_release",
]

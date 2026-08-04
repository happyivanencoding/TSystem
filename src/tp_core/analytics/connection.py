"""Explicit DuckDB connection management.

No module-level ``duckdb.sql`` calls are used here.  Callers receive and own a
connection for the lifetime of a request, test, or single-process writer.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb

from .config import DuckDBConfig


def _options(config: DuckDBConfig) -> dict[str, str]:
    options: dict[str, str] = {}
    if config.memory_limit:
        options["memory_limit"] = config.memory_limit
    if config.threads is not None:
        options["threads"] = str(config.threads)
    if str(config.database_path) != ":memory:":
        options["temp_directory"] = str(config.temp_directory)
    if config.parquet_metadata_cache:
        options["enable_object_cache"] = "true"
    if config.access_mode != "automatic":
        options["access_mode"] = config.access_mode
    return options


@contextmanager
def connect(
    config: DuckDBConfig | None = None,
    *,
    database_path: str | Path | None = None,
    read_only: bool | None = None,
) -> Iterator[Any]:
    """Open one explicit DuckDB connection and close it deterministically."""

    resolved = config or DuckDBConfig.from_env(read_only=read_only, database_path=database_path)
    if config is not None and (database_path is not None or read_only is not None):
        resolved = config.with_database(
            database_path or config.database_path,
            read_only=config.read_only if read_only is None else read_only,
        )
    target = str(resolved.database_path)
    if target != ":memory:" and not resolved.read_only:
        resolved.database_path.parent.mkdir(parents=True, exist_ok=True)
        resolved.temp_directory.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(
        target,
        read_only=resolved.read_only,
        config=_options(resolved),
    )
    try:
        yield connection
    finally:
        connection.close()


def connection_info(connection: Any, config: DuckDBConfig | None = None) -> dict[str, object]:
    """Return the runtime settings that should be recorded with a release."""

    resolved = config or DuckDBConfig.from_env()
    version = connection.execute("SELECT version() AS version").fetchone()[0]
    return {
        "duckdb_version": str(version),
        "database_path": str(resolved.database_path),
        "read_only": resolved.read_only,
        "memory_limit": resolved.memory_limit,
        "threads": resolved.threads,
        "temp_directory": str(resolved.temp_directory),
        "parquet_metadata_cache": resolved.parquet_metadata_cache,
        "access_mode": resolved.access_mode,
    }


__all__ = ["connect", "connection_info"]

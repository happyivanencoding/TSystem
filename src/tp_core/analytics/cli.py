"""Command-line entry points for the DuckDB foundation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .catalog import catalog_health, initialize_database
from .config import DuckDBConfig
from .connection import connect, connection_info
from .parity import compare_frames
from .profiling import parquet_profile, timed_frame


def _json_dump(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _database_config(args: argparse.Namespace, *, read_only: bool) -> DuckDBConfig:
    return DuckDBConfig.from_env(
        read_only=read_only,
        database_path=Path(args.database) if args.database else None,
    )


def build_catalog_main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="创建或检查 TP DuckDB catalog foundation")
    parser.add_argument("--database", help="目标 DuckDB 文件；默认读取 TP_DUCKDB_PATH")
    parser.add_argument("--release-id")
    parser.add_argument("--apply", action="store_true", help="创建/更新 catalog；默认只检查配置")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.apply:
        config = _database_config(args, read_only=True)
        _json_dump({"status": "inspect_only", "config": config.as_dict()})
        return 0
    config = _database_config(args, read_only=False)
    health = initialize_database(
        config,
        release_id=args.release_id or f"foundation-{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
    )
    _json_dump({"status": "applied", "config": config.as_dict(), "health": health.as_dict()})
    return 0 if health.ok else 1


def validate_release_main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="验证 TP DuckDB catalog release")
    parser.add_argument("--database", help="待读取的 DuckDB 文件；默认读取 TP_DUCKDB_PATH")
    args = parser.parse_args(list(argv) if argv is not None else None)
    config = _database_config(args, read_only=True)
    try:
        with connect(config) as connection:
            health = catalog_health(connection)
            payload = {"status": "passed" if health.ok else "failed", "health": health.as_dict()}
    except (duckdb.Error, OSError, ValueError) as exc:
        payload = {"status": "failed", "error": repr(exc), "database": str(config.database_path)}
        _json_dump(payload)
        return 1
    _json_dump(payload)
    return 0 if health.ok else 1


def data_audit_main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查当前 canonical Parquet 元数据")
    parser.add_argument("--root", default=str(DuckDBConfig.from_env().data_root))
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path(args.root)
    paths = {
        "screen_aggregate": root / "00_screen" / "screen_aggregate.parquet",
        "returns": root / "00_screen" / "returns.parquet",
        "last_screen": root / "00_screen" / "last_screen.parquet",
        "screen_aggregate_5y": root / "00_screen" / "screen_aggregate_5Y.parquet",
    }
    payload = {"status": "measured", "canonical": {name: parquet_profile(path) for name, path in paths.items()}}
    _json_dump(payload)
    return 0


def benchmark_main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 DuckDB foundation smoke benchmark")
    parser.add_argument("--database", help="DuckDB 文件；默认读取 TP_DUCKDB_PATH")
    args = parser.parse_args(list(argv) if argv is not None else None)
    config = _database_config(args, read_only=True)
    try:
        with connect(config) as connection:
            smoke = timed_frame("duckdb_select_one", lambda: connection.execute("SELECT 1 AS value").df())
            payload = {"status": smoke.status, "connection": connection_info(connection, config), "workload": smoke.as_dict()}
    except (duckdb.Error, OSError, ValueError) as exc:
        _json_dump({"status": "failed", "error": repr(exc)})
        return 1
    _json_dump(payload)
    return 0


def parity_main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="比较两个 Parquet DataFrame 的基础 parity")
    parser.add_argument("--left", required=True)
    parser.add_argument("--right", required=True)
    parser.add_argument("--key", action="append", default=[])
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = compare_frames(pd.read_parquet(args.left), pd.read_parquet(args.right), key_columns=args.key)
    _json_dump(result.as_dict())
    return 0 if result.equal else 1


__all__ = [
    "benchmark_main",
    "build_catalog_main",
    "data_audit_main",
    "parity_main",
    "validate_release_main",
]

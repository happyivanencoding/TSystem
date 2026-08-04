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
from .manifests import load_manifest
from .parity import compare_frames
from .partitioning import (
    load_current_manifest,
    migrate_dataset,
    validate_mirror,
    write_compatibility_export_from_manifest,
)
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
    parser.add_argument("--left")
    parser.add_argument("--right")
    parser.add_argument("--dataset", choices=("screen", "returns_wide"))
    parser.add_argument("--source")
    parser.add_argument("--manifest")
    parser.add_argument("--root", default=str(DuckDBConfig.from_env().data_root))
    parser.add_argument("--key", action="append", default=[])
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.dataset:
        if not args.source or not args.manifest:
            parser.error("--dataset requires --source and --manifest")
        payload = validate_mirror(args.source, args.manifest, root=args.root)
        _json_dump(payload)
        return 0 if payload["status"] == "passed" else 1
    if not args.left or not args.right:
        parser.error("direct parity requires --left and --right")
    result = compare_frames(pd.read_parquet(args.left), pd.read_parquet(args.right), key_columns=args.key)
    _json_dump(result.as_dict())
    return 0 if result.equal else 1


def _migrate_main(argv: Iterable[str] | None, *, dataset_name: str) -> int:
    parser = argparse.ArgumentParser(description=f"为 {dataset_name} 创建不可变 Parquet 分区镜像")
    parser.add_argument("--root", default=str(DuckDBConfig.from_env().data_root))
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-run-id")
    parser.add_argument("--apply", action="store_true", help="实际写入；默认只审计源文件")
    parser.add_argument("--write-compatibility-export", action="store_true")
    parser.add_argument("--compatibility-export")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = migrate_dataset(
        args.source,
        dataset_name=dataset_name,
        root=args.root,
        apply=args.apply,
        source_run_id=args.source_run_id,
        write_compatibility_export=args.write_compatibility_export,
        compatibility_export_path=args.compatibility_export,
    )
    _json_dump(result.as_dict())
    return 0


def migrate_screen_main(argv: Iterable[str] | None = None) -> int:
    return _migrate_main(argv, dataset_name="screen")


def migrate_returns_main(argv: Iterable[str] | None = None) -> int:
    return _migrate_main(argv, dataset_name="returns_wide")


def compatibility_export_main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从明确 Dataset Manifest 原子重建兼容导出")
    parser.add_argument("--dataset", choices=("screen", "returns_wide"), required=True)
    parser.add_argument("--manifest", help="manifest 路径；默认读取 datasets/<dataset>/current.json")
    parser.add_argument("--output", help="输出路径；默认读取 manifest.compatibility_export.path")
    parser.add_argument("--root", default=str(DuckDBConfig.from_env().data_root))
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path(args.root)
    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.is_absolute():
            manifest_path = root / manifest_path
        manifest = load_manifest(manifest_path, require_files=True, root=root)
    else:
        manifest_path = root / "00_screen" / "datasets" / "manifests" / args.dataset / "current.json"
        manifest = load_current_manifest(manifest_path, root=root)
    export_payload = manifest.payload.get("compatibility_export", {})
    output_raw = args.output or export_payload.get("path")
    if not output_raw:
        parser.error("manifest does not define compatibility_export.path; pass --output")
    output = Path(str(output_raw))
    write_compatibility_export_from_manifest(manifest, output, root=root)
    _json_dump(
        {
            "status": "written",
            "dataset_name": manifest.dataset_name,
            "dataset_version": manifest.dataset_version,
            "manifest_path": str(manifest_path),
            "output_path": str(output),
            "source_role": "compatibility_export",
            "authoritative_dataset_version": manifest.dataset_version,
        }
    )
    return 0


__all__ = [
    "benchmark_main",
    "build_catalog_main",
    "compatibility_export_main",
    "data_audit_main",
    "migrate_returns_main",
    "migrate_screen_main",
    "parity_main",
    "validate_release_main",
]

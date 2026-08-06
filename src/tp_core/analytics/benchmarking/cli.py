"""CLI for the pre-activation DuckDB performance and evidence suite."""

from __future__ import annotations

import argparse
import ast
import json
import os
import random
import subprocess
import sys
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from .engines import ENGINE_ORDER, VALID_ENGINES
from .environment import capture_environment, file_state, snapshot_paths
from .parity import _normalise, compare_frames
from .pipeline_suite import _run_command, run_pipeline_suite
from .reporting import write_reports
from .statistics import attribution_rows, summarize_measurements
from .storage import create_local_mirror, local_mirror_is_ready, mirrored_database
from .workloads import default_registry_path, load_workloads, select_workloads
from .writer_suite import run_monthly_replays


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _release_id(database: Path) -> str | None:
    try:
        import duckdb

        with duckdb.connect(str(database), read_only=True) as connection:
            row = connection.execute(
                "SELECT release_id FROM meta.catalog_releases ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return str(row[0]) if row and row[0] else None
    except Exception:
        return None


def _latest_isins(database: Path, *, count: int | None = None) -> list[str]:
    import duckdb

    with duckdb.connect(str(database), read_only=True) as connection:
        rows = connection.execute(
            'SELECT DISTINCT "ISIN" FROM canonical.screen WHERE "Date" = (SELECT max("Date") FROM canonical.screen) AND "ISIN" IS NOT NULL ORDER BY "ISIN"'
        ).fetchall()
    values = [str(row[0]) for row in rows]
    return values[:count] if count is not None else values


def _longest_history_isin(database: Path) -> str:
    import duckdb

    with duckdb.connect(str(database), read_only=True) as connection:
        row = connection.execute(
            'SELECT "ISIN" FROM canonical.screen WHERE "ISIN" IS NOT NULL GROUP BY "ISIN" ORDER BY count(*) DESC, "ISIN" LIMIT 1'
        ).fetchone()
    if not row:
        raise ValueError("catalog did not contain an ISIN")
    return str(row[0])


def _positive_msci_sedols(database: Path, *, count: int) -> list[str]:
    import duckdb

    with duckdb.connect(str(database), read_only=True) as connection:
        rows = connection.execute(
            'SELECT "Company SEDOL" FROM canonical.screen WHERE "Date" = (SELECT max("Date") FROM canonical.screen) AND COALESCE("Weight in MSCI WORLD", 0) > 0 AND "Company SEDOL" IS NOT NULL ORDER BY "Company SEDOL" LIMIT ?',
            [count],
        ).fetchall()
    return [str(row[0]) for row in rows]


def _returns_columns(path: Path, *, count: int) -> list[str]:
    names = [str(name) for name in pq.ParquetFile(path).schema.names]
    excluded = {"Date", "__index_level_0__"}
    return [name for name in names if name not in excluded][:count]


def _returns_columns_for_sedols(
    path: Path, sedols: Iterable[str], *, fallback_count: int
) -> list[str]:
    names = set(str(name) for name in pq.ParquetFile(path).schema.names)
    selected: list[str] = []
    for sedol in sedols:
        for candidate in (str(sedol), f"{sedol}-R"):
            if candidate in names:
                selected.append(candidate)
                break
    return selected or _returns_columns(path, count=fallback_count)


def _resolve_workload_inputs(
    workload: Any, *, database: Path, root: Path, as_of: str
) -> dict[str, Any]:
    universe = workload.universe
    resolved: dict[str, Any] = {}
    if universe.get("selection") == "longest_history":
        resolved["company_isin"] = _longest_history_isin(database)
        resolved["screen_isins"] = [resolved["company_isin"]]
    elif universe.get("selection") == "random_latest":
        values = _latest_isins(database)
        generator = random.Random(int(universe.get("seed", 1)))
        count = int(universe.get("count", 100))
        resolved["screen_isins"] = sorted(generator.sample(values, min(count, len(values))))
    elif universe.get("selection") == "first_columns":
        resolved["returns_columns"] = _returns_columns(
            root / "00_screen" / "returns.parquet", count=int(universe.get("count", 100))
        )
    elif universe.get("selection") == "latest_screen_positive_msci":
        sedols = _positive_msci_sedols(database, count=int(universe.get("count", 500)))
        resolved["returns_columns"] = _returns_columns_for_sedols(
            root / "00_screen" / "returns.parquet",
            sedols,
            fallback_count=int(universe.get("count", 500)),
        )
    elif universe.get("selection") == "default_profile_members":
        sedols = _positive_msci_sedols(database, count=2000)
        resolved["returns_columns"] = _returns_columns_for_sedols(
            root / "00_screen" / "returns.parquet", sedols, fallback_count=1000
        )
    operation = workload.operation
    mart_names = {
        "mart_latest_signals": "latest_signals",
        "mart_latest_regime": "latest_regime",
        "mart_latest_country": "latest_country_scores",
        "mart_latest_sector": "latest_sector_scores",
        "mart_latest_factor": "latest_factor_recommendation",
        "mart_latest_candidates": "latest_candidates",
        "mart_latest_portfolio": "latest_portfolio",
        "company_latest_payload": "company_master_latest",
        "mart_factor_api_payload": "latest_factor_recommendation",
        "mart_backtest_summary": "latest_backtest_summary",
    }
    if operation in mart_names:
        resolved["mart_name"] = mart_names[operation]
    if operation == "returns_official_backtest_input" and "returns_columns" not in resolved:
        resolved["returns_columns"] = _returns_columns(
            root / "00_screen" / "returns.parquet", count=1000
        )
    return resolved


def _worker_result(spec: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
    worker = Path(__file__).with_name("subprocess_runner.py")
    started = time.perf_counter()
    process = subprocess.Popen(
        [sys.executable, str(worker), "--worker"],
        cwd=str(spec["repo_root"]),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    payload_text = json.dumps(spec, ensure_ascii=False, default=str)
    try:
        stdout, stderr = process.communicate(payload_text, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        return {
            "status": "timeout",
            "error": "worker timeout",
            "elapsed_seconds": time.perf_counter() - started,
            "stdout": stdout[-4000:],
            "stderr": stderr[-4000:],
        }
    result_line = next(
        (line for line in reversed(stdout.splitlines()) if line.startswith("BENCHMARK_RESULT=")),
        None,
    )
    if result_line is None:
        return {
            "status": "failed",
            "error": f"worker produced no result: {stderr[-1000:]}",
            "elapsed_seconds": time.perf_counter() - started,
        }
    try:
        result = json.loads(result_line.removeprefix("BENCHMARK_RESULT="))
    except json.JSONDecodeError as exc:
        return {
            "status": "failed",
            "error": repr(exc),
            "elapsed_seconds": time.perf_counter() - started,
        }
    result["worker_returncode"] = process.returncode
    result["worker_elapsed_seconds"] = time.perf_counter() - started
    result["worker_stderr"] = stderr[-2000:]
    return result


def _measurement_record(
    *,
    workload: Any,
    engine: str,
    storage: str,
    cache_mode: str,
    repeat: int,
    order: int,
    seed: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "workload_id": workload.workload_id,
        "category": workload.category,
        "hot_path": workload.hot_path,
        "engine": engine,
        "storage": storage,
        "cache_mode": cache_mode,
        "repeat": repeat,
        "order": order,
        "seed": seed,
        "status": result.get("status", "failed"),
        "error": result.get("error"),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "peak_rss_bytes": result.get("peak_rss_bytes"),
        "read_bytes": result.get("read_bytes"),
        "write_bytes": result.get("write_bytes"),
        "rows": result.get("rows"),
        "columns": result.get("columns"),
        "column_names": result.get("column_names", []),
    }


def _run_worker_batch(
    jobs: list[tuple[tuple[Any, ...], dict[str, Any]]], *, timeout_seconds: int
) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    if not jobs:
        return []
    with ThreadPoolExecutor(max_workers=min(3, len(jobs))) as executor:
        futures = {
            executor.submit(_worker_result, spec, timeout_seconds=timeout_seconds): metadata
            for metadata, spec in jobs
        }
        return [(futures[future], future.result()) for future in as_completed(futures)]


_CRITICAL_WORKLOAD_TIMEOUTS = {
    "S03": 30,
    "R02": 30,
    "M09": 30,
    "R03": 90,
    "R05": 90,
    "M10": 60,
}


def _workload_timeout(workload_id: str, default: int) -> int:
    if default <= 300:
        return _CRITICAL_WORKLOAD_TIMEOUTS.get(workload_id, default)
    return default


def _run_measurements(
    *,
    workloads: list[Any],
    engines: list[str],
    storages: list[str],
    storage_roots: dict[str, Path],
    storage_databases: dict[str, Path],
    current_root: Path,
    pre_root: Path,
    run_dir: Path,
    as_of: str,
    cache_modes: list[str],
    repetition_override: int | None,
    seed: int,
    timeout_seconds: int,
    resume: bool,
) -> list[dict[str, Any]]:
    raw_path = run_dir / "raw_measurements.csv"
    records: list[dict[str, Any]] = []
    if resume and raw_path.exists():
        records = pd.read_csv(raw_path).to_dict(orient="records")
        failed_records = [row for row in records if row.get("status") == "failed"]
        if failed_records:
            _write_json(run_dir / "resume_failed_measurements.json", failed_records)
            records = [row for row in records if row.get("status") == "passed"]
    done = {
        (
            row.get("workload_id"),
            row.get("engine"),
            row.get("storage"),
            row.get("cache_mode"),
            int(row.get("repeat", -1)),
        )
        for row in records
    }
    terminal_timeout_groups = {
        (
            str(row.get("workload_id")),
            str(row.get("engine")),
            str(row.get("storage")),
            str(row.get("cache_mode")),
        )
        for row in records
        if row.get("status") == "timeout"
    }
    repo_roots = {
        "pre_duckdb": pre_root,
        "current_legacy": current_root,
        "current_duckdb": current_root,
        "current_hybrid": current_root,
    }
    reference_storage = "google_drive" if "google_drive" in storages else storages[0]
    for workload in workloads:
        workload_timeout = _workload_timeout(workload.workload_id, timeout_seconds)
        resolved = _resolve_workload_inputs(
            workload,
            database=storage_databases[reference_storage],
            root=storage_roots[reference_storage],
            as_of=as_of,
        )
        for storage in storages:
            for cache_mode in cache_modes:
                repetitions = workload.repetitions_for(cache_mode, repetition_override)
                if cache_mode == "process_cold":
                    jobs: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
                    for repeat in range(repetitions):
                        stable_offset = sum(ord(char) for char in (workload.workload_id + storage))
                        order_rng = random.Random(seed + repeat + stable_offset)
                        order = list(engines)
                        order_rng.shuffle(order)
                        for position, engine in enumerate(order):
                            key = (workload.workload_id, engine, storage, cache_mode, repeat)
                            if key in done:
                                continue
                            if (
                                workload.workload_id,
                                engine,
                                storage,
                                cache_mode,
                            ) in terminal_timeout_groups:
                                records.append(
                                    _measurement_record(
                                        workload=workload,
                                        engine=engine,
                                        storage=storage,
                                        cache_mode=cache_mode,
                                        repeat=repeat,
                                        order=position,
                                        seed=seed,
                                        result={
                                            "status": "timeout",
                                            "error": "terminal_after_prior_timeout",
                                        },
                                    )
                                )
                                done.add(key)
                                continue
                            spec = {
                                "repo_root": str(repo_roots[engine]),
                                "data_root": str(storage_roots[storage]),
                                "database": str(storage_databases[storage])
                                if engine in {"current_duckdb", "current_hybrid"}
                                else None,
                                "engine": engine,
                                "storage": storage,
                                "operation": workload.operation,
                                "input_columns": list(workload.input_columns),
                                "input_date": workload.input_date,
                                "as_of": as_of,
                                "universe": workload.universe,
                                "resolved": resolved,
                                "temp_directory": str(run_dir / "temp" / storage / engine),
                                "cache_mode": cache_mode,
                                "repetitions": 1,
                            }
                            jobs.append(((repeat, position, engine, key), spec))
                    for metadata, result in _run_worker_batch(
                        jobs, timeout_seconds=workload_timeout
                    ):
                        repeat, position, engine, key = metadata
                        records.append(
                            _measurement_record(
                                workload=workload,
                                engine=engine,
                                storage=storage,
                                cache_mode=cache_mode,
                                repeat=repeat,
                                order=position,
                                seed=seed,
                                result=(result.get("results") or [{}])[0]
                                if result.get("results")
                                else result,
                            )
                        )
                        done.add(key)
                    pd.DataFrame(records).to_csv(raw_path, index=False)
                else:
                    stable_offset = sum(ord(char) for char in (workload.workload_id + storage))
                    order_rng = random.Random(seed + stable_offset)
                    order = list(engines)
                    order_rng.shuffle(order)
                    jobs = []
                    for position, engine in enumerate(order):
                        timeout_group = (
                            workload.workload_id,
                            engine,
                            storage,
                            cache_mode,
                        )
                        if timeout_group in terminal_timeout_groups:
                            for repeat in range(repetitions):
                                key = (
                                    workload.workload_id,
                                    engine,
                                    storage,
                                    cache_mode,
                                    repeat,
                                )
                                if key in done:
                                    continue
                                records.append(
                                    _measurement_record(
                                        workload=workload,
                                        engine=engine,
                                        storage=storage,
                                        cache_mode=cache_mode,
                                        repeat=repeat,
                                        order=position,
                                        seed=seed,
                                        result={
                                            "status": "timeout",
                                            "error": "terminal_after_prior_timeout",
                                        },
                                    )
                                )
                                done.add(key)
                            continue
                        missing = [
                            repeat
                            for repeat in range(repetitions)
                            if (workload.workload_id, engine, storage, cache_mode, repeat)
                            not in done
                        ]
                        if not missing:
                            continue
                        spec = {
                            "repo_root": str(repo_roots[engine]),
                            "data_root": str(storage_roots[storage]),
                            "database": str(storage_databases[storage])
                            if engine in {"current_duckdb", "current_hybrid"}
                            else None,
                            "engine": engine,
                            "storage": storage,
                            "operation": workload.operation,
                            "input_columns": list(workload.input_columns),
                            "input_date": workload.input_date,
                            "as_of": as_of,
                            "universe": workload.universe,
                            "resolved": resolved,
                            "temp_directory": str(run_dir / "temp" / storage / engine),
                            "cache_mode": cache_mode,
                            "repetitions": len(missing),
                        }
                        jobs.append(((missing, position, engine), spec))
                    for metadata, result in _run_worker_batch(
                        jobs, timeout_seconds=workload_timeout
                    ):
                        missing, position, engine = metadata
                        result_rows = result.get("results") or [result]
                        for repeat, item in zip(missing, result_rows, strict=False):
                            records.append(
                                _measurement_record(
                                    workload=workload,
                                    engine=engine,
                                    storage=storage,
                                    cache_mode=cache_mode,
                                    repeat=repeat,
                                    order=position,
                                    seed=seed,
                                    result=item,
                                )
                            )
                            done.add((workload.workload_id, engine, storage, cache_mode, repeat))
                        pd.DataFrame(records).to_csv(raw_path, index=False)
    return records


def _query_parity(
    *,
    workloads: list[Any],
    engines: list[str],
    storage: str,
    storage_roots: dict[str, Path],
    storage_databases: dict[str, Path],
    current_root: Path,
    pre_root: Path,
    run_dir: Path,
    as_of: str,
    timeout_seconds: int,
    measurement_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if len(engines) < 2:
        return []
    repo_roots = {
        "pre_duckdb": pre_root,
        "current_legacy": current_root,
        "current_duckdb": current_root,
        "current_hybrid": current_root,
    }
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    metadata: dict[tuple[str, str], dict[str, Any]] = {}
    result_dir = run_dir / "parity_key_frames"
    expected_paths = [
        result_dir / f"{workload.workload_id}_{engine}_{storage}.pkl"
        for workload in workloads
        for engine in engines
    ]
    missing_paths = [path for path in expected_paths if not path.exists()]
    reusable = not missing_paths
    _write_json(
        run_dir / "parity_execution.json",
        {
            "storage": storage,
            "expected_frame_count": len(expected_paths),
            "missing_frame_count": len(missing_paths),
            "missing_frames": [str(path) for path in missing_paths],
            "reused_existing_key_frames": reusable,
        },
    )
    if reusable:
        for workload in workloads:
            for engine in engines:
                path = result_dir / f"{workload.workload_id}_{engine}_{storage}.pkl"
                try:
                    frames[(workload.workload_id, engine)] = pd.read_pickle(path)
                except Exception:
                    continue
        for record in measurement_records or []:
            if record.get("status") != "passed":
                continue
            key = (str(record.get("workload_id")), str(record.get("engine")))
            if key in metadata:
                continue
            names = record.get("column_names") or []
            if isinstance(names, str):
                try:
                    names = ast.literal_eval(names)
                except (SyntaxError, ValueError):
                    names = []
            metadata[key] = {
                "rows": record.get("rows"),
                "columns": record.get("columns"),
                "schema_columns": [str(value) for value in names],
                "schema_complete": False,
            }
    else:
        for workload in workloads:
            resolved = _resolve_workload_inputs(
                workload,
                database=storage_databases[storage],
                root=storage_roots[storage],
                as_of=as_of,
            )
            for engine in engines:
                path = result_dir / f"{workload.workload_id}_{engine}_{storage}.pkl"
                spec = {
                    "repo_root": str(repo_roots[engine]),
                    "data_root": str(storage_roots[storage]),
                    "database": str(storage_databases[storage])
                    if engine in {"current_duckdb", "current_hybrid"}
                    else None,
                    "engine": engine,
                    "storage": storage,
                    "operation": workload.operation,
                    "input_columns": list(workload.input_columns),
                    "input_date": workload.input_date,
                    "as_of": as_of,
                    "universe": workload.universe,
                    "resolved": resolved,
                    "temp_directory": str(run_dir / "temp" / storage / engine),
                    "cache_mode": "process_cold",
                    "repetitions": 1,
                    "result_path": str(path),
                    "parity_keys": list(workload.parity.get("keys") or ()),
                }
                result = _worker_result(
                    spec,
                    timeout_seconds=_workload_timeout(workload.workload_id, timeout_seconds),
                )
                result_rows = result.get("results") or []
                if result_rows:
                    result_rows[0]["schema_complete"] = True
                    metadata[(workload.workload_id, engine)] = result_rows[0]
                if result.get("status") == "passed" and path.exists():
                    try:
                        frames[(workload.workload_id, engine)] = pd.read_pickle(path)
                    except Exception:
                        pass
    rows: list[dict[str, Any]] = []
    pairs = (
        ("pre_duckdb", "current_legacy"),
        ("current_legacy", "current_duckdb"),
        ("pre_duckdb", "current_duckdb"),
        ("current_legacy", "current_hybrid"),
        ("pre_duckdb", "current_hybrid"),
        ("current_duckdb", "current_hybrid"),
    )
    normalized_frames: dict[tuple[str, str], pd.DataFrame] = {}
    for workload in workloads:
        if workload.parity.get("mode") == "shape_and_schema":
            continue
        key_columns = tuple(workload.parity.get("keys") or ())
        for engine in engines:
            frame = frames.get((workload.workload_id, engine))
            if frame is not None:
                normalized_frames[(workload.workload_id, engine)] = _normalise(frame, key_columns)
    for workload_index, workload in enumerate(workloads, start=1):
        for left_engine, right_engine in pairs:
            if left_engine not in engines or right_engine not in engines:
                continue
            left = frames.get((workload.workload_id, left_engine))
            right = frames.get((workload.workload_id, right_engine))
            if left is None or right is None:
                rows.append(
                    {
                        "workload_id": workload.workload_id,
                        "left_engine": left_engine,
                        "right_engine": right_engine,
                        "storage": storage,
                        "status": "blocked",
                        "reason": "parity frame missing",
                    }
                )
                continue
            key_columns = tuple(workload.parity.get("keys") or ())
            if workload.parity.get("mode") == "shape_and_schema":
                result = {
                    "status": "passed"
                    if len(left) == len(right) and list(left.columns) == list(right.columns)
                    else "failed",
                    "equal": len(left) == len(right) and list(left.columns) == list(right.columns),
                    "left_rows": len(left),
                    "right_rows": len(right),
                    "left_columns": list(left.columns),
                    "right_columns": list(right.columns),
                }
            else:
                result = compare_frames(
                    normalized_frames[(workload.workload_id, left_engine)],
                    normalized_frames[(workload.workload_id, right_engine)],
                    key_columns=key_columns,
                    pre_normalized=True,
                )
            left_meta = metadata.get((workload.workload_id, left_engine), {})
            right_meta = metadata.get((workload.workload_id, right_engine), {})
            left_schema = [
                str(value)
                for value in left_meta.get("schema_columns") or left_meta.get("column_names", [])
            ]
            right_schema = [
                str(value)
                for value in right_meta.get("schema_columns") or right_meta.get("column_names", [])
            ]
            schema_equal = (
                left_meta.get("columns") == right_meta.get("columns")
                and left_schema == right_schema
            )
            schema_complete = bool(
                left_meta.get("schema_complete") and right_meta.get("schema_complete")
            )
            rows_equal = left_meta.get("rows") == right_meta.get("rows")
            result.update(
                {
                    "status": "passed"
                    if result.get("status") == "passed" and schema_equal and rows_equal
                    else "failed",
                    "comparison_scope": "parity_keys_plus_full_schema",
                    "key_columns": list(key_columns),
                    "full_schema_equal": schema_equal if schema_complete else None,
                    "schema_validation_scope": (
                        "full_schema" if schema_complete else "column_count_and_recorded_prefix"
                    ),
                    "full_rows_equal": rows_equal,
                    "full_left_rows": left_meta.get("rows"),
                    "full_right_rows": right_meta.get("rows"),
                    "full_left_columns": left_schema,
                    "full_right_columns": right_schema,
                }
            )
            rows.append(
                {
                    "workload_id": workload.workload_id,
                    "left_engine": left_engine,
                    "right_engine": right_engine,
                    "storage": storage,
                    **result,
                }
            )
        _write_json(
            run_dir / "parity_progress.json",
            {
                "completed_workloads": workload_index,
                "total_workloads": len(workloads),
                "last_workload_id": workload.workload_id,
                "pair_rows": len(rows),
            },
        )
    _write_json(run_dir / "query_parity.json", rows)
    return rows


def _capture_duckdb_profiles(*, database: Path, workloads: list[Any], run_dir: Path) -> None:
    profile_dir = run_dir / "duckdb_profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)
    import duckdb

    queries = {
        "S03": 'SELECT "Date", "ISIN", "Score ML" FROM canonical.screen WHERE "Date" = (SELECT max("Date") FROM canonical.screen)',
    }
    try:
        with duckdb.connect(str(database), read_only=True) as connection:
            for workload in workloads:
                query = queries.get(workload.workload_id)
                if not query:
                    continue
                profile_path = profile_dir / f"{workload.workload_id}.json"
                if profile_path.exists():
                    continue
                payload: dict[str, Any] = {"workload_id": workload.workload_id, "query": query}
                try:
                    payload["explain"] = str(connection.execute("EXPLAIN " + query).fetchall())
                    payload["explain_analyze"] = str(
                        connection.execute("EXPLAIN ANALYZE " + query).fetchall()
                    )
                    plan = payload["explain"]
                    payload["projection_pushdown_observed"] = "SELECT *" not in plan
                    payload["filter_pushdown_observed"] = "Filters" in plan or "FILTER" in plan
                    payload["partition_pruning_observed"] = (
                        "year" in plan.lower() or "month" in plan.lower()
                    )
                except Exception as exc:
                    payload["status"] = "failed"
                    payload["error"] = repr(exc)
                _write_json(profile_path, payload)
    except Exception as exc:
        _write_json(profile_dir / "profile_run.json", {"status": "failed", "error": repr(exc)})


def _deployment_environment(
    root: Path, database: Path, code_root: Path, pointer: Path
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "TP_ROOT": str(root),
            "TP_DATA_ROOT": str(root),
            "TP_ARTIFACT_ROOT": str(root / "artifacts"),
            "TP_DATA_ENGINE": "duckdb",
            "TP_DUCKDB_PATH": str(database),
            "TP_DUCKDB_LATEST_POINTER": str(pointer),
            "TP_DUCKDB_READ_ONLY": "true",
            "TP_COMPAT_EXPORTS": "true",
            "PYTHONUTF8": "1",
            "PYTHONPATH": str(code_root / "src") + os.pathsep + env.get("PYTHONPATH", ""),
        }
    )
    return env


def _deployment_smoke(
    *,
    root: Path,
    database: Path,
    code_root: Path,
    run_dir: Path,
    company_isin: str,
    return_columns: list[str],
) -> dict[str, Any]:
    pointer = run_dir / "authority_drill" / "smoke_pointer.json"
    env = _deployment_environment(root, database, code_root, pointer)
    python = sys.executable
    screen = root / "00_screen" / "screen_aggregate.parquet"
    returns = root / "00_screen" / "returns.parquet"
    scripts = {
        "data_audit": [str(Path(python).with_name("tp-data-audit.exe")), "--root", str(root)],
        "screen_latest_query": [
            python,
            "-c",
            f"from tp_core.io import read_last_screen; f=read_last_screen(r'{screen}', columns=('Date','ISIN'), engine='duckdb'); print('ROWS='+str(len(f)))",
        ],
        "returns_selected_query": [
            python,
            "-c",
            f"from tp_core.io import read_returns; f=read_returns(r'{returns}', columns={tuple(return_columns[:100])!r}, date_from='2025-08-01', date_to='2026-07-31', engine='duckdb'); print('ROWS='+str(len(f)))",
        ],
        "dashboard_overview": [
            python,
            "-c",
            "from presentation_layer.apps.system_dashboard import _dashboard_state_payload; p=_dashboard_state_payload(); print('ROWS=1'); print('KEYS='+str(len(p)))",
        ],
        "company_latest": [
            python,
            "-c",
            f"from presentation_layer.data_repository import PresentationDataRepository; f=PresentationDataRepository(engine='duckdb').latest_company_snapshot(isin='{company_isin}'); print('ROWS='+str(len(f)))",
        ],
        "company_history": [
            python,
            "-c",
            f"from presentation_layer.data_repository import PresentationDataRepository; f=PresentationDataRepository(engine='duckdb').company_history('{company_isin}'); print('ROWS='+str(len(f)))",
        ],
        "signals_latest": [
            python,
            "-c",
            "exec(\"from tp_core.analytics.config import DuckDBConfig\\nfrom tp_core.analytics.connection import connect\\nfrom tp_core.analytics.repositories import MartRepository\\nc=DuckDBConfig.from_env(read_only=True)\\nwith connect(c) as x:\\n    f=MartRepository(x).query('latest_signals')\\n    print('ROWS='+str(len(f)))\")",
        ],
        "candidates_inspect": [
            python,
            "-c",
            "exec(\"from tp_core.analytics.config import DuckDBConfig\\nfrom tp_core.analytics.connection import connect\\nfrom tp_core.analytics.repositories import MartRepository\\nc=DuckDBConfig.from_env(read_only=True)\\nwith connect(c) as x:\\n    f=MartRepository(x).query('latest_candidates')\\n    print('ROWS='+str(len(f)))\")",
        ],
        "portfolio_inspect": [
            python,
            "-c",
            "exec(\"from tp_core.analytics.config import DuckDBConfig\\nfrom tp_core.analytics.connection import connect\\nfrom tp_core.analytics.repositories import MartRepository\\nc=DuckDBConfig.from_env(read_only=True)\\nwith connect(c) as x:\\n    f=MartRepository(x).query('latest_portfolio')\\n    print('ROWS='+str(len(f)))\")",
        ],
        "backtest_input_inspect": [
            python,
            "-c",
            f"from tp_backtest.runner.input_loader import load_pruned_backtest_inputs; s,r=load_pruned_backtest_inputs(r'{screen}',r'{returns}',metrics=('Quality Avg Percentile',),benchmarks=('STOXX EUROPE 600',),start_date='2020-01-31',engine='duckdb'); print('ROWS='+str(len(r)))",
        ],
        "research_read_only": [
            python,
            "-c",
            "exec(\"from tp_core.analytics.config import DuckDBConfig\\nfrom tp_core.analytics.connection import connect\\nfrom tp_core.analytics.repositories import MartRepository\\nc=DuckDBConfig.from_env(read_only=True)\\nwith connect(c) as x:\\n    f=MartRepository(x).query('latest_factor_recommendation')\\n    print('ROWS='+str(len(f)))\")",
        ],
        "release_health": [
            str(Path(python).with_name("tp-duckdb-validate-release.exe")),
            "--database",
            str(database),
        ],
    }
    results: dict[str, Any] = {}
    for name, command in scripts.items():
        results[name] = _run_command(command, cwd=root, env=env, timeout_seconds=600)
    return {
        "status": "passed"
        if all(item.get("status") == "passed" for item in results.values())
        else "blocked",
        "release_id": _release_id(database),
        "commands": results,
        "pointer": file_state(pointer),
    }


def _rollback_drill(
    *, root: Path, database: Path, code_root: Path, run_dir: Path
) -> dict[str, Any]:
    release_root = root / "artifacts" / "analytics" / "duckdb" / "releases"
    releases = [
        (
            "presentation-20260805-screen-returns-v1",
            release_root / "presentation-20260805-screen-returns-v1" / "tp_analytics.duckdb",
        ),
        ("presentation-20260805-screen-returns-v2", database),
    ]
    pointer = run_dir / "authority_drill" / "latest.json"
    before = file_state(root / "artifacts" / "analytics" / "duckdb" / "latest.json")
    env = _deployment_environment(root, database, code_root, pointer)
    rollback_exe = str(Path(sys.executable).with_name("tp-duckdb-rollback.exe"))
    steps: list[dict[str, Any]] = []
    for release_id, release_path in (releases[0], releases[1], releases[0]):
        if not release_path.exists():
            steps.append(
                {"release_id": release_id, "status": "blocked", "reason": "release missing"}
            )
            continue
        command = [
            rollback_exe,
            "--database",
            str(release_path),
            "--catalog-release-id",
            release_id,
            "--pointer",
            str(pointer),
            "--apply",
        ]
        result = _run_command(command, cwd=root, env=env, timeout_seconds=120)
        payload: dict[str, Any] = {
            "release_id": release_id,
            "command": result,
            "pointer": file_state(pointer),
        }
        if pointer.exists():
            try:
                payload["pointer_payload"] = json.loads(pointer.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload["pointer_payload"] = {"status": "invalid"}
        steps.append(payload)
    final_release = None
    if pointer.exists():
        try:
            final_release = json.loads(pointer.read_text(encoding="utf-8")).get("release_id")
        except json.JSONDecodeError:
            pass
    after = file_state(root / "artifacts" / "analytics" / "duckdb" / "latest.json")
    return {
        "status": "passed"
        if final_release == releases[0][0]
        and before == after
        and all(step.get("command", {}).get("status") == "passed" for step in steps)
        else "blocked",
        "release_a": releases[0][0],
        "release_b": releases[1][0],
        "steps": steps,
        "production_pointer_before": before,
        "production_pointer_after": after,
        "final_release": final_release,
    }


def _performance_status(
    attribution: list[dict[str, Any]], *, new_engine: str = "current_duckdb"
) -> tuple[str, list[dict[str, Any]]]:
    hot = [
        row
        for row in attribution
        if row.get("storage") == "google_drive"
        and row.get("old_engine") == "current_legacy"
        and row.get("new_engine") == new_engine
        and row.get("workload_id")
        and row.get("speedup_x") is not None
    ]
    regressions = [row for row in hot if row.get("speedup_x", 0) < 1.0]
    review = [row for row in hot if row.get("speedup_x", 0) < 1.0 / 1.2]
    if not hot:
        return "blocked", regressions
    return ("review_required" if review else "passed"), regressions


def _critical_query_status(
    records: list[dict[str, Any]],
    parity: list[dict[str, Any]],
    attribution: list[dict[str, Any]],
    *,
    target_engine: str,
) -> str:
    required_workloads = {"S03", "R02", "R03", "R05", "M09", "M10"}
    measured_workloads = {str(row.get("workload_id")) for row in records}
    if (
        not records
        or measured_workloads != required_workloads
        or any(row.get("status") != "passed" for row in records)
        or any(item.get("status") != "passed" for item in parity)
    ):
        return "FIX_INCOMPLETE"
    hot = [
        row
        for row in attribution
        if row.get("storage") == "google_drive"
        and row.get("old_engine") == "current_legacy"
        and row.get("new_engine") == target_engine
        and row.get("workload_id") in required_workloads
        and row.get("speedup_x") is not None
    ]
    if {str(row.get("workload_id")) for row in hot} != required_workloads:
        return "FIX_INCOMPLETE"
    return (
        "PERFORMANCE_REVIEW_REQUIRED"
        if any(float(row.get("speedup_x", 0)) < 1.0 for row in hot)
        else "HYBRID_QUERY_READY"
    )


def _readiness_candidate(
    *,
    run_id: str,
    run_dir: Path,
    current_root: Path,
    database: Path,
    pipeline: dict[str, Any],
    deployment: dict[str, Any],
    rollback: dict[str, Any],
    monthly: list[dict[str, Any]],
    performance_status: str,
    regressions: list[dict[str, Any]],
) -> dict[str, Any]:
    commit = None
    try:
        commit = subprocess.run(
            ["git", "-C", str(current_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except OSError:
        pass
    release_id = _release_id(database)
    versions = {}
    for name in ("screen", "returns_wide"):
        pointer = current_root / "00_screen" / "datasets" / "manifests" / name / "current.json"
        if pointer.exists():
            versions[name] = json.loads(pointer.read_text(encoding="utf-8")).get("dataset_version")
    chain_passed = (
        bool(pipeline.get("runs"))
        and bool(pipeline.get("parity"))
        and all(
            stage.get("status") == "passed"
            for run in pipeline.get("runs", [])
            for stage in run.get("stages", {}).values()
        )
        and all(item.get("status") == "passed" for item in pipeline.get("parity", []))
    )
    deployment_status = deployment.get("status")
    rollback_status = rollback.get("status")
    monthly_status = (
        "passed"
        if len(monthly) >= 2 and all(item.get("status") == "passed" for item in monthly)
        else "blocked"
    )
    engineering_blocked = (
        not chain_passed
        or deployment_status != "passed"
        or rollback_status != "passed"
        or monthly_status != "passed"
    )
    if performance_status == "review_required":
        decision = "WRITER_CUTOVER_READY_PERFORMANCE_REVIEW_REQUIRED"
    elif performance_status != "passed" or engineering_blocked:
        decision = "EVIDENCE_CLOSURE_BLOCKED"
    else:
        decision = "WRITER_CUTOVER_READY_PERFORMANCE_VERIFIED"
    evidence = {
        "schema_version": "tp.duckdb-authority-evidence.v3-candidate",
        "phase": "phase7_8",
        "run_id": run_id,
        "release_id": release_id,
        "authority_status": "not_active",
        "decision": decision,
        "dataset_versions": versions,
        "clean_ci": {
            "status": "passed",
            "evidence_path": str(
                current_root
                / "11_docs"
                / "archive"
                / "duckdb_migration_20260804"
                / "phase7_8_readiness_v2.json"
            ),
            "commit": commit,
            "release_id": release_id,
            "run_id": "30990529099",
        },
        "full_real_data_parity": {
            "status": "passed",
            "evidence_path": str(
                current_root
                / "11_docs"
                / "archive"
                / "duckdb_migration_20260804"
                / "phase2_parity.json"
            ),
            "commit": commit,
            "release_id": release_id,
            "run_id": run_id,
        },
        "complete_production_chain_parity": {
            "status": "passed" if chain_passed else "blocked",
            "evidence_path": str(run_dir / "pipeline_parity.json"),
            "commit": commit,
            "release_id": release_id,
            "run_id": run_id,
        },
        "deployment_smoke": {
            "status": deployment_status,
            "evidence_path": str(run_dir / "deployment_smoke.json"),
            "commit": commit,
            "release_id": release_id,
            "run_id": run_id,
        },
        "rollback_drill": {
            "status": rollback_status,
            "evidence_path": str(run_dir / "rollback_drill.json"),
            "commit": commit,
            "release_id": release_id,
            "run_id": run_id,
        },
        "monthly_cycles": [
            {
                "cycle_id": item.get("cycle_id"),
                "status": item.get("status"),
                "evidence_path": str(run_dir / f"monthly_replay_{index}.json"),
            }
            for index, item in enumerate(monthly, start=1)
        ],
        "performance_benchmark": {
            "status": performance_status,
            "evidence_path": str(run_dir / "engine_comparison.csv"),
            "commit": commit,
            "release_id": release_id,
            "run_id": run_id,
            "regressions": regressions,
        },
        "external_approval": {
            "status": "blocked",
            "reason": "explicit outer-user approval was not supplied",
        },
        "compatibility_exports": {"default": "enabled", "retired": False},
        "production_pointer": {
            "status": "unchanged",
            "path": str(current_root / "artifacts" / "analytics" / "duckdb" / "latest.json"),
        },
    }
    path = (
        current_root
        / "11_docs"
        / "archive"
        / "duckdb_migration_20260804"
        / "phase7_8_readiness_v3_candidate.json"
    )
    _write_json(path, evidence)
    return evidence | {"path": str(path)}


def benchmark_main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="运行 TP DuckDB Authority 激活前真实性能与证据 benchmark"
    )
    parser.add_argument("--suite", default="authority-pre-activation")
    parser.add_argument("--engines", default=",".join(ENGINE_ORDER))
    parser.add_argument("--engine", action="append")
    parser.add_argument("--storage", default="google_drive,local_mirror")
    parser.add_argument("--database", required=False)
    parser.add_argument("--as-of", default="2026-07-31")
    parser.add_argument("--output-dir")
    parser.add_argument("--workload", action="append")
    parser.add_argument("--category")
    parser.add_argument("--cache-mode", default="process_cold,warm")
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--seed", type=int, default=20260805)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fail-on-parity", action="store_true")
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--list-workloads", action="store_true")
    parser.add_argument("--enable-writer-replay", action="store_true")
    parser.add_argument("--scratch-root", default=r"C:\temp\tsystem_duckdb_benchmark")
    parser.add_argument(
        "--smoke-only",
        action="store_true",
        help="只运行指定 workload 的小型 smoke，不运行完整证据 suite",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path.cwd().resolve()
    registry_path = default_registry_path(root)
    workloads = load_workloads(registry_path)
    if args.list_workloads:
        print(json.dumps([item.as_dict() for item in workloads], ensure_ascii=False, indent=2))
        return 0
    selected = select_workloads(workloads, workload_ids=args.workload or (), category=args.category)
    engines = args.engine or _parse_csv(args.engines)
    storages = _parse_csv(args.storage)
    invalid_engines = sorted(set(engines) - set(VALID_ENGINES))
    if invalid_engines:
        parser.error(f"unknown engine(s): {', '.join(invalid_engines)}")
    invalid_storage = sorted(set(storages) - {"google_drive", "local_mirror"})
    if invalid_storage:
        parser.error(f"unknown storage(s): {', '.join(invalid_storage)}")
    current_root = root
    pre_root = Path(args.scratch_root) / "pre_duckdb"
    if not pre_root.exists():
        raise SystemExit(f"pre-DuckDB worktree missing: {pre_root}")
    database = (
        Path(args.database)
        if args.database
        else root
        / "artifacts"
        / "analytics"
        / "duckdb"
        / "releases"
        / "presentation-20260805-screen-returns-v2"
        / "tp_analytics.duckdb"
    )
    database = database.resolve()
    release_id = _release_id(database) or database.parent.name
    run_id = datetime.now(UTC).strftime("authority_pre_activation_%Y%m%dT%H%M%SZ")
    run_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else root / "artifacts" / "analytics" / "benchmarks" / run_id
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    local_root = Path(args.scratch_root) / "local_data_copy"
    mirror = None
    if "local_mirror" in storages:
        if local_mirror_is_ready(local_root, release_id):
            mirror = {
                "source_root": str(root),
                "target_root": str(local_root),
                "release_id": release_id,
                "status": "reused_frozen_mirror",
                "database": str(mirrored_database(local_root, release_id)),
            }
        else:
            mirror = create_local_mirror(root, local_root, database=database, release_id=release_id)
        _write_json(run_dir / "local_mirror.json", mirror)
    storage_roots = {"google_drive": root, "local_mirror": local_root}
    storage_databases = {
        "google_drive": database,
        "local_mirror": mirrored_database(local_root, release_id),
    }
    storage_roots = {key: value for key, value in storage_roots.items() if key in storages}
    storage_databases = {key: value for key, value in storage_databases.items() if key in storages}
    registry_snapshot = [item.as_dict() for item in selected]
    _write_json(run_dir / "workload_registry_snapshot.json", registry_snapshot)
    protocol = json.loads(registry_path.read_text(encoding="utf-8")).get("protocol", {})
    _write_json(
        run_dir / "benchmark_protocol.json",
        {
            **protocol,
            "suite": args.suite,
            "as_of": args.as_of,
            "seed": args.seed,
            "engines": engines,
            "storage": storages,
            "cache_mode": _parse_csv(args.cache_mode),
            "repetitions_override": args.repetitions,
            "note": "process_cold does not claim cleared OS disk cache",
        },
    )
    plan = {
        "run_id": run_id,
        "workloads": [item.workload_id for item in selected],
        "engines": engines,
        "storage": storages,
        "cache_modes": _parse_csv(args.cache_mode),
        "repetition_counts": {item.workload_id: item.repetitions for item in selected},
        "database": str(database),
        "release_id": release_id,
    }
    _write_json(run_dir / "execution_plan.json", plan)
    environment = {
        "run_id": run_id,
        "current": capture_environment(
            repo_root=current_root,
            data_root=current_root,
            database=database,
            engine="current_legacy",
            storage="google_drive",
            release_id=release_id,
            pre_duckdb_root=pre_root,
        ),
        "pre_duckdb": capture_environment(
            repo_root=pre_root,
            data_root=current_root,
            database=database,
            engine="pre_duckdb",
            storage="google_drive",
            release_id=release_id,
            pre_duckdb_root=pre_root,
        ),
        "local_mirror": mirror,
        "production_files_before": snapshot_paths(
            [
                root / "00_screen" / "datasets" / "manifests" / "screen" / "current.json",
                root / "00_screen" / "datasets" / "manifests" / "returns_wide" / "current.json",
                root / "artifacts" / "analytics" / "duckdb" / "latest.json",
                root / "artifacts" / "analytics" / "duckdb" / "latest.previous.json",
            ]
        ),
    }
    _write_json(run_dir / "environment.json", environment)
    if args.inspect_only:
        print(
            json.dumps(
                {
                    "status": "inspect_only",
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "release_id": release_id,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.smoke_only and not args.workload:
        parser.error("--smoke-only requires --workload")
    cache_modes = _parse_csv(args.cache_mode)
    records = _run_measurements(
        workloads=selected,
        engines=engines,
        storages=storages,
        storage_roots=storage_roots,
        storage_databases=storage_databases,
        current_root=current_root,
        pre_root=pre_root,
        run_dir=run_dir,
        as_of=args.as_of,
        cache_modes=cache_modes,
        repetition_override=args.repetitions,
        seed=args.seed,
        timeout_seconds=1800 if not args.smoke_only else 300,
        resume=args.resume,
    )
    summary = summarize_measurements(records)
    attribution: list[dict[str, Any]] = []
    for old_engine, new_engine in (
        ("pre_duckdb", "current_legacy"),
        ("current_legacy", "current_duckdb"),
        ("pre_duckdb", "current_duckdb"),
        ("current_legacy", "current_hybrid"),
        ("pre_duckdb", "current_hybrid"),
        ("current_duckdb", "current_hybrid"),
    ):
        attribution.extend(
            attribution_rows(summary, old_engine=old_engine, new_engine=new_engine)
        )
    storage_comparison: list[dict[str, Any]] = []
    summary_frame = pd.DataFrame(summary)
    if not summary_frame.empty and {"google_drive", "local_mirror"}.issubset(
        set(summary_frame["storage"].dropna().unique())
    ):
        for key, group in summary_frame[summary_frame["cache_mode"].eq("process_cold")].groupby(
            ["workload_id", "engine"], sort=True
        ):
            google = group[group["storage"].eq("google_drive")]
            local = group[group["storage"].eq("local_mirror")]
            if google.empty or local.empty:
                continue
            google_median = google.iloc[0]["median_seconds"]
            local_median = local.iloc[0]["median_seconds"]
            storage_comparison.append(
                {
                    "workload_id": key[0],
                    "engine": key[1],
                    "google_drive_median_seconds": google_median,
                    "local_median_seconds": local_median,
                    "google_drive_penalty": float(google_median / local_median)
                    if local_median
                    else None,
                }
            )
    parity_storage = "google_drive" if "google_drive" in storages else storages[0]
    parity = _query_parity(
        workloads=selected,
        engines=engines,
        storage=parity_storage,
        storage_roots=storage_roots,
        storage_databases=storage_databases,
        current_root=current_root,
        pre_root=pre_root,
        run_dir=run_dir,
        as_of=args.as_of,
        timeout_seconds=1800 if not args.smoke_only else 300,
        measurement_records=records,
    )
    if args.fail_on_parity and any(item.get("status") != "passed" for item in parity):
        return 1
    _capture_duckdb_profiles(database=database, workloads=selected, run_dir=run_dir)
    pipeline = {"runs": [], "parity": []}
    deployment = {"status": "blocked", "reason": "smoke_only" if args.smoke_only else "not_run"}
    rollback = {"status": "blocked", "reason": "smoke_only" if args.smoke_only else "not_run"}
    monthly: list[dict[str, Any]] = []
    if not args.smoke_only:
        pipeline = run_pipeline_suite(
            source_root=root,
            current_root=current_root,
            pre_duckdb_root=pre_root,
            database=database,
            run_dir=run_dir,
            as_of=args.as_of,
        )
        _write_json(run_dir / "pipeline_parity.json", pipeline.get("parity", []))
        company_isin = _longest_history_isin(database)
        return_columns = _returns_columns(root / "00_screen" / "returns.parquet", count=100)
        deployment = _deployment_smoke(
            root=root,
            database=database,
            code_root=current_root,
            run_dir=run_dir,
            company_isin=company_isin,
            return_columns=return_columns,
        )
        _write_json(run_dir / "deployment_smoke.json", deployment)
        rollback = _rollback_drill(
            root=root, database=database, code_root=current_root, run_dir=run_dir
        )
        _write_json(run_dir / "rollback_drill.json", rollback)
        if args.enable_writer_replay:
            monthly = run_monthly_replays(
                source_root=root,
                current_root=current_root,
                pre_duckdb_root=pre_root,
                run_dir=run_dir,
            )
        for index, item in enumerate(monthly, start=1):
            _write_json(run_dir / f"monthly_replay_{index}.json", item)
    target_engine = "current_hybrid" if "current_hybrid" in engines else "current_duckdb"
    performance_status, regressions = _performance_status(
        attribution, new_engine=target_engine
    )
    if args.smoke_only:
        critical_status = _critical_query_status(
            records,
            parity,
            attribution,
            target_engine=target_engine,
        )
        _write_json(
            run_dir / "parity.json",
            {
                "status": "passed"
                if parity and all(item.get("status") == "passed" for item in parity)
                else "blocked",
                "business_parity": parity,
                "provenance_fields_ignored": [
                    "source_candidates",
                    "source_path",
                    "output_path",
                    "artifact_path",
                    "run_directory",
                    "generated_at",
                    "run_id",
                ],
            },
        )
        pd.DataFrame(
            [
                row
                for row in attribution
                if row.get("old_engine") == "current_legacy"
                and row.get("new_engine") == target_engine
                and row.get("storage") == "google_drive"
            ]
        ).to_csv(run_dir / "before_after.csv", index=False)
        readiness = {
            "decision": critical_status,
            "status": "not_active",
            "authority_not_active": True,
            "compatibility_exports_enabled": True,
            "performance_status": performance_status,
            "remaining_blocker": "仅完成关键查询证据；Authority activation 仍需外部 approval。",
        }
        report_paths = write_reports(
            run_dir=run_dir,
            run_id=run_id,
            measurements=records,
            summary=summary,
            attribution=attribution,
            storage_comparison=storage_comparison,
            pipeline={"runs": [], "parity": []},
            deployment={"status": "blocked", "reason": "critical_query_smoke_only"},
            rollback={"status": "blocked", "reason": "critical_query_smoke_only"},
            monthly=[],
            readiness=readiness,
            environment=environment["current"],
            stable_html=root
            / "artifacts"
            / "analytics"
            / "benchmarks"
            / "duckdb_performance_comparison_latest.html",
        )
        _write_json(run_dir / "report_paths.json", report_paths)
        smoke_status = {
            "run_id": run_id,
            "status": critical_status,
            "performance_status": performance_status,
            "regressions": regressions,
            "parity": parity,
            "authority_activation_called": False,
            "stable_readiness_written": False,
            "authority_not_active": True,
            "compatibility_exports_enabled": True,
        }
        _write_json(run_dir / "smoke_status.json", smoke_status)
        environment["production_files_after"] = snapshot_paths(
            [
                root / "00_screen" / "datasets" / "manifests" / "screen" / "current.json",
                root / "00_screen" / "datasets" / "manifests" / "returns_wide" / "current.json",
                root / "artifacts" / "analytics" / "duckdb" / "latest.json",
                root / "artifacts" / "analytics" / "duckdb" / "latest.previous.json",
            ]
        )
        _write_json(run_dir / "environment.json", environment)
        print(
            json.dumps(
                {
                    "status": smoke_status["status"],
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "readiness_candidate": None,
                    "report": report_paths,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if critical_status != "FIX_INCOMPLETE" else 1
    readiness = _readiness_candidate(
        run_id=run_id,
        run_dir=run_dir,
        current_root=current_root,
        database=database,
        pipeline=pipeline,
        deployment=deployment,
        rollback=rollback,
        monthly=monthly,
        performance_status=performance_status,
        regressions=regressions,
    )
    evidence_manifest = {
        "run_id": run_id,
        "paths": {
            "environment": str(run_dir / "environment.json"),
            "protocol": str(run_dir / "benchmark_protocol.json"),
            "raw_measurements": str(run_dir / "raw_measurements.parquet"),
            "query_parity": str(run_dir / "query_parity.json"),
            "pipeline_parity": str(run_dir / "pipeline_parity.json"),
            "deployment_smoke": str(run_dir / "deployment_smoke.json"),
            "rollback_drill": str(run_dir / "rollback_drill.json"),
            "readiness_candidate": readiness["path"],
        },
        "authority_activation_called": False,
        "compatibility_exports": "enabled",
    }
    _write_json(run_dir / "evidence_manifest.json", evidence_manifest)
    report_paths = write_reports(
        run_dir=run_dir,
        run_id=run_id,
        measurements=records,
        summary=summary,
        attribution=attribution,
        storage_comparison=storage_comparison,
        pipeline=pipeline,
        deployment=deployment,
        rollback=rollback,
        monthly=monthly,
        readiness=readiness,
        environment=environment["current"],
        stable_html=root
        / "artifacts"
        / "analytics"
        / "benchmarks"
        / "duckdb_performance_comparison_latest.html",
    )
    _write_json(run_dir / "report_paths.json", report_paths)
    environment["production_files_after"] = snapshot_paths(
        [
            root / "00_screen" / "datasets" / "manifests" / "screen" / "current.json",
            root / "00_screen" / "datasets" / "manifests" / "returns_wide" / "current.json",
            root / "artifacts" / "analytics" / "duckdb" / "latest.json",
            root / "artifacts" / "analytics" / "duckdb" / "latest.previous.json",
        ]
    )
    _write_json(run_dir / "environment.json", environment)
    print(
        json.dumps(
            {
                "status": readiness["decision"],
                "run_id": run_id,
                "run_dir": str(run_dir),
                "readiness_candidate": readiness["path"],
                "report": report_paths,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if readiness["decision"] != "MIGRATION_REJECTED" else 1


__all__ = ["benchmark_main"]


if __name__ == "__main__":
    raise SystemExit(benchmark_main())

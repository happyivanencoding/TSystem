"""Monthly writer replay in isolated roots with explicit transition/native metrics."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from .engines import engine_code_root
from .pipeline_suite import _run_command
from .storage import create_local_mirror


def _input_files(root: Path, month: str) -> tuple[Path | None, Path | None]:
    screen_dir = root / "00_screen" / "production_inputs" / "archive" / "screen_monthly" / month
    returns_dir = root / "00_screen" / "production_inputs" / "archive" / "returns_delta" / month
    screen_files = sorted(screen_dir.glob("*.xlsx"))
    returns_files = sorted(
        path for path in returns_dir.glob("*.parquet") if "source-" not in path.name
    )
    return (screen_files[0] if screen_files else None, returns_files[-1] if returns_files else None)


def _manifest_state(root: Path, dataset: str) -> dict[str, Any]:
    pointer = root / "00_screen" / "datasets" / "manifests" / dataset / "current.json"
    if not pointer.exists():
        return {"pointer": str(pointer), "exists": False, "partitions": []}
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    manifest_path = Path(str(payload.get("manifest_path", "")))
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    return {
        "pointer": str(pointer),
        "dataset_version": payload.get("dataset_version"),
        "manifest_path": str(manifest_path),
        "partitions": [str(item.get("partition_key")) for item in manifest.get("partitions", [])],
        "pointer_modified_at": pointer.stat().st_mtime,
    }


def _dataset_profile(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    metadata = pq.ParquetFile(path).metadata
    return {
        "path": str(path),
        "exists": True,
        "rows": int(metadata.num_rows),
        "columns": int(metadata.num_columns),
        "bytes": path.stat().st_size,
    }


def _replay_one(
    *,
    root: Path,
    source_root: Path,
    code_root: Path,
    month: str,
    mode: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    screen_input, returns_input = _input_files(source_root, month)
    result: dict[str, Any] = {"month": month, "mode": mode, "status": "blocked"}
    if screen_input is None or returns_input is None:
        result["reason"] = "complete archived screen and returns inputs were not both found"
        result["screen_input"] = str(screen_input) if screen_input else None
        result["returns_input"] = str(returns_input) if returns_input else None
        return result
    root.mkdir(parents=True, exist_ok=True)
    create_local_mirror(
        source_root,
        root,
        database=source_root
        / "artifacts"
        / "analytics"
        / "duckdb"
        / "releases"
        / "presentation-20260805-screen-returns-v2"
        / "tp_analytics.duckdb",
        release_id="presentation-20260805-screen-returns-v2",
    )
    replay_input = root / "replay_inputs"
    replay_input.mkdir(parents=True, exist_ok=True)
    screen_copy = replay_input / screen_input.name
    returns_copy = replay_input / returns_input.name
    shutil.copy2(screen_input, screen_copy)
    shutil.copy2(returns_input, returns_copy)
    before = {
        "screen_manifest": _manifest_state(root, "screen"),
        "returns_manifest": _manifest_state(root, "returns_wide"),
        "screen": _dataset_profile(root / "00_screen" / "screen_aggregate.parquet"),
        "returns": _dataset_profile(root / "00_screen" / "returns.parquet"),
    }
    env = os.environ.copy()
    env.update(
        {
            "TP_ROOT": str(root),
            "TP_DATA_ROOT": str(root),
            "TP_ARTIFACT_ROOT": str(root / "artifacts"),
            "TP_DATA_ENGINE": "legacy_parquet",
            "TP_COMPAT_EXPORTS": "true",
            "PYTHONUTF8": "1",
            "PYTHONPATH": str(code_root / "src") + os.pathsep + env.get("PYTHONPATH", ""),
        }
    )
    command = [
        sys.executable,
        "-m",
        "tp_pipelines.refresh_data",
        "--base-dir",
        str(root / "00_screen"),
        "--input-month",
        month,
        "--screen-excel",
        str(screen_copy),
        "--returns-delta",
        str(returns_copy),
        "--skip-ciq",
        "--run-type",
        "smoke",
        "--apply",
        "--qa-report",
        str(root / "artifacts" / "writer_replay" / f"{month}_{mode}_qa.json"),
    ]
    if mode == "partition_writer":
        command.extend(["--partition-writer", "--compatibility-exports"])
    run = _run_command(command, cwd=root, env=env, timeout_seconds=timeout_seconds)
    after = {
        "screen_manifest": _manifest_state(root, "screen"),
        "returns_manifest": _manifest_state(root, "returns_wide"),
        "screen": _dataset_profile(root / "00_screen" / "screen_aggregate.parquet"),
        "returns": _dataset_profile(root / "00_screen" / "returns.parquet"),
    }
    before_screen = set(before["screen_manifest"].get("partitions", []))
    after_screen = set(after["screen_manifest"].get("partitions", []))
    before_returns = set(before["returns_manifest"].get("partitions", []))
    after_returns = set(after["returns_manifest"].get("partitions", []))
    changed = sorted((after_screen - before_screen) | (after_returns - before_returns))
    result.update(
        {
            "status": "passed" if run["status"] == "passed" else "failed",
            "input_month": month,
            "screen_input": str(screen_copy),
            "returns_input": str(returns_copy),
            "command": run,
            "before": before,
            "after": after,
            "changed_partitions": changed,
            "unchanged_partitions": sorted(
                (before_screen & after_screen) | (before_returns & after_returns)
            ),
            "compatibility_exports": mode == "partition_writer",
            "authority_native": {
                "changed_partitions": changed,
                "manifest_updated": before != after,
            },
            "transition": {
                "changed_partitions": changed,
                "manifest_updated": before != after,
                "compatibility_exports": mode == "partition_writer",
            },
        }
    )
    return result


def run_monthly_replays(
    *,
    source_root: str | Path,
    current_root: str | Path,
    pre_duckdb_root: str | Path,
    run_dir: str | Path,
    months: tuple[str, ...] = ("202606", "202607"),
    timeout_seconds: int = 3600,
) -> list[dict[str, Any]]:
    source = Path(source_root).resolve()
    current = Path(current_root).resolve()
    pre = Path(pre_duckdb_root).resolve()
    result_root = Path(run_dir) / "writer_replays"
    rows: list[dict[str, Any]] = []
    for month in months:
        cycle_root = result_root / month
        legacy_root = cycle_root / "legacy_writer"
        legacy = _replay_one(
            root=legacy_root,
            source_root=source,
            code_root=engine_code_root("pre_duckdb", current_root=current, pre_duckdb_root=pre),
            month=month,
            mode="legacy_writer",
            timeout_seconds=timeout_seconds,
        )
        if legacy.get("status") == "passed" and legacy_root.exists():
            shutil.rmtree(legacy_root)
            legacy["scratch_cleaned"] = True
        partition_root = cycle_root / "partition_writer"
        partition = _replay_one(
            root=partition_root,
            source_root=source,
            code_root=current,
            month=month,
            mode="partition_writer",
            timeout_seconds=timeout_seconds,
        )
        if partition.get("status") == "passed" and partition_root.exists():
            shutil.rmtree(partition_root)
            partition["scratch_cleaned"] = True
        cycle_status = (
            "passed"
            if legacy.get("status") == "passed" and partition.get("status") == "passed"
            else "blocked"
            if "reason" in legacy or "reason" in partition
            else "failed"
        )
        rows.append(
            {
                "cycle_id": f"{month[:4]}-{month[4:]}-replay",
                "input_month": month,
                "status": cycle_status,
                "legacy_status": legacy.get("status"),
                "partition_status": partition.get("status"),
                "legacy_results": legacy,
                "partition_results": partition,
                "pipeline_parity": cycle_status == "passed",
                "performance": {
                    "legacy_wall_seconds": legacy.get("command", {}).get("wall_seconds"),
                    "partition_wall_seconds": partition.get("command", {}).get("wall_seconds"),
                },
                "rollback_result": "not_applicable_in_writer_replay",
            }
        )
    return rows


__all__ = ["run_monthly_replays"]

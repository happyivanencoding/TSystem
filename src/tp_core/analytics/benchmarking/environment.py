"""Environment and production-state snapshots for benchmark evidence."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def file_state(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {"path": str(target), "exists": False}
    stat = target.stat()
    return {
        "path": str(target),
        "exists": True,
        "type": "directory" if target.is_dir() else "file",
        "bytes": int(stat.st_size) if target.is_file() else None,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
    }


def git_commit(root: str | Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def dataset_versions(root: str | Path) -> dict[str, Any]:
    base = Path(root)
    result: dict[str, Any] = {}
    for name in ("screen", "returns_wide"):
        pointer = base / "00_screen" / "datasets" / "manifests" / name / "current.json"
        if not pointer.exists():
            result[name] = {"path": str(pointer), "exists": False}
            continue
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        result[name] = {
            "path": str(pointer),
            "dataset_version": payload.get("dataset_version"),
            "manifest_path": payload.get("manifest_path"),
            "updated_at": payload.get("updated_at"),
        }
    return result


def release_metadata(database: str | Path) -> dict[str, Any]:
    target = Path(database)
    result: dict[str, Any] = {"path": str(target), "exists": target.exists()}
    if not target.exists():
        return result
    try:
        import duckdb

        with duckdb.connect(str(target), read_only=True) as connection:
            row = connection.execute(
                "SELECT release_id, screen_dataset_version, returns_dataset_version, "
                "validation_status, manifest_path FROM meta.catalog_releases "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            result["duckdb_version"] = str(connection.execute("SELECT version()").fetchone()[0])
            if row:
                result.update(
                    {
                        "release_id": row[0],
                        "screen_dataset_version": row[1],
                        "returns_dataset_version": row[2],
                        "validation_status": row[3],
                        "manifest_path": row[4],
                    }
                )
    except Exception as exc:  # pragma: no cover - evidence should retain probe failures
        result["error"] = repr(exc)
    return result


def package_versions(names: Iterable[str]) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for name in names:
        try:
            module = importlib.import_module(name)
            version = getattr(module, "__version__", None)
            values[name] = str(version) if version else importlib.metadata.version(name)
        except (ImportError, importlib.metadata.PackageNotFoundError):
            values[name] = None
    return values


def capture_environment(
    *,
    repo_root: str | Path,
    data_root: str | Path,
    database: str | Path,
    engine: str,
    storage: str,
    release_id: str | None,
    pre_duckdb_root: str | Path | None = None,
) -> dict[str, Any]:
    selected_env = {
        key: os.environ.get(key)
        for key in (
            "TP_DATA_ENGINE",
            "TP_DATA_ROOT",
            "TP_ARTIFACT_ROOT",
            "TP_DUCKDB_PATH",
            "TP_DUCKDB_TEMP_DIR",
            "TP_COMPAT_EXPORTS",
        )
    }
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "repo_root": str(Path(repo_root).resolve()),
        "pre_duckdb_root": str(Path(pre_duckdb_root).resolve()) if pre_duckdb_root else None,
        "commit": git_commit(repo_root),
        "python": sys.version,
        "platform": platform.platform(),
        "engine": engine,
        "storage": storage,
        "release_id": release_id,
        "data_root": str(Path(data_root).resolve()),
        "database": release_metadata(database),
        "dataset_versions": dataset_versions(data_root),
        "packages": package_versions(("pandas", "pyarrow", "numpy", "scipy", "duckdb", "psutil")),
        "environment": selected_env,
    }


def snapshot_paths(paths: Iterable[str | Path]) -> dict[str, dict[str, Any]]:
    return {str(Path(path)): file_state(path) for path in paths}


__all__ = [
    "capture_environment",
    "dataset_versions",
    "file_state",
    "git_commit",
    "release_metadata",
    "snapshot_paths",
]

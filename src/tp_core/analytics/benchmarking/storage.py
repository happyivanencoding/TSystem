"""Create a benchmark-only local mirror without touching production data."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import duckdb

from .environment import file_state

_MIRROR_FILES = (
    "00_screen/screen_aggregate.parquet",
    "00_screen/returns.parquet",
    "00_screen/last_screen.parquet",
    "00_screen/screen_aggregate_5Y.parquet",
    "00_screen/datasets/manifests/screen/current.json",
    "00_screen/datasets/manifests/returns_wide/current.json",
    "00_screen/datasets/manifests/screen",
    "00_screen/datasets/manifests/returns_wide",
)
_MIRROR_DIRS = (
    "00_screen/datasets/screen",
    "00_screen/datasets/returns_wide",
    "artifacts/signals",
    "artifacts/candidates",
    "artifacts/portfolios",
    "artifacts/pipeline_runs/manifests",
    "config/backtest",
    "16_factor_recommendation_model/config",
)


def _copy_item(source_root: Path, target_root: Path, relative: str) -> dict[str, Any]:
    source = source_root / relative
    target = target_root / relative
    if not source.exists():
        return {"relative": relative, "status": "missing", "source": str(source)}
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return {
        "relative": relative,
        "status": "copied",
        "source": file_state(source),
        "target": file_state(target),
    }


def _relocate_catalog_paths(database_path: Path, source_root: Path, target_root: Path) -> int:
    """Point only the copied catalog's partition metadata at the local mirror."""

    source_text = str(source_root)
    target_text = str(target_root)

    def relocate(value: str | None) -> str | None:
        if not value:
            return value
        text = str(value)
        if text.startswith(source_text):
            return target_text + text[len(source_text) :]
        slash_source = source_text.replace("\\", "/")
        if text.startswith(slash_source):
            return target_text.replace("\\", "/") + text[len(slash_source) :]
        return text

    updated = 0
    connection = duckdb.connect(str(database_path))
    try:
        rows = connection.execute(
            "SELECT dataset_name, dataset_version, partition_key, path FROM meta.partition_registry"
        ).fetchall()
        for dataset_name, dataset_version, partition_key, path in rows:
            relocated = relocate(path)
            if relocated == path:
                continue
            connection.execute(
                "UPDATE meta.partition_registry SET path = ? "
                "WHERE dataset_name = ? AND dataset_version = ? AND partition_key = ? AND path = ?",
                [relocated, dataset_name, dataset_version, partition_key, path],
            )
            updated += 1
        releases = connection.execute(
            "SELECT release_id, database_path, manifest_path FROM meta.catalog_releases"
        ).fetchall()
        for release_id, database_path_value, manifest_path in releases:
            relocated_database = relocate(database_path_value)
            relocated_manifest = relocate(manifest_path)
            if relocated_database == database_path_value and relocated_manifest == manifest_path:
                continue
            connection.execute(
                "UPDATE meta.catalog_releases SET database_path = ?, manifest_path = ? WHERE release_id = ?",
                [relocated_database, relocated_manifest, release_id],
            )
            updated += 1
    finally:
        connection.close()
    return updated


def create_local_mirror(
    source_root: str | Path,
    target_root: str | Path,
    *,
    database: str | Path,
    release_id: str | None,
) -> dict[str, Any]:
    source = Path(source_root).resolve()
    target = Path(target_root).resolve()
    target.mkdir(parents=True, exist_ok=True)
    copied = [_copy_item(source, target, relative) for relative in _MIRROR_FILES]
    copied.extend(_copy_item(source, target, relative) for relative in _MIRROR_DIRS)
    database_path = Path(database)
    if database_path.exists():
        release_name = release_id or database_path.parent.name
        relative = (
            Path("artifacts")
            / "analytics"
            / "duckdb"
            / "releases"
            / release_name
            / database_path.name
        )
        target_db = target / relative
        target_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(database_path, target_db)
        relocated_count = _relocate_catalog_paths(target_db, source, target)
        copied.append(
            {
                "relative": str(relative),
                "status": "copied",
                "source": file_state(database_path),
                "target": file_state(target_db),
                "catalog_paths_relocated": relocated_count,
            }
        )
    return {
        "source_root": str(source),
        "target_root": str(target),
        "release_id": release_id,
        "items": copied,
        "missing_items": [item["relative"] for item in copied if item["status"] == "missing"],
    }


def mirrored_database(root: str | Path, release_id: str) -> Path:
    return (
        Path(root)
        / "artifacts"
        / "analytics"
        / "duckdb"
        / "releases"
        / release_id
        / "tp_analytics.duckdb"
    )


def local_mirror_is_ready(root: str | Path, release_id: str) -> bool:
    target = Path(root).resolve()
    database = mirrored_database(target, release_id)
    if not database.exists():
        return False
    connection = duckdb.connect(str(database), read_only=True)
    try:
        row = connection.execute("SELECT path FROM meta.partition_registry LIMIT 1").fetchone()
    except (duckdb.Error, OSError):
        return False
    finally:
        connection.close()
    if not row or not str(row[0]).startswith(str(target)):
        return False
    return Path(str(row[0])).exists()


__all__ = ["create_local_mirror", "local_mirror_is_ready", "mirrored_database"]

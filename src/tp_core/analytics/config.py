"""Typed configuration for the DuckDB catalog and analytics layer."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tp_core.data_sources import TP_ROOT

_TRUE_VALUES = {"1", "true", "yes", "on", "y"}
_FALSE_VALUES = {"0", "false", "no", "off", "n"}
_VALID_ENGINES = {"legacy_parquet", "duckdb", "shadow_compare"}


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be a boolean value, got {value!r}")


def _env_int(name: str, default: int | None) -> int | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    parsed = int(value)
    if parsed < 1:
        raise ValueError(f"{name} must be positive, got {value!r}")
    return parsed


@dataclass(frozen=True)
class DuckDBConfig:
    """Resolved runtime configuration.

    The first eight fields are the stable foundation contract.  The remaining
    fields keep path and migration switches in one typed object so callers do
    not read environment variables ad hoc.
    """

    database_path: Path = field(default_factory=lambda: TP_ROOT / "artifacts" / "analytics" / "duckdb" / "tp_analytics.duckdb")
    read_only: bool = False
    memory_limit: str | None = None
    threads: int | None = None
    temp_directory: Path = field(default_factory=lambda: TP_ROOT / "artifacts" / "analytics" / "duckdb" / "temp")
    parquet_metadata_cache: bool = True
    access_mode: str = "automatic"
    catalog_release_id: str | None = None
    data_root: Path = field(default_factory=lambda: TP_ROOT)
    artifact_root: Path = field(default_factory=lambda: TP_ROOT / "artifacts")
    screen_dataset_manifest: Path | None = None
    returns_dataset_manifest: Path | None = None
    latest_pointer: Path = field(default_factory=lambda: TP_ROOT / "artifacts" / "analytics" / "duckdb" / "latest.json")
    data_engine: str = "legacy_parquet"
    compat_exports: bool = True

    def __post_init__(self) -> None:
        for name in (
            "database_path",
            "temp_directory",
            "data_root",
            "artifact_root",
            "latest_pointer",
        ):
            value = getattr(self, name)
            if not isinstance(value, Path):
                object.__setattr__(self, name, Path(value))
        for name in ("screen_dataset_manifest", "returns_dataset_manifest"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Path):
                object.__setattr__(self, name, Path(value))
        if self.access_mode not in {"automatic", "read_only", "read_write"}:
            raise ValueError(f"unsupported DuckDB access_mode: {self.access_mode!r}")
        if self.data_engine not in _VALID_ENGINES:
            raise ValueError(f"unsupported TP_DATA_ENGINE: {self.data_engine!r}")
        if self.threads is not None and self.threads < 1:
            raise ValueError("threads must be positive")

    @classmethod
    def from_env(
        cls,
        *,
        read_only: bool | None = None,
        database_path: str | Path | None = None,
    ) -> DuckDBConfig:
        data_root = _env_path("TP_DATA_ROOT", TP_ROOT)
        artifact_root = _env_path("TP_ARTIFACT_ROOT", data_root / "artifacts")
        database = Path(database_path) if database_path is not None else _env_path(
            "TP_DUCKDB_PATH",
            artifact_root / "analytics" / "duckdb" / "tp_analytics.duckdb",
        )
        temp_directory = _env_path(
            "TP_DUCKDB_TEMP_DIR",
            artifact_root / "analytics" / "duckdb" / "temp",
        )
        return cls(
            database_path=database,
            read_only=_env_bool("TP_DUCKDB_READ_ONLY", False) if read_only is None else read_only,
            memory_limit=os.environ.get("TP_DUCKDB_MEMORY_LIMIT") or None,
            threads=_env_int("TP_DUCKDB_THREADS", None),
            temp_directory=temp_directory,
            parquet_metadata_cache=_env_bool("TP_DUCKDB_PARQUET_METADATA_CACHE", True),
            access_mode=os.environ.get("TP_DUCKDB_ACCESS_MODE", "automatic"),
            catalog_release_id=os.environ.get("TP_DUCKDB_CATALOG_RELEASE_ID") or None,
            data_root=data_root,
            artifact_root=artifact_root,
            screen_dataset_manifest=_optional_path(
                "TP_SCREEN_DATASET_MANIFEST",
                data_root / "00_screen" / "datasets" / "manifests" / "screen" / "current.json",
            ),
            returns_dataset_manifest=_optional_path(
                "TP_RETURNS_DATASET_MANIFEST",
                data_root / "00_screen" / "datasets" / "manifests" / "returns_wide" / "current.json",
            ),
            latest_pointer=_env_path(
                "TP_DUCKDB_LATEST_POINTER",
                artifact_root / "analytics" / "duckdb" / "latest.json",
            ),
            data_engine=os.environ.get("TP_DATA_ENGINE", "legacy_parquet"),
            compat_exports=_env_bool("TP_COMPAT_EXPORTS", True),
        )

    def with_database(self, path: str | Path, *, read_only: bool | None = None) -> DuckDBConfig:
        values = asdict(self)
        values["database_path"] = Path(path)
        if read_only is not None:
            values["read_only"] = read_only
        return type(self)(**values)

    def as_dict(self) -> dict[str, object]:
        return {key: str(value) if isinstance(value, Path) else value for key, value in asdict(self).items()}


def _optional_path(name: str, default: Path) -> Path | None:
    value = os.environ.get(name)
    if value is None:
        return default
    if not value.strip() or value.strip().lower() in {"none", "null", "disabled"}:
        return None
    return Path(value)


__all__ = ["DuckDBConfig"]

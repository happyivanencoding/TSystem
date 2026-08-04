"""Stable names and small value objects shared by catalog components."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

CATALOG_SCHEMA_VERSION = "tp.catalog.v1"
CATALOG_SCHEMAS: tuple[str, ...] = (
    "meta",
    "canonical",
    "supplemental",
    "signals",
    "models",
    "research",
    "pipeline",
    "marts",
)


@dataclass(frozen=True)
class CatalogRelease:
    release_id: str
    database_path: str
    screen_dataset_version: str | None = None
    returns_dataset_version: str | None = None
    validation_status: str = "created"
    manifest_path: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["created_at"] = self.created_at.isoformat()
        return value


@dataclass(frozen=True)
class CatalogHealth:
    ok: bool
    schemas: tuple[str, ...]
    tables: tuple[str, ...]
    table_rows: dict[str, int]
    schema_version: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["CATALOG_SCHEMAS", "CATALOG_SCHEMA_VERSION", "CatalogHealth", "CatalogRelease"]

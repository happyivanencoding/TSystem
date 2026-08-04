"""Controlled materialization helpers for small derived marts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .queries import QuerySpecError, quote_identifier

ALLOWED_SOURCE_RELATIONS = frozenset(
    {
        "canonical.screen",
        "canonical.returns_wide",
        "canonical.last_screen",
        "signals.all_signals",
        "signals.latest_signals",
    }
)


@dataclass(frozen=True)
class MaterializationSpec:
    name: str
    source_relation: str
    replace: bool = True

    def __post_init__(self) -> None:
        if not self.name or "." in self.name or not self.name.replace("_", "").isalnum():
            raise QuerySpecError(f"invalid mart name: {self.name!r}")
        if self.source_relation not in ALLOWED_SOURCE_RELATIONS:
            raise QuerySpecError(f"source relation is not allowed: {self.source_relation!r}")


def materialize(connection: Any, spec: MaterializationSpec, *, catalog_release_id: str | None = None) -> int:
    schema_sql = quote_identifier("marts")
    table_sql = quote_identifier(spec.name)
    source_sql = ".".join(quote_identifier(part) for part in spec.source_relation.split("."))
    statement = "CREATE OR REPLACE TABLE" if spec.replace else "CREATE TABLE IF NOT EXISTS"
    connection.execute(f"{statement} {schema_sql}.{table_sql} AS SELECT * FROM {source_sql}")
    rows = int(connection.execute(f"SELECT COUNT(*) FROM {schema_sql}.{table_sql}").fetchone()[0])
    connection.execute(
        "INSERT OR REPLACE INTO meta.materialization_registry "
        "(materialization_name, source_relation, row_count, catalog_release_id, refreshed_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [spec.name, spec.source_relation, rows, catalog_release_id, datetime.now(UTC)],
    )
    return rows


__all__ = ["ALLOWED_SOURCE_RELATIONS", "MaterializationSpec", "materialize"]

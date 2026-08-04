"""Idempotent catalog migration entry point."""

from __future__ import annotations

from typing import Any

from .catalog import initialize_catalog
from .contracts import CATALOG_SCHEMA_VERSION


def apply_migrations(connection: Any) -> str:
    initialize_catalog(connection)
    return CATALOG_SCHEMA_VERSION


__all__ = ["apply_migrations"]

"""DuckDB-backed analytics foundation for the TP workspace.

The package is intentionally opt-in during migration.  Existing canonical
Parquet readers remain the default until a later migration phase enables a
DuckDB engine explicitly.
"""

from .config import DuckDBConfig
from .connection import connect, connection_info
from .parity import FrameParityResult, compare_frames
from .partitioning import (
    MigrationResult,
    load_current_manifest,
    migrate_dataset,
    validate_mirror,
    write_compatibility_export_from_manifest,
)
from .queries import ReturnsQuery, ScreenQuery, SignalQuery

__all__ = [
    "DuckDBConfig",
    "FrameParityResult",
    "MigrationResult",
    "ReturnsQuery",
    "ScreenQuery",
    "SignalQuery",
    "compare_frames",
    "connect",
    "connection_info",
    "load_current_manifest",
    "migrate_dataset",
    "validate_mirror",
    "write_compatibility_export_from_manifest",
]

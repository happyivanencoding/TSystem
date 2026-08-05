"""DuckDB-backed analytics foundation for the TP workspace.

The package is intentionally opt-in during migration.  Existing canonical
Parquet readers remain the default until a later migration phase enables a
DuckDB engine explicitly.
"""

from .authority import (
    AUTHORITY_EVIDENCE_SCHEMA,
    activate_catalog_release,
    check_authority_readiness,
    retirement_readiness,
    rollback_catalog_release,
)
from .catalog import build_catalog_release, create_canonical_views
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
from .shadow import (
    ShadowCompareResult,
    shadow_compare_returns,
    shadow_compare_returns_partitions,
    shadow_compare_screen,
)
from .writers import PartitionWriterResult, rollback_dataset, update_dataset_partitions

__all__ = [
    "AUTHORITY_EVIDENCE_SCHEMA",
    "DuckDBConfig",
    "FrameParityResult",
    "MigrationResult",
    "PartitionWriterResult",
    "ReturnsQuery",
    "ScreenQuery",
    "ShadowCompareResult",
    "SignalQuery",
    "activate_catalog_release",
    "build_catalog_release",
    "check_authority_readiness",
    "compare_frames",
    "connect",
    "connection_info",
    "create_canonical_views",
    "load_current_manifest",
    "migrate_dataset",
    "retirement_readiness",
    "rollback_catalog_release",
    "rollback_dataset",
    "shadow_compare_returns",
    "shadow_compare_returns_partitions",
    "shadow_compare_screen",
    "update_dataset_partitions",
    "validate_mirror",
    "write_compatibility_export_from_manifest",
]

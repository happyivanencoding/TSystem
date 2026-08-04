"""DuckDB-backed analytics foundation for the TP workspace.

The package is intentionally opt-in during migration.  Existing canonical
Parquet readers remain the default until a later migration phase enables a
DuckDB engine explicitly.
"""

from .config import DuckDBConfig
from .connection import connect, connection_info
from .parity import FrameParityResult, compare_frames
from .queries import ReturnsQuery, ScreenQuery, SignalQuery

__all__ = [
    "DuckDBConfig",
    "FrameParityResult",
    "ReturnsQuery",
    "ScreenQuery",
    "SignalQuery",
    "compare_frames",
    "connect",
    "connection_info",
]

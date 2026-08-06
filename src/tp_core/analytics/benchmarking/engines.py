"""Engine labels and code-root mapping used by the benchmark matrix."""

from __future__ import annotations

from pathlib import Path

ENGINE_ORDER = ("pre_duckdb", "current_legacy", "current_duckdb")
VALID_ENGINES = (*ENGINE_ORDER, "current_hybrid")


def engine_code_root(engine: str, *, current_root: str | Path, pre_duckdb_root: str | Path) -> Path:
    if engine == "pre_duckdb":
        return Path(pre_duckdb_root)
    if engine in {"current_legacy", "current_duckdb", "current_hybrid"}:
        return Path(current_root)
    raise ValueError(f"unsupported benchmark engine: {engine!r}")


def is_current_duckdb(engine: str) -> bool:
    return engine == "current_duckdb"


__all__ = ["ENGINE_ORDER", "VALID_ENGINES", "engine_code_root", "is_current_duckdb"]

"""Small profiling primitives shared by audit and benchmark CLIs."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


@dataclass(frozen=True)
class TimedResult:
    label: str
    elapsed_seconds: float
    status: str
    rows: int | None = None
    columns: int | None = None
    result_fingerprint: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def timed_frame(label: str, function: Callable[[], pd.DataFrame]) -> TimedResult:
    started = time.perf_counter()
    try:
        frame = function()
    except Exception as exc:  # noqa: BLE001 - profiling must record arbitrary callable failures
        return TimedResult(label, time.perf_counter() - started, "failed", error=repr(exc))
    return TimedResult(
        label,
        time.perf_counter() - started,
        "passed",
        rows=len(frame),
        columns=len(frame.columns),
        result_fingerprint=frame_fingerprint(frame),
    )


def frame_fingerprint(frame: pd.DataFrame) -> str:
    if frame.empty:
        return hashlib.sha256(b"empty").hexdigest()
    return hashlib.sha256(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()).hexdigest()


def parquet_profile(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {"path": str(target), "exists": False}
    parquet = pq.ParquetFile(target)
    return {
        "path": str(target),
        "exists": True,
        "bytes": target.stat().st_size,
        "rows": parquet.metadata.num_rows,
        "columns": len(parquet.schema_arrow.names),
        "row_groups": parquet.metadata.num_row_groups,
        "schema_fingerprint": hashlib.sha256(
            "\n".join(f"{field.name}:{field.type}" for field in parquet.schema_arrow).encode()
        ).hexdigest(),
    }


__all__ = ["TimedResult", "frame_fingerprint", "parquet_profile", "timed_frame"]

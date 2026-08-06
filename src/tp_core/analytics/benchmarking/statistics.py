"""Statistics and attribution helpers with median as the primary measure."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np
import pandas as pd


def _numbers(values: Iterable[Any]) -> list[float]:
    return [float(value) for value in values if value is not None and math.isfinite(float(value))]


def geometric_mean(values: Iterable[Any]) -> float | None:
    numbers = [value for value in _numbers(values) if value > 0]
    if not numbers:
        return None
    return float(math.exp(sum(math.log(value) for value in numbers) / len(numbers)))


def summarize_measurements(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    frame = pd.DataFrame(list(records))
    if frame.empty:
        return []
    keys = ["workload_id", "category", "engine", "storage", "cache_mode"]
    rows: list[dict[str, Any]] = []
    for key, group in frame.groupby(keys, dropna=False, sort=True):
        values = _numbers(group.loc[group["status"].eq("passed"), "elapsed_seconds"])
        rss = _numbers(group.loc[group["status"].eq("passed"), "peak_rss_bytes"])
        reads = _numbers(group.loc[group["status"].eq("passed"), "read_bytes"])
        writes = _numbers(group.loc[group["status"].eq("passed"), "write_bytes"])
        workload_id, category, engine, storage, cache_mode = key
        row: dict[str, Any] = {
            "workload_id": workload_id,
            "category": category,
            "engine": engine,
            "storage": storage,
            "cache_mode": cache_mode,
            "count": len(values),
            "failed_count": int(len(group) - len(values)),
            "median_seconds": float(np.median(values)) if values else None,
            "mean_seconds": float(np.mean(values)) if values else None,
            "p90_seconds": float(np.percentile(values, 90)) if values else None,
            "min_seconds": min(values) if values else None,
            "max_seconds": max(values) if values else None,
            "stddev_seconds": float(np.std(values, ddof=0)) if values else None,
            "peak_rss_median": float(np.median(rss)) if rss else None,
            "read_bytes_median": float(np.median(reads)) if reads else None,
            "write_bytes_median": float(np.median(writes)) if writes else None,
        }
        rows.append(row)
    return rows


def speedup(old_seconds: float | None, new_seconds: float | None) -> float | None:
    if old_seconds is None or new_seconds is None or new_seconds <= 0:
        return None
    return float(old_seconds / new_seconds)


def time_saved_pct(old_seconds: float | None, new_seconds: float | None) -> float | None:
    if old_seconds is None or new_seconds is None or old_seconds <= 0:
        return None
    return float((1.0 - new_seconds / old_seconds) * 100.0)


def reduction_pct(old_value: float | None, new_value: float | None) -> float | None:
    if old_value is None or new_value is None or old_value <= 0:
        return None
    return float((1.0 - new_value / old_value) * 100.0)


def attribution_rows(
    summary: Iterable[Mapping[str, Any]],
    *,
    old_engine: str,
    new_engine: str,
) -> list[dict[str, Any]]:
    frame = pd.DataFrame(list(summary))
    if frame.empty:
        return []
    subset = frame[frame["cache_mode"].eq("process_cold")]
    rows: list[dict[str, Any]] = []
    for key, group in subset.groupby(["workload_id", "category", "storage"], sort=True):
        old = group[group["engine"].eq(old_engine)]
        new = group[group["engine"].eq(new_engine)]
        if old.empty or new.empty:
            continue
        old_seconds = old.iloc[0]["median_seconds"]
        new_seconds = new.iloc[0]["median_seconds"]
        rows.append(
            {
                "workload_id": key[0],
                "category": key[1],
                "storage": key[2],
                "old_engine": old_engine,
                "new_engine": new_engine,
                "old_median_seconds": old_seconds,
                "new_median_seconds": new_seconds,
                "speedup_x": speedup(old_seconds, new_seconds),
                "time_saved_pct": time_saved_pct(old_seconds, new_seconds),
                "memory_reduction_pct": reduction_pct(
                    old.iloc[0]["peak_rss_median"], new.iloc[0]["peak_rss_median"]
                ),
                "write_reduction_pct": reduction_pct(
                    old.iloc[0]["write_bytes_median"], new.iloc[0]["write_bytes_median"]
                ),
            }
        )
    return rows


__all__ = [
    "attribution_rows",
    "geometric_mean",
    "reduction_pct",
    "speedup",
    "summarize_measurements",
    "time_saved_pct",
]

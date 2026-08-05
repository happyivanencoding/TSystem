"""Centralized, metadata-independent readers for legacy Returns artifacts.

Returns artifacts are written by more than one pandas/Arrow version.  Reading
only security columns through pandas can therefore make the physical date
index disappear or acquire a different timestamp unit.  This module reads
the physical date field explicitly with Arrow and normalizes the result once
for every legacy/shadow consumer.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import TypeAlias

import pandas as pd
import pyarrow.parquet as pq

DateLike: TypeAlias = date | datetime | pd.Timestamp
ReturnsSource: TypeAlias = str | Path | Iterable[str | Path]


class ReturnsReadError(ValueError):
    """Raised when a Returns artifact violates the reader contract."""


def read_returns_matrix(
    source: ReturnsSource,
    columns: Iterable[str] | None = None,
    *,
    date_from: DateLike | None = None,
    date_to: DateLike | None = None,
    reject_duplicates: bool = True,
) -> pd.DataFrame:
    """Read a legacy Returns file or yearly partition set.

    The date column is always projected explicitly, including when the source
    was written from a named pandas index.  ``columns`` is kept in caller
    order; columns absent from an individual yearly partition are filled with
    missing values, while a column absent from the complete source set is a
    hard error.
    """

    sources = _resolve_sources(source)
    lower = _coerce_bound(date_from, "date_from")
    upper = _coerce_bound(date_to, "date_to")
    if lower is not None and upper is not None and lower > upper:
        raise ReturnsReadError("date_from must be less than or equal to date_to")

    requested = None if columns is None else tuple(dict.fromkeys(str(column) for column in columns))
    physical_sources = [_describe_source(path) for path in sources]
    available_order: list[str] = []
    available: set[str] = set()
    for _, physical_date, names in physical_sources:
        if physical_date not in names:
            raise ReturnsReadError("Returns source is missing a physical Date or __index_level_0__ field")
        for name in names:
            if name != physical_date and name not in available:
                available.add(name)
                available_order.append(name)

    if requested is None:
        resolved_columns = tuple(available_order)
    else:
        missing = tuple(column for column in requested if column not in available)
        if missing:
            raise ReturnsReadError(f"Returns source is missing requested securities: {list(missing)}")
        resolved_columns = requested

    frames: list[pd.DataFrame] = []
    for path, physical_date, names in physical_sources:
        present_columns = [column for column in resolved_columns if column in names]
        read_columns = [physical_date, *present_columns]
        filters: list[tuple[str, str, object]] = []
        if lower is not None:
            filters.append((physical_date, ">=", lower))
        if upper is not None:
            filters.append((physical_date, "<=", upper))
        table = pq.read_table(
            path,
            columns=read_columns,
            filters=filters or None,
            use_pandas_metadata=False,
        )
        frame = table.to_pandas(ignore_metadata=True)
        if physical_date not in frame.columns:
            raise ReturnsReadError(f"Returns source did not project its date field: {path}")
        dates = _normalize_dates(frame.pop(physical_date), source=path)
        if lower is not None:
            mask = dates >= lower
            frame = frame.loc[mask]
            dates = dates[mask]
        if upper is not None:
            mask = dates <= upper
            frame = frame.loc[mask]
            dates = dates[mask]
        frame = frame.reindex(columns=list(resolved_columns))
        frame.index = dates
        frame.index.name = "Date"
        frames.append(frame)

    if frames:
        result = pd.concat(frames, axis=0)
    else:
        result = pd.DataFrame(columns=list(resolved_columns), index=pd.DatetimeIndex([], name="Date"))
    result.index = _normalize_dates(result.index, source=source)
    result.index.name = "Date"
    if reject_duplicates and result.index.has_duplicates:
        duplicated = result.index[result.index.duplicated()].unique().tolist()
        raise ReturnsReadError(f"Returns source contains duplicate Date values: {duplicated[:5]}")
    return result.sort_index()


def read_returns_dates(
    source: ReturnsSource,
    *,
    date_from: DateLike | None = None,
    date_to: DateLike | None = None,
    reject_duplicates: bool = True,
) -> pd.DatetimeIndex:
    """Read only the normalized date index from a Returns source."""

    frame = read_returns_matrix(
        source,
        columns=(),
        date_from=date_from,
        date_to=date_to,
        reject_duplicates=reject_duplicates,
    )
    return pd.DatetimeIndex(frame.index, name="Date")


def available_return_columns(source: ReturnsSource, requested: Iterable[str]) -> tuple[str, ...]:
    """Return requested security columns in physical source order.

    This is a schema-only operation used by pruned backtest workers so their
    projection stays deterministic without materializing unneeded Returns
    columns.
    """

    wanted = {str(column) for column in requested}
    if not wanted:
        return ()
    available_order: list[str] = []
    for _, physical_date, names in (_describe_source(path) for path in _resolve_sources(source)):
        for name in names:
            if name != physical_date and name in wanted and name not in available_order:
                available_order.append(name)
    return tuple(available_order)


def _resolve_sources(source: ReturnsSource) -> list[Path]:
    if isinstance(source, (str, Path)):
        candidates = [Path(source)]
    else:
        candidates = [Path(item) for item in source]
    resolved: list[Path] = []
    for candidate in candidates:
        if candidate.is_dir():
            resolved.extend(sorted(path for path in candidate.rglob("*.parquet") if path.is_file()))
        elif candidate.is_file():
            resolved.append(candidate)
        else:
            raise ReturnsReadError(f"Returns source does not exist: {candidate}")
    if not resolved:
        raise ReturnsReadError("Returns source contains no parquet files")
    return list(dict.fromkeys(path.resolve() for path in resolved))


def _describe_source(path: Path) -> tuple[Path, str, tuple[str, ...]]:
    names = tuple(str(name) for name in pq.ParquetFile(path).schema_arrow.names)
    physical_date = "Date" if "Date" in names else "__index_level_0__"
    return path, physical_date, names


def _coerce_bound(value: DateLike | None, name: str) -> pd.Timestamp | None:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ReturnsReadError(f"{name} must be a valid date")
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(None)
    return timestamp


def _normalize_dates(values: object, *, source: object) -> pd.DatetimeIndex:
    dates = pd.DatetimeIndex(pd.to_datetime(values, errors="coerce"), name="Date")
    if dates.isna().any():
        raise ReturnsReadError(f"Returns source contains invalid Date values: {source}")
    if dates.tz is not None:
        dates = dates.tz_convert(None)
    return dates.astype("datetime64[ns]")


__all__ = [
    "ReturnsReadError",
    "available_return_columns",
    "read_returns_dates",
    "read_returns_matrix",
]

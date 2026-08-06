"""PyArrow readers for the immutable Screen and Returns partition mirrors."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from .partitioning import load_current_manifest
from .returns_io import read_returns_dates, read_returns_matrix

DateLike = date | datetime | pd.Timestamp


def read_screen_partitioned(
    source: str | Path,
    columns: Iterable[str] | None = None,
    *,
    filters: Iterable[tuple[str, str, Any]] | None = None,
    date_from: DateLike | None = None,
    date_to: DateLike | None = None,
    as_of: DateLike | None = None,
    isins: Iterable[str] = (),
    sedols: Iterable[str] = (),
) -> pd.DataFrame:
    """Read Screen through the current immutable monthly partitions."""

    manifest, root = _dataset_context(source, "screen")
    parsed = _screen_bounds(
        filters=filters,
        date_from=date_from,
        date_to=date_to,
        as_of=as_of,
        isins=tuple(str(value) for value in isins),
        sedols=tuple(str(value) for value in sedols),
    )
    partitions = _select_partitions(manifest, root, lower=parsed[0], upper=parsed[1])
    return _read_screen_partitions(
        partitions,
        columns=columns,
        lower=parsed[0],
        upper=parsed[1],
        isins=parsed[2],
        sedols=parsed[3],
    )


def read_latest_screen_partitioned(
    source: str | Path,
    columns: Iterable[str] | None = None,
    *,
    as_of: DateLike | None = None,
) -> pd.DataFrame:
    """Read the latest available Screen partition, optionally bounded by ``as_of``."""

    manifest, root = _dataset_context(source, "screen")
    upper = _coerce_date(as_of)
    partitions = _select_partitions(manifest, root, lower=None, upper=upper)
    if not partitions:
        selected = tuple(str(value) for value in columns) if columns is not None else ()
        return pd.DataFrame(columns=list(selected))
    latest = max(pd.Timestamp(str(item.get("date_max"))) for item, _ in partitions)
    return _read_screen_partitions(
        partitions,
        columns=columns,
        lower=latest,
        upper=latest,
        isins=(),
        sedols=(),
    )


def read_returns_partitioned(
    source: str | Path,
    columns: Iterable[str] | None = None,
    *,
    date_from: DateLike | None = None,
    date_to: DateLike | None = None,
) -> pd.DataFrame:
    """Read Returns by selecting only the yearly partitions touching the date window."""

    paths = returns_partition_paths(source, date_from=date_from, date_to=date_to)
    return read_returns_matrix(paths, columns=columns, date_from=date_from, date_to=date_to)


def read_returns_dates_partitioned(
    source: str | Path,
    *,
    date_from: DateLike | None = None,
    date_to: DateLike | None = None,
) -> pd.DatetimeIndex:
    paths = returns_partition_paths(source, date_from=date_from, date_to=date_to)
    return read_returns_dates(paths, date_from=date_from, date_to=date_to)


def screen_partition_paths(
    source: str | Path,
    *,
    date_from: DateLike | None = None,
    date_to: DateLike | None = None,
    as_of: DateLike | None = None,
) -> tuple[Path, ...]:
    manifest, root = _dataset_context(source, "screen")
    lower = _coerce_date(date_from)
    upper = _upper_bound(date_to, as_of)
    return tuple(path for _, path in _select_partitions(manifest, root, lower=lower, upper=upper))


def returns_partition_paths(
    source: str | Path,
    *,
    date_from: DateLike | None = None,
    date_to: DateLike | None = None,
) -> tuple[Path, ...]:
    manifest, root = _dataset_context(source, "returns_wide")
    lower = _coerce_date(date_from)
    upper = _coerce_date(date_to)
    return tuple(path for _, path in _select_partitions(manifest, root, lower=lower, upper=upper))


def _dataset_context(source: str | Path, dataset: str) -> tuple[Any, Path]:
    source_path = Path(source).resolve()
    root = source_path.parent.parent if source_path.parent.name == "00_screen" else source_path.parent
    env_name = "TP_SCREEN_DATASET_MANIFEST" if dataset == "screen" else "TP_RETURNS_DATASET_MANIFEST"
    pointer = Path(os.environ[env_name]) if os.environ.get(env_name) else None
    if pointer is None:
        pointer = root / "00_screen" / "datasets" / "manifests" / dataset / "current.json"
    return load_current_manifest(pointer, root=root), root


def _select_partitions(
    manifest: Any,
    root: Path,
    *,
    lower: pd.Timestamp | None,
    upper: pd.Timestamp | None,
) -> list[tuple[Mapping[str, Any], Path]]:
    selected: list[tuple[Mapping[str, Any], Path]] = []
    for partition in manifest.partitions:
        partition_lower = _coerce_date(partition.get("date_min"))
        partition_upper = _coerce_date(partition.get("date_max"))
        if lower is not None and partition_upper is not None and partition_upper < lower:
            continue
        if upper is not None and partition_lower is not None and partition_lower > upper:
            continue
        path = Path(str(partition["path"]))
        if not path.is_absolute():
            path = root / path
        selected.append((partition, path))
    selected.sort(key=lambda item: (int(item[0].get("year", 0)), int(item[0].get("month", 0) or 0)))
    return selected


def _read_screen_partitions(
    partitions: list[tuple[Mapping[str, Any], Path]],
    *,
    columns: Iterable[str] | None,
    lower: pd.Timestamp | None,
    upper: pd.Timestamp | None,
    isins: tuple[str, ...],
    sedols: tuple[str, ...],
) -> pd.DataFrame:
    if not partitions:
        selected = tuple(str(value) for value in columns) if columns is not None else ()
        return pd.DataFrame(columns=list(selected))
    names = tuple(str(value) for value in pq.ParquetFile(partitions[0][1]).schema_arrow.names)
    selected = tuple(dict.fromkeys(str(value) for value in columns)) if columns is not None else names
    missing = [column for column in selected if column not in names]
    if missing:
        raise ValueError(f"Screen source is missing requested columns: {missing}")
    if (lower is not None or upper is not None) and "Date" not in names:
        raise ValueError("Screen date filters require a Date column")
    if isins and "ISIN" not in names:
        raise ValueError("Screen ISIN filters require an ISIN column")
    if sedols and "Company SEDOL" not in names:
        raise ValueError("Screen SEDOL filters require a Company SEDOL column")
    required = list(selected)
    if (lower is not None or upper is not None) and "Date" in names and "Date" not in required:
        required.append("Date")
    if isins and "ISIN" in names and "ISIN" not in required:
        required.append("ISIN")
    if sedols and "Company SEDOL" in names and "Company SEDOL" not in required:
        required.append("Company SEDOL")
    arrow_filters: list[tuple[str, str, Any]] = []
    if lower is not None:
        arrow_filters.append(("Date", ">=", lower))
    if upper is not None:
        arrow_filters.append(("Date", "<=", upper))
    if isins:
        arrow_filters.append(("ISIN", "in", list(isins)))
    if sedols:
        arrow_filters.append(("Company SEDOL", "in", list(sedols)))
    frames: list[pd.DataFrame] = []
    for _, path in partitions:
        table = pq.read_table(
            path,
            columns=required,
            filters=arrow_filters or None,
            use_pandas_metadata=False,
        )
        frame = table.to_pandas(ignore_metadata=True)
        if "Date" in frame.columns and (lower is not None or upper is not None):
            dates = pd.to_datetime(frame["Date"], errors="coerce")
            mask = dates.notna()
            if lower is not None:
                mask &= dates >= lower
            if upper is not None:
                mask &= dates <= upper
            frame = frame.loc[mask]
        if isins and "ISIN" in frame.columns:
            frame = frame.loc[frame["ISIN"].astype(str).isin(isins)]
        if sedols and "Company SEDOL" in frame.columns:
            frame = frame.loc[frame["Company SEDOL"].astype(str).isin(sedols)]
        frames.append(frame.reindex(columns=list(selected)))
    if not frames:
        return pd.DataFrame(columns=list(selected))
    return pd.concat(frames, ignore_index=True).reindex(columns=list(selected))


def _screen_bounds(
    *,
    filters: Iterable[tuple[str, str, Any]] | None,
    date_from: DateLike | None,
    date_to: DateLike | None,
    as_of: DateLike | None,
    isins: tuple[str, ...],
    sedols: tuple[str, ...],
) -> tuple[pd.Timestamp | None, pd.Timestamp | None, tuple[str, ...], tuple[str, ...]]:
    lower = _coerce_date(date_from)
    upper = _upper_bound(date_to, as_of)
    isin_values = list(isins)
    sedol_values = list(sedols)
    for column, operator, value in filters or ():
        if column == "Date":
            parsed = _coerce_date(value)
            if operator in {">=", ">"}:
                lower = parsed
            elif operator in {"<=", "<"}:
                upper = parsed
            elif operator in {"=", "=="}:
                lower = parsed
                upper = parsed
            else:
                raise ValueError(f"unsupported Screen filter: {(column, operator)!r}")
        elif column == "ISIN":
            if operator in {"=", "=="}:
                isin_values.append(str(value))
            elif operator.lower() == "in":
                isin_values.extend(str(item) for item in value)
            else:
                raise ValueError(f"unsupported Screen filter: {(column, operator)!r}")
        elif column == "Company SEDOL":
            if operator in {"=", "=="}:
                sedol_values.append(str(value))
            elif operator.lower() == "in":
                sedol_values.extend(str(item) for item in value)
            else:
                raise ValueError(f"unsupported Screen filter: {(column, operator)!r}")
        else:
            raise ValueError(f"unsupported Screen filter: {(column, operator)!r}")
    if lower is not None and upper is not None and lower > upper:
        return lower, upper, tuple(dict.fromkeys(isin_values)), tuple(dict.fromkeys(sedol_values))
    return lower, upper, tuple(dict.fromkeys(isin_values)), tuple(dict.fromkeys(sedol_values))


def _upper_bound(date_to: DateLike | None, as_of: DateLike | None) -> pd.Timestamp | None:
    values = [_coerce_date(value) for value in (date_to, as_of) if value is not None]
    return min(values) if values else None


def _coerce_date(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        raise ValueError(f"invalid date value: {value!r}")
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert(None)
    return parsed


__all__ = [
    "read_latest_screen_partitioned",
    "read_returns_dates_partitioned",
    "read_returns_partitioned",
    "read_screen_partitioned",
    "returns_partition_paths",
    "screen_partition_paths",
]

"""TP canonical data readers with explicit legacy/DuckDB engine switches."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .analytics.config import DuckDBConfig
from .analytics.connection import connect
from .analytics.queries import QuerySpecError, ReturnsQuery, ScreenQuery
from .analytics.repositories import ReturnsRepository, ScreenRepository
from .analytics.returns_io import (
    read_returns_dates as read_legacy_returns_dates,
)
from .analytics.returns_io import (
    read_returns_matrix,
)
from .analytics.shadow import shadow_compare_returns, shadow_compare_screen
from .data_contract import drop_deprecated_screen_columns, normalize_screen_dates
from .data_sources import (
    LAST_SCREEN_PATH,
    RETURNS_PATH,
    SCREEN_AGGREGATE_5Y_PATH,
    SCREEN_AGGREGATE_PATH,
)

DateLike = date | datetime


def read_parquet_dataset(
    path: str | Path,
    columns: Iterable[str] | None = None,
    *,
    filters: Iterable[tuple[str, str, Any]] | None = None,
) -> pd.DataFrame:
    return pd.read_parquet(
        Path(path),
        columns=list(columns) if columns is not None else None,
        filters=list(filters) if filters is not None else None,
    )


def read_screen_aggregate(
    path: str | Path = SCREEN_AGGREGATE_PATH,
    columns: Iterable[str] | None = None,
    drop_deprecated: bool = True,
    normalize_dates: bool = True,
    *,
    filters: Iterable[tuple[str, str, Any]] | None = None,
    date_from: DateLike | None = None,
    date_to: DateLike | None = None,
    as_of: DateLike | None = None,
    isins: Iterable[str] = (),
    sedols: Iterable[str] = (),
    engine: str | None = None,
) -> pd.DataFrame:
    resolved_engine = _resolve_engine(engine)
    projection = tuple(columns) if columns is not None else None
    if resolved_engine == "legacy_parquet":
        frame = _read_legacy_screen(
            path,
            projection,
            filters=filters,
            date_from=date_from,
            date_to=date_to,
            as_of=as_of,
            isins=tuple(isins),
            sedols=tuple(sedols),
        )
    else:
        spec = _screen_spec(
            projection,
            filters=filters,
            date_from=date_from,
            date_to=date_to,
            as_of=as_of,
            isins=tuple(isins),
            sedols=tuple(sedols),
        )
        with connect(_read_only_config()) as connection:
            if resolved_engine == "shadow_compare":
                if not spec.columns or all(value is None for value in (spec.date_from, spec.date_to, spec.as_of)):
                    raise QuerySpecError("shadow_compare screen reads require columns and a bounded date filter")
                shadow_compare_screen(connection, path, spec, surface="tp_core.io")
                frame = _read_legacy_screen_spec(path, spec)
            else:
                frame = ScreenRepository(connection).query(spec)
    if drop_deprecated:
        frame = drop_deprecated_screen_columns(frame)
    if normalize_dates:
        frame = normalize_screen_dates(frame)
    return frame


def read_last_screen(
    path: str | Path = LAST_SCREEN_PATH,
    columns: Iterable[str] | None = None,
    drop_deprecated: bool = True,
    normalize_dates: bool = True,
    *,
    engine: str | None = None,
) -> pd.DataFrame:
    resolved_engine = _resolve_engine(engine)
    projection = tuple(columns) if columns is not None else ()
    if resolved_engine == "legacy_parquet":
        frame = read_screen_aggregate(
            path,
            columns=projection or None,
            drop_deprecated=drop_deprecated,
            normalize_dates=normalize_dates,
            engine="legacy_parquet",
        )
        return frame
    with connect(_read_only_config()) as connection:
        frame = ScreenRepository(connection).latest(columns=projection)
        if resolved_engine == "shadow_compare":
            latest_date = pd.Timestamp(frame["Date"].max())
            compare_columns = projection or tuple(frame.columns)
            spec = ScreenQuery(
                columns=compare_columns,
                date_from=latest_date,
                date_to=latest_date,
            )
            shadow_compare_screen(connection, path, spec, surface="tp_core.io.latest")
            legacy = _read_legacy_screen_spec(path, spec)
            return _postprocess_screen(
                legacy,
                drop_deprecated=drop_deprecated,
                normalize_dates=normalize_dates,
            )
    return _postprocess_screen(frame, drop_deprecated=drop_deprecated, normalize_dates=normalize_dates)


def read_screen_5y(
    path: str | Path = SCREEN_AGGREGATE_5Y_PATH,
    columns: Iterable[str] | None = None,
    drop_deprecated: bool = True,
    normalize_dates: bool = True,
    *,
    engine: str | None = None,
) -> pd.DataFrame:
    resolved_engine = _resolve_engine(engine)
    if resolved_engine == "legacy_parquet":
        return read_screen_aggregate(
            path,
            columns=columns,
            drop_deprecated=drop_deprecated,
            normalize_dates=normalize_dates,
            engine="legacy_parquet",
        )
    latest = read_last_screen(
        SCREEN_AGGREGATE_PATH,
        columns=("Date", "ISIN"),
        drop_deprecated=False,
        normalize_dates=True,
        engine="duckdb",
    )
    if latest.empty:
        return latest
    latest_date = pd.Timestamp(latest["Date"].max())
    start_date = latest_date - pd.DateOffset(years=5)
    return read_screen_aggregate(
        SCREEN_AGGREGATE_PATH,
        columns=columns,
        drop_deprecated=drop_deprecated,
        normalize_dates=normalize_dates,
        date_from=start_date,
        date_to=latest_date,
        engine=resolved_engine,
    )


def read_returns(
    path: str | Path = RETURNS_PATH,
    columns: Iterable[str] | None = None,
    *,
    date_from: DateLike | None = None,
    date_to: DateLike | None = None,
    engine: str | None = None,
) -> pd.DataFrame:
    resolved_engine = _resolve_engine(engine)
    projection = tuple(columns) if columns is not None else None
    if resolved_engine == "legacy_parquet":
        return read_returns_matrix(
            path,
            columns=projection,
            date_from=date_from,
            date_to=date_to,
        )
    if projection is None and resolved_engine == "shadow_compare":
        raise QuerySpecError("shadow_compare returns reads require an explicit security projection")
    spec = ReturnsQuery(
        securities=projection or (),
        date_from=date_from,
        date_to=date_to,
    )
    with connect(_read_only_config()) as connection:
        if resolved_engine == "shadow_compare":
            if date_from is None and date_to is None:
                raise QuerySpecError("shadow_compare returns reads require a bounded date window")
            shadow_compare_returns(connection, path, spec, surface="tp_core.io")
            returns = read_returns_matrix(
                path,
                columns=projection,
                date_from=date_from,
                date_to=date_to,
            )
        else:
            returns = ReturnsRepository(connection).matrix(spec)
    return returns.sort_index()


def read_returns_dates(
    path: str | Path = RETURNS_PATH,
    *,
    engine: str | None = None,
) -> pd.DatetimeIndex:
    """Return only the canonical Returns date index without materializing securities."""

    resolved_engine = _resolve_engine(engine)
    if resolved_engine == "legacy_parquet":
        return read_legacy_returns_dates(path)
    with connect(_read_only_config()) as connection:
        duck = connection.execute(
            'SELECT "Date" FROM "canonical"."returns_wide" ORDER BY "Date"'
        ).df()
    dates = pd.DatetimeIndex(pd.to_datetime(duck["Date"], errors="coerce"), name="Date")
    if resolved_engine == "shadow_compare":
        legacy = read_legacy_returns_dates(path)
        if not dates.equals(legacy):
            raise QuerySpecError("shadow_compare returns date index mismatch")
    return dates


def resolve_return_columns(
    path: str | Path = RETURNS_PATH,
    columns: Iterable[str] | None = None,
    *,
    engine: str | None = None,
) -> tuple[str, ...] | None:
    """Resolve a requested security projection against the active source schema."""

    if columns is None:
        return None
    requested = tuple(dict.fromkeys(str(column) for column in columns))
    resolved_engine = _resolve_engine(engine)
    import pyarrow.parquet as pq

    physical = set(pq.ParquetFile(path).schema_arrow.names)
    if resolved_engine == "legacy_parquet":
        available = physical
    else:
        with connect(_read_only_config()) as connection:
            catalog = {
                str(row[0])
                for row in connection.execute('DESCRIBE "canonical"."returns_wide"').fetchall()
            }
        available = physical.intersection(catalog) if resolved_engine == "shadow_compare" else catalog
    resolved: list[str] = []
    for column in requested:
        if column in available:
            resolved.append(column)
        elif f"{column}-R" in available:
            resolved.append(f"{column}-R")
    return tuple(dict.fromkeys(resolved))


def _read_only_config() -> DuckDBConfig:
    return DuckDBConfig.from_env(read_only=True)


def _resolve_engine(engine: str | None) -> str:
    value = engine or DuckDBConfig.from_env().data_engine
    if value not in {"legacy_parquet", "duckdb", "shadow_compare"}:
        raise ValueError(f"unsupported data engine: {value!r}")
    return value


def _screen_spec(
    columns: tuple[str, ...] | None,
    *,
    filters: Iterable[tuple[str, str, Any]] | None,
    date_from: DateLike | None,
    date_to: DateLike | None,
    as_of: DateLike | None,
    isins: tuple[str, ...],
    sedols: tuple[str, ...],
) -> ScreenQuery:
    resolved_date_from = date_from
    resolved_date_to = date_to
    resolved_isins = list(isins)
    resolved_sedols = list(sedols)
    for column, operator, value in filters or ():
        if column == "Date" and operator in {">=", ">"}:
            resolved_date_from = _coerce_date_value(value)
        elif column == "Date" and operator in {"<=", "<"}:
            resolved_date_to = _coerce_date_value(value)
        elif column == "Date" and operator in {"=", "=="}:
            resolved_date_from = _coerce_date_value(value)
            resolved_date_to = _coerce_date_value(value)
        elif column == "ISIN" and operator in {"=", "=="}:
            resolved_isins.append(str(value))
        elif column == "ISIN" and operator.lower() == "in":
            resolved_isins.extend(str(item) for item in value)
        elif column == "Company SEDOL" and operator in {"=", "=="}:
            resolved_sedols.append(str(value))
        elif column == "Company SEDOL" and operator.lower() == "in":
            resolved_sedols.extend(str(item) for item in value)
        else:
            raise QuerySpecError(f"unsupported typed screen filter: {(column, operator)!r}")
    return ScreenQuery(
        columns=columns or (),
        date_from=resolved_date_from,
        date_to=resolved_date_to,
        as_of=as_of,
        isins=tuple(resolved_isins),
        sedols=tuple(resolved_sedols),
    )


def _postprocess_screen(frame: pd.DataFrame, *, drop_deprecated: bool, normalize_dates: bool) -> pd.DataFrame:
    if drop_deprecated:
        frame = drop_deprecated_screen_columns(frame)
    if normalize_dates:
        frame = normalize_screen_dates(frame)
    return frame


def _read_legacy_screen(
    path: str | Path,
    columns: tuple[str, ...] | None,
    *,
    filters: Iterable[tuple[str, str, Any]] | None,
    date_from: DateLike | None,
    date_to: DateLike | None,
    as_of: DateLike | None,
    isins: tuple[str, ...],
    sedols: tuple[str, ...],
) -> pd.DataFrame:
    legacy_filters = list(filters or ())
    if date_from is not None:
        legacy_filters.append(("Date", ">=", pd.Timestamp(date_from)))
    if date_to is not None:
        legacy_filters.append(("Date", "<=", pd.Timestamp(date_to)))
    if as_of is not None:
        legacy_filters.append(("Date", "<=", pd.Timestamp(as_of)))
    if isins:
        legacy_filters.append(("ISIN", "in", list(isins)))
    if sedols:
        legacy_filters.append(("Company SEDOL", "in", list(sedols)))
    frame = read_parquet_dataset(path, columns, filters=legacy_filters or None)
    return _restore_projection_order(frame, columns)


def _read_legacy_screen_spec(path: str | Path, spec: ScreenQuery) -> pd.DataFrame:
    filters: list[tuple[str, str, Any]] = []
    if spec.date_from is not None:
        filters.append(("Date", ">=", pd.Timestamp(spec.date_from)))
    if spec.date_to is not None:
        filters.append(("Date", "<=", pd.Timestamp(spec.date_to)))
    if spec.as_of is not None:
        filters.append(("Date", "<=", pd.Timestamp(spec.as_of)))
    if spec.isins:
        filters.append(("ISIN", "in", list(spec.isins)))
    if spec.sedols:
        filters.append(("Company SEDOL", "in", list(spec.sedols)))
    frame = read_parquet_dataset(path, spec.columns, filters=filters or None)
    return _restore_projection_order(frame, spec.columns)


def _read_legacy_return_dates(path: str | Path) -> pd.DatetimeIndex:
    return read_legacy_returns_dates(path)


def _coerce_date_value(value: Any) -> Any:
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return pd.Timestamp(value)
    if isinstance(value, str):
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.notna(parsed):
            return pd.Timestamp(parsed)
    return value


def _restore_projection_order(frame: pd.DataFrame, columns: tuple[str, ...] | None) -> pd.DataFrame:
    if columns is None:
        return frame
    available = [column for column in columns if column in frame.columns]
    return frame.loc[:, available]


__all__ = [
    "read_last_screen",
    "read_parquet_dataset",
    "read_returns",
    "read_returns_dates",
    "read_screen_5y",
    "read_screen_aggregate",
    "resolve_return_columns",
]

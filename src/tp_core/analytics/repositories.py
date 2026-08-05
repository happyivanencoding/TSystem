"""Read-only repositories over catalog relations.

Repositories deliberately receive an explicit connection.  They do not know
where a DuckDB file lives and they never accept raw SQL from callers.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from .queries import (
    QuerySpecError,
    ReturnsQuery,
    ScreenQuery,
    SignalQuery,
    quote_identifier,
    validate_relation_name,
)


def _relation_sql(relation: str) -> str:
    return ".".join(quote_identifier(part) for part in relation.split("."))


def _available_columns(connection: Any, relation: str) -> tuple[str, ...]:
    try:
        rows = connection.execute(f"DESCRIBE {_relation_sql(relation)}").fetchall()
    except Exception as exc:
        raise QuerySpecError(f"catalog relation is unavailable: {relation}") from exc
    return tuple(str(row[0]) for row in rows)


def _select_columns(available: tuple[str, ...], requested: Iterable[str]) -> str:
    columns = tuple(requested)
    if not columns:
        hidden = tuple(column for column in available if column.startswith("__tp_partition_"))
        if hidden:
            return "* EXCLUDE (" + ", ".join(quote_identifier(column) for column in hidden) + ")"
        return "*"
    missing = [column for column in columns if column not in available]
    if missing:
        raise QuerySpecError(f"requested columns are not in the catalog relation: {missing}")
    return ", ".join(quote_identifier(column) for column in columns)


def _where_in(column: str, values: tuple[str, ...], parameters: list[Any]) -> str:
    parameters.extend(values)
    return f"{quote_identifier(column)} IN ({', '.join('?' for _ in values)})"


def _validate_limit(limit: int) -> None:
    if not isinstance(limit, int) or limit < 1:
        raise QuerySpecError("limit must be a positive integer")


def _date_predicates(
    available: tuple[str, ...],
    date_from: Any,
    date_to: Any,
    as_of: Any,
    parameters: list[Any],
) -> list[str]:
    if any(value is not None for value in (date_from, date_to, as_of)) and "Date" not in available:
        raise QuerySpecError("date filters require a Date column")
    predicates: list[str] = []
    if date_from is not None:
        predicates.append(f"{quote_identifier('Date')} >= ?")
        parameters.append(date_from)
    if date_to is not None:
        predicates.append(f"{quote_identifier('Date')} <= ?")
        parameters.append(date_to)
    if as_of is not None:
        predicates.append(f"{quote_identifier('Date')} <= ?")
        parameters.append(as_of)
    return predicates


def _partition_date_predicates(
    available: tuple[str, ...],
    date_from: Any,
    date_to: Any,
    as_of: Any,
    parameters: list[Any],
) -> list[str]:
    if "__tp_partition_year" not in available:
        return []
    lower = date_from.year if date_from is not None else None
    upper_values = [value.year for value in (date_to, as_of) if value is not None]
    upper = min(upper_values) if upper_values else None
    predicates: list[str] = []
    if lower is not None:
        predicates.append(f"{quote_identifier('__tp_partition_year')} >= ?")
        parameters.append(lower)
    if upper is not None:
        predicates.append(f"{quote_identifier('__tp_partition_year')} <= ?")
        parameters.append(upper)
    return predicates


class ScreenRepository:
    relation = "canonical.screen"

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def query(self, spec: ScreenQuery) -> pd.DataFrame:
        available = _available_columns(self.connection, self.relation)
        selected = _select_columns(available, spec.columns)
        parameters: list[Any] = []
        predicates = _date_predicates(available, spec.date_from, spec.date_to, spec.as_of, parameters)
        predicates.extend(_partition_date_predicates(available, spec.date_from, spec.date_to, spec.as_of, parameters))
        if spec.isins:
            if "ISIN" not in available:
                raise QuerySpecError("isins filter requires an ISIN column")
            predicates.append(_where_in("ISIN", spec.isins, parameters))
        if spec.sedols:
            if "Company SEDOL" not in available:
                raise QuerySpecError("sedols filter requires a Company SEDOL column")
            predicates.append(_where_in("Company SEDOL", spec.sedols, parameters))
        if spec.countries:
            if "Exchange Country Name" not in available:
                raise QuerySpecError("countries filter requires Exchange Country Name")
            predicates.append(_where_in("Exchange Country Name", spec.countries, parameters))
        if spec.benchmark is not None:
            benchmark_column = "Benchmark" if "Benchmark" in available else "Benchmark Country English"
            if benchmark_column not in available:
                raise QuerySpecError("benchmark filter requires a supported benchmark column")
            predicates.append(f"{quote_identifier(benchmark_column)} = ?")
            parameters.append(spec.benchmark)
        if spec.positive_weight_only:
            weight_column = "Weight in MSCI WORLD" if "Weight in MSCI WORLD" in available else None
            if weight_column is None:
                raise QuerySpecError("positive_weight_only requires Weight in MSCI WORLD")
            predicates.append(f"COALESCE({quote_identifier(weight_column)}, 0) > 0")
        query = f"SELECT {selected} FROM {_relation_sql(self.relation)}"
        if predicates:
            query += " WHERE " + " AND ".join(predicates)
        if spec.limit is not None:
            query += " LIMIT ?"
            parameters.append(spec.limit)
        frame = self.connection.execute(query, parameters).df()
        return _normalize_screen_dates(frame)

    def latest(self, *, columns: tuple[str, ...] = (), limit: int | None = None) -> pd.DataFrame:
        available = _available_columns(self.connection, self.relation)
        if "Date" not in available:
            raise QuerySpecError("latest screen query requires a Date column")
        selected = _select_columns(available, columns)
        relation = _relation_sql(self.relation)
        date_column = quote_identifier("Date")
        query = f"SELECT {selected} FROM {relation} WHERE {date_column} = (SELECT MAX({date_column}) FROM {relation})"
        if "__tp_partition_year" in available:
            query += (
                f" AND {quote_identifier('__tp_partition_year')} = "
                f"(SELECT MAX({quote_identifier('__tp_partition_year')}) FROM {relation})"
            )
        parameters: list[Any] = []
        if limit is not None:
            _validate_limit(limit)
            query += " LIMIT ?"
            parameters.append(limit)
        frame = self.connection.execute(query, parameters).df()
        return _normalize_screen_dates(frame)

    def company_history(self, isin: str, *, columns: tuple[str, ...] = ()) -> pd.DataFrame:
        return self.query(ScreenQuery(columns=columns, isins=(isin,)))


class ReturnsRepository:
    relation = "canonical.returns_wide"

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def matrix(self, spec: ReturnsQuery) -> pd.DataFrame:
        available = _available_columns(self.connection, self.relation)
        if "Date" not in available:
            raise QuerySpecError("returns relation must expose Date")
        selected = ["Date"]
        selected.extend(security for security in spec.securities if security != "Date")
        projection = _select_columns(available, tuple(selected) if spec.securities else ())
        parameters: list[Any] = []
        predicates = _date_predicates(available, spec.date_from, spec.date_to, None, parameters)
        partition_source = _returns_partition_source(
            self.connection,
            date_from=spec.date_from,
            date_to=spec.date_to,
        )
        if partition_source is None:
            predicates.extend(_partition_date_predicates(available, spec.date_from, spec.date_to, None, parameters))
        source = partition_source or _relation_sql(self.relation)
        query = f"SELECT {projection} FROM {source}"
        if predicates:
            query += " WHERE " + " AND ".join(predicates)
        query += " ORDER BY " + quote_identifier("Date")
        frame = self.connection.execute(query, parameters).df()
        if spec.preserve_wide and "Date" in frame.columns:
            frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
            frame = frame.set_index("Date")
            frame.index = pd.DatetimeIndex(frame.index).astype("datetime64[ns]")
        return frame


class SignalRepository:
    relation = "signals.all_signals"

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def query(self, spec: SignalQuery, *, columns: tuple[str, ...] = ()) -> pd.DataFrame:
        available = _available_columns(self.connection, self.relation)
        selected = _select_columns(available, columns)
        parameters: list[Any] = []
        predicates: list[str] = []
        for column, values in (
            ("signal_family", spec.families),
            ("signal_name", spec.names),
            ("scope", spec.scopes),
        ):
            if values:
                if column not in available:
                    raise QuerySpecError(f"{column} filter requires a matching signal column")
                predicates.append(_where_in(column, values, parameters))
        date_column = "as_of" if "as_of" in available else "Date" if "Date" in available else None
        if spec.as_of is not None:
            if date_column is None:
                raise QuerySpecError("as_of filter requires as_of or Date")
            predicates.append(f"{quote_identifier(date_column)} <= ?")
            parameters.append(spec.as_of)
        relation = _relation_sql(self.relation)
        query = f"SELECT {selected} FROM {relation}"
        if predicates:
            query += " WHERE " + " AND ".join(predicates)
        if spec.latest_only:
            partition_columns = [column for column in ("signal_family", "signal_name", "scope") if column in available]
            if date_column is None or not partition_columns:
                raise QuerySpecError("latest_only requires signal keys and an as_of/Date column")
            partition_sql = ", ".join(quote_identifier(column) for column in partition_columns)
            base_query = f"SELECT * FROM {relation}"
            if predicates:
                base_query += " WHERE " + " AND ".join(predicates)
            output_projection = selected if columns else "* EXCLUDE (__tp_rn)"
            query = (
                f"SELECT {output_projection} FROM ("
                f"SELECT source.*, ROW_NUMBER() OVER (PARTITION BY {partition_sql} "
                f"ORDER BY {quote_identifier(date_column)} DESC) AS __tp_rn "
                f"FROM ({base_query}) AS source"
                ") AS ranked WHERE __tp_rn = 1"
            )
        return self.connection.execute(query, parameters).df()

    def latest(self, *, columns: tuple[str, ...] = ()) -> pd.DataFrame:
        return self.query(SignalQuery(latest_only=True), columns=columns)


class _RelationRepository:
    def __init__(self, connection: Any, schema: str, relation: str) -> None:
        self.connection = connection
        self.relation = f"{schema}.{validate_relation_name(relation)}"

    def query(self, *, columns: tuple[str, ...] = (), limit: int | None = None) -> pd.DataFrame:
        available = _available_columns(self.connection, self.relation)
        selected = _select_columns(available, columns)
        query = f"SELECT {selected} FROM {_relation_sql(self.relation)}"
        parameters: list[Any] = []
        if limit is not None:
            _validate_limit(limit)
            query += " LIMIT ?"
            parameters.append(limit)
        return self.connection.execute(query, parameters).df()


class ArtifactRepository(_RelationRepository):
    def __init__(self, connection: Any) -> None:
        super().__init__(connection, "meta", "artifact_registry")


class RunRepository(_RelationRepository):
    def __init__(self, connection: Any) -> None:
        super().__init__(connection, "meta", "run_registry")


class DataHealthRepository(_RelationRepository):
    def __init__(self, connection: Any) -> None:
        super().__init__(connection, "meta", "data_quality_results")


class MartRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def query(self, name: str, *, columns: tuple[str, ...] = (), limit: int | None = None) -> pd.DataFrame:
        return _RelationRepository(self.connection, "marts", name).query(columns=columns, limit=limit)


def _normalize_screen_dates(frame: pd.DataFrame) -> pd.DataFrame:
    if "Date" in frame.columns:
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce").astype("datetime64[ns]")
    return frame


def _returns_partition_source(
    connection: Any,
    *,
    date_from: Any,
    date_to: Any,
) -> str | None:
    """Build a narrow external relation from the current Returns manifest."""

    try:
        rows = connection.execute(
            """
            SELECT partition_key, path
            FROM "meta"."partition_registry"
            WHERE dataset_name = 'returns_wide'
              AND dataset_version = (
                  SELECT returns_dataset_version
                  FROM "meta"."catalog_releases"
                  ORDER BY created_at DESC
                  LIMIT 1
              )
            ORDER BY partition_key
            """
        ).fetchall()
    except Exception:
        return None
    if not rows:
        return None
    lower_year = _date_year(date_from)
    upper_year = _date_year(date_to)
    paths: list[str] = []
    for partition_key, path in rows:
        year = _partition_year(str(partition_key))
        if lower_year is not None and year is not None and year < lower_year:
            continue
        if upper_year is not None and year is not None and year > upper_year:
            continue
        paths.append(str(path).replace("\\", "/"))
    if not paths:
        return None
    literals = ", ".join(_sql_string(path) for path in paths)
    return f"read_parquet([{literals}], union_by_name=true, hive_partitioning=false)"


def _partition_year(partition_key: str) -> int | None:
    for part in partition_key.split("/"):
        if part.startswith("year="):
            try:
                return int(part.removeprefix("year="))
            except ValueError:
                return None
    return None


def _date_year(value: Any) -> int | None:
    if value is None:
        return None
    return pd.Timestamp(value).year


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


__all__ = [
    "ArtifactRepository",
    "DataHealthRepository",
    "MartRepository",
    "ReturnsRepository",
    "RunRepository",
    "ScreenRepository",
    "SignalRepository",
]

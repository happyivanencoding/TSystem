"""Read-only legacy-versus-DuckDB shadow query comparisons."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from .manifests import load_manifest, resolve_partition_path
from .parity import FrameParityResult, compare_frames
from .queries import QuerySpecError, ReturnsQuery, ScreenQuery, quote_identifier
from .repositories import ReturnsRepository, ScreenRepository
from .returns_io import read_returns_matrix


@dataclass(frozen=True)
class ShadowCompareResult:
    dataset_name: str
    surface: str
    status: str
    elapsed_seconds: float
    legacy_rows: int
    duckdb_rows: int
    parity: FrameParityResult

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "surface": self.surface,
            "status": self.status,
            "elapsed_seconds": self.elapsed_seconds,
            "legacy_rows": self.legacy_rows,
            "duckdb_rows": self.duckdb_rows,
            "parity": asdict(self.parity),
        }


def shadow_compare_screen(
    connection: Any,
    source_path: str | Path,
    spec: ScreenQuery,
    *,
    surface: str = "screen",
) -> ShadowCompareResult:
    started = time.perf_counter()
    legacy = _read_legacy_screen(source_path, spec)
    duckdb_frame = ScreenRepository(connection).query(spec)
    parity = compare_frames(legacy, duckdb_frame, key_columns=("Date", "ISIN"))
    return ShadowCompareResult(
        dataset_name="screen",
        surface=surface,
        status="passed" if parity.equal else "failed",
        elapsed_seconds=time.perf_counter() - started,
        legacy_rows=len(legacy),
        duckdb_rows=len(duckdb_frame),
        parity=parity,
    )


def shadow_compare_returns(
    connection: Any,
    source_path: str | Path,
    spec: ReturnsQuery,
    *,
    surface: str = "returns",
) -> ShadowCompareResult:
    started = time.perf_counter()
    legacy = _read_legacy_returns(source_path, spec)
    duckdb_frame = ReturnsRepository(connection).matrix(spec)
    parity = compare_frames(legacy, duckdb_frame)
    return ShadowCompareResult(
        dataset_name="returns_wide",
        surface=surface,
        status="passed" if parity.equal else "failed",
        elapsed_seconds=time.perf_counter() - started,
        legacy_rows=len(legacy),
        duckdb_rows=len(duckdb_frame),
        parity=parity,
    )


def shadow_compare_returns_partitions(
    connection: Any,
    source_path: str | Path,
    manifest_path: str | Path,
    spec: ReturnsQuery,
    *,
    root: str | Path,
    surface: str = "returns_partition",
) -> ShadowCompareResult:
    """Compare a Returns query against only manifest partitions in its date window."""

    started = time.perf_counter()
    if not spec.securities:
        raise QuerySpecError("shadow returns queries require an explicit securities projection")
    workspace = Path(root).resolve()
    manifest_target = Path(manifest_path)
    if not manifest_target.is_absolute():
        manifest_target = workspace / manifest_target
    manifest = load_manifest(manifest_target, require_files=True, root=workspace)
    if manifest.dataset_name != "returns_wide":
        raise QuerySpecError(f"expected returns_wide manifest, got {manifest.dataset_name!r}")
    lower_year = spec.date_from.year if spec.date_from is not None else None
    upper_year = spec.date_to.year if spec.date_to is not None else None
    selected_partitions = [
        partition
        for partition in manifest.partitions
        if (lower_year is None or int(partition["year"]) >= lower_year)
        and (upper_year is None or int(partition["year"]) <= upper_year)
    ]
    if not selected_partitions:
        raise QuerySpecError("returns shadow query selected no manifest partitions")
    files = [resolve_partition_path(manifest, partition, root=workspace).resolve() for partition in selected_partitions]
    literals = ", ".join(_sql_string(str(path).replace("\\", "/")) for path in files)
    projection = ", ".join([quote_identifier("Date")] + [quote_identifier(security) for security in spec.securities])
    query = f"SELECT {projection} FROM read_parquet([{literals}], union_by_name=true, hive_partitioning=false)"
    parameters: list[Any] = []
    predicates: list[str] = []
    if spec.date_from is not None:
        predicates.append(f"{quote_identifier('Date')} >= ?")
        parameters.append(spec.date_from)
    if spec.date_to is not None:
        predicates.append(f"{quote_identifier('Date')} <= ?")
        parameters.append(spec.date_to)
    if predicates:
        query += " WHERE " + " AND ".join(predicates)
    query += f" ORDER BY {quote_identifier('Date')}"
    duckdb_frame = connection.execute(query, parameters).df()
    duckdb_frame["Date"] = pd.to_datetime(duckdb_frame["Date"], errors="coerce").astype("datetime64[ns]")
    duckdb_frame = duckdb_frame.set_index("Date")
    legacy = _read_legacy_returns(source_path, spec)
    parity = compare_frames(legacy, duckdb_frame)
    return ShadowCompareResult(
        dataset_name="returns_wide",
        surface=surface,
        status="passed" if parity.equal else "failed",
        elapsed_seconds=time.perf_counter() - started,
        legacy_rows=len(legacy),
        duckdb_rows=len(duckdb_frame),
        parity=parity,
    )


def _read_legacy_screen(path: str | Path, spec: ScreenQuery) -> pd.DataFrame:
    if not spec.columns:
        raise QuerySpecError("shadow screen queries require an explicit column projection")
    if all(value is None for value in (spec.date_from, spec.date_to, spec.as_of)):
        raise QuerySpecError("shadow screen queries require a bounded Date filter")
    required = set(spec.columns)
    required.update({"Date"})
    if spec.isins:
        required.add("ISIN")
    if spec.sedols:
        required.add("Company SEDOL")
    if spec.countries:
        required.add("Exchange Country Name")
    if spec.benchmark is not None:
        required.add("Benchmark Country English")
    if spec.positive_weight_only:
        required.add("Weight in MSCI WORLD")
    parquet = pq.ParquetFile(path)
    frames: list[pd.DataFrame] = []
    for row_group in range(parquet.metadata.num_row_groups):
        if not _row_group_may_match_date(parquet, row_group, spec):
            continue
        frame = parquet.read_row_group(row_group, columns=list(required)).to_pandas()
        if frame.index.name == "ISIN" and "ISIN" not in frame.columns:
            frame = frame.reset_index()
        frames.append(frame)
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=sorted(required))
    if "Date" in frame.columns:
        dates = pd.to_datetime(frame["Date"], errors="coerce")
        if spec.date_from is not None:
            frame = frame.loc[dates >= _timestamp(spec.date_from)]
        if spec.date_to is not None:
            frame = frame.loc[dates <= _timestamp(spec.date_to)]
        if spec.as_of is not None:
            frame = frame.loc[dates <= _timestamp(spec.as_of)]
    if spec.isins:
        frame = frame.loc[frame["ISIN"].isin(spec.isins)]
    if spec.sedols:
        frame = frame.loc[frame["Company SEDOL"].isin(spec.sedols)]
    if spec.benchmark is not None:
        benchmark_column = "Benchmark" if "Benchmark" in frame.columns else "Benchmark Country English"
        if benchmark_column not in frame.columns:
            raise QuerySpecError("benchmark filter requires a supported benchmark column")
        frame = frame.loc[frame[benchmark_column] == spec.benchmark]
    if spec.positive_weight_only:
        frame = frame.loc[frame["Weight in MSCI WORLD"].fillna(0) > 0]
    if spec.countries:
        frame = frame.loc[frame["Exchange Country Name"].isin(spec.countries)]
    if spec.columns:
        missing = [column for column in spec.columns if column not in frame.columns]
        if missing:
            raise QuerySpecError(f"legacy screen projection is missing columns: {missing}")
        frame = frame.loc[:, list(spec.columns)]
    if spec.limit is not None:
        frame = frame.head(spec.limit)
    return frame.reset_index(drop=True)


def _read_legacy_returns(path: str | Path, spec: ReturnsQuery) -> pd.DataFrame:
    if not spec.securities:
        raise QuerySpecError("shadow returns queries require an explicit securities projection")
    return read_returns_matrix(
        path,
        columns=spec.securities,
        date_from=spec.date_from,
        date_to=spec.date_to,
    )


def _timestamp(value: date | datetime) -> pd.Timestamp:
    return pd.Timestamp(value)


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _row_group_may_match_date(parquet: pq.ParquetFile, row_group: int, spec: ScreenQuery) -> bool:
    metadata = parquet.metadata.row_group(row_group)
    date_column = next(
        (index for index in range(metadata.num_columns) if metadata.column(index).path_in_schema == "Date"),
        None,
    )
    if date_column is None:
        return True
    statistics = metadata.column(date_column).statistics
    if statistics is None or statistics.min is None or statistics.max is None:
        return True
    lower = _timestamp(spec.date_from) if spec.date_from is not None else None
    upper = _timestamp(spec.date_to) if spec.date_to is not None else None
    if spec.as_of is not None:
        as_of = _timestamp(spec.as_of)
        upper = as_of if upper is None else min(upper, as_of)
    minimum = pd.Timestamp(statistics.min)
    maximum = pd.Timestamp(statistics.max)
    if lower is not None and maximum < lower:
        return False
    return not (upper is not None and minimum > upper)


__all__ = [
    "ShadowCompareResult",
    "shadow_compare_returns",
    "shadow_compare_returns_partitions",
    "shadow_compare_screen",
]

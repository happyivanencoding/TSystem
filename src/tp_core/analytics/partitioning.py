"""Streaming immutable mirrors for the canonical Screen and Returns files."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .locking import FileLock
from .manifests import DatasetManifest, load_manifest, manifest_fingerprint, write_json_atomic
from .profiling import parquet_profile

DATASET_SETTINGS: dict[str, dict[str, Any]] = {
    "screen": {
        "directory": "screen",
        "partitioning": ("year", "month"),
        "logical_key": ("ISIN", "Date"),
        "compatibility_index_columns": ("ISIN",),
        "source_name": "screen_aggregate",
    },
    "returns_wide": {
        "directory": "returns_wide",
        "partitioning": ("year",),
        "logical_key": ("Date",),
        "compatibility_index_columns": ("Date",),
        "source_name": "returns",
    },
}


@dataclass(frozen=True)
class MigrationResult:
    dataset_name: str
    status: str
    source_path: str
    manifest_path: str | None
    current_pointer: str | None
    dataset_version: str | None
    profile: dict[str, Any]
    compatibility_exports: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "status": self.status,
            "source_path": self.source_path,
            "manifest_path": self.manifest_path,
            "current_pointer": self.current_pointer,
            "dataset_version": self.dataset_version,
            "profile": self.profile,
            "compatibility_exports": list(self.compatibility_exports),
        }


def migrate_dataset(
    source_path: str | Path,
    *,
    dataset_name: str,
    root: str | Path,
    apply: bool = False,
    source_run_id: str | None = None,
    write_compatibility_export: bool = False,
    compatibility_export_path: str | Path | None = None,
) -> MigrationResult:
    """Create an immutable partition mirror without changing the source file."""

    if dataset_name not in DATASET_SETTINGS:
        raise ValueError(f"unsupported dataset: {dataset_name!r}")
    workspace = Path(root).resolve()
    source = Path(source_path)
    if not source.is_absolute():
        source = workspace / source
    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    source_profile = parquet_profile(source)
    if not apply:
        return MigrationResult(
            dataset_name=dataset_name,
            status="dry_run",
            source_path=_relative(source, workspace),
            manifest_path=None,
            current_pointer=None,
            dataset_version=None,
            profile=source_profile,
            compatibility_exports=_compatibility_status(source, workspace),
        )

    manifest, manifest_path, pointer_path = _write_partition_mirror(
        source,
        dataset_name=dataset_name,
        root=workspace,
        source_run_id=source_run_id,
    )
    export_status = _compatibility_status(Path(compatibility_export_path or source), workspace)
    if write_compatibility_export:
        if compatibility_export_path is None:
            raise ValueError("compatibility_export_path is required when writing an export")
        write_compatibility_export_from_manifest(manifest, compatibility_export_path, root=workspace)
        export_status = tuple({**item, "status": "written"} for item in _compatibility_status(Path(compatibility_export_path), workspace))
    return MigrationResult(
        dataset_name=dataset_name,
        status="applied",
        source_path=_relative(source, workspace),
        manifest_path=_relative(manifest_path, workspace),
        current_pointer=_relative(pointer_path, workspace),
        dataset_version=manifest.dataset_version,
        profile=source_profile,
        compatibility_exports=export_status,
    )


def validate_mirror(
    source_path: str | Path,
    manifest_path: str | Path,
    *,
    root: str | Path,
) -> dict[str, Any]:
    """Re-scan source and mirror partitions and compare row/value fingerprints."""

    workspace = Path(root).resolve()
    source = Path(source_path)
    if not source.is_absolute():
        source = workspace / source
    source = source.resolve()
    manifest_target = Path(manifest_path)
    if not manifest_target.is_absolute():
        manifest_target = workspace / manifest_target
    manifest = load_manifest(manifest_target, require_files=True, root=workspace)
    settings = DATASET_SETTINGS.get(manifest.dataset_name)
    if settings is None:
        raise ValueError(f"unsupported manifest dataset: {manifest.dataset_name!r}")
    expected = _source_partition_digests(source, manifest.dataset_name, settings)
    actual: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    for partition in manifest.partitions:
        key = _partition_key_string(partition)
        path = _resolve_partition(manifest, partition, workspace)
        if not path.exists():
            issues.append(f"missing partition: {path}")
            continue
        file_hash = _sha256_file(path)
        digest = _parquet_content_digest(path)
        profile = parquet_profile(path)
        actual[key] = {
            "rows": profile.get("rows"),
            "sha256": file_hash,
            "content_fingerprint": digest,
            "schema_fingerprint": profile.get("schema_fingerprint"),
        }
        if file_hash != partition.get("sha256"):
            issues.append(f"content hash mismatch: {key}")
        if digest != expected.get(key, {}).get("content_fingerprint"):
            issues.append(f"value fingerprint mismatch: {key}")
        if profile.get("rows") != partition.get("row_count"):
            issues.append(f"row count mismatch: {key}")
    if set(expected) != set(actual):
        issues.append("partition key sets differ")
    source_profile = parquet_profile(source)
    manifest_rows = sum(int(item.get("row_count", 0)) for item in manifest.partitions)
    if manifest_rows != source_profile.get("rows"):
        issues.append("total row count mismatch")
    if manifest.payload.get("source_sha256") != _sha256_file(source):
        issues.append("source file changed since mirror creation")
    return {
        "status": "passed" if not issues else "failed",
        "dataset_name": manifest.dataset_name,
        "dataset_version": manifest.dataset_version,
        "source": source_profile,
        "manifest_path": _relative(manifest_target, workspace),
        "expected_partitions": expected,
        "actual_partitions": actual,
        "issues": issues,
    }


def load_current_manifest(pointer_path: str | Path, *, root: str | Path) -> DatasetManifest:
    workspace = Path(root).resolve()
    pointer = Path(pointer_path)
    if not pointer.is_absolute():
        pointer = workspace / pointer
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    target = Path(str(payload["manifest_path"]))
    if not target.is_absolute():
        target = workspace / target
    return load_manifest(target, require_files=True, root=workspace)


def write_compatibility_export_from_manifest(
    manifest: DatasetManifest,
    output_path: str | Path,
    *,
    root: str | Path,
) -> None:
    """Rebuild one legacy-compatible wide file atomically from explicit parts."""

    workspace = Path(root).resolve()
    output = Path(output_path)
    if not output.is_absolute():
        output = workspace / output
    output.parent.mkdir(parents=True, exist_ok=True)
    partitions = sorted(manifest.partitions, key=_partition_sort_key)
    if not partitions:
        raise ValueError("cannot export an empty manifest")
    first = _resolve_partition(manifest, partitions[0], workspace)
    schema = _compatibility_schema(manifest, pq.ParquetFile(first).schema_arrow)
    temporary = output.with_name(f".{output.name}.tmp-{os.getpid()}")
    lock_path = output.with_suffix(output.suffix + ".lock")
    try:
        with FileLock(lock_path):
            writer = pq.ParquetWriter(temporary, schema=schema, compression="zstd")
            try:
                for partition in partitions:
                    path = _resolve_partition(manifest, partition, workspace)
                    parquet = pq.ParquetFile(path)
                    for batch in parquet.iter_batches(batch_size=65_536, use_threads=False):
                        table = pa.Table.from_batches([batch], schema=parquet.schema_arrow)
                        table = pa.Table.from_arrays(list(table.columns), schema=schema)
                        writer.write_table(table)
            finally:
                writer.close()
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_partition_mirror(
    source: Path,
    *,
    dataset_name: str,
    root: Path,
    source_run_id: str | None,
) -> tuple[DatasetManifest, Path, Path]:
    settings = DATASET_SETTINGS[dataset_name]
    parquet = pq.ParquetFile(source)
    source_schema = parquet.schema_arrow
    source_names = list(source_schema.names)
    source_date_field = _source_date_field(source_names, source)
    schema = _canonical_schema(source_schema, dataset_name, source_date_field)
    names = list(schema.names)
    source_sha256 = _sha256_file(source)
    dataset_version = f"{dataset_name}-{source_sha256[:20]}-{_schema_fingerprint(schema)[:12]}"
    dataset_root = root / "00_screen" / "datasets"
    partition_root = dataset_root / str(settings["directory"])
    manifest_root = dataset_root / "manifests" / str(settings["directory"])
    manifest_path = manifest_root / f"{dataset_version}.json"
    pointer_path = manifest_root / "current.json"
    previous_version = _current_dataset_version(pointer_path)
    if previous_version == dataset_version or not (manifest_root / f"{previous_version}.json").exists():
        previous_version = None
    staging_root = dataset_root / "staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f"{dataset_name}-{os.getpid()}-", dir=staging_root))
    writers: dict[str, pq.ParquetWriter] = {}
    stats: dict[str, dict[str, Any]] = {}
    try:
        for batch in parquet.iter_batches(batch_size=65_536, use_threads=False):
            source_table = pa.Table.from_batches([batch], schema=source_schema)
            table = _canonicalize_table(
                source_table,
                canonical_schema=schema,
            )
            for key, filtered in _partition_tables(
                table,
                date_field="Date",
                by_month=len(settings["partitioning"]) == 2,
            ):
                key_payload = {"year": key[0], **({"month": key[1]} if len(key) == 2 else {})}
                key_string = _partition_key_string(key_payload)
                if key_string not in writers:
                    part_staging = staging_dir / key_string
                    part_staging.mkdir(parents=True, exist_ok=True)
                    writers[key_string] = pq.ParquetWriter(
                        part_staging / "part.tmp.parquet",
                        schema=schema,
                        compression="zstd",
                    )
                    stats[key_string] = {
                        "year": key[0],
                        "month": key[1] if len(key) == 2 else None,
                        "row_count": 0,
                        "date_min": None,
                        "date_max": None,
                        "digest": hashlib.sha256(),
                    }
                writers[key_string].write_table(filtered)
                state = stats[key_string]
                state["row_count"] += filtered.num_rows
                date_values = [_as_date(value) for value in filtered["Date"].to_pylist()]
                non_null_dates = _not_none_dates(date_values)
                if non_null_dates:
                    state["date_min"] = min(non_null_dates) if state["date_min"] is None else min(state["date_min"], min(non_null_dates))
                    state["date_max"] = max(non_null_dates) if state["date_max"] is None else max(state["date_max"], max(non_null_dates))
                _update_table_digest(state["digest"], filtered)
    finally:
        for writer in writers.values():
            writer.close()
    partitions: list[dict[str, Any]] = []
    for key_string in sorted(stats, key=_partition_sort_key):
        state = stats[key_string]
        temp_file = staging_dir / key_string / "part.tmp.parquet"
        file_hash = _sha256_file(temp_file)
        final_dir = partition_root / key_string
        final_dir.mkdir(parents=True, exist_ok=True)
        final_file = final_dir / f"part-{file_hash}.parquet"
        if final_file.exists():
            temp_file.unlink()
        else:
            os.replace(temp_file, final_file)
        duplicate_rows = _duplicate_key_rows(
            final_file,
            tuple(settings["logical_key"]),
        )
        partitions.append(
            {
                "year": state["year"],
                **({"month": state["month"]} if state["month"] is not None else {}),
                "partition_key": key_string,
                "path": _relative(final_file, root),
                "sha256": file_hash,
                "bytes": final_file.stat().st_size,
                "row_count": state["row_count"],
                "row_groups": pq.ParquetFile(final_file).metadata.num_row_groups,
                "date_min": _date_iso(state["date_min"]),
                "date_max": _date_iso(state["date_max"]),
                "key_duplicate_rows": duplicate_rows,
                "content_fingerprint": state["digest"].hexdigest(),
            }
        )
    schema_fingerprint = _schema_fingerprint(schema)
    start_dates = [date.fromisoformat(item["date_min"]) for item in partitions if item.get("date_min")]
    end_dates = [date.fromisoformat(item["date_max"]) for item in partitions if item.get("date_max")]
    payload: dict[str, Any] = {
        "schema_version": "tp.dataset-manifest.v1",
        "dataset_name": dataset_name,
        "dataset_version": dataset_version,
        "created_at": datetime.now(UTC).isoformat(),
        "source_run_id": source_run_id or f"mirror-{dataset_version}",
        "source_path": _relative(source, root),
        "source_sha256": source_sha256,
        "logical_key": list(settings["logical_key"]),
        "partitioning": list(settings["partitioning"]),
        "schema_fingerprint": schema_fingerprint,
        "row_count": int(sum(item["row_count"] for item in partitions)),
        "date_min": min(start_dates).isoformat() if start_dates else None,
        "date_max": max(end_dates).isoformat() if end_dates else None,
        "partitions": partitions,
        "parent_dataset_version": previous_version or "",
        "validation_status": "passed",
        "compatibility_export": {
            "path": _relative(source, root),
            "status": "legacy_file_preserved",
            "source_role": "compatibility_export",
            "authoritative_dataset_version": dataset_version,
        },
        "compatibility_index_columns": list(settings["compatibility_index_columns"]),
    }
    if dataset_name == "returns_wide":
        payload.update(
            {
                "date_is_column": "Date" in names,
                "date_index_field": None,
                "source_date_field": source_date_field,
                "security_column_count": len([name for name in names if name != "Date"]),
                "security_columns_by_year": {
                    str(item["year"]): len([name for name in names if name != "Date"]) for item in partitions
                },
                "schema_evolution": {"columns": names, "missing_columns": [], "duplicate_columns": []},
                "extreme_return_qa_fingerprint": _extreme_return_fingerprint(source),
            }
        )
    _write_immutable_manifest(manifest_path, payload)
    pointer_payload = {
        "schema_version": "tp.dataset-pointer.v1",
        "dataset_name": dataset_name,
        "dataset_version": dataset_version,
        "manifest_path": _relative(manifest_path, root),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    write_json_atomic(pointer_path, pointer_payload)
    shutil.rmtree(staging_dir, ignore_errors=False)
    return load_manifest(manifest_path, require_files=True, root=root), manifest_path, pointer_path


def _source_partition_digests(
    source: Path,
    dataset_name: str,
    settings: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    parquet = pq.ParquetFile(source)
    source_schema = parquet.schema_arrow
    source_date_field = _source_date_field(list(source_schema.names), source)
    canonical_schema = _canonical_schema(source_schema, dataset_name, source_date_field)
    expected: dict[str, dict[str, Any]] = {}
    for batch in parquet.iter_batches(batch_size=65_536, use_threads=False):
        source_table = pa.Table.from_batches([batch], schema=source_schema)
        table = _canonicalize_table(source_table, canonical_schema=canonical_schema)
        for key, filtered in _partition_tables(
            table,
            date_field="Date",
            by_month=len(settings["partitioning"]) == 2,
        ):
            key_payload = {"year": key[0], **({"month": key[1]} if len(key) == 2 else {})}
            key_string = _partition_key_string(key_payload)
            state = expected.setdefault(key_string, {"rows": 0, "digest": hashlib.sha256()})
            state["rows"] += filtered.num_rows
            _update_table_digest(state["digest"], filtered)
    return {
        key: {"rows": state["rows"], "content_fingerprint": state["digest"].hexdigest()}
        for key, state in expected.items()
    }


def _canonical_schema(schema: pa.Schema, dataset_name: str, source_date_field: str) -> pa.Schema:
    names = list(schema.names)
    if dataset_name == "returns_wide" and source_date_field != "Date":
        names[names.index(source_date_field)] = "Date"
    fields = [pa.field(name, field.type, nullable=field.nullable) for name, field in zip(names, schema)]
    return pa.schema(fields)


def _canonicalize_table(table: pa.Table, *, canonical_schema: pa.Schema) -> pa.Table:
    return pa.Table.from_arrays(list(table.columns), schema=canonical_schema)


def _compatibility_schema(manifest: DatasetManifest, schema: pa.Schema) -> pa.Schema:
    index_columns = set(manifest.payload.get("compatibility_index_columns", ()))
    fields = [pa.field(field.name, field.type, nullable=field.nullable) for field in schema]
    metadata = dict(schema.metadata or {})
    metadata[b"pandas"] = json.dumps(
        {
            "index_columns": [name for name in schema.names if name in index_columns],
            "column_indexes": [
                {
                    "name": None,
                    "field_name": None,
                    "pandas_type": "unicode",
                    "numpy_type": "object",
                    "metadata": {"encoding": "UTF-8"},
                }
            ],
            "columns": [_pandas_column_metadata(field) for field in schema],
            "creator": {"library": "pyarrow", "version": pa.__version__},
            "pandas_version": pd.__version__,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    return pa.schema(fields, metadata=metadata)


def _pandas_column_metadata(field: pa.Field) -> dict[str, Any]:
    if pa.types.is_timestamp(field.type):
        pandas_type, numpy_type = "datetime", "datetime64[ns]"
    elif pa.types.is_floating(field.type):
        pandas_type, numpy_type = "float64", "float64"
    elif pa.types.is_integer(field.type):
        pandas_type, numpy_type = "int64", "int64"
    elif pa.types.is_boolean(field.type):
        pandas_type, numpy_type = "bool", "bool"
    else:
        pandas_type, numpy_type = "unicode", "object"
    return {
        "name": field.name,
        "field_name": field.name,
        "pandas_type": pandas_type,
        "numpy_type": numpy_type,
        "metadata": None,
    }


def _partition_tables(
    table: pa.Table,
    *,
    date_field: str,
    by_month: bool,
) -> Iterable[tuple[tuple[int, ...], pa.Table]]:
    values = [_as_date(value) for value in table[date_field].to_pylist()]
    keys = sorted({(value.year, value.month) if by_month else (value.year,) for value in values if value is not None})
    for key in keys:
        mask = pa.array([
            value is not None and ((value.year, value.month) if by_month else (value.year,)) == key
            for value in values
        ])
        yield key, table.filter(mask)


def _update_table_digest(digest: Any, table: pa.Table) -> None:
    frame = table.to_pandas(ignore_metadata=True, split_blocks=True)
    values = pd.util.hash_pandas_object(frame, index=False).to_numpy(dtype="uint64", copy=False)
    digest.update(values.tobytes())


def _parquet_content_digest(path: Path) -> str:
    parquet = pq.ParquetFile(path)
    digest = hashlib.sha256()
    for batch in parquet.iter_batches(batch_size=65_536, use_threads=False):
        _update_table_digest(digest, pa.Table.from_batches([batch], schema=parquet.schema_arrow))
    return digest.hexdigest()


def _duplicate_key_rows(path: Path, key_columns: tuple[str, ...]) -> int:
    names = pq.ParquetFile(path).schema_arrow.names
    physical_columns = tuple(
        column if column in names else "__index_level_0__" if column == "Date" else column
        for column in key_columns
    )
    frame = pq.read_table(path, columns=list(physical_columns)).to_pandas(ignore_metadata=True)
    return int(frame.duplicated(list(physical_columns)).sum())


def _extreme_return_fingerprint(path: Path) -> str:
    parquet = pq.ParquetFile(path)
    sample = pq.read_table(path, columns=list(parquet.schema_arrow.names[: min(8, len(parquet.schema_arrow.names))]))
    frame = sample.to_pandas(ignore_metadata=True)
    numeric = frame.select_dtypes(include="number")
    if numeric.empty:
        return hashlib.sha256(b"no_numeric_columns").hexdigest()
    values = pd.Series(numeric.to_numpy().ravel()).dropna()
    extremes = values[(values < -50) | (values > 50)].astype("float64")
    return hashlib.sha256(pd.util.hash_pandas_object(extremes).to_numpy().tobytes()).hexdigest()


def _write_immutable_manifest(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        immutable_keys = (
            "schema_version",
            "dataset_name",
            "dataset_version",
            "source_path",
            "source_sha256",
            "logical_key",
            "partitioning",
            "schema_fingerprint",
            "row_count",
            "date_min",
            "date_max",
            "partitions",
            "validation_status",
        )
        if manifest_fingerprint({key: existing.get(key) for key in immutable_keys}) != manifest_fingerprint({key: payload.get(key) for key in immutable_keys}):
            raise ValueError(f"immutable manifest already exists with different content: {path}")
        return
    write_json_atomic(path, payload)


def _compatibility_status(path: Path, root: Path) -> tuple[dict[str, Any], ...]:
    return (
        {
            "path": _relative(path.resolve(), root),
            "exists": path.exists(),
            "status": "legacy_file_preserved",
        },
    )


def _current_dataset_version(pointer_path: Path) -> str | None:
    if not pointer_path.exists():
        return None
    try:
        payload = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return str(payload.get("dataset_version")) if payload.get("dataset_version") else None


def _partition_key_string(partition: Mapping[str, Any]) -> str:
    values = [f"year={int(partition['year'])}"]
    if partition.get("month") is not None:
        values.append(f"month={int(partition['month']):02d}")
    return "/".join(values)


def _partition_sort_key(value: Mapping[str, Any] | str) -> tuple[int, int]:
    text = value if isinstance(value, str) else _partition_key_string(value)
    year = int(text.split("year=", 1)[1].split("/", 1)[0])
    month = int(text.split("month=", 1)[1]) if "month=" in text else 0
    return year, month


def _resolve_partition(manifest: DatasetManifest, partition: Mapping[str, Any], root: Path) -> Path:
    path = Path(str(partition["path"]))
    return path if path.is_absolute() else root / path


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _source_date_field(names: list[str], source: Path) -> str:
    if "Date" in names:
        return "Date"
    if "__index_level_0__" in names:
        return "__index_level_0__"
    raise ValueError(f"source does not expose a Date column or pandas Date index: {source}")


def _not_none_dates(values: Iterable[date | None]) -> list[date]:
    return [value for value in values if value is not None]


def _date_iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _schema_fingerprint(schema: pa.Schema) -> str:
    description = "\n".join(f"{field.name}:{field.type}" for field in schema)
    return hashlib.sha256(description.encode("utf-8")).hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


__all__ = [
    "DATASET_SETTINGS",
    "MigrationResult",
    "load_current_manifest",
    "migrate_dataset",
    "validate_mirror",
    "write_compatibility_export_from_manifest",
]

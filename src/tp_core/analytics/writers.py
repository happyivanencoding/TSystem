"""Incremental immutable writers for the canonical Screen and Returns lake."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, TypeAlias

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .locking import FileLock
from .manifests import DatasetManifest, load_manifest, write_json_atomic
from .partitioning import (
    DATASET_SETTINGS,
    _canonical_schema,
    _compatibility_schema,
    _extreme_return_fingerprint,
    _parquet_content_digest,
    _partition_key_string,
    _resolve_partition,
    _schema_fingerprint,
    _sha256_file,
    _source_date_field,
    load_current_manifest,
    write_compatibility_export_from_manifest,
)

DateLike: TypeAlias = date | datetime | pd.Timestamp


@dataclass(frozen=True)
class PartitionWriterResult:
    """Evidence returned by one incremental dataset update."""

    dataset_name: str
    status: str
    source_path: str
    manifest_path: str | None
    current_pointer: str | None
    dataset_version: str | None
    affected_partition_keys: tuple[str, ...]
    written_partition_keys: tuple[str, ...]
    reused_partition_keys: tuple[str, ...]
    removed_partition_keys: tuple[str, ...]
    compatibility_exports: tuple[dict[str, Any], ...]
    validation: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "status": self.status,
            "source_path": self.source_path,
            "manifest_path": self.manifest_path,
            "current_pointer": self.current_pointer,
            "dataset_version": self.dataset_version,
            "affected_partition_keys": list(self.affected_partition_keys),
            "written_partition_keys": list(self.written_partition_keys),
            "reused_partition_keys": list(self.reused_partition_keys),
            "removed_partition_keys": list(self.removed_partition_keys),
            "compatibility_exports": list(self.compatibility_exports),
            "validation": self.validation,
        }


def update_dataset_partitions(
    source_path: str | Path,
    *,
    dataset_name: str,
    root: str | Path,
    affected_dates: Iterable[DateLike] = (),
    apply: bool = False,
    source_run_id: str | None = None,
    compatibility_export_paths: Sequence[str | Path] = (),
) -> PartitionWriterResult:
    """Update only affected immutable parts and atomically publish a manifest.

    ``source_path`` is the validated post-update snapshot produced by the
    existing business calculation.  The writer reads only the requested
    month/year slices from that snapshot, reuses all other manifest entries,
    and publishes a new pointer only after every new object and compatibility
    export has been validated.
    """

    if dataset_name not in DATASET_SETTINGS:
        raise ValueError(f"unsupported dataset: {dataset_name!r}")
    workspace = Path(root).resolve()
    source = Path(source_path)
    if not source.is_absolute():
        source = workspace / source
    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    manifest_root = workspace / "00_screen" / "datasets" / "manifests" / dataset_name
    pointer_path = manifest_root / "current.json"
    if not pointer_path.exists():
        raise FileNotFoundError(f"current dataset pointer is required: {pointer_path}")
    current = load_current_manifest(pointer_path, root=workspace)
    source_parquet = pq.ParquetFile(source)
    source_schema = source_parquet.schema_arrow
    source_date_field = _source_date_field(list(source_schema.names), source)
    canonical_schema = _canonical_schema(source_schema, dataset_name, source_date_field)
    settings = DATASET_SETTINGS[dataset_name]
    dates = tuple(_coerce_date(value) for value in affected_dates)
    affected: dict[str, dict[str, int]] = {}
    for value in dates:
        key = _date_partition_key(value, dataset_name)
        affected[_partition_key_string(key)] = key
    if not affected:
        affected = _all_source_partition_keys(source, source_date_field, dataset_name)
    affected_strings = tuple(sorted(affected))

    old_partitions = {
        _partition_key_string(partition): dict(partition) for partition in current.partitions
    }
    if not apply:
        source_rows = int(source_parquet.metadata.num_rows)
        validation = {
            "status": "dry_run",
            "source_rows": source_rows,
            "current_rows": int(sum(int(item.get("row_count", 0)) for item in old_partitions.values())),
            "affected_partition_count": len(affected_strings),
            "source_date_field": source_date_field,
            "schema_fingerprint": _schema_fingerprint(canonical_schema),
        }
        return PartitionWriterResult(
            dataset_name=dataset_name,
            status="dry_run",
            source_path=_relative(source, workspace),
            manifest_path=_relative(current.path, workspace),
            current_pointer=_relative(pointer_path, workspace),
            dataset_version=current.dataset_version,
            affected_partition_keys=affected_strings,
            written_partition_keys=(),
            reused_partition_keys=tuple(sorted(set(old_partitions) - set(affected_strings))),
            removed_partition_keys=(),
            compatibility_exports=tuple(
                {"path": _relative(Path(path).resolve(), workspace), "status": "dry_run"}
                for path in compatibility_export_paths
            ),
            validation=validation,
        )

    dataset_root = workspace / "00_screen" / "datasets"
    partition_root = dataset_root / str(settings["directory"])
    manifest_root.mkdir(parents=True, exist_ok=True)
    staging_root = dataset_root / "staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    lock_path = dataset_root / ".partition-writer.lock"
    staging_dir = Path(tempfile.mkdtemp(prefix=f"{dataset_name}-update-", dir=staging_root))
    new_partitions = dict(old_partitions)
    written_keys: list[str] = []
    removed_keys: list[str] = []
    try:
        with FileLock(lock_path):
            for key_string in sorted(affected):
                key = affected[key_string]
                table = _read_source_partition(
                    source,
                    source_date_field=source_date_field,
                    canonical_schema=canonical_schema,
                    dataset_name=dataset_name,
                    key=key,
                )
                if table.num_rows == 0:
                    if key_string in new_partitions:
                        removed_keys.append(key_string)
                        new_partitions.pop(key_string)
                    continue
                duplicate_rows = _duplicate_key_rows_from_table(table, tuple(settings["logical_key"]))
                if duplicate_rows:
                    raise ValueError(f"duplicate logical keys in updated partition {key_string}: {duplicate_rows}")
                part_staging = staging_dir / key_string.replace("/", "_")
                part_staging.mkdir(parents=True, exist_ok=True)
                temporary = part_staging / "part.tmp.parquet"
                pq.write_table(table, temporary, compression="zstd", row_group_size=65_536)
                file_hash = _sha256_file(temporary)
                final_dir = partition_root / key_string
                final_dir.mkdir(parents=True, exist_ok=True)
                final_file = final_dir / f"part-{file_hash}.parquet"
                if not final_file.exists():
                    os.replace(temporary, final_file)
                else:
                    temporary.unlink()
                dates_in_partition = pd.to_datetime(table["Date"].to_pandas(), errors="coerce").dropna()
                new_partitions[key_string] = {
                    "year": int(key["year"]),
                    **({"month": int(key["month"])} if key.get("month") is not None else {}),
                    "partition_key": key_string,
                    "path": _relative(final_file, workspace),
                    "sha256": file_hash,
                    "bytes": final_file.stat().st_size,
                    "row_count": int(table.num_rows),
                    "row_groups": int(pq.ParquetFile(final_file).metadata.num_row_groups),
                    "date_min": dates_in_partition.min().date().isoformat(),
                    "date_max": dates_in_partition.max().date().isoformat(),
                    "key_duplicate_rows": 0,
                    "content_fingerprint": _parquet_content_digest(final_file),
                }
                written_keys.append(key_string)

            source_rows = int(source_parquet.metadata.num_rows)
            manifest_rows = int(sum(int(item.get("row_count", 0)) for item in new_partitions.values()))
            if source_rows != manifest_rows:
                raise ValueError(
                    "updated partition rows do not cover source rows; "
                    f"source={source_rows}, manifest={manifest_rows}, affected={affected_strings}"
                )
            ordered_partitions = sorted(new_partitions.values(), key=_partition_sort_key)
            schema_fingerprint = _schema_fingerprint(canonical_schema)
            source_sha256 = _sha256_file(source)
            dataset_version = f"{dataset_name}-{source_sha256[:20]}-{schema_fingerprint[:12]}"
            payload = _updated_manifest_payload(
                current,
                dataset_name=dataset_name,
                dataset_version=dataset_version,
                source=source,
                root=workspace,
                source_sha256=source_sha256,
                source_run_id=source_run_id,
                canonical_schema=canonical_schema,
                partitions=ordered_partitions,
            )
            manifest_path = manifest_root / f"{dataset_version}.json"
            _write_manifest_immutable(manifest_path, payload)
            manifest = load_manifest(manifest_path, require_files=True, root=workspace)
            source_parquet.close()
            exports = _write_exports(
                manifest,
                compatibility_export_paths,
                root=workspace,
            )
            pointer_payload = {
                "schema_version": "tp.dataset-pointer.v1",
                "dataset_name": dataset_name,
                "dataset_version": dataset_version,
                "manifest_path": _relative(manifest_path, workspace),
                "updated_at": datetime.now().astimezone().isoformat(),
            }
            write_json_atomic(pointer_path, pointer_payload)
            validation = {
                "status": "passed",
                "source_rows": source_rows,
                "manifest_rows": manifest_rows,
                "source_date_field": source_date_field,
                "schema_fingerprint": schema_fingerprint,
                "non_affected_hashes_reused": _non_affected_hashes_reused(
                    old_partitions,
                    new_partitions,
                    set(affected_strings),
                ),
            }
            return PartitionWriterResult(
                dataset_name=dataset_name,
                status="applied",
                source_path=_relative(source, workspace),
                manifest_path=_relative(manifest_path, workspace),
                current_pointer=_relative(pointer_path, workspace),
                dataset_version=dataset_version,
                affected_partition_keys=affected_strings,
                written_partition_keys=tuple(sorted(written_keys)),
                reused_partition_keys=tuple(sorted(set(old_partitions) - set(affected_strings))),
                removed_partition_keys=tuple(sorted(removed_keys)),
                compatibility_exports=tuple(exports),
                validation=validation,
            )
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def rollback_dataset(
    *,
    dataset_name: str,
    root: str | Path,
    dataset_version: str,
    apply: bool = False,
) -> dict[str, Any]:
    """Move a dataset current pointer back to an immutable manifest."""

    if dataset_name not in DATASET_SETTINGS:
        raise ValueError(f"unsupported dataset: {dataset_name!r}")
    workspace = Path(root).resolve()
    manifest_root = workspace / "00_screen" / "datasets" / "manifests" / dataset_name
    pointer = manifest_root / "current.json"
    target = manifest_root / f"{dataset_version}.json"
    if not target.exists():
        raise FileNotFoundError(target)
    target_manifest = load_manifest(target, require_files=True, root=workspace)
    current_payload = json.loads(pointer.read_text(encoding="utf-8")) if pointer.exists() else {}
    payload = {
        "schema_version": "tp.dataset-pointer.v1",
        "dataset_name": dataset_name,
        "dataset_version": target_manifest.dataset_version,
        "manifest_path": _relative(target, workspace),
        "updated_at": datetime.now().astimezone().isoformat(),
    }
    result = {
        "status": "dry_run" if not apply else "applied",
        "dataset_name": dataset_name,
        "from_dataset_version": current_payload.get("dataset_version"),
        "to_dataset_version": target_manifest.dataset_version,
        "manifest_path": _relative(target, workspace),
        "current_pointer": _relative(pointer, workspace),
    }
    if apply:
        lock_path = workspace / "00_screen" / "datasets" / ".partition-writer.lock"
        with FileLock(lock_path):
            export_paths = _manifest_compatibility_paths(target_manifest, root=workspace)
            result["compatibility_exports"] = _write_exports(
                target_manifest,
                export_paths,
                root=workspace,
            )
            write_json_atomic(pointer, payload)
    return result


def _read_source_partition(
    source: Path,
    *,
    source_date_field: str,
    canonical_schema: pa.Schema,
    dataset_name: str,
    key: Mapping[str, int],
) -> pa.Table:
    year = int(key["year"])
    if key.get("month") is None:
        lower = pd.Timestamp(year=year, month=1, day=1)
        upper = pd.Timestamp(year=year, month=12, day=31)
    else:
        month = int(key["month"])
        lower = pd.Timestamp(year=year, month=month, day=1)
        upper = lower + pd.offsets.MonthEnd(0)
    table = pq.read_table(
        source,
        filters=[(source_date_field, ">=", lower.to_pydatetime()), (source_date_field, "<=", upper.to_pydatetime())],
    )
    table = pa.Table.from_arrays(list(table.columns), schema=canonical_schema)
    sort_columns = [column for column in ("Date", "ISIN") if column in table.column_names]
    if dataset_name == "returns_wide":
        sort_columns = ["Date"]
    if sort_columns:
        table = table.sort_by([(column, "ascending") for column in sort_columns])
    return table


def _updated_manifest_payload(
    current: DatasetManifest,
    *,
    dataset_name: str,
    dataset_version: str,
    source: Path,
    root: Path,
    source_sha256: str,
    source_run_id: str | None,
    canonical_schema: pa.Schema,
    partitions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    dates_min = [item["date_min"] for item in partitions if item.get("date_min")]
    dates_max = [item["date_max"] for item in partitions if item.get("date_max")]
    payload = dict(current.payload)
    payload.update(
        {
            "schema_version": "tp.dataset-manifest.v1",
            "dataset_name": dataset_name,
            "dataset_version": dataset_version,
            "created_at": datetime.now().astimezone().isoformat(),
            "source_run_id": source_run_id or f"partition-update-{dataset_version}",
            "source_path": _relative(source, root),
            "source_sha256": source_sha256,
            "schema_fingerprint": _schema_fingerprint(canonical_schema),
            "row_count": int(sum(int(item.get("row_count", 0)) for item in partitions)),
            "date_min": min(dates_min) if dates_min else None,
            "date_max": max(dates_max) if dates_max else None,
            "partitions": [dict(item) for item in partitions],
            "parent_dataset_version": current.dataset_version,
            "validation_status": "passed",
            "compatibility_export": {
                **dict(current.payload.get("compatibility_export", {})),
                "status": "generated_from_manifest",
                "source_role": "compatibility_export",
                "authoritative_dataset_version": dataset_version,
            },
        }
    )
    if dataset_name == "returns_wide":
        names = list(canonical_schema.names)
        payload.update(
            {
                "date_is_column": "Date" in names,
                "date_index_field": None,
                "security_column_count": len([name for name in names if name != "Date"]),
                "security_columns_by_year": {
                    str(item["year"]): len([name for name in names if name != "Date"])
                    for item in partitions
                },
                "schema_evolution": {"columns": names, "missing_columns": [], "duplicate_columns": []},
                "extreme_return_qa_fingerprint": _extreme_return_fingerprint(source),
            }
        )
    return payload


def _write_exports(
    manifest: DatasetManifest,
    paths: Sequence[str | Path],
    *,
    root: Path,
) -> list[dict[str, Any]]:
    exports: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = root / path
        if manifest.dataset_name == "screen" and path.name in {"last_screen.parquet", "screen_aggregate_5Y.parquet"}:
            _write_screen_slice_export(manifest, path, root=root, latest_only=path.name == "last_screen.parquet")
        else:
            write_compatibility_export_from_manifest(manifest, path, root=root)
        exports.append(
            {
                "path": _relative(path.resolve(), root),
                "status": "written",
                "source_role": "compatibility_export",
                "authoritative_dataset_version": manifest.dataset_version,
            }
        )
    return exports


def _manifest_compatibility_paths(manifest: DatasetManifest, *, root: Path) -> tuple[Path, ...]:
    raw_path = manifest.payload.get("compatibility_export", {}).get("path")
    if not raw_path:
        return ()
    primary = Path(str(raw_path))
    if not primary.is_absolute():
        primary = root / primary
    if manifest.dataset_name != "screen":
        return (primary,)
    return (
        primary,
        primary.with_name("last_screen.parquet"),
        primary.with_name(f"{primary.stem}_5Y{primary.suffix}"),
    )


def _write_screen_slice_export(
    manifest: DatasetManifest,
    output: Path,
    *,
    root: Path,
    latest_only: bool,
) -> None:
    latest = pd.Timestamp(manifest.payload["date_max"])
    cutoff = latest - pd.DateOffset(years=5)
    first_path = _resolve_partition(manifest, manifest.partitions[0], root=root)
    first_schema = pq.ParquetFile(first_path).schema_arrow
    schema = _compatibility_schema(manifest, first_schema)
    temporary = output.with_name(f".{output.name}.tmp-{os.getpid()}")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(output.with_suffix(output.suffix + ".lock")):
            writer = pq.ParquetWriter(temporary, schema=schema, compression="zstd")
            try:
                for partition in manifest.partitions:
                    partition_path = _resolve_partition(manifest, partition, root=root)
                    lower = latest if latest_only else cutoff.to_pydatetime()
                    filters = [("Date", ">=", lower)]
                    if latest_only:
                        filters.append(("Date", "<=", latest.to_pydatetime()))
                    table = pq.read_table(partition_path, partitioning=None, filters=filters)
                    if table.num_rows:
                        writer.write_table(pa.Table.from_arrays(list(table.columns), schema=schema))
            finally:
                writer.close()
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_manifest_immutable(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        existing = load_manifest(path).payload
        keys = (
            "schema_version",
            "dataset_name",
            "dataset_version",
            "source_path",
            "source_sha256",
            "schema_fingerprint",
            "row_count",
            "date_min",
            "date_max",
            "partitions",
            "validation_status",
        )
        existing_fingerprint = _fingerprint_subset(existing, keys)
        new_fingerprint = _fingerprint_subset(payload, keys)
        if existing_fingerprint != new_fingerprint:
            raise ValueError(f"immutable manifest already exists with different content: {path}")
        return
    write_json_atomic(path, payload)


def _fingerprint_subset(payload: Mapping[str, Any], keys: Sequence[str]) -> str:
    encoded = json.dumps({key: payload.get(key) for key in keys}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _non_affected_hashes_reused(
    old: Mapping[str, Mapping[str, Any]],
    new: Mapping[str, Mapping[str, Any]],
    affected: set[str],
) -> bool:
    return all(old[key].get("sha256") == new.get(key, {}).get("sha256") for key in set(old) - affected)


def _all_source_partition_keys(
    source: Path,
    source_date_field: str,
    dataset_name: str,
) -> dict[str, dict[str, int]]:
    dates = pq.read_table(source, columns=[source_date_field])[source_date_field].to_pylist()
    keys: dict[str, dict[str, int]] = {}
    for value in dates:
        if value is None:
            continue
        key = _date_partition_key(_coerce_date(value), dataset_name)
        keys[_partition_key_string(key)] = key
    return keys


def _date_partition_key(value: date, dataset_name: str) -> dict[str, int]:
    key = {"year": value.year}
    if len(DATASET_SETTINGS[dataset_name]["partitioning"]) == 2:
        key["month"] = value.month
    return key


def _coerce_date(value: DateLike) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _duplicate_key_rows_from_table(table: pa.Table, key_columns: Sequence[str]) -> int:
    frame = table.select(list(key_columns)).to_pandas()
    return int(frame.duplicated(list(key_columns)).sum())


def _partition_sort_key(value: Mapping[str, Any]) -> tuple[int, int]:
    return int(value["year"]), int(value.get("month") or 0)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


__all__ = ["PartitionWriterResult", "rollback_dataset", "update_dataset_partitions"]

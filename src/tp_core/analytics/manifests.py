"""Validation and atomic IO helpers for versioned dataset manifests."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA_VERSION = "tp.dataset-manifest.v1"


class ManifestError(ValueError):
    """Raised when a dataset manifest violates the foundation contract."""


@dataclass(frozen=True)
class DatasetManifest:
    path: Path
    payload: Mapping[str, Any]

    @property
    def dataset_name(self) -> str:
        return str(self.payload["dataset_name"])

    @property
    def dataset_version(self) -> str:
        return str(self.payload["dataset_version"])

    @property
    def partitions(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.payload.get("partitions", ()))

    @property
    def fingerprint(self) -> str:
        return manifest_fingerprint(self.payload)


def manifest_fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_manifest(path: str | Path, *, require_files: bool = False, root: Path | None = None) -> DatasetManifest:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read manifest: {target}") from exc
    validate_manifest(payload, require_files=require_files, manifest_path=target, root=root)
    return DatasetManifest(target, payload)


def validate_manifest(
    payload: Mapping[str, Any],
    *,
    require_files: bool = False,
    manifest_path: Path | None = None,
    root: Path | None = None,
) -> None:
    required = ("schema_version", "dataset_name", "dataset_version", "partitions", "validation_status")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ManifestError(f"manifest missing fields: {missing}")
    if payload["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(f"unsupported manifest schema: {payload['schema_version']!r}")
    if not isinstance(payload["dataset_name"], str) or not payload["dataset_name"].strip():
        raise ManifestError("dataset_name must be a non-empty string")
    if not isinstance(payload["dataset_version"], str) or not payload["dataset_version"].strip():
        raise ManifestError("dataset_version must be a non-empty string")
    partitions = payload["partitions"]
    if not isinstance(partitions, list):
        raise ManifestError("partitions must be a list")
    seen: set[str] = set()
    for partition in partitions:
        if not isinstance(partition, Mapping):
            raise ManifestError("each partition must be an object")
        for key in ("path", "sha256", "row_count"):
            if key not in partition:
                raise ManifestError(f"partition missing field: {key}")
        path = str(partition["path"])
        if path in seen:
            raise ManifestError(f"duplicate partition path: {path}")
        seen.add(path)
        if require_files:
            if manifest_path is None:
                raise ManifestError("manifest_path is required when require_files=True")
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = (root or manifest_path.parent) / candidate
            if not candidate.exists():
                raise ManifestError(f"partition file does not exist: {candidate}")


def resolve_partition_path(manifest: DatasetManifest, partition: Mapping[str, Any], *, root: Path | None = None) -> Path:
    path = Path(str(partition["path"]))
    if path.is_absolute():
        return path
    return (root or manifest.path.parent) / path


def write_json_atomic(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "DatasetManifest",
    "ManifestError",
    "load_manifest",
    "manifest_fingerprint",
    "resolve_partition_path",
    "validate_manifest",
    "write_json_atomic",
]

"""Lossless, audited migration of a generated directory within one workspace."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Iterable

from tp_core.data_sources import TP_ROOT

CONTROL_SUFFIXES = {".cfg", ".ini", ".json", ".md", ".toml", ".yaml", ".yml"}
SAMPLE_MODULUS = 100
VERIFY_ATTEMPTS = 60
VERIFY_INTERVAL_SECONDS = 3.0


@dataclass(frozen=True)
class Inventory:
    file_count: int
    total_bytes: int
    inventory_sha256: str
    top_level: dict[str, dict[str, int]]
    extensions: dict[str, dict[str, int]]


def _require_workspace_path(path: Path, workspace: Path, *, label: str) -> Path:
    resolved = path.resolve()
    if resolved == workspace or not resolved.is_relative_to(workspace):
        raise ValueError(f"{label} 必须是工作区内的具体目录：{resolved}")
    return resolved


def _entry_bytes(relative_path: str, size: int, modified_ns: int) -> bytes:
    return f"{relative_path}\0{size}\0{modified_ns}\n".encode("utf-8", errors="surrogatepass")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with _long_path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _long_path(path: Path) -> Path:
    resolved = path.resolve()
    text = str(resolved)
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        return Path(f"\\\\?\\{text}")
    return resolved


def _walk_files(root: Path) -> list[tuple[str, Path]]:
    scan_root = _long_path(root)
    entries: list[tuple[str, Path]] = []
    for current, directory_names, file_names in os.walk(scan_root):
        directory_names.sort()
        file_names.sort()
        for file_name in file_names:
            full_path = Path(current) / file_name
            relative_path = os.path.relpath(full_path, scan_root).replace("\\", "/")
            entries.append((relative_path, full_path))
    entries.sort(key=lambda item: item[0])
    return entries


def build_inventory(
    root: Path,
    *,
    inventory_path: Path | None = None,
    include_content_hashes: bool = False,
) -> tuple[Inventory, dict[str, str]]:
    """Build a deterministic metadata inventory and selected content hashes."""

    root = root.resolve()
    digest = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    top_level: defaultdict[str, Counter[str]] = defaultdict(Counter)
    extensions: defaultdict[str, Counter[str]] = defaultdict(Counter)
    content_hashes: dict[str, str] = {}
    minimum_sample: dict[str, tuple[str, str]] = {}
    inventory_stream = None
    if inventory_path is not None:
        inventory_path.parent.mkdir(parents=True, exist_ok=True)
        inventory_stream = inventory_path.open("w", encoding="utf-8", newline="\n")

    try:
        for relative_path, path in _walk_files(root):
            stat = path.stat()
            size = int(stat.st_size)
            modified_ns = int(stat.st_mtime_ns)
            suffix = path.suffix.lower() or "<none>"
            first_part = Path(relative_path).parts[0]
            digest.update(_entry_bytes(relative_path, size, modified_ns))
            file_count += 1
            total_bytes += size
            top_level[first_part]["files"] += 1
            top_level[first_part]["bytes"] += size
            extensions[suffix]["files"] += 1
            extensions[suffix]["bytes"] += size
            if inventory_stream is not None:
                inventory_stream.write(
                    json.dumps(
                        {"path": relative_path, "size": size, "mtime_ns": modified_ns},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                )

            if not include_content_hashes:
                continue
            selector = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()
            previous = minimum_sample.get(suffix)
            if previous is None or selector < previous[0]:
                minimum_sample[suffix] = (selector, relative_path)
            if path.suffix.lower() in CONTROL_SUFFIXES or int(selector[:8], 16) % SAMPLE_MODULUS == 0:
                content_hashes[relative_path] = _file_sha256(path)
    finally:
        if inventory_stream is not None:
            inventory_stream.close()

    if include_content_hashes:
        for _selector, relative_path in minimum_sample.values():
            if relative_path not in content_hashes:
                content_hashes[relative_path] = _file_sha256(root / relative_path)

    inventory = Inventory(
        file_count=file_count,
        total_bytes=total_bytes,
        inventory_sha256=digest.hexdigest(),
        top_level={key: dict(value) for key, value in sorted(top_level.items())},
        extensions={key: dict(value) for key, value in sorted(extensions.items())},
    )
    return inventory, dict(sorted(content_hashes.items()))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def migrate_directory(
    source: Path,
    target: Path,
    manifest_dir: Path,
    *,
    workspace: Path = TP_ROOT,
    verify_attempts: int = VERIFY_ATTEMPTS,
    verify_interval_seconds: float = VERIFY_INTERVAL_SECONDS,
) -> Path:
    """Move a directory on one volume after recording and verifying its inventory."""

    workspace = workspace.resolve()
    source = _require_workspace_path(source, workspace, label="源目录")
    target = _require_workspace_path(target, workspace, label="目标目录")
    manifest_dir = _require_workspace_path(manifest_dir, workspace, label="清单目录")
    if not source.is_dir():
        raise FileNotFoundError(f"源目录不存在：{source}")
    if target.exists():
        raise FileExistsError(f"目标目录已存在：{target}")
    if source.anchor.lower() != target.anchor.lower():
        raise ValueError("源目录和目标目录必须位于同一卷")
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("源目录和目标目录不能互相包含")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest_path = manifest_dir / f"directory_migration_{timestamp}.json"
    inventory_path = manifest_dir / f"directory_migration_{timestamp}.jsonl"
    staging = target.parent / f".{target.name}.migrating-{timestamp}"
    if staging.exists():
        raise FileExistsError(f"迁移暂存目录已存在：{staging}")

    before, content_hashes = build_inventory(
        source,
        inventory_path=inventory_path,
        include_content_hashes=True,
    )
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": "inventory_complete",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(workspace),
        "source": str(source),
        "target": str(target),
        "inventory_file": str(inventory_path),
        "before": asdict(before),
        "content_hashes": content_hashes,
    }
    _write_json(manifest_path, payload)

    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, staging)
    try:
        after, _ = build_inventory(staging)
        attempts_used = 1
        while after != before and attempts_used < verify_attempts:
            time.sleep(verify_interval_seconds)
            after, _ = build_inventory(staging)
            attempts_used += 1
        if after != before:
            raise RuntimeError(
                "迁移后目录清单不一致："
                f"before={asdict(before)}, after={asdict(after)}"
            )
        mismatches = [
            relative_path
            for relative_path, expected_hash in content_hashes.items()
            if _file_sha256(staging / relative_path) != expected_hash
        ]
        if mismatches:
            raise RuntimeError(f"迁移后内容哈希不一致：{mismatches[:20]}")
        os.replace(staging, target)
    except Exception:
        if staging.exists() and not source.exists():
            os.replace(staging, source)
        payload["status"] = "rolled_back"
        payload["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(manifest_path, payload)
        raise

    payload["status"] = "complete"
    payload["finished_at"] = datetime.now(timezone.utc).isoformat()
    payload["after"] = asdict(after)
    payload["verification_attempts"] = attempts_used
    payload["verified_content_hash_count"] = len(content_hashes)
    _write_json(manifest_path, payload)
    return manifest_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="在同一 TP 工作区内无损迁移生成目录")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--manifest-dir", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=TP_ROOT)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    manifest = migrate_directory(
        args.source,
        args.target,
        args.manifest_dir,
        workspace=args.workspace,
    )
    print(json.dumps({"status": "complete", "manifest": str(manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tp_core.directory_migration import build_inventory, migrate_directory


def test_inventory_is_stable_and_records_metadata(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "a.json").write_text('{"ok": true}', encoding="utf-8")
    nested = root / "group"
    nested.mkdir()
    (nested / "b.csv").write_text("x\n1\n", encoding="utf-8")

    first, hashes = build_inventory(root, include_content_hashes=True)
    second, _ = build_inventory(root)

    assert first == second
    assert first.file_count == 2
    assert first.total_bytes > 0
    assert set(hashes) == {"a.json", "group/b.csv"}


def test_migrate_directory_moves_and_verifies_source(tmp_path: Path) -> None:
    source = tmp_path / "old" / "runs"
    source.mkdir(parents=True)
    (source / "result.yaml").write_text("status: ok\n", encoding="utf-8")
    target = tmp_path / "artifacts" / "research" / "runs" / "historical"
    manifests = tmp_path / "artifacts" / "research" / "migrations"

    manifest_path = migrate_directory(
        source,
        target,
        manifests,
        workspace=tmp_path,
        verify_interval_seconds=0,
    )

    assert not source.exists()
    assert (target / "result.yaml").read_text(encoding="utf-8") == "status: ok\n"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    assert manifest["before"] == manifest["after"]
    assert manifest["verified_content_hash_count"] == 1


def test_migrate_directory_rejects_target_outside_workspace(tmp_path: Path) -> None:
    source = tmp_path / "runs"
    source.mkdir()

    with pytest.raises(ValueError, match="工作区"):
        migrate_directory(
            source,
            tmp_path.parent / "outside",
            tmp_path / "manifests",
            workspace=tmp_path,
        )

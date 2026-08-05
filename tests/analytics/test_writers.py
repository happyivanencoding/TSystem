from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from test_io_engine import _fixture_release

from tp_core.analytics.partitioning import load_current_manifest, validate_mirror
from tp_core.analytics.writers import rollback_dataset, update_dataset_partitions


def _manifest_for(root: Path, dataset: str):
    pointer = root / "00_screen" / "datasets" / "manifests" / dataset / "current.json"
    return load_current_manifest(pointer, root=root)


def test_screen_writer_reuses_unaffected_partitions_and_exports_compatibility_files(tmp_path: Path) -> None:
    _fixture_release(tmp_path)
    screen_path = tmp_path / "00_screen" / "screen_aggregate.parquet"
    before = _manifest_for(tmp_path, "screen")
    before_hashes = {str(item["partition_key"]): str(item["sha256"]) for item in before.partitions}

    screen = pd.read_parquet(screen_path)
    screen.loc[(screen.index == "ISIN1") & (screen["Date"] == pd.Timestamp("2026-02-28")), "value"] = 30.0
    post_screen_path = tmp_path / "post_screen.parquet"
    screen.to_parquet(post_screen_path)
    result = update_dataset_partitions(
        post_screen_path,
        dataset_name="screen",
        root=tmp_path,
        affected_dates=(pd.Timestamp("2026-02-28"),),
        apply=True,
        source_run_id="fixture-screen-update",
        compatibility_export_paths=(
            screen_path,
            tmp_path / "00_screen" / "last_screen.parquet",
            tmp_path / "00_screen" / "screen_aggregate_5Y.parquet",
        ),
    )

    assert result.status == "applied"
    assert result.written_partition_keys == ("year=2026/month=02",)
    assert result.reused_partition_keys == ("year=2026/month=01",)
    after = _manifest_for(tmp_path, "screen")
    after_hashes = {str(item["partition_key"]): str(item["sha256"]) for item in after.partitions}
    assert after_hashes["year=2026/month=01"] == before_hashes["year=2026/month=01"]
    assert after_hashes["year=2026/month=02"] != before_hashes["year=2026/month=02"]
    assert json.loads((tmp_path / "00_screen" / "datasets" / "manifests" / "screen" / "current.json").read_text())["dataset_version"] == after.dataset_version
    assert len(pd.read_parquet(tmp_path / "00_screen" / "last_screen.parquet")) == 1
    assert len(pd.read_parquet(tmp_path / "00_screen" / "screen_aggregate_5Y.parquet")) == 3
    assert validate_mirror(post_screen_path, after.path, root=tmp_path)["status"] == "passed"
    rollback = rollback_dataset(
        dataset_name="screen",
        root=tmp_path,
        dataset_version=before.dataset_version,
        apply=True,
    )
    assert rollback["status"] == "applied"
    assert _manifest_for(tmp_path, "screen").dataset_version == before.dataset_version


def test_returns_writer_updates_only_the_affected_year(tmp_path: Path) -> None:
    _fixture_release(tmp_path)
    returns_path = tmp_path / "00_screen" / "returns.parquet"
    before = _manifest_for(tmp_path, "returns_wide")
    before_hashes = {str(item["partition_key"]): str(item["sha256"]) for item in before.partitions}

    returns = pd.read_parquet(returns_path)
    returns.loc[pd.Timestamp("2026-01-02"), "SED1"] = 0.9
    post_returns_path = tmp_path / "post_returns.parquet"
    returns.to_parquet(post_returns_path)
    result = update_dataset_partitions(
        post_returns_path,
        dataset_name="returns_wide",
        root=tmp_path,
        affected_dates=(pd.Timestamp("2026-01-02"),),
        apply=True,
        source_run_id="fixture-returns-update",
        compatibility_export_paths=(returns_path,),
    )

    assert result.status == "applied"
    assert result.written_partition_keys == ("year=2026",)
    assert result.reused_partition_keys == ("year=2025",)
    after = _manifest_for(tmp_path, "returns_wide")
    after_hashes = {str(item["partition_key"]): str(item["sha256"]) for item in after.partitions}
    assert after_hashes["year=2025"] == before_hashes["year=2025"]
    assert after_hashes["year=2026"] != before_hashes["year=2026"]
    exported = pd.read_parquet(returns_path)
    assert exported.loc[pd.Timestamp("2026-01-02"), "SED1"] == 0.9
    assert validate_mirror(post_returns_path, after.path, root=tmp_path)["status"] == "passed"

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from tp_core.analytics.partitioning import (
    load_current_manifest,
    migrate_dataset,
    validate_mirror,
    write_compatibility_export_from_manifest,
)


def test_screen_mirror_manifest_parity_and_compatibility_export(tmp_path: Path) -> None:
    source = tmp_path / "screen_aggregate.parquet"
    screen = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-01-31", "2026-01-31", "2026-02-28"]),
            "Company SEDOL": ["SED1", "SED2", "SED1"],
            "value": [1.0, 2.0, 3.0],
        },
        index=pd.Index(["ISIN1", "ISIN2", "ISIN1"], name="ISIN"),
    )
    screen.to_parquet(source)

    result = migrate_dataset(source, dataset_name="screen", root=tmp_path, apply=True)
    assert result.status == "applied"
    manifest = load_current_manifest(result.current_pointer or "", root=tmp_path)
    parity = validate_mirror(source, result.manifest_path or "", root=tmp_path)
    assert parity["status"] == "passed"
    assert manifest.payload["row_count"] == 3
    assert len(manifest.partitions) == 2
    assert all(item["key_duplicate_rows"] == 0 for item in manifest.partitions)
    assert manifest.payload["compatibility_export"]["source_role"] == "compatibility_export"
    assert manifest.payload["compatibility_export"]["authoritative_dataset_version"] == manifest.dataset_version

    compatibility = tmp_path / "screen_compatibility.parquet"
    write_compatibility_export_from_manifest(manifest, compatibility, root=tmp_path)
    restored = pd.read_parquet(compatibility)
    assert restored.index.name == "ISIN"
    pd.testing.assert_frame_equal(restored, screen, check_dtype=False)


def test_returns_mirror_partitions_by_year_and_dry_run_is_non_mutating(tmp_path: Path) -> None:
    source = tmp_path / "returns.parquet"
    returns = pd.DataFrame(
        {"SED1": [0.1, 0.2], "SED2": [0.3, 0.4]},
        index=pd.DatetimeIndex(["2025-12-31", "2026-01-02"], name="Date"),
    )
    returns.to_parquet(source)

    dry_run = migrate_dataset(source, dataset_name="returns_wide", root=tmp_path, apply=False)
    assert dry_run.status == "dry_run"
    assert not (tmp_path / "00_screen" / "datasets").exists()

    result = migrate_dataset(source, dataset_name="returns_wide", root=tmp_path, apply=True)
    parity = validate_mirror(source, result.manifest_path or "", root=tmp_path)
    assert parity["status"] == "passed"
    manifest = load_current_manifest(result.current_pointer or "", root=tmp_path)
    assert {item["year"] for item in manifest.partitions} == {2025, 2026}
    assert manifest.payload["date_is_column"] is True
    assert manifest.payload["date_index_field"] is None
    partition_names = pq.ParquetFile(tmp_path / manifest.partitions[0]["path"]).schema_arrow.names
    assert "Date" in partition_names
    assert "__index_level_0__" not in partition_names

    compatibility = tmp_path / "returns_compatibility.parquet"
    write_compatibility_export_from_manifest(manifest, compatibility, root=tmp_path)
    restored = pd.read_parquet(compatibility)
    assert restored.index.name == "Date"
    pd.testing.assert_frame_equal(restored, returns, check_dtype=False)

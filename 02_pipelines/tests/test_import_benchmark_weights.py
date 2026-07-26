from __future__ import annotations

import pandas as pd

from tp_data.import_benchmark_weights import (
    Snapshot,
    SourceRow,
    apply_benchmark_weights,
    map_source_date,
)


def test_map_source_date_month_start_to_previous_month_end() -> None:
    result = map_source_date(
        pd.Timestamp("2009-11-01"),
        [pd.Timestamp("2009-10-31"), pd.Timestamp("2009-11-30")],
    )
    assert result == pd.Timestamp("2009-10-31")


def test_map_source_date_month_end_like_to_same_month_end() -> None:
    result = map_source_date(
        pd.Timestamp("2005-03-30"),
        [pd.Timestamp("2005-02-28"), pd.Timestamp("2005-03-31")],
    )
    assert result == pd.Timestamp("2005-03-31")


def test_apply_sp400_snapshot_preserves_rows_and_normalizes_weights(tmp_path: Path) -> None:
    screen = pd.DataFrame(
        {
            "ISIN": ["US0000000001", "US0000000002"],
            "Date": [pd.Timestamp("2005-03-31"), pd.Timestamp("2005-03-31")],
            "Weight in SP400": [0.25, 0.75],
        }
    ).set_index("ISIN")
    snapshot = Snapshot(
        benchmark="SP400",
        source_path=tmp_path / "source.xlsx",
        source_date=pd.Timestamp("2005-03-30"),
        rows=(
            SourceRow("AAA US Equity", 60.0, "AAA"),
            SourceRow("BBB US Equity", 40.0, "BBB"),
        ),
    )

    updated, report = apply_benchmark_weights(
        screen,
        [snapshot],
        {"AAA US Equity": "US0000000001", "BBB US Equity": "US0000000002"},
    )

    assert len(updated) == len(screen)
    assert report["snapshots_applied"] == 1
    assert updated["Weight in SP400"].sum() == 100.0
    assert updated.loc["US0000000001", "Weight in SP400"] == 60.0
    assert updated.loc["US0000000002", "Weight in SP400"] == 40.0


def test_apply_drops_unmapped_and_missing_keys_before_normalizing(tmp_path: Path) -> None:
    screen = pd.DataFrame(
        {
            "ISIN": ["US0000000001", "US0000000002"],
            "Date": [pd.Timestamp("2005-03-31"), pd.Timestamp("2005-03-31")],
            "Weight in SP400": [0.25, 0.75],
        }
    ).set_index("ISIN")
    snapshot = Snapshot(
        benchmark="SP400",
        source_path=tmp_path / "source.xlsx",
        source_date=pd.Timestamp("2005-03-30"),
        rows=(
            SourceRow("AAA US Equity", 60.0, "AAA"),
            SourceRow("BBB US Equity", 30.0, "BBB"),
            SourceRow("CCC US Equity", 10.0, "CCC"),
        ),
    )

    updated, report = apply_benchmark_weights(
        screen,
        [snapshot],
        {"AAA US Equity": "US0000000001", "BBB US Equity": "US0000000003"},
    )

    assert updated.loc["US0000000001", "Weight in SP400"] == 100.0
    assert pd.isna(updated.loc["US0000000002", "Weight in SP400"])
    assert report["dropped_unmapped_occurrences"] == 1
    assert report["dropped_missing_screen_key_occurrences"] == 1
    assert report["retained_weight_ratio_min"] == 0.6

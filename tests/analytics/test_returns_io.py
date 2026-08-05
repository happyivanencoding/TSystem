from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tp_core.analytics.returns_io import (
    ReturnsReadError,
    available_return_columns,
    read_returns_dates,
    read_returns_matrix,
)


def test_projected_named_index_returns_are_normalized_to_datetime64_ns(tmp_path: Path) -> None:
    source = tmp_path / "returns.parquet"
    pd.DataFrame(
        {"SED1": [0.1, 0.2], "SED2": [0.3, 0.4]},
        index=pd.DatetimeIndex(["2025-12-31", "2026-01-02"], name="Date"),
    ).to_parquet(source)

    frame = read_returns_matrix(source, columns=("SED2",), date_from="2025-12-31")

    assert frame.columns.tolist() == ["SED2"]
    assert frame.index.name == "Date"
    assert str(frame.index.dtype) == "datetime64[ns]"
    assert frame.index.tolist() == [pd.Timestamp("2025-12-31"), pd.Timestamp("2026-01-02")]
    assert frame["SED2"].tolist() == [0.3, 0.4]


def test_partitioned_returns_union_columns_and_schema_order_without_full_read(tmp_path: Path) -> None:
    source = tmp_path / "returns"
    source.mkdir()
    pd.DataFrame(
        {"Date": pd.to_datetime(["2025-12-31"]), "SED1": [0.1]},
    ).to_parquet(source / "year=2025.parquet", index=False)
    pd.DataFrame(
        {"Date": pd.to_datetime(["2026-01-02"]), "SED2": [0.4]},
    ).to_parquet(source / "year=2026.parquet", index=False)

    assert available_return_columns(source, {"SED2", "SED1"}) == ("SED1", "SED2")
    frame = read_returns_matrix(source, columns=("SED1", "SED2"))

    assert frame.columns.tolist() == ["SED1", "SED2"]
    assert frame.index.dtype == "datetime64[ns]"
    assert frame.loc[pd.Timestamp("2025-12-31"), "SED1"] == 0.1
    assert pd.isna(frame.loc[pd.Timestamp("2025-12-31"), "SED2"])
    assert frame.loc[pd.Timestamp("2026-01-02"), "SED2"] == 0.4


def test_returns_dates_uses_the_same_normalized_reader(tmp_path: Path) -> None:
    source = tmp_path / "returns.parquet"
    pd.DataFrame(
        {"SED1": [0.1, 0.2]},
        index=pd.DatetimeIndex(["2025-12-31", "2026-01-02"], name="Date"),
    ).to_parquet(source)

    dates = read_returns_dates(source, date_from="2026-01-01")

    assert dates.name == "Date"
    assert str(dates.dtype) == "datetime64[ns]"
    assert dates.tolist() == [pd.Timestamp("2026-01-02")]


def test_returns_reader_rejects_duplicate_dates_across_partitions(tmp_path: Path) -> None:
    source = tmp_path / "returns"
    source.mkdir()
    for name, value in (("a.parquet", 0.1), ("b.parquet", 0.2)):
        pd.DataFrame({"Date": pd.to_datetime(["2026-01-02"]), "SED1": [value]}).to_parquet(
            source / name,
            index=False,
        )

    with pytest.raises(ReturnsReadError, match="duplicate Date"):
        read_returns_matrix(source, columns=("SED1",))

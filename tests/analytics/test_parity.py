from __future__ import annotations

import pandas as pd

from tp_core.analytics.parity import compare_frames


def test_compare_frames_normalizes_datetime_index_units_and_emits_diagnostics() -> None:
    left = pd.DataFrame(
        {"SED1": [0.1, None]},
        index=pd.DatetimeIndex(
            pd.array(["2026-01-01", "2026-01-02"], dtype="datetime64[us]"),
            name="Date",
        ),
    )
    right = pd.DataFrame(
        {"SED1": [0.1, None]},
        index=pd.DatetimeIndex(
            pd.array(["2026-01-01", "2026-01-02"], dtype="datetime64[ns]"),
            name="Date",
        ),
    )

    result = compare_frames(left, right)

    assert result.equal
    assert result.diagnostics["index"]["left"]["dtype"] == "datetime64[ns]"
    assert result.diagnostics["index"]["right"]["dtype"] == "datetime64[ns]"
    assert result.diagnostics["nan_mask"]["left"]["total_nulls"] == 1
    assert result.diagnostics["max_abs_numeric_diff"] == 0.0


def test_compare_frames_reports_first_mismatch_and_uses_explicit_tolerance() -> None:
    left = pd.DataFrame({"value": [1.0, 2.0]}, index=["a", "b"])
    right = pd.DataFrame({"value": [1.0 + 5e-13, 2.5]}, index=["a", "b"])

    result = compare_frames(left, right)

    assert not result.equal
    assert result.diagnostics["first_mismatch"] == {
        "reason": "cell_value",
        "position": 1,
        "index": "b",
        "column": "value",
        "left": 2.0,
        "right": 2.5,
    }
    assert result.diagnostics["max_abs_numeric_diff"] == 0.5

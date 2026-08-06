"""Value and schema parity for benchmark outputs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd


def _normalise(frame: pd.DataFrame, keys: tuple[str, ...]) -> pd.DataFrame:
    result = frame.copy()
    if isinstance(result.index, pd.DatetimeIndex) or result.index.name is not None:
        result = result.reset_index(drop=False)
    for column in result.columns:
        if pd.api.types.is_datetime64_any_dtype(result[column]):
            result[column] = pd.to_datetime(result[column], errors="coerce").astype(
                "datetime64[ns]"
            )
    if keys and all(key in result.columns for key in keys):
        key_index = pd.MultiIndex.from_frame(result.loc[:, list(keys)])
        if not key_index.is_monotonic_increasing:
            result = result.sort_values(list(keys), kind="mergesort").reset_index(drop=True)
    return result


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if value is pd.NaT or (not isinstance(value, (list, dict, tuple)) and pd.isna(value)):
        return None
    return str(value)


def compare_frames(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    key_columns: Iterable[str] = (),
    rtol: float = 1e-12,
    atol: float = 1e-12,
    pre_normalized: bool = False,
) -> dict[str, Any]:
    keys = tuple(key_columns)
    left_frame = left if pre_normalized else _normalise(left, keys)
    right_frame = right if pre_normalized else _normalise(right, keys)
    left_columns = [str(value) for value in left_frame.columns]
    right_columns = [str(value) for value in right_frame.columns]
    missing = sorted(set(left_columns) - set(right_columns))
    extra = sorted(set(right_columns) - set(left_columns))
    equal = not missing and not extra and len(left_frame) == len(right_frame)
    large_frame = len(left_frame) > 100_000 or (
        len(left_frame) * max(1, len(left_frame.columns)) > 1_000_000
    )
    difference: str | None = None
    if equal:
        if large_frame:
            if not left_frame.equals(right_frame):
                equal = False
                difference = "large_frame value equality failed"
        else:
            try:
                pd.testing.assert_frame_equal(
                    left_frame,
                    right_frame,
                    check_dtype=False,
                    check_like=False,
                    rtol=rtol,
                    atol=atol,
                )
            except AssertionError as exc:
                equal = False
                difference = str(exc).splitlines()[0][:500]
    elif missing or extra:
        difference = "column sets differ"
    else:
        difference = "row counts differ"
    common = [column for column in left_frame.columns if column in right_frame.columns]
    max_abs: float | None = None
    if len(left_frame) == len(right_frame) and not large_frame:
        for column in common:
            if pd.api.types.is_numeric_dtype(left_frame[column]) and pd.api.types.is_numeric_dtype(
                right_frame[column]
            ):
                left_values = pd.to_numeric(left_frame[column], errors="coerce").to_numpy(
                    dtype=float
                )
                right_values = pd.to_numeric(right_frame[column], errors="coerce").to_numpy(
                    dtype=float
                )
                valid = np.isfinite(left_values) & np.isfinite(right_values)
                if valid.any():
                    candidate = float(np.max(np.abs(left_values[valid] - right_values[valid])))
                    max_abs = candidate if max_abs is None else max(max_abs, candidate)
    first_mismatch: dict[str, Any] | None = None
    if len(left_frame) == len(right_frame) and len(left_frame) <= 100_000:
        for position in range(len(left_frame)):
            for column in common:
                left_value = left_frame.iloc[position][column]
                right_value = right_frame.iloc[position][column]
                if pd.isna(left_value) and pd.isna(right_value):
                    continue
                if isinstance(left_value, (int, float, np.number)) and isinstance(
                    right_value, (int, float, np.number)
                ):
                    close = bool(
                        np.isclose(left_value, right_value, rtol=rtol, atol=atol, equal_nan=True)
                    )
                else:
                    close = left_value == right_value
                if not close:
                    first_mismatch = {
                        "position": position,
                        "column": str(column),
                        "left": _safe(left_value),
                        "right": _safe(right_value),
                    }
                    break
            if first_mismatch:
                break
    return {
        "status": "passed" if equal else "failed",
        "equal": bool(equal),
        "left_rows": len(left_frame),
        "right_rows": len(right_frame),
        "left_columns": left_columns,
        "right_columns": right_columns,
        "missing_columns": missing,
        "extra_columns": extra,
        "left_duplicates": None if large_frame else int(left_frame.duplicated().sum()),
        "right_duplicates": None if large_frame else int(right_frame.duplicated().sum()),
        "left_nulls": {}
        if large_frame
        else {str(column): int(value) for column, value in left_frame.isna().sum().items()},
        "right_nulls": {}
        if large_frame
        else {str(column): int(value) for column, value in right_frame.isna().sum().items()},
        "max_abs_numeric_diff": max_abs,
        "difference": difference,
        "first_mismatch": first_mismatch,
        "tolerance": {"rtol": rtol, "atol": atol},
    }


__all__ = ["compare_frames"]

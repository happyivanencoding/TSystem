"""Deterministic DataFrame parity checks used by shadow migration."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_PARITY_RTOL = 1e-10
DEFAULT_PARITY_ATOL = 1e-12


@dataclass(frozen=True)
class FrameParityResult:
    equal: bool
    left_rows: int
    right_rows: int
    left_columns: tuple[str, ...]
    right_columns: tuple[str, ...]
    missing_columns: tuple[str, ...]
    extra_columns: tuple[str, ...]
    left_fingerprint: str
    right_fingerprint: str
    difference: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def frame_fingerprint(frame: pd.DataFrame) -> str:
    if frame.empty:
        return hashlib.sha256(b"empty").hexdigest()
    normalized = _canonicalize_frame(frame)
    normalized = normalized.reset_index(drop=False)
    normalized = normalized.sort_index(axis=1)
    payload = pd.util.hash_pandas_object(normalized, index=True).to_numpy().tobytes()
    return hashlib.sha256(payload).hexdigest()


def compare_frames(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    key_columns: Iterable[str] = (),
    check_dtype: bool = False,
    rtol: float = DEFAULT_PARITY_RTOL,
    atol: float = DEFAULT_PARITY_ATOL,
) -> FrameParityResult:
    left_frame = _canonicalize_frame(left)
    right_frame = _canonicalize_frame(right)
    keys = tuple(key_columns)
    if keys and all(key in left_frame.columns for key in keys) and all(key in right_frame.columns for key in keys):
        left_frame = left_frame.sort_values(list(keys), kind="mergesort").reset_index(drop=True)
        right_frame = right_frame.sort_values(list(keys), kind="mergesort").reset_index(drop=True)
    missing = tuple(sorted(set(left_frame.columns) - set(right_frame.columns)))
    extra = tuple(sorted(set(right_frame.columns) - set(left_frame.columns)))
    equal = not missing and not extra
    difference: str | None = None
    if equal:
        try:
            pd.testing.assert_frame_equal(
                left_frame,
                right_frame,
                check_dtype=check_dtype,
                check_like=False,
                check_exact=rtol == 0 and atol == 0,
                rtol=rtol,
                atol=atol,
            )
        except AssertionError as exc:
            equal = False
            difference = str(exc).splitlines()[0][:500]
    else:
        difference = "column sets differ"
    return FrameParityResult(
        equal=equal,
        left_rows=len(left_frame),
        right_rows=len(right_frame),
        left_columns=tuple(str(column) for column in left_frame.columns),
        right_columns=tuple(str(column) for column in right_frame.columns),
        missing_columns=missing,
        extra_columns=extra,
        left_fingerprint=frame_fingerprint(left_frame),
        right_fingerprint=frame_fingerprint(right_frame),
        difference=difference,
        diagnostics=_diagnostics(
            left_frame,
            right_frame,
            rtol=rtol,
            atol=atol,
        ),
    )


def _canonicalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    if isinstance(normalized.index, pd.DatetimeIndex):
        index = normalized.index
        if index.tz is not None:
            index = index.tz_convert(None)
        normalized.index = index.astype("datetime64[ns]")
    for column in normalized.columns:
        if pd.api.types.is_datetime64_any_dtype(normalized[column]):
            values = pd.to_datetime(normalized[column], errors="coerce")
            if getattr(values.dt, "tz", None) is not None:
                values = values.dt.tz_convert(None)
            normalized[column] = values.astype("datetime64[ns]")
    return normalized


def _diagnostics(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    rtol: float,
    atol: float,
) -> dict[str, Any]:
    common_columns = [column for column in left.columns if column in right.columns]
    return {
        "index": {
            "left": _index_profile(left.index),
            "right": _index_profile(right.index),
        },
        "columns": {
            "left": [str(column) for column in left.columns],
            "right": [str(column) for column in right.columns],
            "common": [str(column) for column in common_columns],
        },
        "dtypes": {
            "left": {str(column): str(dtype) for column, dtype in left.dtypes.items()},
            "right": {str(column): str(dtype) for column, dtype in right.dtypes.items()},
        },
        "nan_mask": {
            "left": _nan_profile(left),
            "right": _nan_profile(right),
        },
        "numeric_tolerance": {"rtol": rtol, "atol": atol},
        "max_abs_numeric_diff": _max_abs_numeric_diff(left, right, common_columns),
        "first_mismatch": _first_mismatch(left, right, common_columns, rtol=rtol, atol=atol),
    }


def _index_profile(index: pd.Index) -> dict[str, Any]:
    values = [_safe_value(value) for value in index[:5].tolist()]
    return {
        "class": type(index).__name__,
        "name": _safe_value(index.name),
        "dtype": str(index.dtype),
        "length": len(index),
        "values_preview": values,
        "has_duplicates": bool(index.has_duplicates),
    }


def _nan_profile(frame: pd.DataFrame) -> dict[str, Any]:
    mask = frame.isna()
    return {
        "mask_fingerprint": frame_fingerprint(mask.astype("uint8")),
        "null_counts": {str(column): int(count) for column, count in mask.sum().items()},
        "total_nulls": int(mask.to_numpy(dtype=bool).sum()),
    }


def _max_abs_numeric_diff(
    left: pd.DataFrame,
    right: pd.DataFrame,
    common_columns: list[Any],
) -> float | None:
    if len(left) != len(right):
        return None
    maximum: float | None = None
    for column in common_columns:
        left_values = left[column]
        right_values = right[column]
        if not (pd.api.types.is_numeric_dtype(left_values) and pd.api.types.is_numeric_dtype(right_values)):
            continue
        left_numeric = pd.to_numeric(left_values, errors="coerce").to_numpy(dtype=float)
        right_numeric = pd.to_numeric(right_values, errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(left_numeric) & np.isfinite(right_numeric)
        if not valid.any():
            continue
        difference = float(np.max(np.abs(left_numeric[valid] - right_numeric[valid])))
        maximum = difference if maximum is None else max(maximum, difference)
    return maximum


def _first_mismatch(
    left: pd.DataFrame,
    right: pd.DataFrame,
    common_columns: list[Any],
    *,
    rtol: float,
    atol: float,
) -> dict[str, Any] | None:
    if len(left) != len(right):
        return {"reason": "row_count", "left": len(left), "right": len(right)}
    if not left.index.equals(right.index):
        for position, (left_value, right_value) in enumerate(zip(left.index, right.index)):
            if left_value != right_value:
                return {
                    "reason": "index_value",
                    "position": position,
                    "left": _safe_value(left_value),
                    "right": _safe_value(right_value),
                }
        return {"reason": "index_metadata", "left": _index_profile(left.index), "right": _index_profile(right.index)}
    for column in common_columns:
        left_values = left[column].tolist()
        right_values = right[column].tolist()
        for position, (left_value, right_value) in enumerate(zip(left_values, right_values)):
            if _values_close(left_value, right_value, rtol=rtol, atol=atol):
                continue
            return {
                "reason": "cell_value",
                "position": position,
                "index": _safe_value(left.index[position]),
                "column": str(column),
                "left": _safe_value(left_value),
                "right": _safe_value(right_value),
            }
    if tuple(left.columns) != tuple(right.columns):
        return {"reason": "column_order", "left": [str(value) for value in left.columns], "right": [str(value) for value in right.columns]}
    return None


def _values_close(left: Any, right: Any, *, rtol: float, atol: float) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    if isinstance(left, (int, float, np.number)) and isinstance(right, (int, float, np.number)):
        return bool(np.isclose(left, right, rtol=rtol, atol=atol, equal_nan=True))
    return left == right


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if value is pd.NaT or pd.isna(value):
        return None
    return str(value)


__all__ = [
    "DEFAULT_PARITY_ATOL",
    "DEFAULT_PARITY_RTOL",
    "FrameParityResult",
    "compare_frames",
    "frame_fingerprint",
]

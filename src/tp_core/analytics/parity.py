"""Deterministic DataFrame parity checks used by shadow migration."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


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

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def frame_fingerprint(frame: pd.DataFrame) -> str:
    if frame.empty:
        return hashlib.sha256(b"empty").hexdigest()
    normalized = frame.copy()
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
) -> FrameParityResult:
    left_frame = left.copy()
    right_frame = right.copy()
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
                check_exact=True,
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
    )


__all__ = ["FrameParityResult", "compare_frames", "frame_fingerprint"]

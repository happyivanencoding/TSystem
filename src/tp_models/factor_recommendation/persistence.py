"""推荐结果的逻辑键幂等持久化。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd


DEFAULT_KEY_COLUMNS: tuple[str, ...] = ("region", "Date", "factor", "model_version")


def logical_key_series(frame: pd.DataFrame, key_columns: Iterable[str]) -> pd.Series:
    keys = tuple(key_columns)
    missing = [column for column in keys if column not in frame.columns]
    if missing:
        raise KeyError(f"logical key columns missing: {missing}")
    return frame.loc[:, keys].astype("string").fillna("<NA>").agg("|".join, axis=1)


def _read_existing(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(path, lines=suffix == ".jsonl")
    raise ValueError(f"unsupported persistence suffix: {path.suffix}")


def _write_frame(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        frame.to_parquet(path, index=False)
    elif suffix == ".csv":
        frame.to_csv(path, index=False, encoding="utf-8-sig")
    elif suffix == ".json":
        path.write_text(frame.to_json(orient="records", date_format="iso"), encoding="utf-8")
    elif suffix == ".jsonl":
        path.write_text(
            frame.to_json(orient="records", lines=True, date_format="iso"), encoding="utf-8"
        )
    else:
        raise ValueError(f"unsupported persistence suffix: {path.suffix}")


def upsert_frame(
    path: str | Path,
    frame: pd.DataFrame,
    *,
    key_columns: Iterable[str] = DEFAULT_KEY_COLUMNS,
) -> pd.DataFrame:
    """按逻辑键 upsert；同一记录重复写入不会增加行数。"""

    output = Path(path)
    incoming = frame.copy()
    keys = tuple(key_columns)
    logical_key_series(incoming, keys)
    existing = _read_existing(output)
    if existing.empty:
        combined = incoming
    else:
        logical_key_series(existing, keys)
        combined = pd.concat([existing, incoming], ignore_index=True, sort=False)
    logical = logical_key_series(combined, keys)
    combined = combined.loc[~logical.duplicated(keep="last")].copy()
    sort_columns = [column for column in keys if column in combined.columns]
    if sort_columns and not combined.empty:
        combined = combined.sort_values(sort_columns, kind="stable", na_position="last")
    combined = combined.reset_index(drop=True)
    _write_frame(combined, output)
    return combined


def load_persisted(path: str | Path) -> pd.DataFrame:
    return _read_existing(Path(path))


persist_recommendations = upsert_frame


__all__ = [
    "DEFAULT_KEY_COLUMNS",
    "load_persisted",
    "logical_key_series",
    "persist_recommendations",
    "upsert_frame",
]

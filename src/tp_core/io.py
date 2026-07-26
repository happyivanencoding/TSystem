"""TP canonical 数据集的统一读取工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from .data_contract import drop_deprecated_screen_columns, normalize_screen_dates
from .data_sources import LAST_SCREEN_PATH, RETURNS_PATH, SCREEN_AGGREGATE_PATH, SCREEN_AGGREGATE_5Y_PATH


def read_parquet_dataset(path: str | Path, columns: Iterable[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(Path(path), columns=list(columns) if columns is not None else None)


def read_screen_aggregate(
    path: str | Path = SCREEN_AGGREGATE_PATH,
    columns: Iterable[str] | None = None,
    drop_deprecated: bool = True,
    normalize_dates: bool = True,
) -> pd.DataFrame:
    df = read_parquet_dataset(path, columns=columns)
    if drop_deprecated:
        df = drop_deprecated_screen_columns(df)
    if normalize_dates:
        df = normalize_screen_dates(df)
    return df


def read_last_screen(
    path: str | Path = LAST_SCREEN_PATH,
    columns: Iterable[str] | None = None,
    drop_deprecated: bool = True,
    normalize_dates: bool = True,
) -> pd.DataFrame:
    return read_screen_aggregate(path, columns=columns, drop_deprecated=drop_deprecated, normalize_dates=normalize_dates)


def read_screen_5y(
    path: str | Path = SCREEN_AGGREGATE_5Y_PATH,
    columns: Iterable[str] | None = None,
    drop_deprecated: bool = True,
    normalize_dates: bool = True,
) -> pd.DataFrame:
    return read_screen_aggregate(path, columns=columns, drop_deprecated=drop_deprecated, normalize_dates=normalize_dates)


def read_returns(path: str | Path = RETURNS_PATH, columns: Iterable[str] | None = None) -> pd.DataFrame:
    returns = read_parquet_dataset(path, columns=columns)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    return returns.sort_index()

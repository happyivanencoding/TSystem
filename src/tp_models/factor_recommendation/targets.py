"""未来一个月目标构造。

目标只使用决策日之后的 returns。这里计算的是研究标签（证券收益的复合
和横截面平均），官方组合 NAV 必须走 ``sleeve_engine`` 的 TP adapter。
"""

from __future__ import annotations

from math import ceil
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from .contracts import DATE_COLUMN, FEATURE_AS_OF_COLUMN, ID_COLUMN, TARGET_DATE_COLUMN, Region
from .factor_definitions import FactorDefinition, load_factor_definitions
from .features import build_security_feature_panel
from .universe import RegionUniverse


def _next_date_map(dates: Iterable[pd.Timestamp]) -> dict[pd.Timestamp, pd.Timestamp]:
    unique = sorted(pd.Timestamp(date) for date in pd.Series(list(dates)).drop_duplicates())
    return {current: following for current, following in zip(unique, unique[1:])}


def build_next_month_targets(
    frame: pd.DataFrame,
    value_columns: Iterable[str] | None = None,
    *,
    group_columns: Iterable[str] = (),
    date_column: str = DATE_COLUMN,
    target_prefix: str = "target_",
) -> pd.DataFrame:
    """把月度值向前移动一个月，并保留显式 ``target_date``。

    ``group_columns`` 适用于证券级面板；不传时输入应为区域级每月一行。
    不会用当前行的值填充缺失月份，也不会把最后一个月错误地当成已实现目标。
    """

    if date_column not in frame.columns:
        raise KeyError(f"frame must contain {date_column}")
    out = frame.copy()
    out[date_column] = pd.to_datetime(out[date_column], errors="coerce")
    if out[date_column].isna().any():
        raise ValueError("frame contains invalid target dates")
    groups = tuple(group_columns)
    values = tuple(
        value_columns
        or [
            column
            for column in out.columns
            if column not in set(groups) | {date_column, TARGET_DATE_COLUMN}
            and pd.api.types.is_numeric_dtype(out[column])
        ]
    )
    missing = [column for column in values if column not in out.columns]
    if missing:
        raise KeyError(f"target value columns missing: {missing}")
    out = out.sort_values([*groups, date_column], kind="stable").reset_index(drop=True)
    if groups:
        out[TARGET_DATE_COLUMN] = out.groupby(list(groups), sort=False)[date_column].shift(-1)
        for column in values:
            out[f"{target_prefix}{column}"] = out.groupby(list(groups), sort=False)[column].shift(-1)
    else:
        date_map = _next_date_map(out[date_column])
        out[TARGET_DATE_COLUMN] = out[date_column].map(date_map)
        next_values = out[[date_column, *values]].copy()
        next_values = next_values.rename(
            columns={date_column: TARGET_DATE_COLUMN, **{column: f"{target_prefix}{column}" for column in values}}
        )
        # Region-level frames have one row per month; duplicate dates are rejected
        # rather than silently choosing a future row.
        if next_values[TARGET_DATE_COLUMN].duplicated().any():
            raise ValueError("group_columns are required when a month has multiple rows")
        out = out.merge(next_values, on=TARGET_DATE_COLUMN, how="left", sort=False)
    return out


def _normalize_returns(returns: pd.DataFrame) -> pd.DataFrame:
    out = returns.copy()
    if DATE_COLUMN in out.columns:
        out[DATE_COLUMN] = pd.to_datetime(out[DATE_COLUMN], errors="coerce")
        out = out.set_index(DATE_COLUMN)
    out.index = pd.to_datetime(out.index, errors="coerce")
    if out.index.isna().any():
        raise ValueError("returns contains invalid dates")
    out.columns = out.columns.astype(str)
    return out.sort_index()


def _security_forward_returns(
    returns: pd.DataFrame,
    decision_date: pd.Timestamp,
    target_date: pd.Timestamp,
) -> pd.Series:
    window = returns.loc[(returns.index > decision_date) & (returns.index <= target_date)]
    if window.empty:
        return pd.Series(dtype=float)
    numeric = window.apply(pd.to_numeric, errors="coerce")
    return (1.0 + numeric).prod(axis=0, min_count=1) - 1.0


def build_factor_sleeve_targets(
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    region: str | Region,
    *,
    definitions: Iterable[FactorDefinition] | None = None,
    quantile: float = 0.2,
    pit_lag_months: int = 1,
    universe_definitions: Mapping[str, RegionUniverse] | None = None,
) -> pd.DataFrame:
    """按 PIT 因子排序生成 next-month long-minus-short 研究标签。"""

    if not 0 < quantile <= 0.5:
        raise ValueError("quantile must be in (0, 0.5]")
    definitions = tuple(definitions or load_factor_definitions())
    panel = build_security_feature_panel(
        screen,
        region,
        definitions=definitions,
        pit_lag_months=pit_lag_months,
        universe_definitions=universe_definitions,
    )
    if panel.empty:
        return pd.DataFrame(columns=[DATE_COLUMN, TARGET_DATE_COLUMN])
    returns_frame = _normalize_returns(returns)
    rows: list[dict[str, object]] = []
    for decision_date, group in panel.groupby(DATE_COLUMN, sort=True):
        decision_date = pd.Timestamp(decision_date)
        target_date = pd.Timestamp(group[TARGET_DATE_COLUMN].iloc[0])
        forward = _security_forward_returns(returns_frame, decision_date, target_date)
        row: dict[str, object] = {
            DATE_COLUMN: decision_date,
            TARGET_DATE_COLUMN: target_date,
            FEATURE_AS_OF_COLUMN: pd.Timestamp(group[FEATURE_AS_OF_COLUMN].iloc[0]),
        }
        for definition in definitions:
            score = pd.to_numeric(group[definition.name], errors="coerce")
            score_frame = group.assign(_score=score).dropna(subset=["_score"])
            available = [
                str(value)
                for value in score_frame.get("Company SEDOL", pd.Series(dtype=object)).tolist()
                if str(value) in forward.index
            ]
            if score_frame.empty or not available:
                row[f"target_{definition.name}"] = np.nan
                row[f"long_{definition.name}"] = np.nan
                row[f"short_{definition.name}"] = np.nan
                row[f"coverage_{definition.name}"] = 0
                continue
            score_frame = score_frame[score_frame["Company SEDOL"].astype(str).isin(available)]
            count = max(1, int(ceil(len(score_frame) * quantile)))
            top = score_frame.nlargest(count, "_score", keep="all").head(count)
            bottom = score_frame.nsmallest(count, "_score", keep="all").head(count)
            long_values = forward.reindex(top["Company SEDOL"].astype(str)).dropna()
            short_values = forward.reindex(bottom["Company SEDOL"].astype(str)).dropna()
            long_return = float(long_values.mean()) if not long_values.empty else np.nan
            short_return = float(short_values.mean()) if not short_values.empty else np.nan
            row[f"long_{definition.name}"] = long_return
            row[f"short_{definition.name}"] = short_return
            row[f"target_{definition.name}"] = (
                long_return - short_return
                if pd.notna(long_return) and pd.notna(short_return)
                else np.nan
            )
            row[f"coverage_{definition.name}"] = int(len(long_values) + len(short_values))
        rows.append(row)
    return pd.DataFrame(rows).sort_values(DATE_COLUMN).reset_index(drop=True)


__all__ = ["build_factor_sleeve_targets", "build_next_month_targets"]

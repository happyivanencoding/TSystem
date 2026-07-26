from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from tp_core.backtesting import TargetWeightSchema, calculate_security_nav
from tp_core.portfolio_weights import (
    cap_weights_preserving_group_totals,
    match_group_weight_targets,
    normalize_long_only_weights,
    normalize_weight_table,
)


CANONICAL_MKT_CAP_COL = "Benchmark Market Value Millions in EUR"
LEGACY_MKT_CAP_COL = "Benchmark Market Value Millions in EUR "
BACKUP_MKT_CAP_COL = "Benchmark Market Value Millions in EUR BK"
DEFAULT_SECTOR_COL = " Benchmark ICB Industry "


@dataclass
class BacktestData:
    patterns: pd.DataFrame
    returns: pd.DataFrame
    screen: pd.DataFrame


@dataclass
class PatternBacktestResult:
    data: BacktestData
    config: dict[str, Any]
    selection_pool: pd.DataFrame
    strategy_rebalance: pd.DataFrame
    benchmark_rebalance: pd.DataFrame
    strategy_exec_weights: pd.DataFrame
    benchmark_exec_weights: pd.DataFrame
    strategy_nav: pd.Series
    benchmark_nav: pd.Series
    strategy_daily_return: pd.Series
    benchmark_daily_return: pd.Series
    nav_df: pd.DataFrame
    summary: pd.DataFrame


def load_backtest_data(
    patterns_path: str | Path,
    returns_path: str | Path,
    screen_path: str | Path,
) -> BacktestData:
    patterns = pd.read_parquet(patterns_path).copy()
    if "Company SEDOL" in patterns.columns:
        patterns = patterns.set_index("Company SEDOL")
    patterns.index = patterns.index.astype(str)
    patterns.index.name = "Company SEDOL"
    patterns["Date"] = pd.to_datetime(patterns["Date"])
    patterns = patterns.sort_values("Date")

    returns = pd.read_parquet(returns_path).copy()
    returns.index = pd.to_datetime(returns.index)
    returns.columns = returns.columns.astype(str)
    returns = returns.sort_index()

    screen = pd.read_parquet(screen_path).copy()
    if "ISIN" not in screen.columns and screen.index.name == "ISIN":
        screen = screen.reset_index()
    screen = _normalize_screen_columns(screen)
    screen["Date"] = pd.to_datetime(screen["Date"])
    screen["Company SEDOL"] = screen["Company SEDOL"].astype(str)
    screen = screen.sort_values(["Date", "Company SEDOL"])

    return BacktestData(patterns=patterns, returns=returns, screen=screen)


def run_ranked_pattern_backtest(
    data: BacktestData,
    benchmark_name: str,
    score_columns: Sequence[str],
    score_weights: Sequence[float] | None = None,
    score_value_map: dict[str, Any] | None = None,
    higher_is_better: Sequence[bool] | None = None,
    ascending_flags: Sequence[bool] | None = None,
    top_n: int | None = None,
    top_pct: float | None = None,
    start_date: str | pd.Timestamp | None = None,
    strategy_name: str = "Pattern Strategy",
    sector_neutral: bool = False,
    sector_column: str = DEFAULT_SECTOR_COL,
    max_weight: float = 1.0,
    min_names: int = 1,
) -> PatternBacktestResult:
    if not score_columns:
        raise ValueError("score_columns 不能为空。")

    score_columns = list(score_columns)
    score_weights = _resolve_score_weights(score_columns, score_weights)
    score_value_map = _resolve_score_value_map(score_columns, score_value_map)
    higher_is_better = _resolve_higher_is_better(score_columns, higher_is_better, ascending_flags)
    benchmark_weight_col = f"Weight in {benchmark_name}"

    selection_pool, strategy_rebalance, benchmark_rebalance = build_ranked_rebalances(
        data=data,
        benchmark_weight_col=benchmark_weight_col,
        score_columns=score_columns,
        score_weights=score_weights,
        score_value_map=score_value_map,
        higher_is_better=higher_is_better,
        top_n=top_n,
        top_pct=top_pct,
        start_date=start_date,
        sector_neutral=sector_neutral,
        sector_column=sector_column,
        max_weight=max_weight,
        min_names=min_names,
    )

    strategy_nav, strategy_daily_return, strategy_exec_weights = run_drift_backtest(
        strategy_rebalance,
        data.returns,
    )
    benchmark_nav, benchmark_daily_return, benchmark_exec_weights = run_drift_backtest(
        benchmark_rebalance,
        data.returns,
    )

    nav_df = pd.concat(
        [
            strategy_nav.rename(strategy_name),
            benchmark_nav.rename(benchmark_name),
        ],
        axis=1,
    )
    summary = pd.concat(
        [
            summarize_nav(strategy_nav).rename(strategy_name),
            summarize_nav(benchmark_nav).rename(benchmark_name),
        ],
        axis=1,
    )

    config = {
        "benchmark_name": benchmark_name,
        "benchmark_weight_col": benchmark_weight_col,
        "score_columns": score_columns,
        "score_weights": score_weights,
        "score_value_map": score_value_map,
        "higher_is_better": higher_is_better,
        "top_n": top_n,
        "top_pct": top_pct,
        "start_date": pd.to_datetime(start_date) if start_date is not None else None,
        "strategy_name": strategy_name,
        "sector_neutral": sector_neutral,
        "sector_column": sector_column,
        "max_weight": max_weight,
        "min_names": min_names,
    }

    return PatternBacktestResult(
        data=data,
        config=config,
        selection_pool=selection_pool,
        strategy_rebalance=strategy_rebalance,
        benchmark_rebalance=benchmark_rebalance,
        strategy_exec_weights=strategy_exec_weights,
        benchmark_exec_weights=benchmark_exec_weights,
        strategy_nav=strategy_nav,
        benchmark_nav=benchmark_nav,
        strategy_daily_return=strategy_daily_return,
        benchmark_daily_return=benchmark_daily_return,
        nav_df=nav_df,
        summary=summary,
    )


def build_ranked_rebalances(
    data: BacktestData,
    benchmark_weight_col: str,
    score_columns: Sequence[str],
    score_weights: Sequence[float],
    score_value_map: dict[str, Any] | None,
    higher_is_better: Sequence[bool],
    top_n: int | None = None,
    top_pct: float | None = None,
    start_date: str | pd.Timestamp | None = None,
    sector_neutral: bool = False,
    sector_column: str = DEFAULT_SECTOR_COL,
    max_weight: float = 1.0,
    min_names: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    selection_base = prepare_selection_base(
        patterns=data.patterns,
        screen=data.screen,
        benchmark_weight_col=benchmark_weight_col,
        score_columns=score_columns,
        start_date=start_date,
        sector_column=sector_column,
    )
    next_date_map = build_next_date_map(data.patterns["Date"])

    selection_rows: list[pd.DataFrame] = []
    strategy_rows: list[pd.DataFrame] = []
    benchmark_rows: list[pd.DataFrame] = []

    for signal_date, group in selection_base.groupby("Signal Date", sort=True):
        effective_date = next_date_map.get(signal_date, pd.NaT)
        if pd.isna(effective_date):
            continue

        group = group.copy()
        group = _fill_market_cap_from_weight(group)
        group = _add_score_columns(
            df=group,
            score_columns=score_columns,
            score_weights=score_weights,
            score_value_map=score_value_map,
            higher_is_better=higher_is_better,
            sector_neutral=sector_neutral,
        )
        group = group[group["Total Score"].notna()].copy()
        if group.empty:
            continue

        target_count = _resolve_target_count(len(group), top_n=top_n, top_pct=top_pct)
        group["Selection Rank"] = group["Total Score"].rank(method="first", ascending=False).astype(int)
        group["Sector Rank"] = group.groupby("Sector")["Total Score"].rank(method="first", ascending=False).astype(int)

        selected = _select_group_members(
            group=group,
            target_count=target_count,
            sector_neutral=sector_neutral,
            max_weight=max_weight,
        )
        if len(selected) < min_names:
            continue

        group["Date"] = pd.to_datetime(effective_date)
        selected["Date"] = pd.to_datetime(effective_date)

        selected = _assign_strategy_weights(
            selected=selected,
            full_group=group,
            sector_neutral=sector_neutral,
            max_weight=max_weight,
        )
        benchmark_group = _assign_market_cap_weights(group.copy(), "Benchmark Portfolio weight")
        benchmark_group["Date"] = pd.to_datetime(effective_date)

        group["Selected"] = group["Company SEDOL"].isin(selected["Company SEDOL"])
        group["Portfolio weight"] = np.nan
        group["Benchmark Portfolio weight"] = benchmark_group["Benchmark Portfolio weight"].values

        selected_for_pool = selected[["Company SEDOL", "Portfolio weight"]].set_index("Company SEDOL")
        selected_mask = group["Selected"]
        group.loc[selected_mask, "Portfolio weight"] = group.loc[selected_mask, "Company SEDOL"].map(selected_for_pool["Portfolio weight"]).to_numpy()

        selection_rows.append(group)
        strategy_rows.append(selected)
        benchmark_rows.append(benchmark_group)

    selection_pool = pd.concat(selection_rows, ignore_index=True) if selection_rows else pd.DataFrame()
    strategy_rebalance = _finalize_rebalance_frame(strategy_rows)
    benchmark_rebalance = _finalize_rebalance_frame(benchmark_rows, weight_col="Benchmark Portfolio weight")
    return selection_pool, strategy_rebalance, benchmark_rebalance


def prepare_selection_base(
    patterns: pd.DataFrame,
    screen: pd.DataFrame,
    benchmark_weight_col: str,
    score_columns: Sequence[str],
    start_date: str | pd.Timestamp | None = None,
    sector_column: str = DEFAULT_SECTOR_COL,
) -> pd.DataFrame:
    missing_score_columns = [col for col in score_columns if col not in patterns.columns]
    if missing_score_columns:
        raise KeyError(f"patterns.parquet 缺少评分列: {missing_score_columns}")

    required_screen_columns = [benchmark_weight_col, CANONICAL_MKT_CAP_COL, sector_column, "Company SEDOL", "Date"]
    missing_screen_columns = [col for col in required_screen_columns if col not in screen.columns]
    if missing_screen_columns:
        raise KeyError(f"screen_aggregate.parquet 缺少字段: {missing_screen_columns}")

    base = patterns.reset_index()[["Company SEDOL", "Date", *score_columns]].copy()
    base = base.rename(columns={"Date": "Signal Date"})
    if start_date is not None:
        base = base[base["Signal Date"] >= pd.to_datetime(start_date)].copy()

    signal_dates = pd.Index(pd.to_datetime(base["Signal Date"].dropna().unique())).sort_values()
    screen_dates = pd.Index(pd.to_datetime(screen["Date"].dropna().unique())).sort_values()
    screen_map = match_screen_dates(signal_dates, screen_dates)
    base["Screen Date"] = base["Signal Date"].map(screen_map)
    base = base.dropna(subset=["Screen Date"]).copy()

    optional_screen_columns = [col for col in ["Name", "Symbol"] if col in screen.columns]
    screen_view = screen[["Date", "Company SEDOL", benchmark_weight_col, CANONICAL_MKT_CAP_COL, sector_column, *optional_screen_columns]].copy()
    screen_view = screen_view.rename(columns={"Date": "Screen Date", benchmark_weight_col: "Benchmark Weight", sector_column: "Sector"})

    merged = base.merge(screen_view, how="left", on=["Screen Date", "Company SEDOL"])
    merged = merged[merged["Benchmark Weight"].fillna(0) > 0].copy()
    merged["Signal Date"] = pd.to_datetime(merged["Signal Date"])
    merged["Screen Date"] = pd.to_datetime(merged["Screen Date"])
    merged["Sector"] = merged["Sector"].fillna("Unknown")
    return merged.sort_values(["Signal Date", "Company SEDOL"]).reset_index(drop=True)


def build_next_date_map(all_dates: Sequence[pd.Timestamp]) -> pd.Series:
    dates = pd.Index(pd.to_datetime(pd.Series(all_dates).dropna().unique())).sort_values()
    if len(dates) < 2:
        return pd.Series(dtype="datetime64[ns]")
    return pd.Series(dates[1:].to_numpy(), index=dates[:-1].to_numpy())


def match_screen_dates(signal_dates: pd.Index, screen_dates: pd.Index) -> pd.Series:
    if screen_dates.empty:
        return pd.Series(pd.NaT, index=signal_dates)
    locs = screen_dates.get_indexer(signal_dates, method="pad")
    matched = pd.Series(pd.NaT, index=signal_dates)
    valid = locs >= 0
    if valid.any():
        matched.iloc[valid] = screen_dates[locs[valid]]
    return matched


def run_drift_backtest(rebal_weights: pd.DataFrame, returns: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    weights = rebal_weights.reset_index().copy()
    result = calculate_security_nav(
        weights=weights,
        returns=returns,
        schema=TargetWeightSchema(date_col="Date", id_col="Company SEDOL", weight_col="Portfolio weight"),
        strictly_after_rebalance=True,
        apply_weights_at_close=True,
    )
    return result.nav, result.daily_returns, result.execution_weights

def summarize_nav(nav: pd.Series) -> pd.Series:
    daily_ret = nav.pct_change().dropna()
    if daily_ret.empty:
        return pd.Series(dtype=float)

    total_return = nav.iloc[-1] / nav.iloc[0] - 1.0
    annual_return = (nav.iloc[-1] / nav.iloc[0]) ** (252 / len(daily_ret)) - 1.0
    annual_vol = daily_ret.std() * np.sqrt(252)
    sharpe_like = annual_return / annual_vol if annual_vol > 0 else np.nan
    max_drawdown = (nav / nav.cummax() - 1.0).min()

    return pd.Series({
        "start": nav.index.min(),
        "end": nav.index.max(),
        "nav_end": nav.iloc[-1],
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_vol": annual_vol,
        "sharpe_like": sharpe_like,
        "max_drawdown": max_drawdown,
    })


def get_selection_reason(selection_pool: pd.DataFrame, company_sedol: str, effective_date: str | pd.Timestamp, top_k: int = 10) -> dict[str, pd.DataFrame | pd.Series]:
    effective_date = pd.to_datetime(effective_date)
    pool = selection_pool[selection_pool["Date"] == effective_date].copy()
    if pool.empty:
        raise ValueError("该日期没有选股池数据。")

    pool = pool.sort_values("Total Score", ascending=False)
    row = pool[pool["Company SEDOL"] == company_sedol]
    if row.empty:
        raise ValueError(f"{company_sedol} 不在该日期的选股池中。")
    row = row.iloc[0]
    peers = pool.head(top_k).copy()
    return {"row": row, "peers": peers}


def _normalize_screen_columns(screen: pd.DataFrame) -> pd.DataFrame:
    screen = screen.copy()
    if LEGACY_MKT_CAP_COL in screen.columns and CANONICAL_MKT_CAP_COL not in screen.columns:
        screen = screen.rename(columns={LEGACY_MKT_CAP_COL: CANONICAL_MKT_CAP_COL})
    if CANONICAL_MKT_CAP_COL not in screen.columns:
        screen[CANONICAL_MKT_CAP_COL] = np.nan
    if LEGACY_MKT_CAP_COL in screen.columns:
        screen[CANONICAL_MKT_CAP_COL] = screen[CANONICAL_MKT_CAP_COL].fillna(screen[LEGACY_MKT_CAP_COL])
    if BACKUP_MKT_CAP_COL in screen.columns:
        screen[CANONICAL_MKT_CAP_COL] = screen[CANONICAL_MKT_CAP_COL].fillna(screen[BACKUP_MKT_CAP_COL])
    return screen


def _resolve_score_weights(score_columns: Sequence[str], score_weights: Sequence[float] | None) -> list[float]:
    if score_weights is None:
        return [1.0 / len(score_columns)] * len(score_columns)
    if len(score_weights) != len(score_columns):
        raise ValueError("score_weights 和 score_columns 长度不一致。")
    weights = pd.Series(score_weights, dtype=float)
    if (weights < 0).any() or weights.sum() <= 0:
        raise ValueError("score_weights 必须为非负，且总和大于 0。")
    weights = weights / weights.sum()
    return weights.tolist()


def _resolve_score_value_map(
    score_columns: Sequence[str],
    score_value_map: dict[str, Any] | None,
) -> dict[str, Any]:
    if score_value_map is None:
        return {}

    unknown_columns = [col for col in score_value_map if col not in score_columns]
    if unknown_columns:
        raise ValueError(f"score_value_map 包含未出现在 score_columns 中的字段: {unknown_columns}")
    return dict(score_value_map)


def _resolve_higher_is_better(
    score_columns: Sequence[str],
    higher_is_better: Sequence[bool] | None,
    ascending_flags: Sequence[bool] | None,
) -> list[bool]:
    if higher_is_better is not None and ascending_flags is not None:
        raise ValueError("higher_is_better 和 ascending_flags 只能传一个。")
    if higher_is_better is not None:
        if len(higher_is_better) != len(score_columns):
            raise ValueError("higher_is_better 和 score_columns 长度不一致。")
        return [bool(x) for x in higher_is_better]
    if ascending_flags is not None:
        if len(ascending_flags) != len(score_columns):
            raise ValueError("ascending_flags 和 score_columns 长度不一致。")
        return [not bool(x) for x in ascending_flags]
    return [True] * len(score_columns)


def _resolve_target_count(group_size: int, top_n: int | None, top_pct: float | None) -> int:
    if top_n is None and top_pct is None:
        raise ValueError("top_n 和 top_pct 需要至少提供一个。")
    if top_n is not None and top_pct is not None:
        raise ValueError("top_n 和 top_pct 只能提供一个。")
    if top_n is not None:
        if top_n <= 0:
            raise ValueError("top_n 必须大于 0。")
        return min(int(top_n), group_size)
    if top_pct is None or top_pct <= 0 or top_pct > 1:
        raise ValueError("top_pct 必须在 (0, 1] 之间。")
    return min(max(int(round(group_size * top_pct)), 1), group_size)


def _fill_market_cap_from_weight(group: pd.DataFrame) -> pd.DataFrame:
    group = group.copy()
    valid = group[["Benchmark Weight", CANONICAL_MKT_CAP_COL]].dropna()
    if len(valid) >= 2:
        fit = np.polyfit(valid["Benchmark Weight"], valid[CANONICAL_MKT_CAP_COL], deg=1)
        model = np.poly1d(fit)
        missing_mask = group[CANONICAL_MKT_CAP_COL].isna()
        if missing_mask.any():
            group.loc[missing_mask, CANONICAL_MKT_CAP_COL] = model(group.loc[missing_mask, "Benchmark Weight"])
    else:
        group[CANONICAL_MKT_CAP_COL] = group[CANONICAL_MKT_CAP_COL].fillna(group["Benchmark Weight"])
    group[CANONICAL_MKT_CAP_COL] = group[CANONICAL_MKT_CAP_COL].clip(lower=0)
    return group


def _add_score_columns(
    df: pd.DataFrame,
    score_columns: Sequence[str],
    score_weights: Sequence[float],
    score_value_map: dict[str, Any] | None,
    higher_is_better: Sequence[bool],
    sector_neutral: bool,
) -> pd.DataFrame:
    df = df.copy()
    score_value_map = score_value_map or {}
    component_cols: list[str] = []

    for col, weight, is_higher_better in zip(score_columns, score_weights, higher_is_better):
        component_col = f"Score::{col}"
        score_series = _prepare_score_series(df[col], score_value_map.get(col))
        if sector_neutral:
            df[component_col] = df.groupby("Sector")[col].transform(
                lambda _: score_series.loc[_.index].rank(method="average", pct=True, ascending=is_higher_better)
            )
        else:
            df[component_col] = score_series.rank(method="average", pct=True, ascending=is_higher_better)
        component_cols.append(component_col)

    weighted_sum = pd.Series(0.0, index=df.index)
    weight_used = pd.Series(0.0, index=df.index)
    for component_col, weight in zip(component_cols, score_weights):
        component = df[component_col]
        weighted_sum = weighted_sum + component.fillna(0.0) * weight
        weight_used = weight_used + component.notna().astype(float) * weight

    df["Total Score"] = weighted_sum / weight_used.replace(0.0, np.nan)
    return df


def _prepare_score_series(series: pd.Series, target_value: Any | None) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return _build_pattern_score_series(series, target_value)

    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")

    return _build_pattern_score_series(series, target_value)


def _build_pattern_score_series(series: pd.Series, target_value: Any | None) -> pd.Series:
    if target_value is None:
        if pd.api.types.is_bool_dtype(series):
            return series.fillna(False).astype(float)
        return _pattern_presence_mask(series).astype(float)

    if isinstance(target_value, (list, tuple, set, frozenset)):
        return series.isin(list(target_value)).fillna(False).astype(float)
    return series.eq(target_value).fillna(False).astype(float)


def _pattern_presence_mask(series: pd.Series) -> pd.Series:
    string_series = series.astype("string")
    return (
        string_series.notna()
        & string_series.str.lower().ne("none")
        & string_series.str.lower().ne("false")
        & string_series.str.lower().ne("nan")
        & string_series.str.len().gt(0)
    )


def _select_group_members(
    group: pd.DataFrame,
    target_count: int,
    sector_neutral: bool,
    max_weight: float = 1.0,
) -> pd.DataFrame:
    group = group.sort_values(["Total Score", "Company SEDOL"], ascending=[False, True]).copy()
    if not sector_neutral:
        return group.head(target_count).copy()

    sector_weights = group.groupby("Sector")["Benchmark Weight"].sum()
    available_counts = group.groupby("Sector").size()
    sector_counts = _allocate_sector_counts(sector_weights, available_counts, target_count)

    selected_parts: list[pd.DataFrame] = []
    for sector, count in sector_counts.items():
        if count <= 0:
            continue
        selected_parts.append(group[group["Sector"] == sector].head(count))

    selected = pd.concat(selected_parts, axis=0) if selected_parts else group.head(0).copy()
    if len(selected) < target_count:
        remaining = group.loc[~group.index.isin(selected.index)].head(target_count - len(selected))
        selected = pd.concat([selected, remaining], axis=0)
    return _ensure_sector_weight_capacity(
        selected=selected,
        eligible=group,
        target_count=target_count,
        max_weight=max_weight,
    )


def _ensure_sector_weight_capacity(
    selected: pd.DataFrame,
    eligible: pd.DataFrame,
    target_count: int,
    max_weight: float,
) -> pd.DataFrame:
    sector_targets = normalize_long_only_weights(
        eligible.groupby("Sector")["Benchmark Weight"].sum()
    )
    if max_weight <= 0:
        raise ValueError("max_weight must be positive")
    required = np.ceil(
        (sector_targets - 1e-12).clip(lower=0.0) / float(max_weight)
    ).astype(int).clip(lower=1)
    available = eligible.groupby("Sector").size().reindex(required.index).fillna(0)
    if (available < required).any():
        sectors = required.index[available < required].astype(str).tolist()
        raise ValueError(
            "sector-neutral cap is infeasible for sectors: "
            + ", ".join(sectors)
        )
    if int(required.sum()) > int(target_count):
        raise ValueError(
            "target_count is too small for sector-neutral max_weight capacity"
        )

    output = selected.copy()
    counts = output.groupby("Sector").size().reindex(required.index).fillna(0)
    for sector, minimum in required.items():
        deficit = int(minimum - counts.loc[sector])
        if deficit <= 0:
            continue
        additions = eligible[
            eligible["Sector"].eq(sector)
            & ~eligible.index.isin(output.index)
        ].head(deficit)
        output = pd.concat([output, additions], axis=0)
        counts.loc[sector] += len(additions)

    while len(output) > target_count:
        counts = output.groupby("Sector").size()
        removable = output[
            output["Sector"].map(counts).gt(output["Sector"].map(required))
        ]
        if removable.empty:
            raise ValueError(
                "cannot keep target_count while preserving sector capacity"
            )
        drop_index = removable.sort_values(
            ["Total Score", "Company SEDOL"],
            ascending=[True, False],
        ).index[0]
        output = output.drop(index=drop_index)
    return output.sort_values(
        ["Total Score", "Company SEDOL"],
        ascending=[False, True],
    ).copy()


def _allocate_sector_counts(sector_weights: pd.Series, available_counts: pd.Series, target_count: int) -> pd.Series:
    available_counts = available_counts[available_counts > 0].astype(int)
    sector_weights = sector_weights.reindex(available_counts.index).fillna(0.0)
    if available_counts.empty or target_count <= 0:
        return pd.Series(dtype=int)

    if sector_weights.sum() <= 0:
        sector_weights = pd.Series(1.0, index=available_counts.index)
    sector_weights = sector_weights / sector_weights.sum()

    raw_counts = sector_weights * target_count
    counts = pd.Series(np.floor(raw_counts).astype(int), index=available_counts.index).clip(upper=available_counts)

    remaining = target_count - int(counts.sum())
    fractional = (raw_counts - np.floor(raw_counts)).sort_values(ascending=False)
    while remaining > 0:
        progressed = False
        for sector in fractional.index:
            if counts[sector] >= available_counts[sector]:
                continue
            counts[sector] += 1
            remaining -= 1
            progressed = True
            if remaining == 0:
                break
        if not progressed:
            break
    return counts.astype(int)


def _assign_strategy_weights(
    selected: pd.DataFrame,
    full_group: pd.DataFrame,
    sector_neutral: bool,
    max_weight: float,
) -> pd.DataFrame:
    selected = selected.copy()
    if not sector_neutral:
        return _assign_market_cap_weights(
            selected,
            "Portfolio weight",
            max_weight=max_weight,
        )

    sector_weights = normalize_long_only_weights(
        full_group.groupby("Sector")["Benchmark Weight"].sum()
    )
    selected["Portfolio weight"] = (
        pd.to_numeric(selected[CANONICAL_MKT_CAP_COL], errors="coerce")
        .fillna(0.0)
        .clip(lower=0.0)
    )
    zero_sector = (
        selected.groupby("Sector")["Portfolio weight"].transform("sum").le(0.0)
    )
    selected.loc[zero_sector, "Portfolio weight"] = 1.0
    selected = match_group_weight_targets(
        selected,
        sector_weights,
        weight_col="Portfolio weight",
        group_cols="Sector",
    )
    return cap_weights_preserving_group_totals(
        selected,
        weight_col="Portfolio weight",
        max_weight=max_weight,
        group_cols="Sector",
    )


def _assign_market_cap_weights(
    df: pd.DataFrame,
    output_col: str,
    *,
    max_weight: float = 1.0,
) -> pd.DataFrame:
    df = df.copy()
    df[output_col] = pd.to_numeric(
        df[CANONICAL_MKT_CAP_COL],
        errors="coerce",
    )
    return normalize_weight_table(
        df,
        weight_col=output_col,
        group_cols=None,
        max_weight=max_weight,
        allow_equal_fallback=True,
    )


def _finalize_rebalance_frame(frames: list[pd.DataFrame], weight_col: str = "Portfolio weight") -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=["Date", "Company SEDOL", "Signal Date", "Screen Date", "Portfolio weight", "Sector", "Name", "Symbol", "Total Score", "Selection Rank", "Sector Rank"]).set_index(["Date", "Company SEDOL"])

    base_columns = ["Date", "Company SEDOL", "Signal Date", "Screen Date", weight_col, "Sector", "Name", "Symbol", "Total Score", "Selection Rank", "Sector Rank"]
    available_cols = [col for col in base_columns if col in frames[0].columns]
    df = pd.concat([frame[available_cols].copy() for frame in frames], ignore_index=True)
    if weight_col != "Portfolio weight":
        df = df.rename(columns={weight_col: "Portfolio weight"})
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index(["Date", "Company SEDOL"]).sort_index()


__all__ = [
    "BacktestData",
    "PatternBacktestResult",
    "build_next_date_map",
    "build_ranked_rebalances",
    "get_selection_reason",
    "load_backtest_data",
    "match_screen_dates",
    "run_drift_backtest",
    "run_ranked_pattern_backtest",
    "summarize_nav",
]

"""General long-only backtest engine used across TP projects.

The common contract is intentionally small:

* input weights are in long format: date, security id, target weight
* returns are in wide format: Date index, one column per security id
* output contains NAV, daily returns, executable weights, metrics and a manifest

Domain projects should build their own signals or selections, then convert them
to this target-weight table before calling the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


DEFAULT_DATE_COL = "Date"
DEFAULT_ID_COL = "Company SEDOL"
DEFAULT_WEIGHT_COL = "Portfolio weight"


@dataclass(frozen=True)
class BacktestSchema:
    """Column mapping for a standard long-format rebalance table."""

    date_col: str = DEFAULT_DATE_COL
    id_col: str = DEFAULT_ID_COL
    weight_col: str = DEFAULT_WEIGHT_COL


@dataclass
class GeneralBacktestResult:
    """Result object returned by the general backtest engine."""

    nav: pd.Series
    daily_returns: pd.Series
    rebalance_weights: pd.DataFrame
    execution_weights: pd.DataFrame
    turnover: pd.Series
    metrics: dict[str, float]
    manifest: dict[str, Any] = field(default_factory=dict)


def load_returns(returns: str | Path | pd.DataFrame) -> pd.DataFrame:
    """Load and normalize a wide daily return matrix."""

    if isinstance(returns, (str, Path)):
        df_returns = pd.read_parquet(returns)
    elif isinstance(returns, pd.DataFrame):
        df_returns = returns.copy(deep=False)
    else:
        raise TypeError("returns must be a parquet path or a pandas DataFrame")

    df_returns.index = pd.to_datetime(df_returns.index)
    df_returns.columns = df_returns.columns.astype(str)
    return df_returns.sort_index()


def ensure_weight_columns(weights: pd.DataFrame, schema: BacktestSchema) -> None:
    """Raise a clear error if the rebalance table does not match the contract."""

    missing = [col for col in [schema.date_col, schema.id_col, schema.weight_col] if col not in weights.columns]
    if missing:
        raise KeyError(f"weight table missing required columns: {missing}")


def normalize_rebalance_weights(
    weights: pd.DataFrame,
    returns_columns: Iterable[str],
    schema: BacktestSchema = BacktestSchema(),
    normalize: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Clean a long-format rebalance table and normalize weights by date."""

    ensure_weight_columns(weights, schema)
    returns_universe = set(pd.Index(returns_columns).astype(str))

    out = weights.copy()
    input_rows = int(len(out))
    out[schema.date_col] = pd.to_datetime(out[schema.date_col])
    out[schema.id_col] = out[schema.id_col].astype(str)
    out[schema.weight_col] = pd.to_numeric(out[schema.weight_col], errors="coerce")

    out = out.dropna(subset=[schema.date_col, schema.id_col, schema.weight_col]).copy()
    dropped_null = input_rows - len(out)

    out = out[out[schema.weight_col] != 0].copy()
    dropped_zero = input_rows - dropped_null - len(out)

    before_universe = len(out)
    out = out[out[schema.id_col].isin(returns_universe)].copy()
    dropped_not_in_returns = before_universe - len(out)

    if out.empty:
        raise ValueError("no rebalance rows remain after applying the returns universe")

    agg: dict[str, str] = {schema.weight_col: "sum"}
    for col in out.columns:
        if col not in [schema.date_col, schema.id_col, schema.weight_col]:
            agg[col] = "first"

    out = out.groupby([schema.date_col, schema.id_col], as_index=False).agg(agg)
    if normalize:
        denom = out.groupby(schema.date_col)[schema.weight_col].transform("sum")
        out = out[denom != 0].copy()
        denom = out.groupby(schema.date_col)[schema.weight_col].transform("sum")
        out[schema.weight_col] = out[schema.weight_col] / denom

    out = out.sort_values([schema.date_col, schema.id_col]).reset_index(drop=True)
    manifest = {
        "input_rows": input_rows,
        "normalized_rows": int(len(out)),
        "dropped_null_rows": int(dropped_null),
        "dropped_zero_weight_rows": int(dropped_zero),
        "dropped_not_in_returns_rows": int(dropped_not_in_returns),
        "rebalance_date_count": int(out[schema.date_col].nunique()),
        "security_count": int(out[schema.id_col].nunique()),
    }
    return out, manifest


def map_rebalance_to_execution_dates(
    weights: pd.DataFrame,
    returns_index: pd.DatetimeIndex,
    schema: BacktestSchema = BacktestSchema(),
    strictly_after_rebalance: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Map rebalance dates to executable dates available in the returns index."""

    if returns_index.empty:
        raise ValueError("returns index is empty")

    out = weights.copy()
    returns_index = pd.DatetimeIndex(pd.to_datetime(returns_index)).sort_values().unique()
    mapped_dates: dict[pd.Timestamp, pd.Timestamp] = {}
    unmapped_dates: list[str] = []

    for raw_date in pd.DatetimeIndex(out[schema.date_col].dropna().unique()).sort_values():
        if strictly_after_rebalance:
            candidates = returns_index[returns_index > raw_date]
        else:
            candidates = returns_index[returns_index >= raw_date]
        if len(candidates) == 0:
            unmapped_dates.append(str(pd.Timestamp(raw_date).date()))
            continue
        mapped_dates[pd.Timestamp(raw_date)] = pd.Timestamp(candidates[0])

    out[schema.date_col] = out[schema.date_col].map(mapped_dates)
    out = out.dropna(subset=[schema.date_col]).copy()
    if out.empty:
        raise ValueError("rebalance dates cannot be mapped to the returns calendar")

    agg: dict[str, str] = {schema.weight_col: "sum"}
    for col in out.columns:
        if col not in [schema.date_col, schema.id_col, schema.weight_col]:
            agg[col] = "first"

    out = out.groupby([schema.date_col, schema.id_col], as_index=False).agg(agg)
    denom = out.groupby(schema.date_col)[schema.weight_col].transform("sum")
    out = out[denom != 0].copy()
    denom = out.groupby(schema.date_col)[schema.weight_col].transform("sum")
    out[schema.weight_col] = out[schema.weight_col] / denom
    out = out.sort_values([schema.date_col, schema.id_col]).reset_index(drop=True)

    manifest = {
        "execution_date_count": int(out[schema.date_col].nunique()),
        "unmapped_rebalance_dates": unmapped_dates,
        "strictly_after_rebalance": bool(strictly_after_rebalance),
    }
    return out, manifest


def calculate_simple_turnover(
    execution_weights: pd.DataFrame,
    schema: BacktestSchema = BacktestSchema(),
) -> pd.Series:
    """Calculate one-way turnover between consecutive target-weight vectors."""

    dates = pd.DatetimeIndex(execution_weights[schema.date_col].unique()).sort_values()
    previous = pd.Series(dtype=float)
    values: list[float] = []

    for date in dates:
        current = (
            execution_weights.loc[execution_weights[schema.date_col] == date, [schema.id_col, schema.weight_col]]
            .set_index(schema.id_col)[schema.weight_col]
            .astype(float)
        )
        all_ids = previous.index.union(current.index)
        diff = current.reindex(all_ids, fill_value=0.0) - previous.reindex(all_ids, fill_value=0.0)
        values.append(float(diff.abs().sum() / 2.0))
        previous = current

    return pd.Series(values, index=dates, name="turnover")


def summarize_daily_returns(daily_returns: pd.Series, periods_per_year: int = 252) -> dict[str, float]:
    """Return standard performance metrics for a daily return series."""

    daily_returns = pd.Series(daily_returns).dropna().astype(float)
    if daily_returns.empty:
        return {}

    nav = (1.0 + daily_returns).cumprod()
    total_return = float(nav.iloc[-1] - 1.0)
    years = max(len(daily_returns) / periods_per_year, np.nan)
    if years and years > 0:
        annual_return = float((1.0 + total_return) ** (1.0 / years) - 1.0)
    else:
        annual_return = np.nan

    annual_volatility = float(daily_returns.std() * np.sqrt(periods_per_year))
    sharpe = float(annual_return / annual_volatility) if annual_volatility > 0 else np.nan
    max_drawdown = float((nav / nav.cummax() - 1.0).min())

    return {
        "start": daily_returns.index.min(),
        "end": daily_returns.index.max(),
        "observations": int(len(daily_returns)),
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe_like": sharpe,
        "max_drawdown": max_drawdown,
    }


def backtest_weight_table(
    weights: pd.DataFrame,
    returns: str | Path | pd.DataFrame,
    schema: BacktestSchema = BacktestSchema(),
    initial_nav: float = 100.0,
    normalize: bool = True,
    strictly_after_rebalance: bool = True,
    apply_weights_at_close: bool = True,
) -> GeneralBacktestResult:
    """Run a drift-aware backtest from target weights and a returns matrix."""

    df_returns = load_returns(returns)
    rebalance_weights, normalize_manifest = normalize_rebalance_weights(
        weights=weights,
        returns_columns=df_returns.columns,
        schema=schema,
        normalize=normalize,
    )
    execution_weights, execution_manifest = map_rebalance_to_execution_dates(
        weights=rebalance_weights,
        returns_index=df_returns.index,
        schema=schema,
        strictly_after_rebalance=strictly_after_rebalance,
    )

    target_by_date = {
        pd.Timestamp(date): group.set_index(schema.id_col)[schema.weight_col].astype(float)
        for date, group in execution_weights.groupby(schema.date_col)
    }

    start_date = execution_weights[schema.date_col].min()
    current_weights: pd.Series | None = None
    nav_dates: list[pd.Timestamp] = []
    daily_return_values: list[float] = []

    for date, row in df_returns.loc[df_returns.index >= start_date].iterrows():
        date = pd.Timestamp(date)
        if not apply_weights_at_close and date in target_by_date:
            current_weights = target_by_date[date].copy()

        if current_weights is None:
            portfolio_return = 0.0
        else:
            asset_returns = row.reindex(current_weights.index).fillna(0.0).astype(float)
            portfolio_return = float((current_weights * asset_returns).sum())
            current_weights = current_weights * (1.0 + asset_returns)
            total_weight = float(current_weights.sum())
            if total_weight != 0:
                current_weights = current_weights / total_weight

        nav_dates.append(date)
        daily_return_values.append(portfolio_return)

        if apply_weights_at_close and date in target_by_date:
            current_weights = target_by_date[date].copy()

    daily_returns = pd.Series(daily_return_values, index=pd.DatetimeIndex(nav_dates), name="daily_return")
    nav = (1.0 + daily_returns.fillna(0.0)).cumprod() * float(initial_nav)
    nav.name = "nav"
    turnover = calculate_simple_turnover(execution_weights=execution_weights, schema=schema)
    metrics = summarize_daily_returns(daily_returns=daily_returns)

    manifest = {
        **normalize_manifest,
        **execution_manifest,
        "initial_nav": float(initial_nav),
        "apply_weights_at_close": bool(apply_weights_at_close),
        "returns_start": df_returns.index.min(),
        "returns_end": df_returns.index.max(),
        "returns_observations": int(len(df_returns)),
    }

    return GeneralBacktestResult(
        nav=nav,
        daily_returns=daily_returns,
        rebalance_weights=rebalance_weights,
        execution_weights=execution_weights.set_index([schema.date_col, schema.id_col]).sort_index(),
        turnover=turnover,
        metrics=metrics,
        manifest=manifest,
    )


class GeneralBacktestEngine:
    """Reusable engine for all projects that can produce target weights."""

    def __init__(self, returns: str | Path | pd.DataFrame):
        self.returns = load_returns(returns)
        self.last_result: GeneralBacktestResult | None = None

    def run_weights(
        self,
        weights: pd.DataFrame,
        schema: BacktestSchema = BacktestSchema(),
        initial_nav: float = 100.0,
        normalize: bool = True,
        strictly_after_rebalance: bool = True,
        apply_weights_at_close: bool = True,
    ) -> GeneralBacktestResult:
        """Run a general backtest from a standard target-weight table."""

        result = backtest_weight_table(
            weights=weights,
            returns=self.returns,
            schema=schema,
            initial_nav=initial_nav,
            normalize=normalize,
            strictly_after_rebalance=strictly_after_rebalance,
            apply_weights_at_close=apply_weights_at_close,
        )
        self.last_result = result
        return result


__all__ = [
    "BacktestSchema",
    "GeneralBacktestEngine",
    "GeneralBacktestResult",
    "backtest_weight_table",
    "calculate_simple_turnover",
    "load_returns",
    "map_rebalance_to_execution_dates",
    "normalize_rebalance_weights",
    "summarize_daily_returns",
]

"""Exact security-level drift and NAV calculation for TP portfolios.

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
NAV_ENGINE_ID = "tp.security_nav"
NAV_ENGINE_VERSION = "3.0.0"


@dataclass(frozen=True)
class TargetWeightSchema:
    """Column mapping for a standard long-format rebalance table."""

    date_col: str = DEFAULT_DATE_COL
    id_col: str = DEFAULT_ID_COL
    weight_col: str = DEFAULT_WEIGHT_COL


@dataclass
class SecurityNavResult:
    """Result of an exact security-level target-weight calculation."""

    nav: pd.Series
    daily_returns: pd.Series
    rebalance_weights: pd.DataFrame
    execution_weights: pd.DataFrame
    turnover: pd.Series
    metrics: dict[str, float]
    manifest: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReturnSeriesNavResult:
    """Result returned for an already-aggregated return series."""

    nav: pd.Series
    returns: pd.Series
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


def ensure_weight_columns(weights: pd.DataFrame, schema: TargetWeightSchema) -> None:
    """Raise a clear error if the rebalance table does not match the contract."""

    missing = [col for col in [schema.date_col, schema.id_col, schema.weight_col] if col not in weights.columns]
    if missing:
        raise KeyError(f"weight table missing required columns: {missing}")


def normalize_rebalance_weights(
    weights: pd.DataFrame,
    returns_columns: Iterable[str],
    schema: TargetWeightSchema = TargetWeightSchema(),
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
    schema: TargetWeightSchema = TargetWeightSchema(),
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
    schema: TargetWeightSchema = TargetWeightSchema(),
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


def nav_engine_metadata(
    *,
    strictly_after_rebalance: bool | None = None,
    apply_weights_at_close: bool | None = None,
) -> dict[str, Any]:
    """Return stable engine identity and optional execution semantics."""

    metadata: dict[str, Any] = {
        "engine_id": NAV_ENGINE_ID,
        "engine_version": NAV_ENGINE_VERSION,
    }
    if strictly_after_rebalance is not None or apply_weights_at_close is not None:
        metadata["execution_policy"] = {
            "strictly_after_rebalance": strictly_after_rebalance,
            "apply_weights_at_close": apply_weights_at_close,
            "rebalance_mapping": (
                "first_returns_date_strictly_after_rebalance"
                if strictly_after_rebalance
                else "first_returns_date_on_or_after_rebalance"
            ),
            "weight_application": (
                "after_close_return"
                if apply_weights_at_close
                else "before_open_return"
            ),
        }
    return metadata


def calculate_return_series_nav(
    returns: pd.Series,
    *,
    initial_nav: float = 100.0,
    periods_per_year: int = 252,
    name: str = "strategy",
    fill_missing_with_zero: bool = True,
) -> ReturnSeriesNavResult:
    """Build NAV and metrics for an already-aggregated return series."""

    series = pd.Series(returns).copy()
    series.index = pd.to_datetime(series.index)
    series = pd.to_numeric(series, errors="coerce").sort_index()
    if fill_missing_with_zero:
        series = series.fillna(0.0)
    else:
        series = series.dropna()
    series.name = name
    nav = (1.0 + series).cumprod() * float(initial_nav)
    nav.name = f"{name}_nav"
    manifest = {
        **nav_engine_metadata(),
        "input_kind": "aggregated_return_series",
        "execution_policy": {
            "return_observation": "already_aggregated",
            "weight_application": "not_applicable",
            "compounding": "same_observation",
        },
        "periods_per_year": int(periods_per_year),
        "initial_nav": float(initial_nav),
        "fill_missing_with_zero": bool(fill_missing_with_zero),
        "observations": int(len(series)),
    }
    return ReturnSeriesNavResult(
        nav=nav,
        returns=series,
        metrics=summarize_daily_returns(series, periods_per_year=periods_per_year),
        manifest=manifest,
    )


def _calculate_daily_returns_exact(
    df_returns: pd.DataFrame,
    execution_weights: pd.DataFrame,
    schema: TargetWeightSchema,
    *,
    apply_weights_at_close: bool,
) -> pd.Series:
    """Run the exact drift loop with NumPy rows instead of pandas iterrows."""

    target_by_date: dict[pd.Timestamp, tuple[np.ndarray, np.ndarray]] = {}
    return_columns = pd.Index(df_returns.columns)
    for date, group in execution_weights.groupby(schema.date_col):
        ids = group[schema.id_col].astype(str)
        positions = return_columns.get_indexer(ids)
        if (positions < 0).any():
            raise ValueError("execution weights contain securities absent from returns")
        target_by_date[pd.Timestamp(date)] = (
            positions,
            group[schema.weight_col].to_numpy(dtype=float, copy=True),
        )

    start_date = execution_weights[schema.date_col].min()
    return_block = df_returns.loc[df_returns.index >= start_date]
    return_values = return_block.to_numpy(dtype=float, copy=False)
    current_positions: np.ndarray | None = None
    current_weights: np.ndarray | None = None
    daily_return_values = np.empty(len(return_block), dtype=float)

    for row_number, date in enumerate(return_block.index):
        date = pd.Timestamp(date)
        target = target_by_date.get(date)
        if not apply_weights_at_close and target is not None:
            current_positions, current_weights = target
            current_weights = current_weights.copy()

        if current_weights is None or current_positions is None:
            portfolio_return = 0.0
        else:
            asset_returns = return_values[row_number, current_positions]
            if np.isnan(asset_returns).any():
                asset_returns = np.nan_to_num(asset_returns, nan=0.0)
            portfolio_return = float((current_weights * asset_returns).sum())
            current_weights = current_weights * (1.0 + asset_returns)
            total_weight = float(current_weights.sum())
            if total_weight != 0:
                current_weights = current_weights / total_weight

        daily_return_values[row_number] = portfolio_return

        if apply_weights_at_close and target is not None:
            current_positions, current_weights = target
            current_weights = current_weights.copy()

    return pd.Series(
        daily_return_values,
        index=pd.DatetimeIndex(return_block.index.to_numpy(copy=True)),
        name="daily_return",
    )


def calculate_security_nav(
    weights: pd.DataFrame,
    returns: str | Path | pd.DataFrame,
    schema: TargetWeightSchema = TargetWeightSchema(),
    initial_nav: float = 100.0,
    normalize: bool = True,
    strictly_after_rebalance: bool = True,
    apply_weights_at_close: bool = True,
) -> SecurityNavResult:
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

    daily_returns = _calculate_daily_returns_exact(
        df_returns=df_returns,
        execution_weights=execution_weights,
        schema=schema,
        apply_weights_at_close=apply_weights_at_close,
    )
    nav = (1.0 + daily_returns.fillna(0.0)).cumprod() * float(initial_nav)
    nav.name = "nav"
    turnover = calculate_simple_turnover(execution_weights=execution_weights, schema=schema)
    metrics = summarize_daily_returns(daily_returns=daily_returns)

    manifest = {
        **nav_engine_metadata(
            strictly_after_rebalance=strictly_after_rebalance,
            apply_weights_at_close=apply_weights_at_close,
        ),
        **normalize_manifest,
        **execution_manifest,
        "initial_nav": float(initial_nav),
        "apply_weights_at_close": bool(apply_weights_at_close),
        "returns_start": df_returns.index.min(),
        "returns_end": df_returns.index.max(),
        "returns_observations": int(len(df_returns)),
    }

    return SecurityNavResult(
        nav=nav,
        daily_returns=daily_returns,
        rebalance_weights=rebalance_weights,
        execution_weights=execution_weights.set_index([schema.date_col, schema.id_col]).sort_index(),
        turnover=turnover,
        metrics=metrics,
        manifest=manifest,
    )


class SecurityNavEngine:
    """Exact drift/NAV calculator for standard security target weights."""

    def __init__(self, returns: str | Path | pd.DataFrame):
        self.returns = load_returns(returns)
        self.last_result: SecurityNavResult | None = None

    def run_weights(
        self,
        weights: pd.DataFrame,
        schema: TargetWeightSchema = TargetWeightSchema(),
        initial_nav: float = 100.0,
        normalize: bool = True,
        strictly_after_rebalance: bool = True,
        apply_weights_at_close: bool = True,
    ) -> SecurityNavResult:
        """Calculate security-level NAV from a standard target-weight table."""

        result = calculate_security_nav(
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
    "NAV_ENGINE_ID",
    "NAV_ENGINE_VERSION",
    "ReturnSeriesNavResult",
    "SecurityNavEngine",
    "SecurityNavResult",
    "TargetWeightSchema",
    "calculate_return_series_nav",
    "calculate_security_nav",
    "calculate_simple_turnover",
    "nav_engine_metadata",
    "load_returns",
    "map_rebalance_to_execution_dates",
    "normalize_rebalance_weights",
    "summarize_daily_returns",
]

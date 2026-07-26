"""Weight-space order and fill simulation layered on the exact TP NAV contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import uuid

import numpy as np
import pandas as pd

from tp_core.security_nav_engine import (
    SecurityNavResult,
    TargetWeightSchema,
    calculate_security_nav,
    load_returns,
    map_rebalance_to_execution_dates,
    normalize_rebalance_weights,
    summarize_daily_returns,
)

EXECUTION_ENGINE_ID = "tp.weight_execution"
EXECUTION_ENGINE_VERSION = "1.0.0"


@dataclass(frozen=True)
class ExecutionAssumptions:
    mode: str = "fast_nav"
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    max_one_way_turnover_per_day: float | None = None
    missing_return_policy: str = "zero_with_audit"

    def __post_init__(self) -> None:
        if self.mode not in {"fast_nav", "weight_simulated"}:
            raise ValueError(f"不支持的 execution mode：{self.mode}")
        if self.commission_bps < 0 or self.slippage_bps < 0:
            raise ValueError("commission_bps 和 slippage_bps 不能为负")
        cap = self.max_one_way_turnover_per_day
        if cap is not None and not 0 < cap <= 1:
            raise ValueError("max_one_way_turnover_per_day 必须位于 (0, 1]")
        if self.missing_return_policy != "zero_with_audit":
            raise ValueError("当前仅支持 missing_return_policy=zero_with_audit")


@dataclass(frozen=True)
class WeightOrder:
    order_id: str
    execution_date: str
    security_id: str
    current_weight: float
    target_weight: float
    requested_delta_weight: float


@dataclass(frozen=True)
class WeightFill:
    fill_id: str
    order_id: str
    execution_date: str
    security_id: str
    filled_delta_weight: float
    one_way_turnover: float
    commission_cost: float
    slippage_cost: float


@dataclass
class WeightExecutionResult:
    gross_nav: pd.Series
    net_nav: pd.Series
    gross_daily_returns: pd.Series
    net_daily_returns: pd.Series
    orders: pd.DataFrame
    fills: pd.DataFrame
    residuals: pd.DataFrame
    end_weights: pd.DataFrame
    turnover: pd.Series
    metrics: dict[str, float]
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def nav(self) -> pd.Series:
        return self.net_nav

    @property
    def daily_returns(self) -> pd.Series:
        return self.net_daily_returns


def _records_frame(records: list[object], columns: list[str]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame([asdict(record) for record in records])


def simulate_weight_execution(
    weights: pd.DataFrame,
    returns: str | Path | pd.DataFrame,
    *,
    assumptions: ExecutionAssumptions = ExecutionAssumptions(mode="weight_simulated"),
    schema: TargetWeightSchema = TargetWeightSchema(),
    initial_nav: float = 100.0,
    normalize: bool = True,
    strictly_after_rebalance: bool = True,
) -> WeightExecutionResult:
    """Simulate close fills, residual carry and portfolio-level execution costs."""

    if assumptions.mode != "weight_simulated":
        raise ValueError("simulate_weight_execution 需要 mode=weight_simulated")
    df_returns = load_returns(returns)
    normalized, normalize_manifest = normalize_rebalance_weights(
        weights,
        returns_columns=df_returns.columns,
        schema=schema,
        normalize=normalize,
    )
    executable, mapping_manifest = map_rebalance_to_execution_dates(
        normalized,
        returns_index=df_returns.index,
        schema=schema,
        strictly_after_rebalance=strictly_after_rebalance,
    )
    target_by_date = {
        pd.Timestamp(date): group.set_index(schema.id_col)[schema.weight_col].astype(float)
        for date, group in executable.groupby(schema.date_col)
    }
    return_block = df_returns.loc[df_returns.index >= executable[schema.date_col].min()]
    columns = pd.Index(return_block.columns.astype(str))
    current = np.zeros(len(columns), dtype=float)
    desired: np.ndarray | None = None
    active_orders: dict[int, str] = {}
    order_records: list[WeightOrder] = []
    fill_records: list[WeightFill] = []
    residual_rows: list[dict[str, Any]] = []
    weight_rows: list[dict[str, Any]] = []
    gross_values: list[float] = []
    net_values: list[float] = []
    turnover_values: list[float] = []
    missing_held_return_count = 0
    cost_rate_per_turnover = (assumptions.commission_bps + assumptions.slippage_bps) / 10_000

    for row_number, date in enumerate(return_block.index):
        timestamp = pd.Timestamp(date)
        asset_returns = return_block.iloc[row_number].to_numpy(dtype=float, copy=True)
        missing = np.isnan(asset_returns)
        missing_held_return_count += int(np.count_nonzero(missing & (np.abs(current) > 0)))
        asset_returns[missing] = 0.0
        gross_return = float(np.dot(current, asset_returns))
        denominator = 1.0 + gross_return
        if denominator != 0:
            current = current * (1.0 + asset_returns) / denominator

        target = target_by_date.get(timestamp)
        if target is not None:
            desired = np.zeros(len(columns), dtype=float)
            positions = columns.get_indexer(target.index.astype(str))
            desired[positions] = target.to_numpy(dtype=float)
            active_orders = {}
            deltas = desired - current
            for position in np.flatnonzero(np.abs(deltas) > 1e-15):
                order_id = f"{timestamp:%Y%m%d}-{position}-{uuid.uuid4().hex[:8]}"
                active_orders[int(position)] = order_id
                order_records.append(
                    WeightOrder(
                        order_id=order_id,
                        execution_date=timestamp.date().isoformat(),
                        security_id=str(columns[position]),
                        current_weight=float(current[position]),
                        target_weight=float(desired[position]),
                        requested_delta_weight=float(deltas[position]),
                    )
                )

        turnover = 0.0
        if desired is not None:
            outstanding = desired - current
            requested_turnover = float(np.abs(outstanding).sum() / 2.0)
            cap = assumptions.max_one_way_turnover_per_day
            scale = 1.0 if cap is None or requested_turnover <= cap else cap / requested_turnover
            filled = outstanding * scale
            turnover = float(np.abs(filled).sum() / 2.0)
            current = current + filled
            for position in np.flatnonzero(np.abs(filled) > 1e-15):
                order_id = active_orders.get(int(position))
                if order_id is None:
                    order_id = f"{timestamp:%Y%m%d}-{position}-carry"
                    active_orders[int(position)] = order_id
                fill_records.append(
                    WeightFill(
                        fill_id=f"{order_id}-{timestamp:%Y%m%d}",
                        order_id=order_id,
                        execution_date=timestamp.date().isoformat(),
                        security_id=str(columns[position]),
                        filled_delta_weight=float(filled[position]),
                        one_way_turnover=float(abs(filled[position]) / 2.0),
                        commission_cost=float(abs(filled[position]) / 2.0 * assumptions.commission_bps / 10_000),
                        slippage_cost=float(abs(filled[position]) / 2.0 * assumptions.slippage_bps / 10_000),
                    )
                )
            residual = desired - current
            for position in np.flatnonzero(np.abs(residual) > 1e-12):
                residual_rows.append(
                    {
                        "execution_date": timestamp,
                        "security_id": str(columns[position]),
                        "residual_delta_weight": float(residual[position]),
                    }
                )

        gross_values.append(gross_return)
        net_values.append(gross_return - turnover * cost_rate_per_turnover)
        turnover_values.append(turnover)
        for position in np.flatnonzero(np.abs(current) > 1e-15):
            weight_rows.append(
                {
                    "execution_date": timestamp,
                    "security_id": str(columns[position]),
                    "end_weight": float(current[position]),
                }
            )

    index = pd.DatetimeIndex(return_block.index)
    gross_returns = pd.Series(gross_values, index=index, name="gross_daily_return")
    turnover_series = pd.Series(turnover_values, index=index, name="filled_one_way_turnover")
    if assumptions.max_one_way_turnover_per_day is None:
        fast_result = calculate_security_nav(
            weights,
            df_returns,
            schema=schema,
            initial_nav=initial_nav,
            normalize=normalize,
            strictly_after_rebalance=strictly_after_rebalance,
            apply_weights_at_close=True,
        )
        gross_returns = fast_result.daily_returns.rename("gross_daily_return")
    net_returns = (
        gross_returns - turnover_series.reindex(gross_returns.index, fill_value=0.0) * cost_rate_per_turnover
    ).rename("net_daily_return")
    gross_nav = ((1.0 + gross_returns).cumprod() * float(initial_nav)).rename("gross_nav")
    net_nav = ((1.0 + net_returns).cumprod() * float(initial_nav)).rename("net_nav")
    metrics = {
        **{f"gross_{key}": value for key, value in summarize_daily_returns(gross_returns).items()},
        **{f"net_{key}": value for key, value in summarize_daily_returns(net_returns).items()},
    }
    manifest = {
        "engine_id": EXECUTION_ENGINE_ID,
        "engine_version": EXECUTION_ENGINE_VERSION,
        "assumptions": asdict(assumptions),
        "semantics": {
            "decision_to_execution": "first_returns_date_strictly_after_decision",
            "fill_timing": "after_execution_date_close_return",
            "residual_policy": "carry_until_filled_or_replaced_by_new_target",
            "turnover": "0.5 * sum(abs(filled_delta_weight))",
            "missing_return": "zero_with_audit",
        },
        "missing_held_return_count": missing_held_return_count,
        "commission_cost_total": float(sum(record.commission_cost for record in fill_records)),
        "slippage_cost_total": float(sum(record.slippage_cost for record in fill_records)),
        **normalize_manifest,
        **mapping_manifest,
    }
    return WeightExecutionResult(
        gross_nav=gross_nav,
        net_nav=net_nav,
        gross_daily_returns=gross_returns,
        net_daily_returns=net_returns,
        orders=_records_frame(order_records, list(WeightOrder.__annotations__)),
        fills=_records_frame(fill_records, list(WeightFill.__annotations__)),
        residuals=pd.DataFrame(
            residual_rows,
            columns=["execution_date", "security_id", "residual_delta_weight"],
        ),
        end_weights=pd.DataFrame(
            weight_rows,
            columns=["execution_date", "security_id", "end_weight"],
        ),
        turnover=turnover_series,
        metrics=metrics,
        manifest=manifest,
    )


def run_weight_backtest(
    weights: pd.DataFrame,
    returns: str | Path | pd.DataFrame,
    *,
    assumptions: ExecutionAssumptions = ExecutionAssumptions(),
    schema: TargetWeightSchema = TargetWeightSchema(),
    **kwargs: Any,
) -> SecurityNavResult | WeightExecutionResult:
    """Keep fast NAV as default while exposing the optional execution layer."""

    if assumptions.mode == "fast_nav":
        return calculate_security_nav(weights, returns, schema=schema, **kwargs)
    return simulate_weight_execution(
        weights,
        returns,
        assumptions=assumptions,
        schema=schema,
        **kwargs,
    )


__all__ = [
    "EXECUTION_ENGINE_ID",
    "EXECUTION_ENGINE_VERSION",
    "ExecutionAssumptions",
    "WeightExecutionResult",
    "WeightFill",
    "WeightOrder",
    "run_weight_backtest",
    "simulate_weight_execution",
]

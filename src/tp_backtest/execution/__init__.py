"""Optional order/fill simulation for target-weight backtests."""

from .simulator import (
    EXECUTION_ENGINE_ID,
    EXECUTION_ENGINE_VERSION,
    ExecutionAssumptions,
    WeightExecutionResult,
    WeightFill,
    WeightOrder,
    run_weight_backtest,
    simulate_weight_execution,
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

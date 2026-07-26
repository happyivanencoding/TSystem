"""Objective construction for the canonical portfolio optimizer."""

from __future__ import annotations

from .contracts import OptimizerConfig, OptimizerObjective


def build_objective_expression(
    *,
    objective: OptimizerObjective,
    tracking_error_variance,
    portfolio_variance,
    score_expression,
    turnover_expression,
    active_weight_l2,
    config: OptimizerConfig,
):
    if objective == OptimizerObjective.MIN_TRACKING_ERROR:
        expression = config.tracking_error_weight * tracking_error_variance
    elif objective == OptimizerObjective.MAX_SCORE:
        expression = -config.score_weight * score_expression
    elif objective == OptimizerObjective.MIN_TURNOVER:
        expression = config.turnover_weight * turnover_expression
        if config.turnover_weight == 0:
            expression = turnover_expression
    elif objective == OptimizerObjective.MIN_VARIANCE:
        expression = config.tracking_error_weight * portfolio_variance
    else:
        expression = (
            config.tracking_error_weight * tracking_error_variance
            - config.score_weight * score_expression
        )

    if objective != OptimizerObjective.MIN_TURNOVER and config.turnover_weight:
        expression += config.turnover_weight * turnover_expression
    if config.active_weight_penalty:
        expression += config.active_weight_penalty * active_weight_l2
    return expression


__all__ = ["build_objective_expression"]

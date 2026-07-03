"""当前 Python 组合优化器主线。

现役标准是从 `download_09_optimizer_reference.py` 迁入的
`optimizer_engine.py`。旧 `portfolio_generator.py`、`turnover_optimization.py` 和
`sec_list_generation.py` 已移动到 `_quarantine_20260701/legacy_optimizer/`，
仅作可回滚历史参考。
"""

from __future__ import annotations

from collections.abc import Iterable

try:
    from .optimizer_engine import (
        adjust_constraint,
        adjust_lb_ub_rebal,
        apply_ub_thresholds,
        check_data_integrity,
        compute_sigma_ACP,
        define_bool_rebal,
        define_lb_ub,
        define_secto_target_and_geo_target,
        define_secto_target_and_geo_target2,
        drift_weight,
        drop_duplicates_keep_less_missing,
        generate_covariance_matrix,
        generate_exposure_reports,
        generate_heuristique,
        generate_screen_for_optim,
        log_constraints,
        merge_ticker_secondaire,
        merge_weight_by_pairs,
        optimize,
        read_liste_noire,
        to_standard_weight_table,
        verifier_contraintes,
    )
except ImportError:
    from optimizer_engine import (
        adjust_constraint,
        adjust_lb_ub_rebal,
        apply_ub_thresholds,
        check_data_integrity,
        compute_sigma_ACP,
        define_bool_rebal,
        define_lb_ub,
        define_secto_target_and_geo_target,
        define_secto_target_and_geo_target2,
        drift_weight,
        drop_duplicates_keep_less_missing,
        generate_covariance_matrix,
        generate_exposure_reports,
        generate_heuristique,
        generate_screen_for_optim,
        log_constraints,
        merge_ticker_secondaire,
        merge_weight_by_pairs,
        optimize,
        read_liste_noire,
        to_standard_weight_table,
        verifier_contraintes,
    )


def turnover(x: Iterable[float], old_weight: Iterable[float]) -> float:
    """计算组合双边权重差异总和，沿用 download 优化器的换手率定义。"""

    return float(sum(abs(float(new) - float(old)) for new, old in zip(x, old_weight)))


__all__ = [
    "adjust_constraint",
    "adjust_lb_ub_rebal",
    "apply_ub_thresholds",
    "check_data_integrity",
    "compute_sigma_ACP",
    "define_bool_rebal",
    "define_lb_ub",
    "define_secto_target_and_geo_target",
    "define_secto_target_and_geo_target2",
    "drift_weight",
    "drop_duplicates_keep_less_missing",
    "generate_covariance_matrix",
    "generate_exposure_reports",
    "generate_heuristique",
    "generate_screen_for_optim",
    "log_constraints",
    "merge_ticker_secondaire",
    "merge_weight_by_pairs",
    "optimize",
    "read_liste_noire",
    "to_standard_weight_table",
    "verifier_contraintes",
    "turnover",
]

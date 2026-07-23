"""Compatibility layer for the retired ML-local BacktestEngine copy.

The original 03_ml_enhanced/Codes/BacktestEngine.py was a large standalone
copy of portfolio construction and backtest logic.  It has been archived under
99_archive/backtest_engine_versions_20260629 and this module now delegates to
the code-first backtest mainline plus tp_core.general_backtest.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Any


TP_ROOT = Path(__file__).resolve().parents[2]
if str(TP_ROOT) not in sys.path:
    sys.path.insert(0, str(TP_ROOT))

from tp_core.backtesting import (  # noqa: E402
    BacktestEngine,
    BacktestSchema,
    GeneralBacktestEngine,
    GeneralBacktestResult,
    PerformanceMetrics,
    PtfBuilder as _ActivePtfBuilder,
    backtest_weight_table,
    get_backtest_engine_module,
)


_engine_module = get_backtest_engine_module()
PlotlyVisualizer = _engine_module.PlotlyVisualizer
read_liste_noire = _engine_module.read_liste_noire
merge_weight_by_pairs = _engine_module.merge_weight_by_pairs
_active_merge_ticker_secondaire = _engine_module.merge_ticker_secondaire


class PtfBuilder(_ActivePtfBuilder):
    """Legacy-compatible constructor for ML notebooks."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        legacy_controls = {
            "country_sector_optimize": kwargs.pop("country_sector_optimize", False),
            "country_group_top_n": kwargs.pop("country_group_top_n", None),
            "country_col": kwargs.pop("country_col", None),
            "top_mandatory_by_country": kwargs.pop("top_mandatory_by_country", None),
            "optimize_objective": kwargs.pop("optimize_objective", None),
            "optimize_margin": kwargs.pop("optimize_margin", None),
        }

        enabled_removed_controls = [
            name
            for name, value in legacy_controls.items()
            if name in {"country_sector_optimize", "top_mandatory_by_country"} and bool(value)
        ]
        if enabled_removed_controls:
            raise NotImplementedError(
                "旧 ML BacktestEngine 的国家/行业二次优化已从主线回测引擎移除；"
                "请把这类约束放到 06_optimiser 或标准组合优化层。"
                f" 启用的旧参数: {enabled_removed_controls}"
            )

        ignored_controls = {name: value for name, value in legacy_controls.items() if value not in (None, False)}
        if ignored_controls:
            warnings.warn(
                f"Ignoring retired ML-local BacktestEngine parameters: {sorted(ignored_controls)}",
                DeprecationWarning,
                stacklevel=2,
            )

        super().__init__(*args, **kwargs)


def merge_ticker_secondaire(df, bench: str = "MSCI WORLD"):
    """Legacy wrapper accepting the old optional bench argument."""

    if bench in (None, "MSCI WORLD"):
        return _active_merge_ticker_secondaire(df)

    from utils.constants import ISIN_PAIRS  # noqa: WPS433

    if len(ISIN_PAIRS) % 2 != 0:
        raise ValueError("The ISIN pair list length must be even.")
    pairs = list(zip(ISIN_PAIRS[::2], ISIN_PAIRS[1::2]))
    return merge_weight_by_pairs(df=df, pairs=pairs, weight_col=f"Weight in {bench}", drop_second=True)


def add_country_group(*args: Any, **kwargs: Any):
    raise NotImplementedError(
        "add_country_group belonged to the retired ML-local backtest copy. "
        "Move country grouping into the signal or optimizer layer before backtesting."
    )


def optimize_weights(*args: Any, **kwargs: Any):
    raise NotImplementedError(
        "optimize_weights belonged to the retired ML-local backtest copy. "
        "Use 06_optimiser or a dedicated portfolio optimization module."
    )


__all__ = [
    "BacktestEngine",
    "BacktestSchema",
    "GeneralBacktestEngine",
    "GeneralBacktestResult",
    "PtfBuilder",
    "PerformanceMetrics",
    "PlotlyVisualizer",
    "add_country_group",
    "backtest_weight_table",
    "merge_ticker_secondaire",
    "merge_weight_by_pairs",
    "optimize_weights",
    "read_liste_noire",
]

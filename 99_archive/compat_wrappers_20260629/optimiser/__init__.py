"""兼容包：真实组合优化代码位于 `06_optimiser/`。"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

_REAL_PACKAGE = Path(__file__).resolve().parents[1] / "06_optimiser"
__path__ = [str(_REAL_PACKAGE)]


def turnover(x: Iterable[float], old_weight: Iterable[float]) -> float:
    """计算投资组合换手率。"""

    return float(sum(abs(float(new) - float(old)) for new, old in zip(x, old_weight)))


def __getattr__(name: str) -> Any:
    if name == "push_mf_tilt_bloom_new":
        from .portfolio_generator import push_mf_tilt_bloom_new

        return push_mf_tilt_bloom_new
    if name == "optimize_portfolio_turnover":
        from .turnover_optimization import optimize_portfolio_turnover

        return optimize_portfolio_turnover
    raise AttributeError(name)


__all__ = [
    "push_mf_tilt_bloom_new",
    "optimize_portfolio_turnover",
    "turnover",
]

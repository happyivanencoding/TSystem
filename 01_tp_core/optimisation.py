"""共享组合优化约束与换手率工具。

该模块集中维护 `06_optimiser` 原先分散的底层优化算法。业务目录可以继续
保留自己的输入清洗、候选构建和输出命名，但求解器、约束矩阵和换手率语义
统一从这里导入。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import copy

import numpy as np
import pandas as pd
import scipy.optimize


ArrayLike = Iterable[float] | np.ndarray | pd.Series


@dataclass(frozen=True)
class OptimisationResult:
    """通用 SLSQP 优化结果。"""

    weights: np.ndarray
    success: bool
    turnover: float
    message: str
    objective_value: float


def as_float_array(values: ArrayLike, name: str) -> np.ndarray:
    """Convert an iterable to a one-dimensional float array with clear errors."""

    arr = np.asarray(list(values) if not isinstance(values, np.ndarray) else values, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if not np.isfinite(arr).all():
        raise ValueError(f"{name} contains NaN or infinite values")
    return arr


def turnover(x: ArrayLike, old_weight: ArrayLike) -> float:
    """计算组合双边权重差异总和，沿用旧优化器的换手率定义。"""

    new = as_float_array(x, "x")
    old = as_float_array(old_weight, "old_weight")
    if len(new) != len(old):
        raise ValueError("x and old_weight must have the same length")
    return float(np.abs(new - old).sum())


def transform_flag_to_theme(flag: pd.Series, bool_column: bool = False, list_flag="No") -> np.ndarray:
    """将行业/因子标记列转换成约束矩阵。

    这是旧 `portfolio_generator.transform_flag_to_theme` 的共享实现。
    """

    if isinstance(list_flag, str):
        list_flag = np.sort(flag.dropna().unique())

    list_theme = []
    for flag_val in list_flag:
        temp = copy.deepcopy(flag.values)
        if not isinstance(flag_val, str):
            if flag_val == 0:
                if not bool_column:
                    list_theme.append(np.where(temp, 0, 1))
            else:
                temp[temp != flag_val] = 0
                temp[temp == flag_val] = 1
                list_theme.append(temp)
        else:
            index_0 = temp != flag_val
            index_1 = temp == flag_val
            temp[index_0] = 0
            temp[index_1] = 1
            list_theme.append(temp)
    return np.array(list_theme, dtype=float)


def add_dev_secto(
    weight: pd.Series,
    reco: Iterable[float],
    max_secto: ArrayLike,
    min_secto: ArrayLike,
    abs_shift: float = 0.05,
    relatif: float = 0.2,
    normalize: bool = True,
    **legacy_kwargs,
) -> tuple[pd.Series, pd.Series]:
    """根据行业推荐方向生成行业权重上下限。"""

    if "abs" in legacy_kwargs:
        abs_shift = float(legacy_kwargs.pop("abs"))
    if legacy_kwargs:
        raise TypeError(f"unexpected keyword argument(s): {sorted(legacy_kwargs)}")

    weight_copy = copy.deepcopy(weight).astype(float)
    reco_list = list(reco)

    for i, reco_value in enumerate(reco_list):
        if i >= len(weight_copy):
            break
        if reco_value == 1:
            weight_copy.iloc[i] = weight_copy.iloc[i] * (1 + relatif) + abs_shift
        elif reco_value == -1:
            weight_copy.iloc[i] = max(weight_copy.iloc[i] * (1 - relatif) - abs_shift, 0.0025)

    if normalize:
        total = float(weight_copy.sum())
        if total > 0:
            weight_copy = weight_copy / total

    max_arr = as_float_array(max_secto, "max_secto")
    min_arr = as_float_array(min_secto, "min_secto")
    if len(max_arr) != len(weight_copy) or len(min_arr) != len(weight_copy):
        raise ValueError("sector bounds must have the same length as weight")

    weight_min = pd.Series(np.minimum(weight_copy.to_numpy() - 0.02, max_arr), index=weight_copy.index)
    weight_min[weight_min < 0.0025] = 0.0025

    weight_max = pd.Series(np.maximum(weight_copy.to_numpy() + 0.02, min_arr), index=weight_copy.index)
    return weight_min, weight_max


def add_dev_facto(
    weight: pd.Series,
    reco: Iterable[float],
    min_abs: float = 0.5,
    min_relatif: float = 0.15,
) -> tuple[np.ndarray, np.ndarray]:
    """根据因子推荐方向生成因子暴露上下限。"""

    reco_arr = as_float_array(reco, "reco")
    if np.sum(reco_arr) == 0:
        return np.array([0.0] * len(reco_arr), dtype=float), np.array([1.0] * len(reco_arr), dtype=float)

    weight_copy = copy.deepcopy(weight).astype(float)
    weight_min = []
    weight_max = []

    for i, reco_value in enumerate(reco_arr):
        base = float(weight_copy.iloc[i]) if i < len(weight_copy) else 0.0
        if reco_value == 1:
            weight_min.append(min(base + min_relatif, min_abs))
            weight_max.append(1.0)
        else:
            weight_min.append(0.0)
            weight_max.append(base)

    return np.array(weight_min, dtype=float), np.array(weight_max, dtype=float)


def solve_constrained_turnover(
    objective: Callable[..., float],
    x0: ArrayLike,
    exposure_matrix: np.ndarray,
    equality_rhs: ArrayLike,
    inequality_rhs: ArrayLike,
    upper_bounds: ArrayLike,
    lower_bounds: ArrayLike,
    old_weight: ArrayLike,
    max_turnover: float = 0.3,
    *args,
) -> OptimisationResult:
    """Solve a long-only constrained optimisation with turnover cap."""

    x0_arr = as_float_array(x0, "x0")
    old_arr = as_float_array(old_weight, "old_weight")
    upper = as_float_array(upper_bounds, "upper_bounds")
    lower = as_float_array(lower_bounds, "lower_bounds")
    eq_rhs = as_float_array(equality_rhs, "equality_rhs")
    ineq_rhs = as_float_array(inequality_rhs, "inequality_rhs")
    matrix = np.asarray(exposure_matrix, dtype=float)

    if matrix.ndim != 2:
        raise ValueError("exposure_matrix must be two-dimensional")
    if matrix.shape[1] != len(x0_arr):
        raise ValueError("exposure_matrix column count must match x0 length")
    if matrix.shape[0] != len(ineq_rhs):
        raise ValueError("exposure_matrix row count must match inequality_rhs length")
    if not (len(x0_arr) == len(old_arr) == len(upper) == len(lower)):
        raise ValueError("x0, old_weight and bounds must have the same length")

    bounds = scipy.optimize.Bounds(lower, upper)
    ineq_cons = {"type": "ineq", "fun": lambda x: (matrix @ x) - ineq_rhs}
    turnover_cons = {"type": "ineq", "fun": lambda x: float(max_turnover) - turnover(x, old_arr)}
    eq_cons = {"type": "eq", "fun": lambda x: (np.ones(len(x)).reshape(1, -1) @ x) - eq_rhs}

    res = scipy.optimize.minimize(
        objective,
        x0_arr,
        args=args,
        method="SLSQP",
        options={"maxiter": 50000},
        bounds=bounds,
        constraints=[eq_cons, ineq_cons, turnover_cons],
    )

    solved_turnover = turnover(res.x, old_arr)
    return OptimisationResult(
        weights=np.asarray(res.x, dtype=float),
        success=bool(res.success),
        turnover=float(solved_turnover),
        message=str(res.message),
        objective_value=float(res.fun) if np.isscalar(res.fun) else float(solved_turnover),
    )


def optimizer(
    fun: Callable[..., float],
    x0: ArrayLike,
    A: np.ndarray,
    eqb: ArrayLike,
    ineqb: ArrayLike,
    ub: ArrayLike,
    lb: ArrayLike,
    old_weight: ArrayLike,
    ineq_turnover: float = 0.3,
    *args,
) -> tuple[np.ndarray, bool, float]:
    """兼容旧优化器签名，返回 `(weights, success, turnover)`。"""

    result = solve_constrained_turnover(
        fun,
        x0,
        A,
        eqb,
        ineqb,
        ub,
        lb,
        old_weight,
        ineq_turnover,
        *args,
    )
    return result.weights, result.success, result.turnover


__all__ = [
    "OptimisationResult",
    "add_dev_facto",
    "add_dev_secto",
    "as_float_array",
    "optimizer",
    "solve_constrained_turnover",
    "transform_flag_to_theme",
    "turnover",
]

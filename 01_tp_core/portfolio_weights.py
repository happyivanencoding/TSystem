"""Canonical portfolio weight transformations used across TP."""

from __future__ import annotations

from collections.abc import Hashable, Iterable

import numpy as np
import pandas as pd


WEIGHT_TOLERANCE = 1e-12


def normalize_long_only_weights(
    values: pd.Series | Iterable[float],
    *,
    allow_equal_fallback: bool = False,
) -> pd.Series:
    """Return finite, non-negative weights that sum to one."""

    series = values.copy() if isinstance(values, pd.Series) else pd.Series(values, dtype=float)
    series = pd.to_numeric(series, errors="coerce").fillna(0.0).clip(lower=0.0)
    total = float(series.sum())
    if total > WEIGHT_TOLERANCE:
        return series / total
    if allow_equal_fallback and len(series):
        return pd.Series(1.0 / len(series), index=series.index, dtype=float)
    raise ValueError("weights must contain at least one positive finite value")


def cap_and_redistribute_weights(
    values: pd.Series | Iterable[float],
    max_weight: float | None,
    *,
    allow_equal_fallback: bool = False,
) -> pd.Series:
    """Apply a hard cap and redistribute excess proportionally until feasible."""

    weights = normalize_long_only_weights(
        values,
        allow_equal_fallback=allow_equal_fallback,
    )
    if max_weight is None:
        return weights / float(weights.sum())
    cap = float(max_weight)
    if not np.isfinite(cap) or cap <= 0:
        raise ValueError("max_weight must be a positive finite number")
    if cap >= 1.0:
        return weights / float(weights.sum())
    if len(weights) * cap < 1.0 - WEIGHT_TOLERANCE:
        raise ValueError(
            f"max_weight={cap} is infeasible for {len(weights)} securities"
        )

    result = pd.Series(0.0, index=weights.index, dtype=float)
    fixed = pd.Series(False, index=weights.index)
    remaining = 1.0

    while (~fixed).any():
        free = ~fixed
        base = weights.loc[free]
        base_total = float(base.sum())
        if base_total <= WEIGHT_TOLERANCE:
            proposal = pd.Series(remaining / int(free.sum()), index=base.index)
        else:
            proposal = base / base_total * remaining

        over = proposal > cap + WEIGHT_TOLERANCE
        if not over.any():
            result.loc[free] = proposal
            break

        capped_index = proposal.index[over]
        result.loc[capped_index] = cap
        fixed.loc[capped_index] = True
        remaining = 1.0 - float(result.loc[fixed].sum())

    residual = 1.0 - float(result.sum())
    if abs(residual) > WEIGHT_TOLERANCE:
        capacity = (cap - result).clip(lower=0.0)
        available = capacity[capacity > WEIGHT_TOLERANCE]
        if available.empty:
            if abs(residual) > 1e-9:
                raise RuntimeError("unable to distribute capped-weight residual")
        else:
            result.loc[available.index] += residual * available / float(available.sum())

    if float(result.max()) > cap + 1e-10:
        raise RuntimeError("weight cap was violated after redistribution")
    return result / float(result.sum())


def apply_weighting_transform(
    frame: pd.DataFrame,
    method: str,
    value_col: str,
) -> pd.DataFrame:
    """Transform a positive weighting base without normalizing it."""

    result = frame.copy()
    values = pd.to_numeric(result[value_col], errors="coerce")
    if method == "Racine cube":
        result[value_col] = values.clip(lower=0.0) ** (1.0 / 3.0)
    elif method == "Racine carrée":
        result[value_col] = values.clip(lower=0.0) ** 0.5
    elif method == "Market cap":
        result[value_col] = values
    elif method == "Log":
        result[value_col] = np.log(values.where(values > 0))
    elif method in {"Equalweight", "EW"}:
        result[value_col] = 1.0
    else:
        raise ValueError(f"unknown weighting method: {method}")
    return result


def normalize_weight_table(
    frame: pd.DataFrame,
    *,
    weight_col: str,
    group_cols: str | list[str] | tuple[str, ...] | None,
    max_weight: float | None = None,
    allow_equal_fallback: bool = False,
) -> pd.DataFrame:
    """Normalize and optionally cap weights independently in each group."""

    result = frame.copy()
    if group_cols is None:
        result[weight_col] = cap_and_redistribute_weights(
            result[weight_col],
            max_weight,
            allow_equal_fallback=allow_equal_fallback,
        )
        return result

    columns = [group_cols] if isinstance(group_cols, str) else list(group_cols)
    if max_weight is None or float(max_weight) >= 1.0:
        result[weight_col] = (
            pd.to_numeric(result[weight_col], errors="coerce")
            .fillna(0.0)
            .clip(lower=0.0)
        )
        totals = result.groupby(
            columns,
            dropna=False,
            sort=False,
        )[weight_col].transform("sum")
        if (totals <= WEIGHT_TOLERANCE).any():
            if not allow_equal_fallback:
                raise ValueError(
                    "weights must contain at least one positive value per group"
                )
            counts = result.groupby(
                columns,
                dropna=False,
                sort=False,
            )[weight_col].transform("size")
            zero_groups = totals <= WEIGHT_TOLERANCE
            result.loc[zero_groups, weight_col] = 1.0 / counts.loc[zero_groups]
        else:
            result[weight_col] = result.groupby(
                columns,
                dropna=False,
                sort=False,
            )[weight_col].transform(lambda values: values / values.sum())
        second_totals = result.groupby(
            columns,
            dropna=False,
            sort=False,
        )[weight_col].transform("sum")
        result[weight_col] /= second_totals
        return result

    result[weight_col] = (
        result.groupby(columns, dropna=False, sort=False, group_keys=False)[weight_col]
        .apply(
            lambda values: cap_and_redistribute_weights(
                values,
                max_weight,
                allow_equal_fallback=allow_equal_fallback,
            )
        )
        .reindex(result.index)
    )
    return result


def cap_weights_preserving_group_totals(
    frame: pd.DataFrame,
    *,
    weight_col: str,
    max_weight: float,
    group_cols: str | list[str] | tuple[str, ...],
) -> pd.DataFrame:
    """Cap individual weights while preserving every group's total weight."""

    result = frame.copy()
    columns = [group_cols] if isinstance(group_cols, str) else list(group_cols)
    pieces: list[pd.DataFrame] = []
    for _, group in result.groupby(columns, dropna=False, sort=False):
        group = group.copy()
        group_total = float(pd.to_numeric(group[weight_col], errors="coerce").fillna(0.0).sum())
        if group_total <= WEIGHT_TOLERANCE:
            group[weight_col] = 0.0
        else:
            relative_cap = float(max_weight) / group_total
            group[weight_col] = (
                cap_and_redistribute_weights(group[weight_col], relative_cap)
                * group_total
            )
        pieces.append(group)
    return pd.concat(pieces).sort_index() if pieces else result


def match_group_weight_targets(
    frame: pd.DataFrame,
    targets: pd.Series,
    *,
    weight_col: str,
    group_cols: str | list[str] | tuple[str, ...],
    normalization_cols: str | list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Scale within-group weights to explicit target totals."""

    result = frame.copy()
    columns = [group_cols] if isinstance(group_cols, str) else list(group_cols)
    target_series = pd.Series(targets, dtype=float)
    if len(columns) == 1:
        observed_keys: set[Hashable] = set(result[columns[0]].tolist())
    else:
        observed_keys = set(
            tuple(values)
            for values in result[columns].itertuples(index=False, name=None)
        )
    missing_positive_targets = [
        key
        for key, target in target_series.items()
        if target > WEIGHT_TOLERANCE and key not in observed_keys
    ]
    if missing_positive_targets:
        raise ValueError(
            "positive group targets have no eligible securities: "
            + ", ".join(str(key) for key in missing_positive_targets)
        )
    current = result.groupby(columns, dropna=False)[weight_col].transform("sum")

    if len(columns) == 1:
        keys: pd.Index = pd.Index(result[columns[0]])
    else:
        keys = pd.MultiIndex.from_frame(result[columns])
    mapped = target_series.reindex(keys).to_numpy(dtype=float)
    if np.isnan(mapped).any():
        missing_rows = result.loc[np.isnan(mapped), columns].drop_duplicates()
        raise ValueError(
            "missing group weight targets: "
            + missing_rows.astype(str).agg("|".join, axis=1).str.cat(sep=", ")
        )
    if (current <= WEIGHT_TOLERANCE).any():
        raise ValueError("cannot match a positive group target from zero current weight")

    result[weight_col] = (
        pd.to_numeric(result[weight_col], errors="coerce").fillna(0.0)
        * mapped
        / current.to_numpy(dtype=float)
    )
    if normalization_cols is not None:
        result = normalize_weight_table(
            result,
            weight_col=weight_col,
            group_cols=normalization_cols,
        )
    return result


__all__ = [
    "WEIGHT_TOLERANCE",
    "apply_weighting_transform",
    "cap_and_redistribute_weights",
    "cap_weights_preserving_group_totals",
    "match_group_weight_targets",
    "normalize_long_only_weights",
    "normalize_weight_table",
]

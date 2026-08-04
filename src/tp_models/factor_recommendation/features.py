"""月度 PIT 因子特征构建。"""

from __future__ import annotations

from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from .contracts import (
    DATE_COLUMN,
    FEATURE_AS_OF_COLUMN,
    ID_COLUMN,
    SEDOL_COLUMN,
    TARGET_DATE_COLUMN,
    FeatureContract,
    Region,
    UniverseSelection,
    normalize_region,
    validate_temporal_contract,
)
from .factor_definitions import FactorDefinition, compute_factor_scores, load_factor_definitions
from .universe import RegionUniverse, load_region_universes, select_universe


def _screen_with_id(screen: pd.DataFrame) -> pd.DataFrame:
    out = screen.copy()
    if ID_COLUMN not in out.columns and out.index.name == ID_COLUMN:
        out = out.reset_index()
    if DATE_COLUMN not in out.columns:
        raise KeyError(f"screen must contain {DATE_COLUMN}")
    out[DATE_COLUMN] = pd.to_datetime(out[DATE_COLUMN], errors="coerce")
    if out[DATE_COLUMN].isna().any():
        raise ValueError("screen contains invalid Date values")
    return out


def _empty_feature_columns(definitions: Iterable[FactorDefinition]) -> list[str]:
    return [
        DATE_COLUMN,
        FEATURE_AS_OF_COLUMN,
        TARGET_DATE_COLUMN,
        ID_COLUMN,
        SEDOL_COLUMN,
        "universe_component",
        "universe_benchmark",
        "universe_weight",
        *[definition.name for definition in definitions],
    ]


def build_security_feature_panel(
    screen: pd.DataFrame,
    region: str | Region,
    *,
    definitions: Iterable[FactorDefinition] | None = None,
    pit_lag_months: int = 1,
    universe_definitions: Mapping[str, RegionUniverse] | None = None,
    include_unlabeled_latest: bool = False,
) -> pd.DataFrame:
    """将 t-lag 的 canonical screen 特征映射到决策月 t。

    例如默认 ``pit_lag_months=1`` 时，决策月 2020-03 使用
    ``feature_as_of_date=2020-02`` 的 screen，目标窗口从 2020-03 到
    2020-04。不会把同月 screen 字段直接拿来预测同一月目标。
    """

    if pit_lag_months < 1:
        raise ValueError("pit_lag_months must be >= 1")
    definitions = tuple(definitions or load_factor_definitions())
    source = _screen_with_id(screen)
    selection = select_universe(
        source,
        region,
        definitions=universe_definitions,
    )
    scored = compute_factor_scores(selection.frame, definitions)
    dates = sorted(pd.Timestamp(value) for value in scored[DATE_COLUMN].unique())
    rows: list[pd.DataFrame] = []
    last_decision_index = len(dates) if include_unlabeled_latest else len(dates) - 1
    for decision_index in range(pit_lag_months, max(pit_lag_months, last_decision_index)):
        if decision_index >= len(dates):
            continue
        source_date = dates[decision_index - pit_lag_months]
        decision_date = dates[decision_index]
        target_date = dates[decision_index + 1] if decision_index + 1 < len(dates) else pd.NaT
        if pd.isna(target_date) and not include_unlabeled_latest:
            continue
        part = scored.loc[scored[DATE_COLUMN].eq(source_date)].copy()
        if part.empty:
            continue
        part[FEATURE_AS_OF_COLUMN] = source_date
        part[DATE_COLUMN] = decision_date
        part[TARGET_DATE_COLUMN] = target_date
        rows.append(part)
    if not rows:
        return pd.DataFrame(columns=_empty_feature_columns(definitions))
    result = pd.concat(rows, ignore_index=True)
    result[DATE_COLUMN] = pd.to_datetime(result[DATE_COLUMN])
    result[FEATURE_AS_OF_COLUMN] = pd.to_datetime(result[FEATURE_AS_OF_COLUMN])
    result[TARGET_DATE_COLUMN] = pd.to_datetime(result[TARGET_DATE_COLUMN], errors="coerce")
    result = result.sort_values([DATE_COLUMN, ID_COLUMN], kind="stable").reset_index(drop=True)
    if result[TARGET_DATE_COLUMN].notna().all():
        validate_temporal_contract(result)
    return result


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.notna()
    if not valid.any():
        return float("nan")
    weight = pd.to_numeric(weights, errors="coerce").fillna(0.0)
    weight = weight.where(valid, 0.0)
    if float(weight.sum()) <= 0:
        return float(numeric.loc[valid].mean())
    return float(np.average(numeric.loc[valid], weights=weight.loc[valid]))


def build_monthly_features(
    screen: pd.DataFrame,
    region: str | Region,
    *,
    definitions: Iterable[FactorDefinition] | None = None,
    pit_lag_months: int = 1,
    universe_definitions: Mapping[str, RegionUniverse] | None = None,
    include_unlabeled_latest: bool = False,
) -> pd.DataFrame:
    """将证券级 PIT 特征聚合成区域级月度特征。"""

    definitions = tuple(definitions or load_factor_definitions())
    security = build_security_feature_panel(
        screen,
        region,
        definitions=definitions,
        pit_lag_months=pit_lag_months,
        universe_definitions=universe_definitions,
        include_unlabeled_latest=include_unlabeled_latest,
    )
    if security.empty:
        return pd.DataFrame(
            columns=[
                DATE_COLUMN,
                FEATURE_AS_OF_COLUMN,
                TARGET_DATE_COLUMN,
                "region",
                *[definition.name for definition in definitions],
                "n_securities",
                "n_components",
                "research_only",
                "benchmark_approved",
            ]
        )
    region_name = normalize_region(region)
    region_specs = dict(universe_definitions or load_region_universes())
    region_spec = region_specs[region_name]
    rows: list[dict[str, object]] = []
    for decision_date, group in security.groupby(DATE_COLUMN, sort=True):
        row: dict[str, object] = {
            DATE_COLUMN: pd.Timestamp(decision_date),
            FEATURE_AS_OF_COLUMN: pd.Timestamp(group[FEATURE_AS_OF_COLUMN].iloc[0]),
            TARGET_DATE_COLUMN: pd.Timestamp(group[TARGET_DATE_COLUMN].iloc[0])
            if group[TARGET_DATE_COLUMN].notna().any()
            else pd.NaT,
            "region": region_name,
            "n_securities": int(len(group)),
            "n_components": int(group["universe_component"].nunique()),
            "research_only": bool(region_spec.research_only),
            "benchmark_approved": bool(region_spec.benchmark_approved),
            "component_aggregation_weight_sum": float(
                group.drop_duplicates("universe_component")["component_aggregation_weight"].sum()
            ),
        }
        for definition in definitions:
            if len(region_spec.components) == 1:
                row[definition.name] = _weighted_mean(
                    group[definition.name], group["universe_weight"]
                )
                continue
            # ASIA 的组件权重是配置固定的 0.5/0.5；缺失组件时不把剩余组件
            # 自动重标到 100%，因此 coverage/aggregation weight sum 可审计。
            aggregate = 0.0
            has_value = False
            for component_name, component_group in group.groupby(
                "universe_component", sort=False
            ):
                component_value = _weighted_mean(
                    component_group[definition.name], component_group["universe_weight"]
                )
                if pd.notna(component_value):
                    aggregate += float(component_value) * float(
                        region_spec.aggregation_weights[component_name]
                    )
                    has_value = True
            row[definition.name] = aggregate if has_value else np.nan
        rows.append(row)
    result = pd.DataFrame(rows).sort_values(DATE_COLUMN).reset_index(drop=True)
    if result[TARGET_DATE_COLUMN].notna().all():
        validate_temporal_contract(result)
    return result


def latest_month_features(
    screen: pd.DataFrame,
    region: str | Region,
    *,
    definitions: Iterable[FactorDefinition] | None = None,
    pit_lag_months: int = 1,
    universe_definitions: Mapping[str, RegionUniverse] | None = None,
) -> pd.DataFrame:
    """返回可用于当前推荐、但没有伪造未来目标的最新 PIT 特征。"""

    return build_monthly_features(
        screen,
        region,
        definitions=definitions,
        pit_lag_months=pit_lag_months,
        universe_definitions=universe_definitions,
        include_unlabeled_latest=True,
    ).tail(1).reset_index(drop=True)


__all__ = [
    "build_monthly_features",
    "build_security_feature_panel",
    "latest_month_features",
]

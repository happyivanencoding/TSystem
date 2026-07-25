"""Run the preregistered STOXX 600 sparse lag-alternative study.

The study keeps revision and PMOM fixed, treats Oper Margin lag3/6/12 as
mutually exclusive core-quality definitions, and tests eight mutually
exclusive sleeve definitions.  Different lags of the same raw field are never
stacked in one model.

All singles are gated first.  Only candidates whose raw components pass their
official Top/Worst gates are admitted to pair, full-model and leave-one-out
backtests.
"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import run_stoxx600_sparse_core_sleeve_research as official
from backtest_code.research.executor import (
    RelativeLevelSpec,
    build_same_security_relative_variables,
    dedupe_official_results,
    read_official_results,
)


DEFAULT_OUTPUT = (
    official.BACKTEST_ROOT
    / "runs"
    / "ad_hoc"
    / "stoxx600_sparse_lag_extension_20260723"
)
PRIOR_SPARSE_OUTPUT = (
    official.BACKTEST_ROOT
    / "runs"
    / "ad_hoc"
    / "stoxx600_sparse_core_sleeve_20260723"
)
LAG6_OUTPUT = (
    official.BACKTEST_ROOT
    / "runs"
    / "ad_hoc"
    / "stoxx600_relative_lag6_20260723"
)


SIGNALS: tuple[official.SignalSpec, ...] = (
    official.SignalSpec(
        key="revision",
        metric="stoxx600_momentum_eps_revision_ratio_score",
        raw_column="EPS Revision Ratio",
        family="momentum",
        direction=1.0,
        source="local_or_derived",
        economic_role="analyst earnings-estimate diffusion",
        role="core",
    ),
    official.SignalSpec(
        key="pmom",
        metric="stoxx600_momentum_pmom_12m1m_score",
        raw_column="PMOM 12M1M",
        family="momentum",
        direction=1.0,
        source="local_or_derived",
        economic_role="medium-term price-information diffusion",
        role="core",
    ),
    official.SignalSpec(
        key="q3",
        metric="stoxx600_reldelta_quality_oper_margin_lag3_score",
        raw_column="Oper Margin",
        family="quality",
        direction=1.0,
        source="FactSet_or_database",
        economic_role="Oper Margin directional_delta lag3",
        transform="directional_delta",
        lag_observations=3,
        role="core_alternative",
    ),
    official.SignalSpec(
        key="q6",
        metric="stoxx600_reldelta_quality_oper_margin_lag6_score",
        raw_column="Oper Margin",
        family="quality",
        direction=1.0,
        source="FactSet_or_database",
        economic_role="Oper Margin directional_delta lag6",
        transform="directional_delta",
        lag_observations=6,
        role="core_alternative",
    ),
    official.SignalSpec(
        key="q12",
        metric="stoxx600_reldelta_quality_oper_margin_lag12_score",
        raw_column="Oper Margin",
        family="quality",
        direction=1.0,
        source="FactSet_or_database",
        economic_role="Oper Margin directional_delta lag12",
        transform="directional_delta",
        lag_observations=12,
        role="core_alternative",
    ),
    official.SignalSpec(
        key="e1",
        metric="stoxx600_reldelta_value_earns_yield_fy1_lag1_score",
        raw_column="Earns Yield FY1",
        family="value",
        direction=1.0,
        source="FactSet_or_database",
        economic_role="Earns Yield FY1 directional_delta lag1",
        transform="directional_delta",
        lag_observations=1,
        role="sleeve_alternative",
    ),
    official.SignalSpec(
        key="e6",
        metric="stoxx600_reldelta_value_earns_yield_fy1_lag6_score",
        raw_column="Earns Yield FY1",
        family="value",
        direction=1.0,
        source="FactSet_or_database",
        economic_role="Earns Yield FY1 directional_delta lag6",
        transform="directional_delta",
        lag_observations=6,
        role="sleeve_alternative",
    ),
    official.SignalSpec(
        key="e12",
        metric="stoxx600_reldelta_value_earns_yield_fy1_lag12_score",
        raw_column="Earns Yield FY1",
        family="value",
        direction=1.0,
        source="FactSet_or_database",
        economic_role="Earns Yield FY1 directional_delta lag12",
        transform="directional_delta",
        lag_observations=12,
        role="sleeve_alternative",
    ),
    official.SignalSpec(
        key="d3",
        metric="stoxx600_reldelta_quality_netdebt_to_ebitda_exfin_lag3_score",
        raw_column="NetDebt to EBITDA exFIN",
        family="quality",
        direction=-1.0,
        source="FactSet_or_database",
        economic_role="NetDebt to EBITDA exFIN directional_delta lag3",
        transform="directional_delta",
        lag_observations=3,
        role="sleeve_alternative",
    ),
    official.SignalSpec(
        key="d6",
        metric="stoxx600_reldelta_quality_netdebt_to_ebitda_exfin_lag6_score",
        raw_column="NetDebt to EBITDA exFIN",
        family="quality",
        direction=-1.0,
        source="FactSet_or_database",
        economic_role="NetDebt to EBITDA exFIN directional_delta lag6",
        transform="directional_delta",
        lag_observations=6,
        role="sleeve_alternative",
    ),
    official.SignalSpec(
        key="d12",
        metric="stoxx600_reldelta_quality_netdebt_to_ebitda_exfin_lag12_score",
        raw_column="NetDebt to EBITDA exFIN",
        family="quality",
        direction=-1.0,
        source="FactSet_or_database",
        economic_role="NetDebt to EBITDA exFIN directional_delta lag12",
        transform="directional_delta",
        lag_observations=12,
        role="sleeve_alternative",
    ),
    official.SignalSpec(
        key="growth",
        metric="stoxx600_growth_gross_income_growth_fy1_score",
        raw_column="Gross Income Growth FY1",
        family="growth",
        direction=1.0,
        source="FactSet_or_database",
        economic_role="Gross Income Growth FY1",
        role="sleeve",
    ),
    official.SignalSpec(
        key="dividend",
        metric="stoxx600_dividend_dps_1y_growth_ntm_score",
        raw_column="DPS 1Y Growth NTM",
        family="dividend",
        direction=1.0,
        source="FactSet_or_database",
        economic_role="DPS 1Y Growth NTM",
        role="sleeve",
    ),
)

QUALITY_KEYS = ("q3", "q6", "q12")
SLEEVE_KEYS = ("e1", "e6", "e12", "d3", "d6", "d12", "growth", "dividend")
SIGNAL_BY_KEY = {spec.key: spec for spec in SIGNALS}
SIGNAL_BY_VARIANT = {
    (spec.raw_column, spec.transform, spec.lag_observations): spec
    for spec in SIGNALS
    if spec.transform != "level"
}


def signal_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for spec in SIGNALS:
        rows.append(
            {
                "metric": spec.metric,
                "label": (
                    spec.economic_role
                    if spec.transform != "level"
                    else spec.raw_column
                ),
                "candidate_type": "single",
                "bucket": spec.key,
                "components": json.dumps([spec.metric]),
                "component_weights": json.dumps({spec.metric: 1.0}),
                "component_count": 1,
                "parent_metric": "",
                "left_out_component": "",
                "deployable_architecture": False,
                "trial_role": "single_variable_control",
                **asdict(spec),
            }
        )
    return rows


def core_metric(quality_key: str) -> str:
    return f"stoxx600_sx_core_{quality_key}"


def pair_metric(left: str, right: str) -> str:
    ordered = sorted((left, right))
    return f"stoxx600_sx_pair_{ordered[0]}_{ordered[1]}"


def full_metric(quality_key: str, sleeve_key: str) -> str:
    return f"stoxx600_sx_full_{quality_key}_{sleeve_key}"


def loo_metric(
    quality_key: str,
    sleeve_key: str,
    left_out: str,
) -> str:
    return f"stoxx600_sx_loo_{quality_key}_{sleeve_key}_x_{left_out}"


def build_candidate_registry(
    screen: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = signal_rows()
    metric_by_key = {spec.key: spec.metric for spec in SIGNALS}
    seen = set(metric_by_key.values())
    constructed: dict[str, pd.Series] = {}

    def add(
        metric: str,
        label: str,
        candidate_type: str,
        keys: Sequence[str],
        *,
        parent_metric: str = "",
        left_out_component: str = "",
        deployable: bool = False,
        trial_role: str = "evidence",
    ) -> None:
        if metric in seen:
            return
        components = [metric_by_key[key] for key in keys]
        constructed[metric] = official.strict_equal_score(screen, components)
        weight = 1.0 / len(components)
        rows.append(
            {
                "metric": metric,
                "label": label,
                "candidate_type": candidate_type,
                "bucket": "|".join(keys),
                "components": json.dumps(components),
                "component_weights": json.dumps(
                    {component: weight for component in components}
                ),
                "component_count": len(components),
                "parent_metric": parent_metric,
                "left_out_component": left_out_component,
                "deployable_architecture": bool(deployable),
                "trial_role": trial_role,
                "key": "",
                "raw_column": "",
                "family": "",
                "direction": np.nan,
                "source": "constructed_from_gated_signals",
                "economic_role": "fixed strict equal-weight combination",
                "transform": "strict_equal_mean",
                "lag_observations": 0,
                "role": "architecture" if deployable else "diagnostic",
            }
        )
        seen.add(metric)

    add(
        pair_metric("revision", "pmom"),
        "EPS Revision Ratio + PMOM 12M1M",
        "core_pair",
        ["revision", "pmom"],
        trial_role="core_subset_control",
    )
    for quality_key in QUALITY_KEYS:
        add(
            pair_metric("revision", quality_key),
            f"EPS Revision Ratio + {SIGNAL_BY_KEY[quality_key].economic_role}",
            "core_pair",
            ["revision", quality_key],
            trial_role="core_subset_control",
        )
        add(
            pair_metric("pmom", quality_key),
            f"PMOM 12M1M + {SIGNAL_BY_KEY[quality_key].economic_role}",
            "core_pair",
            ["pmom", quality_key],
            trial_role="core_subset_control",
        )
        add(
            core_metric(quality_key),
            (
                "EPS Revision Ratio + PMOM 12M1M + "
                f"{SIGNAL_BY_KEY[quality_key].economic_role}"
            ),
            "core_model",
            ["revision", "pmom", quality_key],
            deployable=True,
            trial_role="quality_lag_architecture",
        )

    for sleeve_key in SLEEVE_KEYS:
        sleeve_label = SIGNAL_BY_KEY[sleeve_key].economic_role
        add(
            pair_metric("revision", sleeve_key),
            f"EPS Revision Ratio + {sleeve_label}",
            "core_sleeve_pair",
            ["revision", sleeve_key],
            trial_role="pair_synergy_evidence",
        )
        add(
            pair_metric("pmom", sleeve_key),
            f"PMOM 12M1M + {sleeve_label}",
            "core_sleeve_pair",
            ["pmom", sleeve_key],
            trial_role="pair_synergy_evidence",
        )
        for quality_key in QUALITY_KEYS:
            quality_label = SIGNAL_BY_KEY[quality_key].economic_role
            add(
                pair_metric(quality_key, sleeve_key),
                f"{quality_label} + {sleeve_label}",
                "core_sleeve_pair",
                [quality_key, sleeve_key],
                trial_role="pair_synergy_evidence",
            )
            parent = full_metric(quality_key, sleeve_key)
            full_keys = ["revision", "pmom", quality_key, sleeve_key]
            add(
                parent,
                (
                    "EPS Revision Ratio + PMOM 12M1M + "
                    f"{quality_label} + {sleeve_label}"
                ),
                "core_plus_fixed_sleeve",
                full_keys,
                deployable=True,
                trial_role="lag_alternative_architecture",
            )
            for left_out in ("revision", "pmom", quality_key):
                kept = [key for key in full_keys if key != left_out]
                add(
                    loo_metric(quality_key, sleeve_key, left_out),
                    (
                        f"{quality_key}/{sleeve_key} model without "
                        f"{left_out}"
                    ),
                    "leave_one_out",
                    kept,
                    parent_metric=parent,
                    left_out_component=left_out,
                    trial_role="full_model_leave_one_out",
                )

    registry = pd.DataFrame(rows)
    expected = 159
    if len(registry) != expected:
        raise ValueError(
            f"expected {expected} preregistered candidates, got {len(registry)}"
        )
    if registry["metric"].duplicated().any():
        raise ValueError("sparse lag registry contains duplicate metric names")
    if constructed:
        screen = pd.concat(
            [screen, pd.DataFrame(constructed, index=screen.index)],
            axis=1,
        )
    return screen, registry


def relative_column_name(
    spec: RelativeLevelSpec,
    transform: str,
    lag: int,
) -> str:
    key = (spec.raw_column, transform, lag)
    if key not in SIGNAL_BY_VARIANT:
        raise ValueError(f"unregistered relative variant: {key}")
    return SIGNAL_BY_VARIANT[key].metric


def build_research_screen(
    screen_path: Path,
    output_dir: Path,
    *,
    force: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    output_path = output_dir / "stoxx600_sparse_core_sleeve_screen.parquet"
    registry_path = output_dir / "candidate_registry.csv"
    definitions_path = output_dir / "relative_variable_definitions.csv"
    if (
        output_path.exists()
        and registry_path.exists()
        and definitions_path.exists()
        and not force
    ):
        return pd.read_parquet(output_path), pd.read_csv(registry_path)

    available = set(pq.ParquetFile(screen_path).schema_arrow.names)
    required = [
        official.DATE_COL,
        official.ISIN_COL,
        official.SEDOL_COL,
        "Name",
        official.SECTOR_COL,
        official.MKT_CAP_COL,
        official.WEIGHT_COL,
        *[spec.raw_column for spec in SIGNALS],
    ]
    required = list(dict.fromkeys(required))
    missing = sorted(set(required).difference(available))
    if missing:
        raise KeyError(f"canonical screen is missing columns: {missing}")

    screen = pd.read_parquet(screen_path, columns=required)
    if official.ISIN_COL not in screen.columns and screen.index.name == official.ISIN_COL:
        screen = screen.reset_index()
    screen[official.DATE_COL] = pd.to_datetime(
        screen[official.DATE_COL],
        errors="coerce",
    )
    screen[official.WEIGHT_COL] = pd.to_numeric(
        screen[official.WEIGHT_COL],
        errors="coerce",
    )
    screen = screen.loc[
        screen[official.WEIGHT_COL].gt(0)
        & screen[official.DATE_COL].ge(official.RESEARCH_START)
    ].copy()
    screen = screen.dropna(
        subset=[
            official.DATE_COL,
            official.ISIN_COL,
            official.SEDOL_COL,
            official.SECTOR_COL,
        ]
    )
    screen = screen.sort_values(
        [official.SEDOL_COL, official.DATE_COL]
    ).reset_index(drop=True)

    for spec in SIGNALS:
        if spec.transform == "level":
            screen[spec.metric] = official.score_level(
                screen,
                spec.raw_column,
                spec.direction,
            )

    definitions: list[pd.DataFrame] = []
    relative_raws = sorted(
        {
            spec.raw_column
            for spec in SIGNALS
            if spec.transform != "level"
        }
    )
    for raw_index, raw_column in enumerate(relative_raws):
        variants = [
            spec
            for spec in SIGNALS
            if spec.raw_column == raw_column and spec.transform != "level"
        ]
        reference = variants[0]
        hidden = f"__relative_level_score_{raw_index:02d}"
        screen[hidden] = official.score_level(
            screen,
            raw_column,
            reference.direction,
        )
        relative_spec = RelativeLevelSpec(
            raw_column=raw_column,
            score_column=hidden,
            family=reference.family,
            direction=reference.direction,
            role=reference.role,
            source=reference.source,
            note=reference.economic_role,
        )
        screen, definition = build_same_security_relative_variables(
            screen,
            [relative_spec],
            lags=sorted({spec.lag_observations for spec in variants}),
            transforms=["directional_delta"],
            date_col=official.DATE_COL,
            security_col=official.SEDOL_COL,
            sector_col=official.SECTOR_COL,
            raw_score=lambda frame, item: frame[item.score_column],
            sector_score=official.sector_rank_score,
            winsorize=official.winsorize_by_date,
            column_name=relative_column_name,
        )
        definitions.append(definition)
        screen = screen.drop(columns=[hidden])

    screen, registry = build_candidate_registry(screen)
    screen = screen.sort_values(
        [official.DATE_COL, official.ISIN_COL]
    ).reset_index(drop=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    screen.to_parquet(output_path, index=False)
    registry.to_csv(registry_path, index=False)
    pd.concat(definitions, ignore_index=True).to_csv(
        definitions_path,
        index=False,
    )
    return screen, registry


def build_synergy_evidence(
    summary: pd.DataFrame,
    gate: pd.DataFrame,
    registry: pd.DataFrame,
) -> pd.DataFrame:
    top = (
        summary.loc[
            summary["side"].eq("Top") & summary["status"].eq("success")
        ]
        .drop_duplicates("metric", keep="last")
        .set_index("metric")
    )
    gate_map = gate.set_index("metric")["pass_gate"].to_dict()
    rows: list[dict[str, object]] = []
    for quality_key in QUALITY_KEYS:
        quality_metric = SIGNAL_BY_KEY[quality_key].metric
        current_core = core_metric(quality_key)
        for sleeve_key in SLEEVE_KEYS:
            sleeve_metric = SIGNAL_BY_KEY[sleeve_key].metric
            current_full = full_metric(quality_key, sleeve_key)
            pairs = [
                pair_metric("revision", sleeve_key),
                pair_metric("pmom", sleeve_key),
                pair_metric(quality_key, sleeve_key),
            ]
            loos = [
                loo_metric(quality_key, sleeve_key, left_out)
                for left_out in ("revision", "pmom", quality_key)
            ]
            required = [
                SIGNAL_BY_KEY["revision"].metric,
                SIGNAL_BY_KEY["pmom"].metric,
                quality_metric,
                sleeve_metric,
                current_core,
                current_full,
                *pairs,
                *loos,
            ]
            complete = all(metric in top.index for metric in required)
            if not complete:
                rows.append(
                    {
                        "quality_key": quality_key,
                        "sleeve_key": sleeve_key,
                        "quality_metric": quality_metric,
                        "sleeve_metric": sleeve_metric,
                        "core_metric": current_core,
                        "full_metric": current_full,
                        "evidence_complete": False,
                        "classification": "incomplete",
                        "reason": "missing or gate-blocked official Top evidence",
                    }
                )
                continue

            core_row = top.loc[current_core]
            sleeve_row = top.loc[sleeve_metric]
            full_row = top.loc[current_full]
            loo_robust = [
                float(top.loc[metric, "robust_score"]) for metric in loos
            ]
            singles_pass = all(
                bool(gate_map.get(metric, False))
                for metric in [
                    SIGNAL_BY_KEY["revision"].metric,
                    SIGNAL_BY_KEY["pmom"].metric,
                    quality_metric,
                    sleeve_metric,
                ]
            )
            pair_pass_count = sum(
                bool(gate_map.get(metric, False)) for metric in pairs
            )
            ratio_beats_core = (
                float(full_row["ratio_cagr"])
                > float(core_row["ratio_cagr"])
            )
            ratio_beats_sleeve = (
                float(full_row["ratio_cagr"])
                > float(sleeve_row["ratio_cagr"])
            )
            robust_beats_core = (
                float(full_row["robust_score"])
                > float(core_row["robust_score"])
            )
            robust_beats_loo = all(
                float(full_row["robust_score"]) > value
                for value in loo_robust
            )
            strict = bool(
                singles_pass
                and bool(gate_map.get(current_core, False))
                and bool(gate_map.get(current_full, False))
                and pair_pass_count >= 2
                and ratio_beats_core
                and ratio_beats_sleeve
                and robust_beats_core
                and robust_beats_loo
            )
            additive = bool(
                singles_pass
                and bool(gate_map.get(current_core, False))
                and bool(gate_map.get(current_full, False))
                and pair_pass_count >= 1
                and (
                    ratio_beats_core
                    or robust_beats_core
                    or robust_beats_loo
                )
            )
            rows.append(
                {
                    "quality_key": quality_key,
                    "sleeve_key": sleeve_key,
                    "quality_metric": quality_metric,
                    "sleeve_metric": sleeve_metric,
                    "core_metric": current_core,
                    "full_metric": current_full,
                    "evidence_complete": True,
                    "all_single_gates_pass": singles_pass,
                    "core_gate_pass": bool(
                        gate_map.get(current_core, False)
                    ),
                    "full_gate_pass": bool(
                        gate_map.get(current_full, False)
                    ),
                    "pair_gate_passes": int(pair_pass_count),
                    "pair_gate_total": len(pairs),
                    "full_ratio_cagr": float(full_row["ratio_cagr"]),
                    "core_ratio_cagr": float(core_row["ratio_cagr"]),
                    "sleeve_ratio_cagr": float(
                        sleeve_row["ratio_cagr"]
                    ),
                    "full_robust_score": float(
                        full_row["robust_score"]
                    ),
                    "core_robust_score": float(
                        core_row["robust_score"]
                    ),
                    "max_loo_robust_score": max(loo_robust),
                    "ratio_beats_core": ratio_beats_core,
                    "ratio_beats_sleeve": ratio_beats_sleeve,
                    "robust_beats_core": robust_beats_core,
                    "robust_beats_all_loo": robust_beats_loo,
                    "classification": (
                        "strict_synergy"
                        if strict
                        else "additive_or_diversifying"
                        if additive
                        else "no_synergy_support"
                    ),
                    "reason": (
                        "Classification requires singles, three cross-pairs, "
                        "the full model and three leave-one-out controls."
                    ),
                }
            )
    return pd.DataFrame(rows)


def write_report(
    *,
    output_dir: Path,
    audit: Mapping[str, object],
    registry: pd.DataFrame,
    gate: pd.DataFrame,
    summary: pd.DataFrame,
    synergy: pd.DataFrame,
    drift_check: pd.DataFrame,
) -> Path:
    del drift_check
    top = summary.loc[
        summary["side"].eq("Top") & summary["status"].eq("success")
    ].copy()
    top = top.merge(
        registry[
            [
                "metric",
                "label",
                "candidate_type",
                "deployable_architecture",
            ]
        ],
        on="metric",
        how="left",
    )
    top = top.merge(
        gate[["metric", "pass_gate", "fail_reasons"]],
        on="metric",
        how="left",
    )
    singles = top.loc[top["candidate_type"].eq("single")].sort_values(
        "robust_score",
        ascending=False,
    )
    architectures = top.loc[
        top["deployable_architecture"].fillna(False)
    ].sort_values("robust_score", ascending=False)
    single_table = singles[
        [
            "label",
            "coverage",
            "ratio_cagr",
            "top_worst_ratio_return",
            "robust_score",
            "pass_gate",
        ]
    ].to_markdown(index=False)
    architecture_table = architectures[
        [
            "label",
            "coverage",
            "ratio_cagr",
            "top_worst_ratio_return",
            "robust_score",
            "pass_gate",
        ]
    ].head(40).to_markdown(index=False)
    synergy_table = synergy[
        [
            "quality_key",
            "sleeve_key",
            "pair_gate_passes",
            "full_ratio_cagr",
            "core_ratio_cagr",
            "full_robust_score",
            "classification",
        ]
    ].to_markdown(index=False)
    report = f"""# STOXX Europe 600 稀疏模型 lag6/lag12 扩展研究

## 预注册范围

本轮锁定 {len(registry)} 个唯一 trial：13 个单变量、7 个 core pair、40 个
core/sleeve pair、3 个互斥 quality-lag core、24 个互斥 core+sleeve 架构和
72 个 parent-specific leave-one-out。`Oper Margin` 的 lag3/6/12 互斥；
`Earns Yield FY1` 与 `NetDebt to EBITDA exFIN` 的各 lag 也互斥，同一 raw
的不同 lag 从未出现在同一组合中。

## 执行口径

- Benchmark：`{official.BENCHMARK}`；区间：{audit['benchmark_start']} 至
  {audit['benchmark_end']}
- raw gate 先于所有组合；任一组件失败，相关组合记录为 blocked/skipped
- Top/Worst 各 20%，Market cap weighting，ICB 19 score/weight neutral
- 缺失值保持 NaN；无有效截面时不调仓，上一期持仓按真实收益漂移
- 引擎：`tp.security_nav 3.0.0`；本轮不调用优化器

## 单变量 Gate

{single_table}

## 架构结果

{architecture_table}

## 协同证据

{synergy_table}

只有 `strict_synergy` 可以解释为协同；`additive_or_diversifying` 仅表示有
增量或分散化证据，不能表述成内部 synergy。`incomplete` 表示某个 raw
gate 失败或证据链未完成。
"""
    path = output_dir / "stoxx600_sparse_lag_extension_report.md"
    path.write_text(report, encoding="utf-8")
    return path


def _install_profile() -> None:
    official.DEFAULT_OUTPUT = DEFAULT_OUTPUT
    official.SIGNALS = SIGNALS
    official.CORE_KEYS = ("revision", "pmom", *QUALITY_KEYS)
    official.SLEEVE_KEYS = SLEEVE_KEYS
    official.SIGNAL_BY_KEY = SIGNAL_BY_KEY
    official.SIGNAL_BY_RAW = {}
    official.build_research_screen = build_research_screen
    official.build_synergy_evidence = build_synergy_evidence
    official.write_report = write_report


def _fingerprints_match(left: Path, right: Path) -> bool:
    left_path = left / "input_fingerprints.json"
    right_path = right / "input_fingerprints.json"
    if not left_path.exists() or not right_path.exists():
        return False
    return json.loads(left_path.read_text(encoding="utf-8")) == json.loads(
        right_path.read_text(encoding="utf-8")
    )


def _manifest_is_compatible(run_dir: Path) -> bool:
    path = run_dir / "manifest.json"
    if not path.exists():
        return False
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return bool(
        manifest.get("status") == "complete"
        and manifest.get("engine_id") == "tp.security_nav"
        and manifest.get("engine_version") == "3.0.0"
        and manifest.get("benchmark") == official.BENCHMARK
    )


def seed_verified_prior_results(output_dir: Path) -> pd.DataFrame:
    """Reuse exact unified-API controls only after score equality checks."""

    target_screen_path = (
        output_dir / "stoxx600_sparse_core_sleeve_screen.parquet"
    )
    if not target_screen_path.exists():
        return pd.DataFrame()
    target_columns = {
        spec.metric
        for spec in SIGNALS
    }
    target = pd.read_parquet(
        target_screen_path,
        columns=[
            official.DATE_COL,
            official.ISIN_COL,
            *sorted(target_columns),
        ],
    ).sort_values([official.DATE_COL, official.ISIN_COL]).reset_index(drop=True)

    sources = [
        (
            PRIOR_SPARSE_OUTPUT,
            {
                SIGNAL_BY_KEY[key].metric
                for key in (
                    "revision",
                    "pmom",
                    "q3",
                    "e1",
                    "d3",
                    "growth",
                    "dividend",
                )
            },
        ),
        (
            LAG6_OUTPUT,
            {
                SIGNAL_BY_KEY[key].metric
                for key in ("q6", "e6", "d6")
            },
        ),
    ]
    seeded_records: list[dict[str, object]] = []
    provenance_rows: list[dict[str, object]] = []
    for source_dir, requested_metrics in sources:
        if not _manifest_is_compatible(source_dir):
            continue
        if not _fingerprints_match(output_dir, source_dir):
            continue
        source_screen_path = (
            source_dir / "stoxx600_sparse_core_sleeve_screen.parquet"
        )
        if not source_screen_path.exists():
            continue
        available = set(pq.ParquetFile(source_screen_path).schema_arrow.names)
        metrics = sorted(requested_metrics.intersection(available))
        if not metrics:
            continue
        source = pd.read_parquet(
            source_screen_path,
            columns=[
                official.DATE_COL,
                official.ISIN_COL,
                *metrics,
            ],
        ).sort_values([official.DATE_COL, official.ISIN_COL]).reset_index(
            drop=True
        )
        if not source[
            [official.DATE_COL, official.ISIN_COL]
        ].equals(target[[official.DATE_COL, official.ISIN_COL]]):
            continue
        exact_metrics: list[str] = []
        for metric in metrics:
            if source[metric].equals(target[metric]):
                exact_metrics.append(metric)
        if not exact_metrics:
            continue
        results = read_official_results(
            [source_dir / "official_run_results.csv"]
        )
        results = results.loc[
            results["metric"].astype(str).isin(exact_metrics)
            & results["status"].eq("success")
        ].copy()
        for record in results.to_dict("records"):
            seeded_records.append(record)
        for metric in exact_metrics:
            sides = set(
                results.loc[
                    results["metric"].astype(str).eq(metric),
                    "side",
                ].astype(str)
            )
            provenance_rows.append(
                {
                    "metric": metric,
                    "source_run": str(source_dir),
                    "score_values_exact": True,
                    "input_fingerprints_exact": True,
                    "engine_compatible": True,
                    "top_seeded": "Top" in sides,
                    "worst_seeded": "Worst" in sides,
                }
            )
    provenance = pd.DataFrame(provenance_rows)
    if seeded_records:
        existing = read_official_results(
            [output_dir / "official_run_results.csv"]
        )
        combined = dedupe_official_results(
            pd.concat(
                [existing, pd.DataFrame(seeded_records)],
                ignore_index=True,
            )
        )
        combined.to_csv(output_dir / "official_run_results.csv", index=False)
    provenance.to_csv(output_dir / "seeded_result_provenance.csv", index=False)
    return provenance


def _rewrite_preregistration(output_dir: Path) -> None:
    path = output_dir / "preregistration.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(
        {
            "study_id": "stoxx600_sparse_lag_extension",
            "research_question": (
                "Which mutually exclusive lag definitions preserve robust "
                "evidence across regimes, and which fixed sparse combinations "
                "have complete pair/subset/leave-one-out support?"
            ),
            "quality_lag_alternatives": list(QUALITY_KEYS),
            "sleeve_alternatives": list(SLEEVE_KEYS),
            "same_raw_lag_policy": (
                "Different lags of the same raw variable are mutually "
                "exclusive and never stacked in one model."
            ),
            "candidate_count": 159,
            "deployable_architecture_count": 27,
        }
    )
    official.json_dump(path, payload)
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(
            {
                "study_id": "stoxx600_sparse_lag_extension",
                "candidate_count": 159,
                "quality_lag_alternatives": list(QUALITY_KEYS),
                "sleeve_alternatives": list(SLEEVE_KEYS),
            }
        )
        official.json_dump(manifest_path, manifest)


def main(argv: Iterable[str] | None = None) -> int:
    _install_profile()
    args = list(argv) if argv is not None else None
    parsed = official.build_parser().parse_args(args)
    output_dir = parsed.output_dir.resolve()
    if not parsed.build_only:
        build_research_screen(
            parsed.screen.resolve(),
            output_dir,
            force=parsed.force_build,
        )
        seed_verified_prior_results(output_dir)
    result = official.main(args)
    _rewrite_preregistration(output_dir)
    return result


if __name__ == "__main__":
    raise SystemExit(main())

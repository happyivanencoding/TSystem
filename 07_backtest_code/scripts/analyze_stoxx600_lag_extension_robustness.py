"""Analyze STOXX 600 lag6 raw trials and sparse lag alternatives."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

import analyze_stoxx600_sparse_core_sleeve_robustness as robust


BACKTEST_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAG6_RUN = (
    BACKTEST_ROOT
    / "runs"
    / "ad_hoc"
    / "stoxx600_relative_lag6_20260723"
)
DEFAULT_SPARSE_RUN = (
    BACKTEST_ROOT
    / "runs"
    / "ad_hoc"
    / "stoxx600_sparse_lag_extension_20260723"
)
DEFAULT_LEVEL_GATE = (
    BACKTEST_ROOT
    / "runs"
    / "ad_hoc"
    / "stoxx600_raw_gated_20260708_0100"
    / "raw_validation_gate.csv"
)
DEFAULT_PRIOR_RELATIVE_GATE = (
    BACKTEST_ROOT
    / "runs"
    / "ad_hoc"
    / "stoxx600_relative_variables_20260709"
    / "relative_validation_gate.csv"
)


def json_dump(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def build_level_comparison(
    lag6_gate: pd.DataFrame,
    level_gate: pd.DataFrame,
) -> pd.DataFrame:
    level = level_gate[
        [
            "raw_column",
            "metric",
            "coverage",
            "ratio_cagr",
            "top_worst_ratio_return",
            "robust_score",
            "pass_gate",
            "fail_reasons",
        ]
    ].rename(
        columns={
            "metric": "level_metric",
            "coverage": "level_coverage",
            "ratio_cagr": "level_ratio_cagr",
            "top_worst_ratio_return": "level_top_worst_ratio_return",
            "robust_score": "level_robust_score",
            "pass_gate": "level_pass_gate",
            "fail_reasons": "level_fail_reasons",
        }
    )
    columns = [
        "metric",
        "raw_column",
        "transform",
        "lag_observations",
        "coverage",
        "ratio_cagr",
        "top_worst_ratio_return",
        "robust_score",
        "pass_gate",
        "fail_reasons",
    ]
    comparison = lag6_gate[columns].merge(
        level,
        on="raw_column",
        how="left",
        validate="many_to_one",
    )
    comparison["ratio_cagr_minus_level"] = (
        comparison["ratio_cagr"] - comparison["level_ratio_cagr"]
    )
    comparison["robust_score_minus_level"] = (
        comparison["robust_score"] - comparison["level_robust_score"]
    )
    comparison["lag6_pass_level_fail"] = (
        comparison["pass_gate"].fillna(False)
        & ~comparison["level_pass_gate"].fillna(False)
    )
    return comparison.sort_values(
        ["pass_gate", "robust_score"],
        ascending=[False, False],
    )


def build_lag_comparison(
    lag6_gate: pd.DataFrame,
    prior_gate: pd.DataFrame,
) -> pd.DataFrame:
    prior = prior_gate.loc[
        prior_gate["lag_observations"].isin([1, 3, 12])
    ].copy()
    prior["lag_observations"] = prior["lag_observations"].astype(int)
    value_columns = [
        "ratio_cagr",
        "top_worst_ratio_return",
        "robust_score",
        "pass_gate",
    ]
    wide_parts: list[pd.DataFrame] = []
    for value in value_columns:
        wide = prior.pivot_table(
            index=["raw_column", "transform"],
            columns="lag_observations",
            values=value,
            aggfunc="last",
        )
        wide.columns = [f"{value}_lag{int(column)}" for column in wide.columns]
        wide_parts.append(wide)
    prior_wide = pd.concat(wide_parts, axis=1).reset_index()
    result = lag6_gate[
        [
            "metric",
            "raw_column",
            "transform",
            "coverage",
            "ratio_cagr",
            "top_worst_ratio_return",
            "robust_score",
            "pass_gate",
            "fail_reasons",
        ]
    ].rename(
        columns={
            "coverage": "coverage_lag6",
            "ratio_cagr": "ratio_cagr_lag6",
            "top_worst_ratio_return": "top_worst_ratio_return_lag6",
            "robust_score": "robust_score_lag6",
            "pass_gate": "pass_gate_lag6",
            "fail_reasons": "fail_reasons_lag6",
        }
    ).merge(
        prior_wide,
        on=["raw_column", "transform"],
        how="left",
        validate="one_to_one",
    )
    robust_columns = [
        column
        for column in result.columns
        if column.startswith("robust_score_lag")
    ]
    result["best_robust_lag"] = result[robust_columns].idxmax(
        axis=1,
        skipna=True,
    ).str.replace("robust_score_lag", "", regex=False)
    result["lag6_is_best_robust"] = result["best_robust_lag"].eq("6")
    return result.sort_values(
        ["pass_gate_lag6", "robust_score_lag6"],
        ascending=[False, False],
    )


def analyze_metric_set(
    run_dir: Path,
    metrics: list[str],
    *,
    prefix: str,
    trial_count: int,
) -> dict[str, object]:
    inputs = robust.load_inputs(run_dir)
    nav_map = robust.build_nav_map(inputs["results"])
    regime_metrics = robust.build_regime_metrics(
        metrics,
        nav_map,
        inputs["summary"],
    )
    regime_summary = robust.summarize_regime_robustness(regime_metrics)
    rolling = robust.rolling_robustness(metrics, nav_map)
    breaks = robust.break_2020_tests(metrics, nav_map)
    matrix = robust.active_monthly_matrix(metrics, nav_map)
    dsr = robust.deflated_sharpe(matrix, trial_count=trial_count)
    pbo_summary, pbo_splits = robust.probability_of_backtest_overfitting(
        matrix
    )
    regime_metrics.to_csv(
        run_dir / f"{prefix}_regime_metrics.csv",
        index=False,
    )
    regime_summary.to_csv(
        run_dir / f"{prefix}_regime_summary.csv",
        index=False,
    )
    rolling.to_csv(
        run_dir / f"{prefix}_rolling_robustness.csv",
        index=False,
    )
    breaks.to_csv(run_dir / f"{prefix}_break_2020_tests.csv", index=False)
    matrix.to_csv(run_dir / f"{prefix}_monthly_active_returns.csv")
    dsr.to_csv(run_dir / f"{prefix}_deflated_sharpe.csv", index=False)
    pbo_splits.to_csv(run_dir / f"{prefix}_pbo_splits.csv", index=False)
    return {
        "metric_count": len(metrics),
        "trial_count_for_dsr": trial_count,
        "pbo": pbo_summary,
        "regime_summary": regime_summary,
        "breaks": breaks,
        "dsr": dsr,
    }


def write_report(
    lag6_run: Path,
    lag6_gate: pd.DataFrame,
    level_comparison: pd.DataFrame,
    lag_comparison: pd.DataFrame,
    lag6_analysis: dict[str, object],
    sparse_analysis: dict[str, object],
) -> Path:
    passed = lag6_gate.loc[lag6_gate["pass_gate"]].sort_values(
        "robust_score",
        ascending=False,
    )
    regime = lag6_analysis["regime_summary"].merge(
        lag6_gate[["metric", "raw_column", "transform"]],
        on="metric",
        how="left",
    )
    breaks = lag6_analysis["breaks"].merge(
        lag6_gate[["metric", "raw_column", "transform"]],
        on="metric",
        how="left",
    )
    supported = breaks.loc[breaks["difference_supported_95pct"]]
    table = passed[
        [
            "raw_column",
            "transform",
            "coverage",
            "ratio_cagr",
            "top_worst_ratio_return",
            "robust_score",
        ]
    ].to_markdown(index=False)
    regime_table = regime[
        [
            "raw_column",
            "transform",
            "positive_active_regimes",
            "positive_top_worst_regimes",
            "median_active_cagr",
            "min_active_cagr",
            "worst_regime_label",
        ]
    ].sort_values(
        ["positive_active_regimes", "min_active_cagr"],
        ascending=False,
    ).to_markdown(index=False)
    comparison_table = lag_comparison.loc[
        lag_comparison["pass_gate_lag6"]
    ][
        [
            "raw_column",
            "transform",
            "robust_score_lag1",
            "robust_score_lag3",
            "robust_score_lag6",
            "robust_score_lag12",
            "best_robust_lag",
        ]
    ].to_markdown(index=False)
    level_only = level_comparison.loc[
        level_comparison["lag6_pass_level_fail"]
    ]["raw_column"].drop_duplicates().tolist()
    report = f"""# STOXX Europe 600 lag6 与稀疏 lag 扩展稳健性分析

## lag6 单变量

62 个预注册 lag6 变量中，{len(passed)} 个通过 official Top/Worst gate：

{table}

其中 lag6 通过而静态 level 未通过的 raw variable 为：
{", ".join(level_only) if level_only else "无"}。这类结论应解释为同证券边际改善
有效，而不是静态 family 已被验证。

## 与 lag1/lag3/lag12 比较

{comparison_table}

`best_robust_lag` 是同一 raw、同一 transform 在四个离散 lag 中的描述性最优，
不能据此连续调参。四个 lag 都属于已登记试验，DSR 的 trial penalty 不会因
只展示通过者而缩小。

## Regime

{regime_table}

lag6 通过者中，2020 前后主动月收益均值差由 block bootstrap 95% 区间支持的
数量为 {len(supported)}。这只检验均值变化，不把 2020 设定成唯一制度断点。

## 过拟合诊断

- lag6 gate-passed 单变量集合 PBO：
  {lag6_analysis['pbo']['pbo']:.2%}
- 稀疏研究 gate-passed 单变量集合 PBO：
  {sparse_analysis['pbo']['pbo']:.2%}
- lag6 DSR 使用全部 62 个预注册 trial 作为多重试验惩罚分母。
- 稀疏单变量 DSR 使用全部 13 个预注册 singles 作为惩罚分母。

PBO 是候选排序不稳定诊断，不是未来亏损概率。若同一 lag 只在某一段占优，
应将它视为 rotation 证据或待验证假设，而不是据此建立事后 regime router。
"""
    path = lag6_run / "stoxx600_lag_extension_robustness_report.md"
    path.write_text(report, encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lag6-run", type=Path, default=DEFAULT_LAG6_RUN)
    parser.add_argument("--sparse-run", type=Path, default=DEFAULT_SPARSE_RUN)
    parser.add_argument("--level-gate", type=Path, default=DEFAULT_LEVEL_GATE)
    parser.add_argument(
        "--prior-relative-gate",
        type=Path,
        default=DEFAULT_PRIOR_RELATIVE_GATE,
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    lag6_run = args.lag6_run.resolve()
    sparse_run = args.sparse_run.resolve()
    lag6_gate = pd.read_csv(lag6_run / "official_validation_gate.csv")
    level_gate = pd.read_csv(args.level_gate.resolve())
    prior_gate = pd.read_csv(args.prior_relative_gate.resolve())

    lag6_gate.to_csv(
        lag6_run / "relative_validation_gate.csv",
        index=False,
    )
    level_comparison = build_level_comparison(lag6_gate, level_gate)
    level_comparison.to_csv(
        lag6_run / "relative_vs_level_comparison.csv",
        index=False,
    )
    lag_comparison = build_lag_comparison(lag6_gate, prior_gate)
    lag_comparison.to_csv(
        lag6_run / "lag6_vs_lag1_lag3_lag12.csv",
        index=False,
    )

    lag6_pass_metrics = lag6_gate.loc[
        lag6_gate["pass_gate"],
        "metric",
    ].astype(str).tolist()
    lag6_analysis = analyze_metric_set(
        lag6_run,
        lag6_pass_metrics,
        prefix="lag6_passed_single",
        trial_count=len(lag6_gate),
    )

    sparse_inputs = robust.load_inputs(sparse_run)
    sparse_registry = sparse_inputs["registry"]
    sparse_gate = sparse_inputs["gate"]
    sparse_single_metrics = sparse_registry.loc[
        sparse_registry["candidate_type"].eq("single")
        & sparse_registry["metric"].isin(
            sparse_gate.loc[sparse_gate["pass_gate"], "metric"]
        ),
        "metric",
    ].astype(str).tolist()
    sparse_analysis = analyze_metric_set(
        sparse_run,
        sparse_single_metrics,
        prefix="passed_single",
        trial_count=int(
            sparse_registry["candidate_type"].eq("single").sum()
        ),
    )
    report = write_report(
        lag6_run,
        lag6_gate,
        level_comparison,
        lag_comparison,
        lag6_analysis,
        sparse_analysis,
    )
    manifest = {
        "status": "complete",
        "lag6_run": str(lag6_run),
        "sparse_run": str(sparse_run),
        "lag6_candidate_count": len(lag6_gate),
        "lag6_gate_pass_count": len(lag6_pass_metrics),
        "sparse_single_gate_pass_count": len(sparse_single_metrics),
        "lag6_pbo": lag6_analysis["pbo"],
        "sparse_single_pbo": sparse_analysis["pbo"],
        "report": str(report),
    }
    json_dump(lag6_run / "lag_extension_analysis_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

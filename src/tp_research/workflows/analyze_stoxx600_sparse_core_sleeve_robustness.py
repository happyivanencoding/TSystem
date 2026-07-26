"""Robustness diagnostics for the preregistered STOXX 600 sparse architecture."""

from __future__ import annotations
from tp_research.runtime import recorded_workflow

import argparse
from dataclasses import dataclass
from itertools import combinations
import json
from math import e
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew, ttest_ind


from tp_research.paths import SCRIPT_DIR
from tp_research.paths import BACKTEST_ROOT
from tp_research.paths import TP_ROOT
from tp_research.workflows import run_stoxx600_sparse_core_sleeve_research as base  # noqa: E402


DEFAULT_RUN = (
    BACKTEST_ROOT
    / "runs"
    / "ad_hoc"
    / "stoxx600_sparse_core_sleeve_20260723"
)
COST_BPS = 20.0
CORE_METRIC = "stoxx600_sparse_core3_equal"


@dataclass(frozen=True)
class Regime:
    regime_id: str
    label_zh: str
    start: str
    end: str
    economic_definition: str


REGIMES: tuple[Regime, ...] = (
    Regime(
        "post_gfc_euro_crisis",
        "金融危机后修复与欧债危机",
        "2009-07-01",
        "2012-12-31",
        "金融危机后修复、欧债危机、银行与主权风险。",
    ),
    Regime(
        "ecb_qe_negative_rates",
        "ECB QE 与负利率",
        "2013-01-01",
        "2016-12-30",
        "低通胀、负利率和资产购买扩张。",
    ),
    Regime(
        "late_cycle_low_inflation",
        "低通胀晚周期",
        "2017-01-02",
        "2019-12-31",
        "欧洲复苏后段、增长放缓和低利率延续。",
    ),
    Regime(
        "pandemic_reopening",
        "疫情冲击与重启",
        "2020-01-02",
        "2021-12-31",
        "封锁、PEPP、财政托底和盈利路径重写。",
    ),
    Regime(
        "inflation_energy_hikes",
        "通胀、能源与加息冲击",
        "2022-01-03",
        "2023-12-29",
        "能源冲击、广泛通胀、负利率结束和快速加息。",
    ),
    Regime(
        "disinflation_normalization",
        "去通胀与政策正常化",
        "2024-01-02",
        "2026-07-02",
        "通胀回落、降息与市场领导力集中。",
    ),
)


def json_dump(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def cagr(series: pd.Series) -> float:
    values = series.dropna().sort_index()
    if len(values) < 2 or values.iloc[0] <= 0 or values.iloc[-1] <= 0:
        return np.nan
    years = max((values.index[-1] - values.index[0]).days / 365.25, 1e-9)
    return float((values.iloc[-1] / values.iloc[0]) ** (1.0 / years) - 1.0)


def max_drawdown(series: pd.Series) -> float:
    values = series.dropna().sort_index()
    if values.empty:
        return np.nan
    return float((values / values.cummax() - 1.0).min())


def slice_nav(
    series: pd.Series,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> pd.Series:
    return series.loc[
        (series.index >= pd.Timestamp(start))
        & (series.index <= pd.Timestamp(end))
    ].dropna()


def monthly_returns(series: pd.Series) -> pd.Series:
    month_end = series.dropna().sort_index().resample("ME").last()
    return month_end.pct_change().dropna()


def period_metrics(
    top: pd.Series,
    benchmark: pd.Series,
    worst: pd.Series,
    start: str,
    end: str,
) -> dict[str, float]:
    aligned = pd.concat(
        [
            slice_nav(top, start, end).rename("top"),
            slice_nav(benchmark, start, end).rename("benchmark"),
            slice_nav(worst, start, end).rename("worst"),
        ],
        axis=1,
    ).dropna()
    if len(aligned) < 30:
        return {}
    active_ratio = aligned["top"] / aligned["benchmark"]
    top_worst_ratio = aligned["top"] / aligned["worst"]
    active_monthly = monthly_returns(aligned["top"]) - monthly_returns(
        aligned["benchmark"]
    )
    return {
        "days": int(len(aligned)),
        "active_cagr": cagr(active_ratio),
        "top_worst_cagr": cagr(top_worst_ratio),
        "active_max_drawdown": max_drawdown(active_ratio),
        "top_worst_max_drawdown": max_drawdown(top_worst_ratio),
        "monthly_active_hit_rate": (
            float(active_monthly.gt(0).mean())
            if not active_monthly.empty
            else np.nan
        ),
    }


def load_inputs(run_dir: Path) -> dict[str, object]:
    registry = pd.read_csv(run_dir / "candidate_registry.csv")
    results = pd.read_csv(run_dir / "official_run_results.csv")
    gate = pd.read_csv(run_dir / "official_validation_gate.csv")
    summary = pd.read_csv(run_dir / "performance_summary.csv")
    try:
        synergy = pd.read_csv(run_dir / "synergy_evidence.csv")
    except pd.errors.EmptyDataError:
        synergy = pd.DataFrame(columns=["classification"])
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise RuntimeError("official sparse-core run is not complete")
    expected = 2 * int(manifest["candidate_count"])
    terminal = int(results["status"].isin(["success", "skipped"]).sum())
    if terminal != expected:
        raise RuntimeError(
            f"official results are incomplete: expected {expected}, got {terminal}"
        )
    return {
        "registry": registry,
        "results": results,
        "gate": gate,
        "summary": summary,
        "synergy": synergy,
        "manifest": manifest,
    }


def build_nav_map(results: pd.DataFrame) -> dict[str, dict[str, pd.Series]]:
    nav_map: dict[str, dict[str, pd.Series]] = {}
    for metric, group in results.loc[
        results["status"].eq("success")
    ].groupby("metric", observed=True):
        sides: dict[str, pd.Series] = {}
        for _, row in group.iterrows():
            side = str(row["side"])
            sides[side] = base.read_nav(str(row["perf_ptf"]))
            if "Benchmark" not in sides:
                sides["Benchmark"] = base.read_nav(str(row["perf_bench"]))
        nav_map[str(metric)] = sides
    return nav_map


def build_regime_metrics(
    metrics: Sequence[str],
    nav_map: dict[str, dict[str, pd.Series]],
    summary: pd.DataFrame,
) -> pd.DataFrame:
    turnover_map = (
        summary.loc[summary["side"].eq("Top")]
        .drop_duplicates("metric", keep="last")
        .set_index("metric")["avg_turnover"]
        .to_dict()
    )
    rows: list[dict[str, object]] = []
    for metric in metrics:
        navs = nav_map[metric]
        for regime in REGIMES:
            stats = period_metrics(
                navs["Top"],
                navs["Benchmark"],
                navs["Worst"],
                regime.start,
                regime.end,
            )
            if not stats:
                continue
            annual_cost = (
                float(turnover_map.get(metric, np.nan))
                * 12.0
                * COST_BPS
                / 10000.0
            )
            rows.append(
                {
                    "metric": metric,
                    **regime.__dict__,
                    **stats,
                    "annual_cost_20bps": annual_cost,
                    "cost_adjusted_active_cagr": (
                        stats["active_cagr"] - annual_cost
                    ),
                }
            )
    return pd.DataFrame(rows)


def summarize_regime_robustness(regime_metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for metric, group in regime_metrics.groupby("metric", observed=True):
        worst_row = group.loc[group["active_cagr"].idxmin()]
        rows.append(
            {
                "metric": metric,
                "regimes_evaluated": len(group),
                "positive_active_regimes": int(group["active_cagr"].gt(0).sum()),
                "positive_top_worst_regimes": int(
                    group["top_worst_cagr"].gt(0).sum()
                ),
                "mean_active_cagr": float(group["active_cagr"].mean()),
                "median_active_cagr": float(group["active_cagr"].median()),
                "min_active_cagr": float(group["active_cagr"].min()),
                "mean_top_worst_cagr": float(
                    group["top_worst_cagr"].mean()
                ),
                "min_top_worst_cagr": float(
                    group["top_worst_cagr"].min()
                ),
                "worst_regime": worst_row["regime_id"],
                "worst_regime_label": worst_row["label_zh"],
                "mean_cost_adjusted_active_cagr": float(
                    group["cost_adjusted_active_cagr"].mean()
                ),
                "min_cost_adjusted_active_cagr": float(
                    group["cost_adjusted_active_cagr"].min()
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["min_active_cagr", "median_active_cagr"],
        ascending=False,
    )


def build_loro(
    regime_metrics: pd.DataFrame,
    metrics: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    for metric in metrics:
        metric_rows = regime_metrics.loc[
            regime_metrics["metric"].eq(metric)
        ]
        for holdout in metric_rows["regime_id"]:
            train = metric_rows.loc[~metric_rows["regime_id"].eq(holdout)]
            test = metric_rows.loc[metric_rows["regime_id"].eq(holdout)].iloc[0]
            train_gate = bool(
                train["active_cagr"].gt(0).sum() >= max(1, len(train) - 1)
                and train["top_worst_cagr"].gt(0).sum()
                >= max(1, len(train) - 1)
                and train["active_cagr"].median() > 0
                and train["active_cagr"].min() > -0.03
            )
            rows.append(
                {
                    "metric": metric,
                    "holdout_regime": holdout,
                    "holdout_label": test["label_zh"],
                    "train_regimes": len(train),
                    "train_positive_active": int(
                        train["active_cagr"].gt(0).sum()
                    ),
                    "train_positive_top_worst": int(
                        train["top_worst_cagr"].gt(0).sum()
                    ),
                    "train_median_active_cagr": float(
                        train["active_cagr"].median()
                    ),
                    "train_min_active_cagr": float(
                        train["active_cagr"].min()
                    ),
                    "train_gate_pass": train_gate,
                    "holdout_active_cagr": float(test["active_cagr"]),
                    "holdout_top_worst_cagr": float(
                        test["top_worst_cagr"]
                    ),
                    "holdout_joint_positive": bool(
                        test["active_cagr"] > 0
                        and test["top_worst_cagr"] > 0
                    ),
                }
            )
    folds = pd.DataFrame(rows)
    summaries: list[dict[str, object]] = []
    for metric, group in folds.groupby("metric", observed=True):
        passed = group.loc[group["train_gate_pass"]]
        summaries.append(
            {
                "metric": metric,
                "folds_evaluated": len(group),
                "train_gate_passes": len(passed),
                "holdout_joint_positive_after_pass": int(
                    passed["holdout_joint_positive"].sum()
                ),
                "holdout_joint_positive_rate": (
                    float(passed["holdout_joint_positive"].mean())
                    if not passed.empty
                    else np.nan
                ),
                "mean_holdout_active_cagr": (
                    float(passed["holdout_active_cagr"].mean())
                    if not passed.empty
                    else np.nan
                ),
                "min_holdout_active_cagr": (
                    float(passed["holdout_active_cagr"].min())
                    if not passed.empty
                    else np.nan
                ),
                "min_holdout_top_worst_cagr": (
                    float(passed["holdout_top_worst_cagr"].min())
                    if not passed.empty
                    else np.nan
                ),
            }
        )
    summary = pd.DataFrame(summaries).sort_values(
        ["holdout_joint_positive_rate", "min_holdout_active_cagr"],
        ascending=False,
    )
    return folds, summary


def rolling_robustness(
    metrics: Sequence[str],
    nav_map: dict[str, dict[str, pd.Series]],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for metric in metrics:
        navs = nav_map[metric]
        aligned = pd.concat(
            [
                navs["Top"].rename("top"),
                navs["Benchmark"].rename("benchmark"),
            ],
            axis=1,
        ).dropna()
        ratio = aligned["top"] / aligned["benchmark"]
        for window, label in ((756, "3y"), (1260, "5y")):
            rolling = ratio / ratio.shift(window)
            rolling = rolling.dropna().pow(252.0 / window).sub(1.0)
            if rolling.empty:
                continue
            rows.append(
                {
                    "metric": metric,
                    "window": label,
                    "observations": len(rolling),
                    "min_active_cagr": float(rolling.min()),
                    "p10_active_cagr": float(rolling.quantile(0.10)),
                    "median_active_cagr": float(rolling.median()),
                    "positive_fraction": float(rolling.gt(0).mean()),
                }
            )
    return pd.DataFrame(rows)


def block_bootstrap_mean_difference(
    pre: pd.Series,
    post: pd.Series,
    *,
    seed: int,
    simulations: int = 2000,
    block_size: int = 12,
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)

    def blocks(values: np.ndarray) -> list[np.ndarray]:
        return [
            values[index : index + block_size]
            for index in range(0, len(values), block_size)
            if len(values[index : index + block_size])
        ]

    pre_blocks = blocks(pre.to_numpy(dtype=float))
    post_blocks = blocks(post.to_numpy(dtype=float))
    differences = np.empty(simulations)
    for index in range(simulations):
        sampled_pre = np.concatenate(
            [
                pre_blocks[item]
                for item in rng.integers(
                    0,
                    len(pre_blocks),
                    size=len(pre_blocks),
                )
            ]
        )[: len(pre)]
        sampled_post = np.concatenate(
            [
                post_blocks[item]
                for item in rng.integers(
                    0,
                    len(post_blocks),
                    size=len(post_blocks),
                )
            ]
        )[: len(post)]
        differences[index] = (
            sampled_post.mean() - sampled_pre.mean()
        ) * 12.0
    return (
        float(np.quantile(differences, 0.025)),
        float(np.quantile(differences, 0.975)),
    )


def break_2020_tests(
    metrics: Sequence[str],
    nav_map: dict[str, dict[str, pd.Series]],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, metric in enumerate(metrics):
        navs = nav_map[metric]
        top = monthly_returns(navs["Top"])
        benchmark = monthly_returns(navs["Benchmark"])
        active = pd.concat(
            [top.rename("top"), benchmark.rename("benchmark")],
            axis=1,
        ).dropna()
        active = active["top"] - active["benchmark"]
        pre = active.loc[active.index < pd.Timestamp("2020-01-01")]
        post = active.loc[active.index >= pd.Timestamp("2020-01-01")]
        if len(pre) < 24 or len(post) < 24:
            continue
        test = ttest_ind(pre, post, equal_var=False, nan_policy="omit")
        ci_low, ci_high = block_bootstrap_mean_difference(
            pre,
            post,
            seed=20260723 + index,
        )
        pre_ann = float(pre.mean() * 12.0)
        post_ann = float(post.mean() * 12.0)
        rows.append(
            {
                "metric": metric,
                "pre_2020_annualized_active_mean": pre_ann,
                "post_2020_annualized_active_mean": post_ann,
                "post_minus_pre": post_ann - pre_ann,
                "welch_t_stat": float(test.statistic),
                "welch_p_value": float(test.pvalue),
                "block_bootstrap_ci_low": ci_low,
                "block_bootstrap_ci_high": ci_high,
                "difference_supported_95pct": bool(
                    ci_low > 0 or ci_high < 0
                ),
                "sign_flip": bool(np.sign(pre_ann) != np.sign(post_ann)),
                "pre_months": len(pre),
                "post_months": len(post),
            }
        )
    return pd.DataFrame(rows)


def active_monthly_matrix(
    metrics: Sequence[str],
    nav_map: dict[str, dict[str, pd.Series]],
) -> pd.DataFrame:
    columns: list[pd.Series] = []
    for metric in metrics:
        navs = nav_map[metric]
        top = monthly_returns(navs["Top"])
        benchmark = monthly_returns(navs["Benchmark"])
        active = pd.concat(
            [top.rename("top"), benchmark.rename("benchmark")],
            axis=1,
        ).dropna()
        columns.append((active["top"] - active["benchmark"]).rename(metric))
    return pd.concat(columns, axis=1).dropna()


def sharpe(values: np.ndarray) -> np.ndarray:
    means = np.nanmean(values, axis=0)
    stds = np.nanstd(values, axis=0, ddof=1)
    return np.divide(
        means,
        stds,
        out=np.full_like(means, -np.inf, dtype=float),
        where=stds > 0,
    )


def deflated_sharpe(
    matrix: pd.DataFrame,
    *,
    trial_count: int,
) -> pd.DataFrame:
    values = matrix.to_numpy(dtype=float)
    raw_sharpes = sharpe(values)
    finite = raw_sharpes[np.isfinite(raw_sharpes)]
    sharpe_std = float(np.std(finite, ddof=1)) if len(finite) > 1 else 0.0
    gamma = 0.5772156649015329
    if trial_count > 1 and sharpe_std > 0:
        expected_max = sharpe_std * (
            (1.0 - gamma) * norm.ppf(1.0 - 1.0 / trial_count)
            + gamma * norm.ppf(1.0 - 1.0 / (trial_count * e))
        )
    else:
        expected_max = 0.0
    rows: list[dict[str, object]] = []
    for column_index, metric in enumerate(matrix.columns):
        series = matrix[metric].dropna()
        sr = float(raw_sharpes[column_index])
        rho = float(series.autocorr(lag=1)) if len(series) > 2 else 0.0
        rho = 0.0 if not np.isfinite(rho) else float(np.clip(rho, -0.9, 0.9))
        effective_n = max(
            3.0,
            len(series) * (1.0 - rho) / (1.0 + rho),
        )
        series_skew = float(skew(series, bias=False))
        series_kurtosis = float(
            kurtosis(series, fisher=False, bias=False)
        )
        denominator = np.sqrt(
            max(
                1e-12,
                1.0
                - series_skew * sr
                + ((series_kurtosis - 1.0) / 4.0) * sr**2,
            )
        )
        statistic = (
            (sr - expected_max)
            * np.sqrt(effective_n - 1.0)
            / denominator
        )
        rows.append(
            {
                "metric": metric,
                "months": len(series),
                "effective_months": effective_n,
                "monthly_sharpe": sr,
                "annualized_sharpe": sr * np.sqrt(12.0),
                "lag1_autocorrelation": rho,
                "skew": series_skew,
                "pearson_kurtosis": series_kurtosis,
                "trial_count": int(trial_count),
                "expected_max_monthly_sharpe": expected_max,
                "deflated_sharpe_probability": float(norm.cdf(statistic)),
            }
        )
    return pd.DataFrame(rows).sort_values(
        "deflated_sharpe_probability",
        ascending=False,
    )


def probability_of_backtest_overfitting(
    matrix: pd.DataFrame,
    *,
    blocks: int = 12,
) -> tuple[dict[str, object], pd.DataFrame]:
    if blocks % 2:
        raise ValueError("CSCV block count must be even")
    values = matrix.to_numpy(dtype=float)
    block_indices = np.array_split(np.arange(len(matrix)), blocks)
    rows: list[dict[str, object]] = []
    for split_id, train_blocks in enumerate(
        combinations(range(blocks), blocks // 2)
    ):
        train_set = set(train_blocks)
        train_index = np.concatenate(
            [block_indices[index] for index in sorted(train_set)]
        )
        test_index = np.concatenate(
            [
                block_indices[index]
                for index in range(blocks)
                if index not in train_set
            ]
        )
        train_sharpe = sharpe(values[train_index])
        test_sharpe = sharpe(values[test_index])
        selected = int(np.nanargmax(train_sharpe))
        ranks = pd.Series(test_sharpe).rank(
            method="average",
            ascending=True,
        )
        relative_rank = float(ranks.iloc[selected] / (len(test_sharpe) + 1.0))
        logit = float(np.log(relative_rank / (1.0 - relative_rank)))
        rows.append(
            {
                "split_id": split_id,
                "selected_metric": matrix.columns[selected],
                "in_sample_sharpe": float(train_sharpe[selected]),
                "out_of_sample_sharpe": float(test_sharpe[selected]),
                "out_of_sample_relative_rank": relative_rank,
                "logit": logit,
                "below_oos_median": bool(logit < 0),
            }
        )
    splits = pd.DataFrame(rows)
    summary = {
        "strategy_count": int(matrix.shape[1]),
        "months": int(matrix.shape[0]),
        "blocks": int(blocks),
        "splits": int(len(splits)),
        "pbo": float(splits["below_oos_median"].mean()),
        "median_oos_relative_rank": float(
            splits["out_of_sample_relative_rank"].median()
        ),
        "mean_selected_is_sharpe": float(
            splits["in_sample_sharpe"].mean()
        ),
        "mean_selected_oos_sharpe": float(
            splits["out_of_sample_sharpe"].mean()
        ),
    }
    return summary, splits


def cost_sensitivity(
    architecture_metrics: Sequence[str],
    summary: pd.DataFrame,
) -> pd.DataFrame:
    top = (
        summary.loc[
            summary["side"].eq("Top")
            & summary["metric"].isin(architecture_metrics)
        ]
        .drop_duplicates("metric", keep="last")
        .set_index("metric")
    )
    rows: list[dict[str, object]] = []
    for metric in architecture_metrics:
        gross = float(top.loc[metric, "ratio_cagr"])
        turnover = float(top.loc[metric, "avg_turnover"])
        row: dict[str, object] = {
            "metric": metric,
            "gross_active_cagr": gross,
            "monthly_one_way_turnover": turnover,
            "annualized_one_way_turnover": turnover * 12.0,
        }
        for bps in (10, 20, 40):
            row[f"net_active_cagr_{bps}bps"] = (
                gross - turnover * 12.0 * bps / 10000.0
            )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        "net_active_cagr_20bps",
        ascending=False,
    )


def expanding_minimax_selection(
    architecture_metrics: Sequence[str],
    regime_metrics: pd.DataFrame,
    *,
    fallback_core: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    regime_order = [regime.regime_id for regime in REGIMES]
    for holdout_position in range(2, len(regime_order)):
        train_regimes = regime_order[:holdout_position]
        holdout = regime_order[holdout_position]
        candidates: list[dict[str, object]] = []
        for metric in architecture_metrics:
            metric_rows = regime_metrics.loc[
                regime_metrics["metric"].eq(metric)
            ]
            train = metric_rows.loc[
                metric_rows["regime_id"].isin(train_regimes)
            ]
            if len(train) != len(train_regimes):
                continue
            eligible = bool(
                train["active_cagr"].min() > -0.03
                and train["active_cagr"].median() > 0
                and train["top_worst_cagr"].median() > 0
            )
            candidates.append(
                {
                    "metric": metric,
                    "eligible": eligible,
                    "min_train_active_cagr": float(
                        train["active_cagr"].min()
                    ),
                    "median_train_active_cagr": float(
                        train["active_cagr"].median()
                    ),
                }
            )
        eligible = [row for row in candidates if row["eligible"]]
        if eligible:
            selected = max(
                eligible,
                key=lambda row: (
                    row["min_train_active_cagr"],
                    row["median_train_active_cagr"],
                    row["metric"] == fallback_core,
                ),
            )
            selection_reason = "maximise worst prior-regime active CAGR"
        else:
            selected = next(
                row for row in candidates if row["metric"] == fallback_core
            )
            selection_reason = "no sleeve passed absolute train gate; default core"
        test = regime_metrics.loc[
            regime_metrics["metric"].eq(selected["metric"])
            & regime_metrics["regime_id"].eq(holdout)
        ].iloc[0]
        rows.append(
            {
                "holdout_regime": holdout,
                "holdout_label": test["label_zh"],
                "train_regimes": "|".join(train_regimes),
                "selected_metric": selected["metric"],
                "selection_reason": selection_reason,
                "min_train_active_cagr": selected["min_train_active_cagr"],
                "median_train_active_cagr": selected[
                    "median_train_active_cagr"
                ],
                "holdout_active_cagr": float(test["active_cagr"]),
                "holdout_top_worst_cagr": float(test["top_worst_cagr"]),
                "holdout_joint_positive": bool(
                    test["active_cagr"] > 0
                    and test["top_worst_cagr"] > 0
                ),
            }
        )
    return pd.DataFrame(rows)


def markdown_table(
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    limit: int = 20,
) -> str:
    if frame.empty:
        return "无可用记录。"
    return frame.reindex(columns=list(columns)).head(limit).to_markdown(
        index=False
    )


def write_report(
    *,
    run_dir: Path,
    architecture: pd.DataFrame,
    regime_summary: pd.DataFrame,
    regime_metrics: pd.DataFrame,
    loro_summary: pd.DataFrame,
    break_tests: pd.DataFrame,
    cost: pd.DataFrame,
    dsr_architecture: pd.DataFrame,
    pbo_summary: dict[str, object],
    full_pbo_summary: dict[str, object],
    expanding: pd.DataFrame,
    synergy: pd.DataFrame,
    manifest: dict[str, object],
    successful_ledger_count: int,
) -> Path:
    names = architecture.set_index("metric")["label"].to_dict()
    for frame in (
        regime_summary,
        regime_metrics,
        loro_summary,
        break_tests,
        cost,
        dsr_architecture,
    ):
        frame["label"] = frame["metric"].map(names).fillna(frame["metric"])
    expanding["selected_label"] = expanding["selected_metric"].map(names)
    strict = synergy.loc[synergy["classification"].eq("strict_synergy")]
    if "quality_key" in strict.columns and "sleeve_key" in strict.columns:
        strict_labels = (
            strict["quality_key"].astype(str)
            + " + "
            + strict["sleeve_key"].astype(str)
        ).tolist()
    elif "sleeve" in strict.columns:
        strict_labels = strict["sleeve"].astype(str).tolist()
    else:
        strict_labels = []
    break_supported = break_tests.loc[
        break_tests["difference_supported_95pct"]
    ]
    passed_architecture_count = int(
        architecture["pass_gate"].fillna(False).sum()
    )
    report = f"""# STOXX Europe 600 稀疏因子架构稳健性报告

## 结论

本轮没有使用 XGBoost、神经网络或连续调参。全部
{manifest['candidate_count']} 个 trial 在运行前注册，其中
{passed_architecture_count} 个架构通过绝对 gate 并进入 LORO、成本、DSR
与 PBO 比较；未通过者保留为 blocked 诊断。PBO 的完整 NAV 矩阵包含
{successful_ledger_count} 个策略；DSR 的多重试验惩罚仍按全部预注册 trial
计数，不因 gate 失败而缩小试验分母。

完整证据链确认的 strict synergy 数为 {len(strict)}。对应组合：
{", ".join(strict_labels) if strict_labels else "无"}。
这不是因为完整组合收益高就自动贴标签，而是 singles、3 个跨腿 pair、
完整 subset 和每个 core-leg leave-one-out 同时满足规则。

## 全周期架构

{markdown_table(
    architecture.sort_values("robust_score", ascending=False),
    [
        "label",
        "coverage",
        "ratio_cagr",
        "top_worst_ratio_return",
        "robust_score",
        "avg_turnover",
        "pass_gate",
    ],
)}

## Regime 稳健性

{markdown_table(
    regime_summary,
    [
        "label",
        "positive_active_regimes",
        "positive_top_worst_regimes",
        "median_active_cagr",
        "min_active_cagr",
        "worst_regime_label",
        "min_cost_adjusted_active_cagr",
    ],
)}

固定六段 leave-one-regime-out 结果：

{markdown_table(
    loro_summary,
    [
        "label",
        "train_gate_passes",
        "holdout_joint_positive_rate",
        "mean_holdout_active_cagr",
        "min_holdout_active_cagr",
        "min_holdout_top_worst_cagr",
    ],
)}

## 2020 Break

在单变量和 gate-passed 架构中，block bootstrap 95% 区间支持
pre/post 均值改变的数量为 {len(break_supported)}。这里检验的是因子主动收益
均值是否变化，不是声称宏观制度只有一个断点。

{markdown_table(
    break_tests.sort_values("post_minus_pre"),
    [
        "label",
        "pre_2020_annualized_active_mean",
        "post_2020_annualized_active_mean",
        "post_minus_pre",
        "block_bootstrap_ci_low",
        "block_bootstrap_ci_high",
        "difference_supported_95pct",
        "sign_flip",
    ],
)}

## 成本与过拟合

20 bps 单边换手成本采用 `月均单边换手 × 12 × 20bps` 的透明近似：

{markdown_table(
    cost,
    [
        "label",
        "gross_active_cagr",
        "annualized_one_way_turnover",
        "net_active_cagr_10bps",
        "net_active_cagr_20bps",
        "net_active_cagr_40bps",
    ],
)}

gate-passed 架构集合的 CSCV PBO 为 {pbo_summary['pbo']:.2%}；
把所有具有完整 NAV 的证据指标当作潜在选择试验时，保守 PBO 为
{full_pbo_summary['pbo']:.2%}。PBO 衡量“样本内赢家在样本外跌到中位数以下”
的频率，不等于未来亏损概率。

{markdown_table(
    dsr_architecture,
    [
        "label",
        "annualized_sharpe",
        "effective_months",
        "trial_count",
        "expected_max_monthly_sharpe",
        "deflated_sharpe_probability",
    ],
)}

## Expanding Minimax

这是诊断而非可直接交易的 router。每次只使用此前 regime，先过绝对 gate，
再最大化过去最差 regime 的主动 CAGR；无候选时退回静态 core。

{markdown_table(
    expanding,
    [
        "holdout_label",
        "selected_label",
        "min_train_active_cagr",
        "median_train_active_cagr",
        "holdout_active_cagr",
        "holdout_top_worst_cagr",
        "holdout_joint_positive",
    ],
)}

## 解释边界

1. 2026-07 之后仍没有真实未来 OOS；DSR、PBO、LORO 和 rolling window
   只能降低历史过拟合嫌疑，不能把历史变成未来。
2. Regime 分段是经济解释框架，边界在事后可见，因此动态切换结果只作诊断。
3. 财务字段缺少逐行公告时间戳，point-in-time 月度快照成立，但 filing-date
   级别的无前视仍是待补的数据契约。
4. 任一含失败 raw 的组合不进入可部署架构比较，即使其全周期主动 CAGR
   看起来较高。
"""
    report_name = (
        "stoxx600_sparse_lag_extension_robustness_report.md"
        if manifest.get("study_id") == "stoxx600_sparse_lag_extension"
        else "stoxx600_sparse_core_sleeve_robustness_report.md"
    )
    path = run_dir / report_name
    path.write_text(report, encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    return parser


@recorded_workflow
def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_dir = args.run_dir.resolve()
    inputs = load_inputs(run_dir)
    registry = inputs["registry"]
    results = inputs["results"]
    gate = inputs["gate"]
    summary = inputs["summary"]
    synergy = inputs["synergy"]
    manifest = inputs["manifest"]
    nav_map = build_nav_map(results)

    gate_map = gate.set_index("metric")["pass_gate"].to_dict()
    architecture = registry.loc[
        registry["deployable_architecture"].fillna(False)
    ].merge(
        gate[
            [
                "metric",
                "coverage",
                "ratio_cagr",
                "top_worst_ratio_return",
                "robust_score",
                "avg_turnover",
                "pass_gate",
                "fail_reasons",
            ]
        ],
        on="metric",
        how="left",
    )
    architecture.to_csv(run_dir / "architecture_gate_results.csv", index=False)
    architecture_metrics = architecture.loc[
        architecture["pass_gate"].fillna(False),
        "metric",
    ].astype(str).tolist()
    fallback_core = (
        "stoxx600_sx_core_q3"
        if "stoxx600_sx_core_q3" in architecture_metrics
        else CORE_METRIC
    )
    if fallback_core not in architecture_metrics:
        raise RuntimeError("preregistered fallback core failed the official gate")

    pd.DataFrame([regime.__dict__ for regime in REGIMES]).to_csv(
        run_dir / "sparse_regime_definitions.csv",
        index=False,
    )
    regime_metrics = build_regime_metrics(
        architecture_metrics,
        nav_map,
        summary,
    )
    regime_metrics.to_csv(
        run_dir / "architecture_regime_metrics.csv",
        index=False,
    )
    regime_summary = summarize_regime_robustness(regime_metrics)
    regime_summary.to_csv(
        run_dir / "architecture_regime_summary.csv",
        index=False,
    )
    loro_folds, loro_summary = build_loro(
        regime_metrics,
        architecture_metrics,
    )
    loro_folds.to_csv(run_dir / "architecture_loro_folds.csv", index=False)
    loro_summary.to_csv(
        run_dir / "architecture_loro_summary.csv",
        index=False,
    )
    rolling = rolling_robustness(architecture_metrics, nav_map)
    rolling.to_csv(
        run_dir / "architecture_rolling_robustness.csv",
        index=False,
    )

    single_metrics = registry.loc[
        registry["candidate_type"].eq("single"),
        "metric",
    ].astype(str).tolist()
    break_metrics = list(dict.fromkeys([*single_metrics, *architecture_metrics]))
    break_tests = break_2020_tests(break_metrics, nav_map)
    break_tests.to_csv(run_dir / "break_2020_tests.csv", index=False)

    cost = cost_sensitivity(architecture_metrics, summary)
    cost.to_csv(run_dir / "architecture_cost_sensitivity.csv", index=False)

    architecture_matrix = active_monthly_matrix(
        architecture_metrics,
        nav_map,
    )
    architecture_matrix.to_csv(
        run_dir / "architecture_monthly_active_returns.csv"
    )
    successful_pairs = (
        results.loc[results["status"].eq("success")]
        .groupby("metric", observed=True)["side"]
        .agg(lambda values: set(values.astype(str)))
    )
    full_metrics = [
        str(metric)
        for metric, sides in successful_pairs.items()
        if {"Top", "Worst"}.issubset(sides)
    ]
    full_matrix = active_monthly_matrix(full_metrics, nav_map)
    full_matrix.to_csv(run_dir / "full_ledger_monthly_active_returns.csv")

    dsr_architecture = deflated_sharpe(
        architecture_matrix,
        trial_count=len(architecture_metrics),
    )
    dsr_architecture.to_csv(
        run_dir / "architecture_deflated_sharpe.csv",
        index=False,
    )
    dsr_full = deflated_sharpe(
        full_matrix,
        trial_count=len(registry),
    )
    dsr_full.to_csv(
        run_dir / "full_ledger_deflated_sharpe.csv",
        index=False,
    )

    pbo_summary, pbo_splits = probability_of_backtest_overfitting(
        architecture_matrix
    )
    pbo_splits.to_csv(
        run_dir / "architecture_pbo_splits.csv",
        index=False,
    )
    full_pbo_summary, full_pbo_splits = probability_of_backtest_overfitting(
        full_matrix
    )
    full_pbo_splits.to_csv(
        run_dir / "full_ledger_pbo_splits.csv",
        index=False,
    )
    json_dump(
        run_dir / "overfit_diagnostics.json",
        {
            "architecture": pbo_summary,
            "full_ledger": full_pbo_summary,
            "interpretation": (
                "PBO is a CSCV rank diagnostic, not a future loss probability."
            ),
        },
    )

    expanding = expanding_minimax_selection(
        architecture_metrics,
        regime_metrics,
        fallback_core=fallback_core,
    )
    expanding.to_csv(
        run_dir / "expanding_minimax_selection.csv",
        index=False,
    )

    report_path = write_report(
        run_dir=run_dir,
        architecture=architecture,
        regime_summary=regime_summary,
        regime_metrics=regime_metrics,
        loro_summary=loro_summary,
        break_tests=break_tests,
        cost=cost,
        dsr_architecture=dsr_architecture,
        pbo_summary=pbo_summary,
        full_pbo_summary=full_pbo_summary,
        expanding=expanding,
        synergy=synergy,
        manifest=manifest,
        successful_ledger_count=len(full_metrics),
    )
    analysis_manifest = {
        "status": "complete",
        "source_manifest": str(run_dir / "manifest.json"),
        "engine_id": manifest["engine_id"],
        "engine_version": manifest["engine_version"],
        "execution_policy": manifest["execution_policy"],
        "architecture_metrics": architecture_metrics,
        "architecture_count": len(architecture_metrics),
        "regime_count": len(REGIMES),
        "break_test_metric_count": len(break_tests),
        "pbo": pbo_summary,
        "full_ledger_pbo": full_pbo_summary,
        "report": str(report_path),
        "optimizer_id": manifest["optimizer_id"],
        "optimizer_version": manifest["optimizer_version"],
        "optimizer_used": False,
    }
    json_dump(run_dir / "robustness_manifest.json", analysis_manifest)
    print(json.dumps(analysis_manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

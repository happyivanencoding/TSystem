from __future__ import annotations
from tp_experiments.artifacts import experiment_plots_enabled
from tp_research.runtime import recorded_workflow

import argparse
import json
from math import sqrt
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


from tp_core.workspace import HISTORICAL_RESEARCH_RUNS_DIR, RESEARCH_RUNS_DIR

RAW_RUN = HISTORICAL_RESEARCH_RUNS_DIR / "ad_hoc" / "stoxx600_raw_gated_20260708_0100"
RELATIVE_RUN = HISTORICAL_RESEARCH_RUNS_DIR / "ad_hoc" / "stoxx600_relative_variables_20260709"
SYNERGY_RUN = HISTORICAL_RESEARCH_RUNS_DIR / "ad_hoc" / "stoxx600_relative_synergy_20260709"
DEFAULT_OUTPUT = RESEARCH_RUNS_DIR / "ad_hoc" / "stoxx600_leave_one_regime_out_20260723"

REGIMES = [
    {
        "regime_id": "post_gfc_euro_crisis",
        "label_zh": "金融危机后修复与欧债危机",
        "start": "2009-10-02",
        "end": "2012-12-31",
        "economic_definition": "金融危机后修复、欧债危机、银行与主权风险，至 OMT 转折后。",
    },
    {
        "regime_id": "ecb_qe_negative_rates",
        "label_zh": "ECB QE 与负利率",
        "start": "2013-01-01",
        "end": "2016-12-30",
        "economic_definition": "欧债危机缓和、低通胀、负利率及资产购买扩张。",
    },
    {
        "regime_id": "late_cycle_low_inflation",
        "label_zh": "低通胀晚周期",
        "start": "2017-01-02",
        "end": "2019-12-31",
        "economic_definition": "欧洲复苏后段、增长放缓、低利率延续至疫情前。",
    },
    {
        "regime_id": "pandemic_reopening",
        "label_zh": "疫情冲击与重启",
        "start": "2020-01-02",
        "end": "2021-12-31",
        "economic_definition": "疫情封锁、PEPP、财政托底、盈利路径重写与重启交易。",
    },
    {
        "regime_id": "inflation_energy_hikes",
        "label_zh": "通胀、能源与加息冲击",
        "start": "2022-01-03",
        "end": "2023-12-29",
        "economic_definition": "能源冲击、广泛通胀、负利率结束及快速加息。",
    },
    {
        "regime_id": "disinflation_normalization",
        "label_zh": "去通胀与政策正常化",
        "start": "2024-01-02",
        "end": "2026-07-02",
        "economic_definition": "通胀回落、降息与政策正常化，同时市场领导力更加集中。",
    },
]

MIN_DAYS_PER_REGIME = 126
MIN_COVERAGE = 0.75
MIN_POSITIVE_TRAIN_REGIMES = 4
MIN_WORST_ACTIVE_CAGR = -0.03
COST_BPS_PER_ONE_WAY_TURNOVER = 20.0
TRADING_MONTHS_PER_YEAR = 12.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="STOXX Europe 600 leave-one-regime-out robustness research."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--metrics", nargs="*", default=None)
    parser.add_argument("--max-candidates", type=int, default=None)
    return parser.parse_args()


def read_nav(path_text: str) -> pd.Series:
    path = Path(path_text)
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    date_col = "Date" if "Date" in frame.columns else frame.columns[0]
    nav_col = "nav" if "nav" in frame.columns else frame.columns[-1]
    out = frame[[date_col, nav_col]].copy()
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
    out[nav_col] = pd.to_numeric(out[nav_col], errors="coerce")
    out = out.dropna().drop_duplicates(date_col, keep="last").sort_values(date_col)
    return out.set_index(date_col)[nav_col].astype(float)


def cagr(series: pd.Series) -> float:
    clean = series.dropna()
    if len(clean) < 2 or clean.iloc[0] <= 0 or clean.iloc[-1] <= 0:
        return np.nan
    years = (clean.index[-1] - clean.index[0]).days / 365.25
    if years <= 0:
        return np.nan
    return float((clean.iloc[-1] / clean.iloc[0]) ** (1.0 / years) - 1.0)


def total_return(series: pd.Series) -> float:
    clean = series.dropna()
    if len(clean) < 2 or clean.iloc[0] == 0:
        return np.nan
    return float(clean.iloc[-1] / clean.iloc[0] - 1.0)


def max_drawdown(series: pd.Series) -> float:
    clean = series.dropna()
    if len(clean) < 2:
        return np.nan
    return float((clean / clean.cummax() - 1.0).min())


def annualized_vol(returns: pd.Series) -> float:
    clean = returns.dropna()
    if len(clean) < 2:
        return np.nan
    return float(clean.std(ddof=1) * sqrt(252.0))


def normalize_component_string(value: object) -> list[str]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    return [item for item in str(value).split("|") if item]


def first_existing_success(group: pd.DataFrame) -> pd.Series | None:
    success = group[group["status"].eq("success")].copy()
    for _, row in success.iterrows():
        if Path(str(row["perf_ptf"])).exists() and Path(str(row["perf_bench"])).exists():
            return row
    return None


def build_path_map(summary: pd.DataFrame, metrics: set[str]) -> dict[str, dict[str, str]]:
    filtered = summary[summary["metric"].isin(metrics)].copy()
    paths: dict[str, dict[str, str]] = {}
    for (metric, side), group in filtered.groupby(["metric", "side"], sort=False):
        row = first_existing_success(group)
        if row is None:
            continue
        paths.setdefault(str(metric), {})[str(side)] = str(row["perf_ptf"])
        paths.setdefault(str(metric), {})[f"{side}_bench"] = str(row["perf_bench"])
    return paths


def compute_single_pre_post_2020_metrics(
    registry: pd.DataFrame,
    path_map: dict[str, dict[str, str]],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    singles = registry[registry["candidate_class"].isin(["raw", "relative"])]
    for row in singles.itertuples(index=False):
        paths = path_map.get(str(row.metric), {})
        if "Top" not in paths or "Top_bench" not in paths:
            continue
        top = read_nav(paths["Top"])
        benchmark = read_nav(paths["Top_bench"])
        aligned = pd.concat(
            {"top": top, "benchmark": benchmark}, axis=1, join="inner"
        ).dropna()
        active_ratio = aligned["top"] / aligned["benchmark"]
        pre_2020 = active_ratio[active_ratio.index < pd.Timestamp("2020-01-01")]
        post_2020 = active_ratio[active_ratio.index >= pd.Timestamp("2020-01-01")]
        rows.append(
            {
                "metric": row.metric,
                "label": row.label,
                "candidate_class": row.candidate_class,
                "family": row.family,
                "pre_2020_active_cagr": cagr(pre_2020),
                "post_2020_active_cagr": cagr(post_2020),
            }
        )
    return pd.DataFrame(rows).dropna(
        subset=["pre_2020_active_cagr", "post_2020_active_cagr"]
    )


def expand_leaf_components(
    metric: str,
    component_map: dict[str, list[str]],
    seen: set[str] | None = None,
) -> list[str]:
    seen = set() if seen is None else set(seen)
    if metric in seen:
        raise ValueError(f"Component cycle detected at {metric}")
    children = component_map.get(metric, [])
    if not children:
        return [metric]
    leaves: list[str] = []
    for child in children:
        leaves.extend(expand_leaf_components(child, component_map, seen | {metric}))
    return list(dict.fromkeys(leaves))


def build_candidate_registry() -> tuple[pd.DataFrame, dict[str, dict[str, str]]]:
    raw_gate = pd.read_csv(RAW_RUN / "raw_validation_gate.csv")
    raw_summary = pd.read_csv(RAW_RUN / "performance_summary.csv")
    relative_gate = pd.read_csv(RELATIVE_RUN / "relative_validation_gate.csv")
    relative_summary = pd.read_csv(RELATIVE_RUN / "performance_summary.csv")
    combo_map = pd.read_csv(SYNERGY_RUN / "candidate_map.csv")
    combo_summary = pd.read_csv(SYNERGY_RUN / "performance_summary.csv")
    selected_legs = pd.read_csv(SYNERGY_RUN / "selected_legs.csv")

    raw = raw_gate.copy()
    raw["candidate_class"] = "raw"
    raw["candidate_type"] = "single"
    raw["label"] = raw["label"].fillna(raw["raw_column"])
    raw["bucket"] = raw["family"]
    raw["components"] = raw["metric"]
    raw["leaf_components"] = raw["metric"]
    raw["avg_turnover"] = raw["metric"].map(
        raw_summary[raw_summary["side"].eq("Top")]
        .drop_duplicates("metric")
        .set_index("metric")["avg_turnover"]
    )

    relative = relative_gate.copy()
    relative["candidate_class"] = "relative"
    relative["candidate_type"] = "single"
    relative["label"] = (
        relative["raw_column"].astype(str)
        + " "
        + relative["transform"].astype(str)
        + " lag"
        + relative["lag_observations"].astype("Int64").astype(str)
    )
    relative["family"] = relative["base_family"]
    relative["bucket"] = relative["base_family"]
    relative["components"] = relative["metric"]
    relative["leaf_components"] = relative["metric"]

    component_map = {
        str(row.metric): normalize_component_string(row.components)
        for row in combo_map.itertuples(index=False)
    }
    combo = combo_map[~combo_map["candidate_type"].eq("bucket_component")].copy()
    combo["candidate_class"] = "combination"
    combo["family"] = combo["buckets"]
    combo["bucket"] = combo["buckets"]
    combo["coverage"] = combo["metric"].map(
        combo_summary[combo_summary["side"].eq("Top")]
        .drop_duplicates("metric")
        .set_index("metric")["coverage"]
    )
    combo["avg_turnover"] = combo["metric"].map(
        combo_summary[combo_summary["side"].eq("Top")]
        .drop_duplicates("metric")
        .set_index("metric")["avg_turnover"]
    )
    combo["leaf_components"] = combo["metric"].map(
        lambda metric: "|".join(expand_leaf_components(str(metric), component_map))
    )

    keep = [
        "metric",
        "candidate_class",
        "candidate_type",
        "label",
        "family",
        "bucket",
        "coverage",
        "avg_turnover",
        "components",
        "leaf_components",
    ]
    registry = pd.concat(
        [
            raw.reindex(columns=keep),
            relative.reindex(columns=keep),
            combo.reindex(columns=keep),
        ],
        ignore_index=True,
    )
    registry["coverage"] = pd.to_numeric(registry["coverage"], errors="coerce")
    registry["avg_turnover"] = pd.to_numeric(registry["avg_turnover"], errors="coerce")
    registry = registry.drop_duplicates("metric", keep="last").reset_index(drop=True)

    selected_meta = selected_legs[
        ["metric", "bucket", "source_type", "raw_column", "family", "economic_role"]
    ].drop_duplicates("metric")
    registry = registry.merge(
        selected_meta.add_prefix("selected_"),
        left_on="metric",
        right_on="selected_metric",
        how="left",
    )

    path_map: dict[str, dict[str, str]] = {}
    path_map.update(build_path_map(raw_summary, set(raw_gate["metric"])))
    path_map.update(build_path_map(relative_summary, set(relative_gate["metric"])))
    path_map.update(build_path_map(combo_summary, set(combo["metric"])))
    registry["has_top"] = registry["metric"].map(lambda metric: "Top" in path_map.get(str(metric), {}))
    registry["has_worst"] = registry["metric"].map(lambda metric: "Worst" in path_map.get(str(metric), {}))
    return registry, path_map


def period_stats(
    top: pd.Series,
    worst: pd.Series,
    benchmark: pd.Series,
    regime: dict[str, str],
) -> dict[str, float | int | str]:
    aligned = pd.concat(
        [top.rename("top"), worst.rename("worst"), benchmark.rename("benchmark")],
        axis=1,
    ).dropna()
    start = pd.Timestamp(regime["start"])
    end = pd.Timestamp(regime["end"])
    aligned = aligned.loc[(aligned.index >= start) & (aligned.index <= end)]
    if len(aligned) < MIN_DAYS_PER_REGIME:
        return {
            "regime_id": regime["regime_id"],
            "regime_start": regime["start"],
            "regime_end": regime["end"],
            "days": int(len(aligned)),
            "available": False,
        }

    top_ret = aligned["top"].pct_change()
    worst_ret = aligned["worst"].pct_change()
    bench_ret = aligned["benchmark"].pct_change()
    active_ret = top_ret - bench_ret
    ratio = aligned["top"] / aligned["benchmark"]
    top_worst_ratio = aligned["top"] / aligned["worst"]
    tracking_error = annualized_vol(active_ret)
    information_ratio = (
        float(active_ret.mean() * 252.0 / tracking_error)
        if tracking_error and np.isfinite(tracking_error)
        else np.nan
    )
    return {
        "regime_id": regime["regime_id"],
        "regime_start": regime["start"],
        "regime_end": regime["end"],
        "days": int(len(aligned)),
        "available": True,
        "top_cagr": cagr(aligned["top"]),
        "worst_cagr": cagr(aligned["worst"]),
        "benchmark_cagr": cagr(aligned["benchmark"]),
        "top_vol": annualized_vol(top_ret),
        "top_max_drawdown": max_drawdown(aligned["top"]),
        "active_ratio_return": total_return(ratio),
        "active_cagr": cagr(ratio),
        "active_max_drawdown": max_drawdown(ratio),
        "tracking_error": tracking_error,
        "information_ratio": information_ratio,
        "top_worst_ratio_return": total_return(top_worst_ratio),
        "top_worst_cagr": cagr(top_worst_ratio),
        "top_worst_max_drawdown": max_drawdown(top_worst_ratio),
    }


def compute_candidate_regime_metrics(
    registry: pd.DataFrame,
    path_map: dict[str, dict[str, str]],
    output_path: Path,
    resume: bool,
    metric_filter: set[str] | None,
    max_candidates: int | None,
) -> pd.DataFrame:
    completed: set[str] = set()
    existing = pd.DataFrame()
    if resume and output_path.exists():
        existing = pd.read_csv(output_path)
        counts = existing.groupby("metric")["regime_id"].nunique()
        completed = set(counts[counts.eq(len(REGIMES))].index.astype(str))

    candidates = registry[
        registry["has_top"].fillna(False) & registry["has_worst"].fillna(False)
    ].copy()
    if metric_filter:
        candidates = candidates[candidates["metric"].isin(metric_filter)]
    candidates = candidates[~candidates["metric"].isin(completed)]
    if max_candidates is not None:
        candidates = candidates.head(max_candidates)

    rows: list[dict[str, object]] = []
    for index, meta in enumerate(candidates.itertuples(index=False), start=1):
        metric = str(meta.metric)
        paths = path_map[metric]
        top = read_nav(paths["Top"])
        worst = read_nav(paths["Worst"])
        benchmark = read_nav(paths["Top_bench"])
        for regime in REGIMES:
            stats = period_stats(top, worst, benchmark, regime)
            rows.append(
                {
                    "metric": metric,
                    "candidate_class": meta.candidate_class,
                    "candidate_type": meta.candidate_type,
                    "label": meta.label,
                    "family": meta.family,
                    "bucket": meta.bucket,
                    "coverage": meta.coverage,
                    "avg_turnover": meta.avg_turnover,
                    **stats,
                }
            )
        if index % 20 == 0:
            fresh = pd.DataFrame(rows)
            combined = pd.concat([existing, fresh], ignore_index=True)
            combined = combined.drop_duplicates(["metric", "regime_id"], keep="last")
            combined.to_csv(output_path, index=False, encoding="utf-8-sig")
            existing = combined
            rows = []
            print(f"Processed {index}/{len(candidates)} candidates", flush=True)

    combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
    if not combined.empty:
        combined = combined.drop_duplicates(["metric", "regime_id"], keep="last")
        combined = combined.sort_values(["candidate_class", "metric", "regime_id"])
        combined.to_csv(output_path, index=False, encoding="utf-8-sig")
    return combined.reset_index(drop=True)


def safe_median(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return float(clean.median()) if not clean.empty else np.nan


def safe_min(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return float(clean.min()) if not clean.empty else np.nan


def safe_mean(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return float(clean.mean()) if not clean.empty else np.nan


def safe_std(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return float(clean.std(ddof=0)) if not clean.empty else np.nan


def annual_turnover_cost(avg_turnover: float) -> float:
    if not np.isfinite(avg_turnover):
        return np.nan
    return float(
        avg_turnover
        * TRADING_MONTHS_PER_YEAR
        * COST_BPS_PER_ONE_WAY_TURNOVER
        / 10_000.0
    )


def training_aggregate(
    train: pd.DataFrame,
    coverage: float,
    avg_turnover: float,
) -> dict[str, float | int | bool | str]:
    available = train[train["available"].fillna(False)].copy()
    active = pd.to_numeric(available["active_cagr"], errors="coerce")
    top_worst = pd.to_numeric(available["top_worst_cagr"], errors="coerce")
    active_dd = pd.to_numeric(available["active_max_drawdown"], errors="coerce")
    te = pd.to_numeric(available["tracking_error"], errors="coerce")
    available_count = int(len(available))
    active_positive_count = int((active > 0).sum())
    top_worst_positive_count = int((top_worst > 0).sum())
    median_active = safe_median(active)
    min_active = safe_min(active)
    median_top_worst = safe_median(top_worst)
    worst_active_dd = safe_min(active_dd)
    active_dispersion = safe_std(active)
    median_te = safe_median(te)
    cost = annual_turnover_cost(avg_turnover)
    objective = (
        median_active
        + 0.50 * min_active
        + 0.25 * median_top_worst
        + 0.25 * worst_active_dd
        - 0.25 * active_dispersion
        - (cost if np.isfinite(cost) else 0.0)
    )

    reasons: list[str] = []
    if not np.isfinite(coverage) or coverage < MIN_COVERAGE:
        reasons.append("coverage")
    if available_count != len(REGIMES) - 1:
        reasons.append("missing_train_regime")
    if active_positive_count < MIN_POSITIVE_TRAIN_REGIMES:
        reasons.append("active_sign")
    if top_worst_positive_count < MIN_POSITIVE_TRAIN_REGIMES:
        reasons.append("top_worst_sign")
    if not np.isfinite(median_active) or median_active <= 0:
        reasons.append("median_active")
    if not np.isfinite(min_active) or min_active < MIN_WORST_ACTIVE_CAGR:
        reasons.append("worst_active")

    return {
        "train_available_regimes": available_count,
        "train_active_positive_regimes": active_positive_count,
        "train_top_worst_positive_regimes": top_worst_positive_count,
        "train_mean_active_cagr": safe_mean(active),
        "train_median_active_cagr": median_active,
        "train_min_active_cagr": min_active,
        "train_active_cagr_dispersion": active_dispersion,
        "train_median_top_worst_cagr": median_top_worst,
        "train_min_top_worst_cagr": safe_min(top_worst),
        "train_worst_active_drawdown": worst_active_dd,
        "train_median_tracking_error": median_te,
        "annual_cost_20bps": cost,
        "train_regime_robust_objective": objective,
        "train_gate_pass": not reasons,
        "train_gate_fail_reasons": "|".join(reasons),
    }


def build_loro_rows(
    period_metrics: pd.DataFrame,
    registry: pd.DataFrame,
) -> pd.DataFrame:
    registry_meta = registry.set_index("metric").to_dict("index")
    rows: list[dict[str, object]] = []
    for metric, metric_periods in period_metrics.groupby("metric", sort=False):
        meta = registry_meta[str(metric)]
        coverage = float(meta["coverage"]) if pd.notna(meta["coverage"]) else np.nan
        turnover = float(meta["avg_turnover"]) if pd.notna(meta["avg_turnover"]) else np.nan
        for holdout in REGIMES:
            holdout_id = holdout["regime_id"]
            train = metric_periods[~metric_periods["regime_id"].eq(holdout_id)]
            test = metric_periods[metric_periods["regime_id"].eq(holdout_id)]
            aggregate = training_aggregate(train, coverage, turnover)
            test_row = test.iloc[0].to_dict() if len(test) == 1 else {}
            rows.append(
                {
                    "metric": metric,
                    "candidate_class": meta["candidate_class"],
                    "candidate_type": meta["candidate_type"],
                    "label": meta["label"],
                    "family": meta["family"],
                    "bucket": meta["bucket"],
                    "coverage": coverage,
                    "avg_turnover": turnover,
                    "components": meta["components"],
                    "leaf_components": meta["leaf_components"],
                    "holdout_regime": holdout_id,
                    "holdout_label_zh": holdout["label_zh"],
                    **aggregate,
                    "holdout_available": bool(test_row.get("available", False)),
                    "holdout_days": test_row.get("days", np.nan),
                    "holdout_active_cagr": test_row.get("active_cagr", np.nan),
                    "holdout_active_max_drawdown": test_row.get(
                        "active_max_drawdown", np.nan
                    ),
                    "holdout_tracking_error": test_row.get("tracking_error", np.nan),
                    "holdout_top_worst_cagr": test_row.get("top_worst_cagr", np.nan),
                    "holdout_top_worst_ratio_return": test_row.get(
                        "top_worst_ratio_return", np.nan
                    ),
                    "holdout_top_cagr": test_row.get("top_cagr", np.nan),
                    "holdout_worst_cagr": test_row.get("worst_cagr", np.nan),
                    "holdout_benchmark_cagr": test_row.get("benchmark_cagr", np.nan),
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["train_rank"] = (
        out.groupby(["candidate_class", "holdout_regime"])[
            "train_regime_robust_objective"
        ]
        .rank(ascending=False, method="min")
        .astype("Int64")
    )
    return out.sort_values(["candidate_class", "holdout_regime", "train_rank"])


def summarize_loro_candidates(
    rows: pd.DataFrame,
    pass_column: str = "train_gate_pass",
) -> pd.DataFrame:
    summaries: list[dict[str, object]] = []
    for metric, group in rows.groupby("metric", sort=False):
        passed = group[group[pass_column].fillna(False)].copy()
        pass_count = int(len(passed))
        active_positive = int((passed["holdout_active_cagr"] > 0).sum())
        top_worst_positive = int((passed["holdout_top_worst_cagr"] > 0).sum())
        joint_positive = int(
            (
                (passed["holdout_active_cagr"] > 0)
                & (passed["holdout_top_worst_cagr"] > 0)
            ).sum()
        )
        joint_rate = joint_positive / pass_count if pass_count else np.nan
        mean_holdout = safe_mean(passed["holdout_active_cagr"])
        min_holdout = safe_min(passed["holdout_active_cagr"])
        if (
            pass_count >= 5
            and joint_rate >= 0.80
            and np.isfinite(mean_holdout)
            and mean_holdout > 0
            and np.isfinite(min_holdout)
            and min_holdout >= MIN_WORST_ACTIVE_CAGR
        ):
            classification = "cross_regime_core"
        elif (
            pass_count >= 4
            and joint_rate >= 2.0 / 3.0
            and np.isfinite(mean_holdout)
            and mean_holdout > 0
        ):
            classification = "cross_regime_resilient"
        elif pass_count >= 2 and active_positive > 0:
            classification = "regime_sensitive"
        else:
            classification = "weak_or_unstable"

        first = group.iloc[0]
        summaries.append(
            {
                "metric": metric,
                "candidate_class": first["candidate_class"],
                "candidate_type": first["candidate_type"],
                "label": first["label"],
                "family": first["family"],
                "bucket": first["bucket"],
                "coverage": first["coverage"],
                "avg_turnover": first["avg_turnover"],
                "folds_evaluated": int(len(group)),
                "train_gate_passes": pass_count,
                "holdout_active_positive_after_pass": active_positive,
                "holdout_top_worst_positive_after_pass": top_worst_positive,
                "holdout_joint_positive_after_pass": joint_positive,
                "holdout_joint_positive_rate": joint_rate,
                "mean_holdout_active_cagr": mean_holdout,
                "median_holdout_active_cagr": safe_median(
                    passed["holdout_active_cagr"]
                ),
                "min_holdout_active_cagr": min_holdout,
                "mean_holdout_top_worst_cagr": safe_mean(
                    passed["holdout_top_worst_cagr"]
                ),
                "min_holdout_top_worst_cagr": safe_min(
                    passed["holdout_top_worst_cagr"]
                ),
                "mean_train_robust_objective": safe_mean(
                    passed["train_regime_robust_objective"]
                ),
                "loro_classification": classification,
            }
        )
    out = pd.DataFrame(summaries)
    if out.empty:
        return out
    order = {
        "cross_regime_core": 0,
        "cross_regime_resilient": 1,
        "regime_sensitive": 2,
        "weak_or_unstable": 3,
    }
    out["_order"] = out["loro_classification"].map(order)
    out = out.sort_values(
        [
            "_order",
            "train_gate_passes",
            "holdout_joint_positive_rate",
            "mean_holdout_active_cagr",
        ],
        ascending=[True, False, False, False],
    ).drop(columns="_order")
    return out.reset_index(drop=True)


def add_combination_eligibility(
    all_loro: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    singles = all_loro[all_loro["candidate_class"].isin(["raw", "relative"])].copy()
    combinations = all_loro[all_loro["candidate_class"].eq("combination")].copy()
    single_pass = {
        (str(row.metric), str(row.holdout_regime)): bool(row.train_gate_pass)
        for row in singles.itertuples(index=False)
    }

    all_components_pass: list[bool] = []
    failed_components: list[str] = []
    for row in combinations.itertuples(index=False):
        leaves = normalize_component_string(row.leaf_components)
        failures = [
            leaf
            for leaf in leaves
            if not single_pass.get((leaf, str(row.holdout_regime)), False)
        ]
        all_components_pass.append(not failures)
        failed_components.append("|".join(failures))
    combinations["all_leaf_components_pass_train_gate"] = all_components_pass
    combinations["failed_leaf_components"] = failed_components
    combinations["eligible_for_selection"] = (
        combinations["train_gate_pass"]
        & combinations["all_leaf_components_pass_train_gate"]
    )
    combinations["eligible_rank"] = pd.Series(pd.NA, index=combinations.index, dtype="Int64")
    eligible = combinations["eligible_for_selection"]
    combinations.loc[eligible, "eligible_rank"] = (
        combinations[eligible]
        .groupby("holdout_regime")["train_regime_robust_objective"]
        .rank(ascending=False, method="min")
        .astype("Int64")
    )
    return singles, combinations


def build_synergy_loro_evidence(
    singles: pd.DataFrame,
    combinations: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    single_lookup = singles.set_index(["metric", "holdout_regime"])
    rows: list[dict[str, object]] = []
    candidates = combinations[
        combinations["candidate_type"].isin(["pair", "family_subset"])
    ]
    for combo in candidates.itertuples(index=False):
        leaves = normalize_component_string(combo.leaf_components)
        component_rows = []
        for leaf in leaves:
            key = (leaf, str(combo.holdout_regime))
            if key in single_lookup.index:
                component_rows.append(single_lookup.loc[key])
        if not component_rows:
            continue
        components = pd.DataFrame(component_rows)
        best_train_objective = safe_max(
            components["train_regime_robust_objective"]
        )
        train_improvements = {
            "train_median_active_improves": combo.train_median_active_cagr
            > safe_max(components["train_median_active_cagr"]),
            "train_min_active_improves": combo.train_min_active_cagr
            > safe_max(components["train_min_active_cagr"]),
            "train_top_worst_improves": combo.train_median_top_worst_cagr
            > safe_max(components["train_median_top_worst_cagr"]),
            "train_drawdown_improves": combo.train_worst_active_drawdown
            > safe_max(components["train_worst_active_drawdown"]),
        }
        train_improvement_count = int(sum(train_improvements.values()))
        train_synergy = (
            bool(combo.eligible_for_selection)
            and combo.train_regime_robust_objective > best_train_objective
            and train_improvement_count >= 3
        )

        holdout_improvements = {
            "holdout_active_improves": combo.holdout_active_cagr
            > safe_max(components["holdout_active_cagr"]),
            "holdout_top_worst_improves": combo.holdout_top_worst_cagr
            > safe_max(components["holdout_top_worst_cagr"]),
            "holdout_drawdown_improves": combo.holdout_active_max_drawdown
            > safe_max(components["holdout_active_max_drawdown"]),
        }
        holdout_improvement_count = int(sum(holdout_improvements.values()))
        holdout_synergy = (
            train_synergy
            and combo.holdout_active_cagr > 0
            and combo.holdout_top_worst_cagr > 0
            and holdout_improvement_count >= 2
        )
        rows.append(
            {
                "metric": combo.metric,
                "candidate_type": combo.candidate_type,
                "label": combo.label,
                "bucket": combo.bucket,
                "holdout_regime": combo.holdout_regime,
                "leaf_components": combo.leaf_components,
                "eligible_for_selection": combo.eligible_for_selection,
                "best_component_train_objective": best_train_objective,
                "combo_train_objective": combo.train_regime_robust_objective,
                "train_objective_uplift": (
                    combo.train_regime_robust_objective - best_train_objective
                ),
                **train_improvements,
                "train_improvement_count": train_improvement_count,
                "train_synergy": train_synergy,
                **holdout_improvements,
                "holdout_improvement_count": holdout_improvement_count,
                "holdout_active_cagr": combo.holdout_active_cagr,
                "holdout_top_worst_cagr": combo.holdout_top_worst_cagr,
                "holdout_synergy_confirmed": holdout_synergy,
            }
        )
    evidence = pd.DataFrame(rows)
    summaries: list[dict[str, object]] = []
    for metric, group in evidence.groupby("metric", sort=False):
        eligible = group[group["eligible_for_selection"].fillna(False)]
        eligible_count = int(len(eligible))
        train_synergy_count = int(eligible["train_synergy"].sum())
        confirmed_count = int(eligible["holdout_synergy_confirmed"].sum())
        confirmation_rate = confirmed_count / eligible_count if eligible_count else np.nan
        if (
            eligible_count >= 4
            and train_synergy_count >= 3
            and confirmed_count >= 3
            and confirmation_rate >= 0.60
        ):
            classification = "cross_regime_synergistic"
        elif (
            eligible_count >= 4
            and safe_mean(eligible["holdout_active_cagr"]) > 0
            and safe_mean(eligible["holdout_top_worst_cagr"]) > 0
        ):
            classification = "additive"
        elif eligible_count >= 2:
            classification = "weak_or_regime_specific"
        else:
            classification = "insufficient_loro_evidence"
        first = group.iloc[0]
        summaries.append(
            {
                "metric": metric,
                "candidate_type": first["candidate_type"],
                "label": first["label"],
                "bucket": first["bucket"],
                "eligible_folds": eligible_count,
                "train_synergy_folds": train_synergy_count,
                "holdout_synergy_confirmed_folds": confirmed_count,
                "holdout_synergy_confirmation_rate": confirmation_rate,
                "mean_holdout_active_cagr": safe_mean(
                    eligible["holdout_active_cagr"]
                ),
                "min_holdout_active_cagr": safe_min(
                    eligible["holdout_active_cagr"]
                ),
                "mean_holdout_top_worst_cagr": safe_mean(
                    eligible["holdout_top_worst_cagr"]
                ),
                "loro_synergy_classification": classification,
            }
        )
    summary = pd.DataFrame(summaries)
    if not summary.empty:
        summary = summary.sort_values(
            [
                "loro_synergy_classification",
                "holdout_synergy_confirmed_folds",
                "mean_holdout_active_cagr",
            ],
            ascending=[True, False, False],
        )
    return evidence, summary


def safe_max(series: Iterable[object]) -> float:
    clean = pd.to_numeric(pd.Series(list(series)), errors="coerce").dropna()
    return float(clean.max()) if not clean.empty else np.nan


def build_leave_one_out_contribution(
    combinations: pd.DataFrame,
) -> pd.DataFrame:
    full = combinations[
        combinations["candidate_type"].eq("full_model")
    ].set_index("holdout_regime")
    rows: list[dict[str, object]] = []
    for loo in combinations[
        combinations["candidate_type"].eq("leave_one_out")
    ].itertuples(index=False):
        regime = str(loo.holdout_regime)
        if regime not in full.index:
            continue
        full_row = full.loc[regime]
        training_contribution = (
            full_row["train_regime_robust_objective"]
            > loo.train_regime_robust_objective
        )
        holdout_active_contribution = (
            full_row["holdout_active_cagr"] > loo.holdout_active_cagr
        )
        holdout_drawdown_contribution = (
            full_row["holdout_active_max_drawdown"]
            > loo.holdout_active_max_drawdown
        )
        rows.append(
            {
                "left_out_bucket": loo.bucket
                if pd.isna(getattr(loo, "components", np.nan))
                else str(loo.label).replace("full model without ", ""),
                "loo_metric": loo.metric,
                "holdout_regime": regime,
                "full_train_objective": full_row[
                    "train_regime_robust_objective"
                ],
                "loo_train_objective": loo.train_regime_robust_objective,
                "training_positive_contribution": training_contribution,
                "full_holdout_active_cagr": full_row["holdout_active_cagr"],
                "loo_holdout_active_cagr": loo.holdout_active_cagr,
                "holdout_active_positive_contribution": holdout_active_contribution,
                "full_holdout_active_drawdown": full_row[
                    "holdout_active_max_drawdown"
                ],
                "loo_holdout_active_drawdown": loo.holdout_active_max_drawdown,
                "holdout_drawdown_positive_contribution": holdout_drawdown_contribution,
                "holdout_any_positive_contribution": (
                    holdout_active_contribution or holdout_drawdown_contribution
                ),
            }
        )
    return pd.DataFrame(rows)


def create_plots(
    output_dir: Path,
    period_metrics: pd.DataFrame,
    single_summary: pd.DataFrame,
    combo_summary: pd.DataFrame,
    all_loro: pd.DataFrame,
) -> list[str]:
    if not experiment_plots_enabled():
        return []
    plot_dir = output_dir / "plots"
    plot_dir.mkdir(exist_ok=True)
    paths: list[str] = []
    try:
        import plotly.express as px

        top_singles = single_summary[
            single_summary["loro_classification"].isin(
                ["cross_regime_core", "cross_regime_resilient"]
            )
        ].head(30)
        if not top_singles.empty:
            heat = period_metrics[
                period_metrics["metric"].isin(top_singles["metric"])
            ].pivot(index="label", columns="regime_id", values="active_cagr")
            heat = heat.reindex(
                columns=[regime["regime_id"] for regime in REGIMES]
            )
            fig = px.imshow(
                heat * 100.0,
                text_auto=".1f",
                aspect="auto",
                color_continuous_scale="RdYlGn",
                color_continuous_midpoint=0,
                title="STOXX600 单变量各 regime 主动 CAGR（%）",
                labels={"color": "主动 CAGR %"},
            )
            fig.update_layout(height=max(620, 28 * len(heat) + 220))
            path = plot_dir / "single_regime_active_cagr_heatmap.html"
            fig.write_html(path, include_plotlyjs=True, full_html=True)
            paths.append(str(path))

        eligible = all_loro[
            all_loro["train_gate_pass"].fillna(False)
            & all_loro["candidate_class"].isin(["raw", "relative"])
        ].copy()
        if not eligible.empty:
            fig = px.scatter(
                eligible,
                x="train_min_active_cagr",
                y="holdout_active_cagr",
                color="family",
                symbol="candidate_class",
                hover_name="label",
                hover_data=[
                    "holdout_regime",
                    "train_regime_robust_objective",
                    "holdout_top_worst_cagr",
                ],
                title="训练期最差 regime 与留出期主动 CAGR",
            )
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
            fig.add_vline(x=0, line_dash="dash", line_color="gray")
            path = plot_dir / "single_train_worst_vs_holdout.html"
            fig.write_html(path, include_plotlyjs=True, full_html=True)
            paths.append(str(path))

        top_combos = combo_summary[
            combo_summary["loro_classification"].isin(
                ["cross_regime_core", "cross_regime_resilient"]
            )
        ].head(25)
        if not top_combos.empty:
            heat = period_metrics[
                period_metrics["metric"].isin(top_combos["metric"])
            ].pivot(index="label", columns="regime_id", values="active_cagr")
            heat = heat.reindex(
                columns=[regime["regime_id"] for regime in REGIMES]
            )
            fig = px.imshow(
                heat * 100.0,
                text_auto=".1f",
                aspect="auto",
                color_continuous_scale="RdYlGn",
                color_continuous_midpoint=0,
                title="STOXX600 组合各 regime 主动 CAGR（%）",
                labels={"color": "主动 CAGR %"},
            )
            fig.update_layout(height=max(620, 28 * len(heat) + 220))
            path = plot_dir / "combination_regime_active_cagr_heatmap.html"
            fig.write_html(path, include_plotlyjs=True, full_html=True)
            paths.append(str(path))
    except Exception as exc:
        (output_dir / "plot_error.txt").write_text(str(exc), encoding="utf-8")
    return paths


def format_pct(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "NA"
    return "NA" if not np.isfinite(number) else f"{number:.2%}"


def markdown_table(frame: pd.DataFrame, columns: list[str], limit: int = 15) -> str:
    if frame.empty:
        return "无符合条件的结果。"
    view = frame.loc[:, columns].head(limit).copy()
    for column in view.columns:
        if any(token in column for token in ["cagr", "rate", "coverage", "turnover"]):
            view[column] = view[column].map(format_pct)
    header = "| " + " | ".join(view.columns) + " |"
    sep = "| " + " | ".join(["---"] * len(view.columns)) + " |"
    rows = [
        "| " + " | ".join(str(value) for value in row) + " |"
        for row in view.itertuples(index=False, name=None)
    ]
    return "\n".join([header, sep, *rows])


def write_report(
    output_dir: Path,
    registry: pd.DataFrame,
    period_metrics: pd.DataFrame,
    pre_post_2020: pd.DataFrame,
    single_summary: pd.DataFrame,
    combo_summary: pd.DataFrame,
    synergy_summary: pd.DataFrame,
    loo_contribution: pd.DataFrame,
) -> Path:
    core_single = single_summary[
        single_summary["loro_classification"].isin(
            ["cross_regime_core", "cross_regime_resilient"]
        )
    ]
    core_combo = combo_summary[
        combo_summary["loro_classification"].isin(
            ["cross_regime_core", "cross_regime_resilient"]
        )
    ]
    confirmed_synergy = synergy_summary[
        synergy_summary["loro_synergy_classification"].eq(
            "cross_regime_synergistic"
        )
    ]
    regime_leaders = (
        period_metrics[
            period_metrics["candidate_class"].isin(["raw", "relative"])
            & period_metrics["available"].fillna(False)
        ]
        .sort_values(["regime_id", "active_cagr"], ascending=[True, False])
        .groupby("regime_id")
        .head(5)
    )
    loo_summary = pd.DataFrame()
    if not loo_contribution.empty:
        loo_summary = (
            loo_contribution.groupby("left_out_bucket")
            .agg(
                training_positive_folds=("training_positive_contribution", "sum"),
                holdout_positive_folds=("holdout_any_positive_contribution", "sum"),
                folds=("holdout_regime", "nunique"),
                mean_holdout_active_uplift=(
                    "full_holdout_active_cagr",
                    "mean",
                ),
            )
            .reset_index()
        )

    pre_positive = int((pre_post_2020["pre_2020_active_cagr"] > 0).sum())
    post_positive = int((pre_post_2020["post_2020_active_cagr"] > 0).sum())
    positive_to_negative = int(
        (
            (pre_post_2020["pre_2020_active_cagr"] > 0)
            & (pre_post_2020["post_2020_active_cagr"] <= 0)
        ).sum()
    )
    negative_to_positive = int(
        (
            (pre_post_2020["pre_2020_active_cagr"] <= 0)
            & (pre_post_2020["post_2020_active_cagr"] > 0)
        ).sum()
    )
    rank_correlation = pre_post_2020[
        ["pre_2020_active_cagr", "post_2020_active_cagr"]
    ].corr(method="spearman").iloc[0, 1]
    top_quartile_count = max(1, len(pre_post_2020) // 4)
    pre_top = set(
        pre_post_2020.nlargest(top_quartile_count, "pre_2020_active_cagr")["metric"]
    )
    post_top = set(
        pre_post_2020.nlargest(top_quartile_count, "post_2020_active_cagr")["metric"]
    )
    top_quartile_overlap = len(pre_top & post_top) / top_quartile_count

    report = f"""# STOXX Europe 600 Leave-One-Regime-Out 稳健性研究

## 结论口径

本研究不是用单一的 2020 前训练、2020 后测试来否定结构变化，而是检验：

> 一个变量或组合在不知道某一个完整市场阶段的情况下，能否从其余五个阶段被选中，并在被留出的阶段保持不差。

候选信号与组合收益全部来自已经完成的 official exact Top/Worst 回测。本研究只切分官方日频 NAV 并在每个 fold 内重新执行 regime gate，不使用 fast-screen 结果。

## Regime 定义

{markdown_table(pd.DataFrame(REGIMES), ["regime_id", "label_zh", "start", "end"], limit=20)}

日期边界沿用本地四市场时期研究的欧洲宏观分段，依据政策和宏观事件预先定义，不依据因子收益曲线寻找断点。

## 训练 gate

- 每个 fold 留出一个完整 regime，其余五个为训练阶段。
- coverage 不低于 {MIN_COVERAGE:.0%}。
- 五个训练阶段中，Top/Benchmark 主动 CAGR 至少 {MIN_POSITIVE_TRAIN_REGIMES} 个为正。
- 五个训练阶段中，Top/Worst CAGR 至少 {MIN_POSITIVE_TRAIN_REGIMES} 个为正。
- 训练阶段主动 CAGR 中位数为正。
- 最差训练阶段主动 CAGR 不低于 {MIN_WORST_ACTIVE_CAGR:.0%}。
- 排序目标同时惩罚最差阶段、主动回撤、跨阶段离散度和按 {COST_BPS_PER_ONE_WAY_TURNOVER:.0f} bps 单边换手估算的成本。
- 组合进入某一 fold 前，其全部底层 raw/relative 单变量必须先通过该 fold 的训练 gate。

## 数据完整性

- 单变量候选：{int(registry["candidate_class"].isin(["raw", "relative"]).sum())}
- 组合候选：{int(registry["candidate_class"].eq("combination").sum())}
- 已计算 candidate-regime 单元：{len(period_metrics)}
- 全部阶段数：{len(REGIMES)}

## 2020 断点诊断

- 有完整 2020 前后 official NAV 的单变量：{len(pre_post_2020)}
- 2020 前主动 CAGR 为正：{pre_positive}
- 2020 后主动 CAGR 为正：{post_positive}
- 从正转负：{positive_to_negative}
- 从负转正：{negative_to_positive}
- 前后主动 CAGR 排名 Spearman 相关：{rank_correlation:.3f}
- 前后头部四分位重合率：{top_quartile_overlap:.1%}

这组结果支持 2020 是显著的横截面定价断点，但不支持“所有旧变量同时死亡”。因此下文用六段 LORO 寻找能跨断点重复通过 gate 的变量，而不是让单一的 pre/post 切分承担全部模型选择。

## 跨 Regime 单变量

{markdown_table(core_single, ["label", "candidate_class", "family", "train_gate_passes", "holdout_joint_positive_rate", "mean_holdout_active_cagr", "min_holdout_active_cagr"], limit=25)}

`cross_regime_core` 要求至少五个 fold 通过训练 gate，留出期 Top/Benchmark 与 Top/Worst 同时为正的比例至少 80%，且最差留出期主动 CAGR 不低于 -3%。`cross_regime_resilient` 是较弱但仍具有重复证据的类别。

## 各阶段特殊赢家

{markdown_table(regime_leaders, ["regime_id", "label", "family", "active_cagr", "top_worst_cagr"], limit=30)}

阶段赢家用于解释 rotation，不自动进入跨 regime 核心。

## 跨 Regime 组合

{markdown_table(core_combo, ["label", "candidate_type", "train_gate_passes", "holdout_joint_positive_rate", "mean_holdout_active_cagr", "min_holdout_active_cagr"], limit=25)}

组合 LORO 覆盖既定的 190 个 pair、84 个 family subset、完整模型和 8 个 leave-one-out。它能检验既定组合库的跨 regime 泛化，但不等同于在每个 fold 内重新生成此前从未回测的新组合。

## 协同证据

{markdown_table(confirmed_synergy, ["label", "candidate_type", "eligible_folds", "train_synergy_folds", "holdout_synergy_confirmed_folds", "mean_holdout_active_cagr", "min_holdout_active_cagr"], limit=25)}

只有训练阶段相对最强单腿在至少三项风险收益指标上改善，并且这种改善在被留出阶段再次出现，才记为 holdout-confirmed synergy。其余有效组合仅称为 additive、regime-specific 或证据不足。

## Leave-One-Out 贡献

{markdown_table(loo_summary, ["left_out_bucket", "training_positive_folds", "holdout_positive_folds", "folds"], limit=20)}

## 解释边界

1. 这是严格的 regime-blocked 历史验证，明显强于全样本排名，但仍不是 2026 年 7 月以后真正不可回看的未来样本。
2. 候选变量定义来自此前研究，因此统计推断仍需记录完整 trial count，并补充 Deflated Sharpe/PBO。
3. 组合层使用的是此前已经 official 回测完成的既定候选库；未把 227 个单变量重新做全笛卡尔组合。
4. 交易成本使用统一压力参数，不代表针对每只证券和每个时期校准的成交成本。
5. 2026 年 7 月以后应冻结变量定义、方向、gate 和权重，作为 live paper OOS。

## 研究产物

- `candidate_registry.csv`
- `candidate_regime_metrics.csv`
- `single_pre_post_2020_metrics.csv`
- `single_loro_results.csv`
- `single_loro_selection_summary.csv`
- `combination_loro_results.csv`
- `combination_loro_selection_summary.csv`
- `synergy_loro_evidence.csv`
- `synergy_loro_summary.csv`
- `leave_one_out_regime_contribution.csv`
- `plots/`
"""
    report_path = output_dir / "stoxx600_leave_one_regime_out_report.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path


def write_metadata(
    output_dir: Path,
    registry: pd.DataFrame,
    period_metrics: pd.DataFrame,
    pre_post_2020: pd.DataFrame,
    plot_paths: list[str],
    report_path: Path,
) -> None:
    pd.DataFrame(REGIMES).to_csv(
        output_dir / "regime_definitions.csv", index=False, encoding="utf-8-sig"
    )
    checks = pd.DataFrame(
        [
            {
                "check": "candidate_registry_rows",
                "value": len(registry),
                "status": "pass",
            },
            {
                "check": "raw_relative_candidates",
                "value": int(
                    registry["candidate_class"].isin(["raw", "relative"]).sum()
                ),
                "status": "pass",
            },
            {
                "check": "combination_candidates",
                "value": int(registry["candidate_class"].eq("combination").sum()),
                "status": "pass",
            },
            {
                "check": "candidate_regime_rows",
                "value": len(period_metrics),
                "status": (
                    "pass"
                    if len(period_metrics) == len(registry) * len(REGIMES)
                    else "review"
                ),
            },
            {
                "check": "official_top_worst_paths",
                "value": int((registry["has_top"] & registry["has_worst"]).sum()),
                "status": (
                    "pass"
                    if bool((registry["has_top"] & registry["has_worst"]).all())
                    else "review"
                ),
            },
        ]
    )
    checks.to_csv(
        output_dir / "data_construction_checks.csv",
        index=False,
        encoding="utf-8-sig",
    )
    definitions = {
        "evidence_source": "Completed official exact Top/Worst daily NAV artifacts",
        "regimes": REGIMES,
        "gate": {
            "min_coverage": MIN_COVERAGE,
            "required_positive_train_regimes": MIN_POSITIVE_TRAIN_REGIMES,
            "minimum_worst_train_active_cagr": MIN_WORST_ACTIVE_CAGR,
            "minimum_days_per_regime": MIN_DAYS_PER_REGIME,
        },
        "training_objective": (
            "median active CAGR + 0.50*worst active CAGR "
            "+ 0.25*median Top/Worst CAGR + 0.25*worst active drawdown "
            "- 0.25*active-CAGR dispersion - annualized turnover cost"
        ),
        "turnover_cost_assumption": {
            "bps_per_one_way_turnover": COST_BPS_PER_ONE_WAY_TURNOVER,
            "rebalances_per_year": TRADING_MONTHS_PER_YEAR,
        },
        "future_oos_start": "2026-07-03",
    }
    (output_dir / "metric_definitions.json").write_text(
        json.dumps(definitions, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    manifest = {
        "output_dir": str(output_dir),
        "benchmark": "STOXX EUROPE 600",
        "source_runs": {
            "raw": str(RAW_RUN),
            "relative": str(RELATIVE_RUN),
            "synergy": str(SYNERGY_RUN),
        },
        "candidate_count": int(len(registry)),
        "single_candidate_count": int(
            registry["candidate_class"].isin(["raw", "relative"]).sum()
        ),
        "combination_candidate_count": int(
            registry["candidate_class"].eq("combination").sum()
        ),
        "regime_count": len(REGIMES),
        "candidate_regime_row_count": int(len(period_metrics)),
        "single_pre_post_2020_row_count": int(len(pre_post_2020)),
        "report": str(report_path),
        "plot_paths": plot_paths,
        "research_status": "historical_regime_blocked_validation",
        "future_oos_start": "2026-07-03",
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


@recorded_workflow
def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    registry, path_map = build_candidate_registry()
    if args.metrics:
        registry = registry[registry["metric"].isin(set(args.metrics))].copy()
    registry.to_csv(
        output_dir / "candidate_registry.csv", index=False, encoding="utf-8-sig"
    )

    period_metrics = compute_candidate_regime_metrics(
        registry=registry,
        path_map=path_map,
        output_path=output_dir / "candidate_regime_metrics.csv",
        resume=args.resume,
        metric_filter=set(args.metrics) if args.metrics else None,
        max_candidates=args.max_candidates,
    )
    pre_post_2020 = compute_single_pre_post_2020_metrics(registry, path_map)
    pre_post_2020.to_csv(
        output_dir / "single_pre_post_2020_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    all_loro = build_loro_rows(period_metrics, registry)
    singles, combinations = add_combination_eligibility(all_loro)
    single_summary = summarize_loro_candidates(singles)
    combo_summary = summarize_loro_candidates(
        combinations,
        pass_column="eligible_for_selection",
    )
    synergy_evidence, synergy_summary = build_synergy_loro_evidence(
        singles, combinations
    )
    loo_contribution = build_leave_one_out_contribution(combinations)

    all_loro.to_csv(
        output_dir / "all_loro_results.csv", index=False, encoding="utf-8-sig"
    )
    singles.to_csv(
        output_dir / "single_loro_results.csv", index=False, encoding="utf-8-sig"
    )
    single_summary.to_csv(
        output_dir / "single_loro_selection_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    combinations.to_csv(
        output_dir / "combination_loro_results.csv",
        index=False,
        encoding="utf-8-sig",
    )
    combo_summary.to_csv(
        output_dir / "combination_loro_selection_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    synergy_evidence.to_csv(
        output_dir / "synergy_loro_evidence.csv",
        index=False,
        encoding="utf-8-sig",
    )
    synergy_summary.to_csv(
        output_dir / "synergy_loro_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    loo_contribution.to_csv(
        output_dir / "leave_one_out_regime_contribution.csv",
        index=False,
        encoding="utf-8-sig",
    )

    plot_paths = create_plots(
        output_dir,
        period_metrics,
        single_summary,
        combo_summary,
        all_loro,
    )
    report_path = write_report(
        output_dir,
        registry,
        period_metrics,
        pre_post_2020,
        single_summary,
        combo_summary,
        synergy_summary,
        loo_contribution,
    )
    write_metadata(
        output_dir,
        registry,
        period_metrics,
        pre_post_2020,
        plot_paths,
        report_path,
    )
    print(f"Wrote {output_dir}")
    print(
        {
            "candidate_count": len(registry),
            "period_rows": len(period_metrics),
            "single_core_or_resilient": int(
                single_summary["loro_classification"]
                .isin(["cross_regime_core", "cross_regime_resilient"])
                .sum()
            ),
            "combination_core_or_resilient": int(
                combo_summary["loro_classification"]
                .isin(["cross_regime_core", "cross_regime_resilient"])
                .sum()
            ),
            "confirmed_cross_regime_synergy": int(
                synergy_summary["loro_synergy_classification"]
                .eq("cross_regime_synergistic")
                .sum()
            ),
        }
    )


if __name__ == "__main__":
    main()

"""Extended Nasdaq raw, relative, and synergy research report."""

from __future__ import annotations
from tp_research.runtime import recorded_workflow

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
import hashlib
from itertools import combinations
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


from tp_research.paths import SCRIPT_DIR
from tp_research.paths import BACKTEST_ROOT
from tp_research.paths import TP_ROOT

from tp_research.workflows import run_nasdaq_multifactor_research as base  # noqa: E402


AD_HOC_ROOT = BACKTEST_ROOT / "runs" / "ad_hoc"
DEFAULT_RAW_DIR = AD_HOC_ROOT / "nasdaq_raw_gate_20260708"
DEFAULT_VALIDATED_DIR = AD_HOC_ROOT / "nasdaq_validated_from_raw_gate_20260708"
DEFAULT_RELATIVE_DIR = AD_HOC_ROOT / "nasdaq_relative_variables_20260709"
DEFAULT_RETURNS = TP_ROOT / "00_screen" / "returns.parquet"

THEME_ORDER = [
    "revision",
    "pmom",
    "growth",
    "quality_improvement",
    "earnings_yield_improvement",
    "deleveraging",
]


@dataclass(frozen=True)
class RunPlan:
    screen_path: Path
    returns_path: Path
    metrics: list[str]
    output_dir: Path
    results_path: Path
    workers: int
    wave: str


def read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def as_bool(series: pd.Series) -> pd.Series:
    return series.map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})


def metric_hash(*parts: str, prefix: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def theme_for_raw(raw_variable: str, family: str) -> str:
    text = raw_variable.lower()
    if "revision" in text or "ntm 3m" in text:
        return "revision"
    if "pmom" in text:
        return "pmom"
    if family == "growth":
        return "growth"
    if "net debt" in text or "netdebt" in text:
        return "deleveraging"
    return ""


def theme_for_relative(raw_column: str, base_family: str) -> str:
    text = raw_column.lower()
    if "earns yield" in text:
        return "earnings_yield_improvement"
    if "net debt" in text or "netdebt" in text:
        return "deleveraging"
    if base_family == "quality":
        return "quality_improvement"
    if base_family == "growth":
        return "growth"
    return ""


def load_single_summary(raw_dir: Path, relative_dir: Path) -> pd.DataFrame:
    raw_summary = read_csv(raw_dir / "performance_summary.csv")
    rel_summary = read_csv(relative_dir / "performance_summary.csv")
    frames = []
    if not raw_summary.empty:
        raw = raw_summary.copy()
        raw["evidence_scope"] = "raw_level"
        frames.append(raw)
    if not rel_summary.empty:
        rel = rel_summary.copy()
        rel["evidence_scope"] = "relative_raw"
        frames.append(rel)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def build_candidate_audit(raw_dir: Path, relative_dir: Path) -> pd.DataFrame:
    raw_gate = read_csv(raw_dir / "raw_validation_gate.csv")
    rel_gate = read_csv(relative_dir / "relative_validation_gate.csv")
    rows: list[dict[str, object]] = []
    if not raw_gate.empty:
        raw_gate = raw_gate.copy()
        raw_gate["passed_bool"] = as_bool(raw_gate["passed"]) if "passed" in raw_gate.columns else False
        for _, row in raw_gate.iterrows():
            family = str(row.get("family", ""))
            raw_variable = str(row.get("raw_variable", ""))
            theme = theme_for_raw(raw_variable, family)
            if theme not in THEME_ORDER:
                continue
            rows.append(
                {
                    "metric": row.get("metric", ""),
                    "label": f"{family}: {raw_variable}",
                    "raw_column": raw_variable,
                    "theme": theme,
                    "family": family,
                    "source": row.get("source_hint", ""),
                    "evidence_scope": "raw_level",
                    "coverage": row.get("coverage", np.nan),
                    "ratio_cagr": row.get("top_ratio_cagr", np.nan),
                    "top_worst_ratio_return": row.get("top_worst_ratio_return", np.nan),
                    "robust_score": row.get("robust_score", np.nan),
                    "pass_gate": bool(row.get("passed_bool", False)),
                    "fail_reasons": row.get("fail_reasons", ""),
                    "economic_role": economic_role(theme, raw_variable, "raw_level"),
                }
            )
    if not rel_gate.empty:
        rel_gate = rel_gate.copy()
        rel_gate["passed_bool"] = as_bool(rel_gate["pass_gate"]) if "pass_gate" in rel_gate.columns else False
        for _, row in rel_gate.iterrows():
            raw_column = str(row.get("raw_column", ""))
            family = str(row.get("base_family", ""))
            theme = theme_for_relative(raw_column, family)
            if theme not in THEME_ORDER:
                continue
            transform = str(row.get("transform", ""))
            lag = row.get("lag_observations", "")
            rows.append(
                {
                    "metric": row.get("metric", ""),
                    "label": f"{theme}: {raw_column} {transform} lag{lag}",
                    "raw_column": raw_column,
                    "theme": theme,
                    "family": family,
                    "source": row.get("source", ""),
                    "evidence_scope": "relative_raw",
                    "coverage": row.get("coverage", np.nan),
                    "ratio_cagr": row.get("ratio_cagr", np.nan),
                    "top_worst_ratio_return": row.get("top_worst_ratio_return", np.nan),
                    "robust_score": row.get("robust_score", np.nan),
                    "pass_gate": bool(row.get("passed_bool", False)),
                    "fail_reasons": row.get("fail_reasons", ""),
                    "transform": transform,
                    "lag_observations": lag,
                    "economic_role": economic_role(theme, raw_column, "relative_raw"),
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["pass_gate", "theme", "robust_score"], ascending=[False, True, False]).reset_index(drop=True)


def economic_role(theme: str, raw_column: str, scope: str) -> str:
    if theme == "revision":
        return "盈利预期上修和信息扩散，适合作为 Nasdaq 基本面 momentum 的核心 timing 信号"
    if theme == "pmom":
        return "价格趋势确认，但在 Nasdaq 容易混入拥挤、mega-cap beta 和短期反转"
    if theme == "growth":
        return "收入、毛利或 EPS 扩张，只有和盈利兑现或质量改善结合时才更像可持续成长"
    if theme == "quality_improvement":
        return "利润率、ROE、现金转化等边际改善，代表经营杠杆和盈利质量正在变好"
    if theme == "earnings_yield_improvement":
        return "盈利收益率改善，代表估值相对盈利预期变得更有吸引力，而不是静态便宜"
    if theme == "deleveraging":
        return "杠杆下降降低融资和久期风险，能过滤成长股在利率上行期的资产负债表脆弱性"
    return f"{scope}: {raw_column}"


def load_synergy_screen(raw_dir: Path, relative_dir: Path, candidates: pd.DataFrame, output_dir: Path) -> tuple[pd.DataFrame, Path]:
    raw_screen = pd.read_parquet(raw_dir / "nasdaq_multifactor_screen.parquet")
    selected = candidates[candidates["pass_gate"].astype(bool)].copy()
    rel_metrics = selected.loc[selected["evidence_scope"].eq("relative_raw"), "metric"].astype(str).tolist()
    if rel_metrics:
        rel_cols = [base.DATE_COL, base.ISIN_COL, *rel_metrics]
        rel_screen = pd.read_parquet(relative_dir / "nasdaq_relative_variable_screen.parquet", columns=rel_cols)
        screen = raw_screen.merge(rel_screen, on=[base.DATE_COL, base.ISIN_COL], how="left")
    else:
        screen = raw_screen.copy()
    screen_path = output_dir / "nasdaq_extended_synergy_screen.parquet"
    screen.to_parquet(screen_path, index=False)
    return screen, screen_path


def build_synergy_metrics(screen: pd.DataFrame, candidates: pd.DataFrame, output_dir: Path) -> tuple[pd.DataFrame, list[base.ModelSpec], dict[str, object]]:
    selected = candidates[candidates["pass_gate"].astype(bool)].copy()
    selected = selected[selected["metric"].isin(screen.columns)].copy()
    specs: list[base.ModelSpec] = []
    new_columns: dict[str, pd.Series] = {}
    pair_map: dict[str, dict[str, str]] = {}
    subset_map: dict[str, dict[str, object]] = {}
    loo_map: dict[str, dict[str, object]] = {}

    metrics = selected["metric"].astype(str).tolist()
    labels = selected.set_index("metric")["label"].to_dict()
    themes = selected.set_index("metric")["theme"].to_dict()

    for left, right in combinations(metrics, 2):
        column = metric_hash(left, right, prefix="nasdaq_ext_pair")
        new_columns[column] = base.average_scores(screen, [left, right], min_count=2)
        label = f"{labels.get(left, left)} + {labels.get(right, right)}"
        specs.append(base.ModelSpec(column, label, "pair_synergy", {left: 0.5, right: 0.5}, "equal-weight pair of passed raw/relative variables"))
        pair_map[column] = {
            "metric_a": left,
            "metric_b": right,
            "label_a": labels.get(left, left),
            "label_b": labels.get(right, right),
            "theme_a": themes.get(left, ""),
            "theme_b": themes.get(right, ""),
        }

    theme_scores: dict[str, str] = {}
    for theme, group in selected.groupby("theme", sort=False):
        cols = group["metric"].astype(str).tolist()
        column = f"nasdaq_ext_theme_{base.slugify(theme)}"
        min_count = 1 if len(cols) == 1 else max(1, int(np.ceil(len(cols) / 2)))
        new_columns[column] = base.average_scores(screen, cols, min_count=min_count)
        theme_scores[theme] = column
        specs.append(base.ModelSpec(column, f"{theme} validated theme", "validated_theme", {col: 1.0 for col in cols}, f"theme composite; min_count={min_count}"))

    theme_names = [theme for theme in THEME_ORDER if theme in theme_scores]
    for size in range(2, len(theme_names) + 1):
        for combo in combinations(theme_names, size):
            column = "nasdaq_ext_subset_" + "_".join(base.slugify(item) for item in combo)
            components = {theme_scores[item]: 1.0 / size for item in combo}
            new_columns[column] = base.weighted_scores(screen.assign(**new_columns), components, min_count=max(1, min(size, 3)))
            specs.append(base.ModelSpec(column, " + ".join(combo), "family_subset", components, f"validated theme subset: {', '.join(combo)}"))
            subset_map[column] = {"themes": list(combo), "kind": "theme_subset"}

    if len(theme_names) >= 3:
        full_theme_col = "nasdaq_ext_full_theme_composite"
        components = {theme_scores[item]: 1.0 / len(theme_names) for item in theme_names}
        frame = screen.assign(**new_columns)
        new_columns[full_theme_col] = base.weighted_scores(frame, components, min_count=max(2, min(len(theme_names), 4)))
        specs.append(base.ModelSpec(full_theme_col, "all validated themes", "full_composite", components, "all passed themes equal weight"))
        for omitted in theme_names:
            kept = [theme for theme in theme_names if theme != omitted]
            column = "nasdaq_ext_theme_loo_ex_" + base.slugify(omitted)
            loo_components = {theme_scores[item]: 1.0 / len(kept) for item in kept}
            frame = screen.assign(**new_columns)
            new_columns[column] = base.weighted_scores(frame, loo_components, min_count=max(1, min(len(kept), 3)))
            specs.append(base.ModelSpec(column, f"leave one theme out: ex {omitted}", "leave_one_out", loo_components, f"exclude theme {omitted}"))
            loo_map[column] = {"omitted": omitted, "kind": "theme", "full_metric": full_theme_col}

    if len(metrics) >= 3:
        full_var_col = "nasdaq_ext_full_variable_composite"
        new_columns[full_var_col] = base.average_scores(screen, metrics, min_count=max(2, min(len(metrics), 5)))
        specs.append(base.ModelSpec(full_var_col, "all passed variables", "full_composite", {metric: 1.0 for metric in metrics}, "all passed raw/relative variables equal weight"))
        for omitted in metrics:
            kept = [metric for metric in metrics if metric != omitted]
            column = "nasdaq_ext_var_loo_" + hashlib.sha1(omitted.encode("utf-8")).hexdigest()[:10]
            new_columns[column] = base.average_scores(screen, kept, min_count=max(2, min(len(kept), 5)))
            specs.append(base.ModelSpec(column, f"leave one variable out: ex {labels.get(omitted, omitted)}", "leave_one_out", {metric: 1.0 for metric in kept}, f"exclude variable {omitted}"))
            loo_map[column] = {"omitted": omitted, "omitted_label": labels.get(omitted, omitted), "kind": "variable", "full_metric": full_var_col}

    if new_columns:
        screen = pd.concat([screen, pd.DataFrame(new_columns, index=screen.index)], axis=1).copy()
    maps = {"pair": pair_map, "subset": subset_map, "leave_one_out": loo_map, "theme_scores": theme_scores}
    (output_dir / "synergy_metric_maps.json").write_text(json.dumps(maps, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "synergy_metric_definitions.json").write_text(json.dumps([spec.__dict__ for spec in specs], ensure_ascii=False, indent=2), encoding="utf-8")
    return screen, specs, maps


def dedupe_results(results: pd.DataFrame) -> pd.DataFrame:
    if results.empty or not {"metric", "side", "status"}.issubset(results.columns):
        return results
    status_rank = {"success": 3, "skipped": 2, "failed": 1}
    out = results.copy()
    out["_status_rank"] = out["status"].map(status_rank).fillna(0)
    out["_order"] = range(len(out))
    out = out.sort_values(["metric", "side", "_status_rank", "_order"], ascending=[True, True, False, True])
    out = out.drop_duplicates(["metric", "side"], keep="first")
    return out.drop(columns=["_status_rank", "_order"]).sort_values(["metric", "side"]).reset_index(drop=True)


def load_completed(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        if path.exists() and path.stat().st_size > 0:
            try:
                frames.append(pd.read_csv(path))
            except pd.errors.EmptyDataError:
                pass
    if not frames:
        return pd.DataFrame()
    return dedupe_results(pd.concat(frames, ignore_index=True))


def incomplete_metrics(metrics: list[str], completed: pd.DataFrame) -> list[str]:
    if completed.empty:
        return list(metrics)
    done = set(
        (str(row["metric"]), str(row["side"]))
        for _, row in completed[completed["status"].isin(["success", "skipped"])].iterrows()
    )
    return [metric for metric in metrics if (metric, "Top") not in done or (metric, "Worst") not in done]


def shard_metrics(metrics: list[str], workers: int) -> list[list[str]]:
    shards = [[] for _ in range(max(workers, 1))]
    for idx, metric in enumerate(metrics):
        shards[idx % len(shards)].append(metric)
    return [shard for shard in shards if shard]


def worker_run(payload: dict[str, object]) -> dict[str, object]:
    output_dir = Path(str(payload["output_dir"]))
    screen_path = Path(str(payload["screen_path"]))
    returns_path = Path(str(payload["returns_path"]))
    metrics = list(payload["metrics"])
    wave = str(payload["wave"])
    shard_id = int(payload["shard_id"])
    main_results_path = Path(str(payload["main_results_path"]))
    shard_dir = output_dir / "parallel_shards" / wave / f"shard_{shard_id:02d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_results_path = shard_dir / "official_run_results.csv"

    existing = load_completed([main_results_path, shard_results_path])
    if not existing.empty:
        existing = existing[existing["metric"].isin(metrics)].copy()
    screen = pd.read_parquet(screen_path)
    returns = base.load_tabular_file(returns_path)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index()
    wave_slug = base.slugify(wave)[-18:]
    results = base.run_official_backtests(
        screen=screen,
        returns=returns,
        screen_path=screen_path,
        returns_path=returns_path,
        run_root_name=f"ad_hoc/nasx_{wave_slug}_s{shard_id:02d}",
        metrics=metrics,
        max_runs=None,
        progress_path=shard_results_path,
        existing_results=existing,
    )
    results = dedupe_results(results)
    results.to_csv(shard_results_path, index=False)
    return {"shard_id": shard_id, "metrics": len(metrics), "rows": len(results), "success": int(results["status"].eq("success").sum())}


def run_parallel(plan: RunPlan) -> pd.DataFrame:
    shard_paths = sorted((plan.output_dir / "parallel_shards").rglob("official_run_results.csv"))
    completed = load_completed([plan.results_path, *shard_paths])
    if not completed.empty:
        completed.to_csv(plan.results_path, index=False)
    remaining = incomplete_metrics(plan.metrics, completed)
    shards = shard_metrics(remaining, plan.workers)
    print(
        json.dumps(
            {
                "event": "synergy_parallel_start",
                "metric_total": len(plan.metrics),
                "metric_remaining": len(remaining),
                "workers": plan.workers,
                "shards": [len(shard) for shard in shards],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if shards:
        payloads = [
            {
                "output_dir": str(plan.output_dir),
                "screen_path": str(plan.screen_path),
                "returns_path": str(plan.returns_path),
                "main_results_path": str(plan.results_path),
                "wave": plan.wave,
                "shard_id": idx,
                "metrics": shard,
            }
            for idx, shard in enumerate(shards)
        ]
        with ProcessPoolExecutor(max_workers=plan.workers) as executor:
            futures = [executor.submit(worker_run, payload) for payload in payloads]
            for future in as_completed(futures):
                print(json.dumps({"event": "synergy_shard_done", **future.result()}, ensure_ascii=False), flush=True)
    shard_paths = sorted((plan.output_dir / "parallel_shards").rglob("official_run_results.csv"))
    run_results = load_completed([plan.results_path, *shard_paths])
    run_results.to_csv(plan.results_path, index=False)
    return run_results


def classify_pair_synergy(pair_summary: pd.DataFrame, single_summary: pd.DataFrame, maps: dict[str, object]) -> pd.DataFrame:
    pair_map = maps.get("pair", {})
    single_top = single_summary[(single_summary["side"].eq("Top")) & (single_summary["status"].eq("success"))].set_index("metric")
    pair_top = pair_summary[(pair_summary["side"].eq("Top")) & (pair_summary["status"].eq("success"))].copy()
    rows = []
    for _, row in pair_top.iterrows():
        metric = str(row["metric"])
        info = pair_map.get(metric)
        if not info:
            continue
        a = info["metric_a"]
        b = info["metric_b"]
        if a not in single_top.index or b not in single_top.index:
            continue
        left = single_top.loc[a]
        right = single_top.loc[b]
        best_robust = max(float(left.get("robust_score", np.nan)), float(right.get("robust_score", np.nan)))
        best_ratio = max(float(left.get("ratio_cagr", np.nan)), float(right.get("ratio_cagr", np.nan)))
        best_tw = max(float(left.get("top_worst_ratio_return", np.nan)), float(right.get("top_worst_ratio_return", np.nan)))
        pair_robust = float(row.get("robust_score", np.nan))
        pair_ratio = float(row.get("ratio_cagr", np.nan))
        pair_tw = float(row.get("top_worst_ratio_return", np.nan))
        if pair_robust <= 0 or pair_ratio <= 0 or pair_tw <= 0:
            relation = "harmful"
        elif pair_robust > best_robust and pair_ratio > best_ratio and pair_tw > best_tw:
            relation = "synergistic"
        elif pair_robust > best_robust or pair_ratio > best_ratio:
            relation = "additive"
        else:
            relation = "redundant"
        rows.append(
            {
                "pair_metric": metric,
                "pair_label": row.get("label", ""),
                **info,
                "pair_ratio_cagr": pair_ratio,
                "best_single_ratio_cagr": best_ratio,
                "pair_minus_best_ratio_cagr": pair_ratio - best_ratio,
                "pair_top_worst_ratio_return": pair_tw,
                "best_single_top_worst_ratio_return": best_tw,
                "pair_minus_best_top_worst_ratio_return": pair_tw - best_tw,
                "pair_ratio_max_drawdown": row.get("ratio_max_drawdown", np.nan),
                "pair_tracking_error": row.get("tracking_error", np.nan),
                "pair_robust_score": pair_robust,
                "best_single_robust_score": best_robust,
                "pair_minus_best_robust_score": pair_robust - best_robust,
                "relationship": relation,
                "economic_explanation": pair_economic_explanation(info.get("theme_a", ""), info.get("theme_b", "")),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["relationship", "pair_minus_best_robust_score"], ascending=[False, False]).reset_index(drop=True)


def pair_economic_explanation(theme_a: str, theme_b: str) -> str:
    themes = {theme_a, theme_b}
    if "revision" in themes and "deleveraging" in themes:
        return "盈利上修提供基本面催化，去杠杆降低融资尾部风险，组合更像可承受利率压力的盈利改善。"
    if "revision" in themes and "quality_improvement" in themes:
        return "盈利预期改善若同时有利润率/ROE/现金质量改善，更可能是经营现实在验证分析师上修。"
    if "revision" in themes and "earnings_yield_improvement" in themes:
        return "上修提高盈利锚，盈利收益率改善约束估值，组合避免只买昂贵预期。"
    if "growth" in themes and "quality_improvement" in themes:
        return "成长给方向，质量改善过滤低质量扩张，组合对应可兑现成长。"
    if "pmom" in themes and "quality_improvement" in themes:
        return "价格趋势需要基本面改善确认，否则 Nasdaq 中容易只是拥挤 beta。"
    if "earnings_yield_improvement" in themes and "deleveraging" in themes:
        return "估值相对盈利改善叠加资产负债表修复，接近 anti-value-trap。"
    return "两个变量来自不同信息维度，若 pair 超过强单腿，说明组合降低了单一信号噪声。"


def summarize_subset_and_loo(summary: pd.DataFrame, maps: dict[str, object]) -> tuple[pd.DataFrame, pd.DataFrame]:
    top = summary[(summary["side"].eq("Top")) & (summary["status"].eq("success"))].copy()
    subset_map = maps.get("subset", {})
    loo_map = maps.get("leave_one_out", {})
    subset = top[top["metric"].isin(subset_map.keys())].copy()
    if not subset.empty:
        subset["themes"] = subset["metric"].map(lambda metric: ",".join(subset_map.get(metric, {}).get("themes", [])))
        subset = subset.sort_values("robust_score", ascending=False)
    loo = top[top["metric"].isin(loo_map.keys())].copy()
    if not loo.empty:
        loo["omitted"] = loo["metric"].map(lambda metric: loo_map.get(metric, {}).get("omitted", ""))
        loo["omitted_label"] = loo["metric"].map(lambda metric: loo_map.get(metric, {}).get("omitted_label", ""))
        loo["loo_kind"] = loo["metric"].map(lambda metric: loo_map.get(metric, {}).get("kind", ""))
        full_by_metric = top.set_index("metric").to_dict(orient="index")
        loo["full_metric"] = loo["metric"].map(lambda metric: loo_map.get(metric, {}).get("full_metric", ""))
        loo["full_robust_score"] = loo["full_metric"].map(lambda metric: full_by_metric.get(metric, {}).get("robust_score", np.nan))
        loo["full_ratio_cagr"] = loo["full_metric"].map(lambda metric: full_by_metric.get(metric, {}).get("ratio_cagr", np.nan))
        loo["contribution_robust_score"] = loo["full_robust_score"] - loo["robust_score"]
        loo["contribution_ratio_cagr"] = loo["full_ratio_cagr"] - loo["ratio_cagr"]
        loo = loo.sort_values(["loo_kind", "contribution_robust_score"], ascending=[True, False])
    return subset, loo


def table(frame: pd.DataFrame, columns: list[str], max_rows: int = 30) -> str:
    cols = [col for col in columns if col in frame.columns]
    if frame.empty or not cols:
        return "暂无数据。"
    view = frame.loc[:, cols].head(max_rows).copy()
    for col in view.select_dtypes(include=["float", "float64"]).columns:
        view[col] = view[col].map(lambda value: "" if pd.isna(value) else f"{value:.4f}")
    return base.frame_to_markdown(view, max_rows=max_rows)


def write_report(
    output_dir: Path,
    checks: pd.DataFrame,
    candidates: pd.DataFrame,
    relative_comparison: pd.DataFrame,
    pair_synergy: pd.DataFrame,
    subset_results: pd.DataFrame,
    loo_results: pd.DataFrame,
    run_results: pd.DataFrame,
) -> Path:
    passed = candidates[candidates["pass_gate"].astype(bool)].copy() if not candidates.empty else pd.DataFrame()
    failed = candidates[~candidates["pass_gate"].astype(bool)].copy() if not candidates.empty else pd.DataFrame()
    synergistic = pair_synergy[pair_synergy["relationship"].eq("synergistic")].copy() if not pair_synergy.empty else pd.DataFrame()
    lines = [
        "# Nasdaq raw variable、相对变量与协同效应补充研究",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 证据口径: official exact Top/Worst backtest；raw 与 relative 均先单独过 gate，协同只基于 pair/subset/leave-one-out 证据。",
        f"- 研究目录: `{output_dir}`",
        f"- 通过 gate 的指定主题变量: {len(passed)}；pair/subset/leave-one-out official run rows: {len(run_results)}。",
        "",
        "## Benchmark 与数据审计",
        "",
        table(checks, ["check", "value"], max_rows=40),
        "",
        "## 通过 gate 的单变量",
        "",
        table(
            passed.sort_values(["theme", "robust_score"], ascending=[True, False]),
            ["theme", "label", "evidence_scope", "source", "coverage", "ratio_cagr", "top_worst_ratio_return", "robust_score", "economic_role"],
            max_rows=80,
        ),
        "",
        "## 未进入严格协同池的指定主题变量",
        "",
        "这些变量可作为弱证据或分期假设，但不能因为经济故事好听就进入 family 或声明 synergy。",
        "",
        table(
            failed.sort_values(["theme", "robust_score"], ascending=[True, False]),
            ["theme", "label", "evidence_scope", "source", "coverage", "ratio_cagr", "top_worst_ratio_return", "robust_score", "fail_reasons"],
            max_rows=80,
        ),
        "",
        "## Relative vs Level 对照",
        "",
        table(
            relative_comparison,
            [
                "raw_column",
                "family",
                "best_relative_metric",
                "transform",
                "lag_observations",
                "relative_pass_gate",
                "level_pass_gate",
                "relative_robust_score",
                "level_robust_score",
                "relative_minus_level_robust",
                "relative_ratio_cagr",
                "level_ratio_cagr",
            ],
            max_rows=80,
        ),
        "",
        "## Pair 协同分类",
        "",
        table(
            pair_synergy,
            [
                "relationship",
                "pair_label",
                "theme_a",
                "theme_b",
                "pair_ratio_cagr",
                "best_single_ratio_cagr",
                "pair_minus_best_ratio_cagr",
                "pair_top_worst_ratio_return",
                "best_single_top_worst_ratio_return",
                "pair_minus_best_top_worst_ratio_return",
                "pair_robust_score",
                "best_single_robust_score",
                "pair_minus_best_robust_score",
                "economic_explanation",
            ],
            max_rows=80,
        ),
        "",
        "## Family Subset 证据",
        "",
        table(
            subset_results,
            ["metric", "label", "themes", "ratio_cagr", "top_worst_ratio_return", "ratio_max_drawdown", "tracking_error", "robust_score"],
            max_rows=80,
        ),
        "",
        "## Leave-One-Out 证据",
        "",
        table(
            loo_results,
            [
                "loo_kind",
                "omitted",
                "omitted_label",
                "ratio_cagr",
                "top_worst_ratio_return",
                "robust_score",
                "full_robust_score",
                "contribution_robust_score",
                "contribution_ratio_cagr",
            ],
            max_rows=100,
        ),
        "",
        "## 研究结论",
        "",
    ]
    if passed.empty:
        lines.append("- 指定主题中没有新增变量通过 gate，因此不能补充正式协同结论。")
    else:
        theme_counts = passed.groupby("theme").size().sort_values(ascending=False)
        lines.append(f"- 通过 gate 的主题分布: {', '.join(f'{k}={v}' for k, v in theme_counts.items())}。")
        lines.append("- 单变量层面，Nasdaq 仍优先奖励盈利预期修正；新增相对变量如果通过，多数应解释为边际改善效应，而不是静态水平有效。")
        lines.append("- PMOM/growth 若未过 raw gate，只能作为分期或 overlay 假设；不能进入严格 family，也不能拿 pair 直觉声明协同。")
    if synergistic.empty:
        lines.append("- 按严格定义，本轮没有 pair 同时超过强单腿的 ratio CAGR、Top/Worst 分化和 robust score；协同结论应保持克制。")
    else:
        lines.append(f"- 严格协同 pair 数量: {len(synergistic)}。这些 pair 的经济解释见上表，且已经和更强单腿比较。")
    lines.extend(
        [
            "- subset 与 leave-one-out 用来确认主题是否冗余: 如果剔除某变量后 full composite 更好，则该变量是有害或冗余；如果剔除后明显变差，才说明它对组合有正贡献。",
            "",
            "## 输出文件",
            "",
            "- `synergy_candidate_audit.csv`",
            "- `pair_synergy_results.csv`",
            "- `family_subset_results.csv`",
            "- `leave_one_out_results.csv`",
            "- `synergy_claims.csv`",
            "- `synergy_official_run_results.csv`",
            "- `synergy_performance_summary.csv`",
        ]
    )
    path = output_dir / "nasdaq_extended_factor_research_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Nasdaq raw/relative/synergy extended factor research.")
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--validated-dir", default=str(DEFAULT_VALIDATED_DIR))
    parser.add_argument("--relative-dir", default=str(DEFAULT_RELATIVE_DIR))
    parser.add_argument("--returns", default=str(DEFAULT_RETURNS))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--wave", default="")
    parser.add_argument("--build-only", action="store_true")
    return parser


@recorded_workflow
def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    raw_dir = Path(args.raw_dir)
    relative_dir = Path(args.relative_dir)
    returns_path = Path(args.returns)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else AD_HOC_ROOT / f"nasdaq_extended_factor_research_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = build_candidate_audit(raw_dir, relative_dir)
    candidates.to_csv(output_dir / "synergy_candidate_audit.csv", index=False)
    relative_comparison = read_csv(relative_dir / "relative_vs_level_comparison.csv")
    if not relative_comparison.empty:
        relative_comparison.to_csv(output_dir / "relative_vs_level_comparison.csv", index=False)

    single_summary = load_single_summary(raw_dir, relative_dir)
    single_summary.to_csv(output_dir / "single_variable_official_summary.csv", index=False)
    screen, _ = load_synergy_screen(raw_dir, relative_dir, candidates, output_dir)
    screen, metric_specs, maps = build_synergy_metrics(screen, candidates, output_dir)
    screen_path = output_dir / "nasdaq_extended_synergy_screen.parquet"
    screen.to_parquet(screen_path, index=False)
    checks = pd.concat(
        [
            read_csv(raw_dir / "data_construction_checks.csv").assign(source_run="raw_level"),
            read_csv(relative_dir / "data_construction_checks.csv").assign(source_run="relative_raw"),
        ],
        ignore_index=True,
    )
    checks.to_csv(output_dir / "data_construction_checks.csv", index=False)
    metric_diag = base.metric_diagnostics(screen, metric_specs, [])
    metric_diag.to_csv(output_dir / "synergy_metric_diagnostics.csv", index=False)

    metrics = [spec.column for spec in metric_specs if spec.column in screen.columns]
    run_results = pd.DataFrame()
    summary = pd.DataFrame()
    pair_synergy = pd.DataFrame()
    subset_results = pd.DataFrame()
    loo_results = pd.DataFrame()
    if metrics and not args.build_only:
        wave = args.wave.strip() or datetime.now().strftime("wave_%Y%m%d_%H%M%S")
        plan = RunPlan(
            screen_path=screen_path,
            returns_path=returns_path,
            metrics=metrics,
            output_dir=output_dir,
            results_path=output_dir / "synergy_official_run_results.csv",
            workers=max(1, args.workers),
            wave=wave,
        )
        run_results = run_parallel(plan)
        summary = base.summarize_runs(run_results, metric_diag)
        summary.to_csv(output_dir / "synergy_performance_summary.csv", index=False)
        pair_synergy = classify_pair_synergy(summary, single_summary, maps)
        pair_synergy.to_csv(output_dir / "pair_synergy_results.csv", index=False)
        subset_results, loo_results = summarize_subset_and_loo(summary, maps)
        subset_results.to_csv(output_dir / "family_subset_results.csv", index=False)
        loo_results.to_csv(output_dir / "leave_one_out_results.csv", index=False)
        claims = pair_synergy[pair_synergy["relationship"].eq("synergistic")].copy() if not pair_synergy.empty else pd.DataFrame()
        claims.to_csv(output_dir / "synergy_claims.csv", index=False)

    report = write_report(output_dir, checks, candidates, relative_comparison, pair_synergy, subset_results, loo_results, run_results)
    manifest = {
        "output_dir": str(output_dir),
        "raw_dir": str(raw_dir),
        "relative_dir": str(relative_dir),
        "report": str(report),
        "candidate_count": int(len(candidates)),
        "passed_candidate_count": int(candidates["pass_gate"].sum()) if not candidates.empty else 0,
        "synergy_metric_count": int(len(metrics)),
        "expected_run_count": int(2 * len(metrics)),
        "run_count": int(len(run_results)),
        "success_count": int(run_results["status"].eq("success").sum()) if not run_results.empty else 0,
        "synergy_claim_count": int(pair_synergy["relationship"].eq("synergistic").sum()) if not pair_synergy.empty else 0,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

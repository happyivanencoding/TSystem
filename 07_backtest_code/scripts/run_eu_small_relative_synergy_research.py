"""
MSCI Europe Small raw + relative-variable synergy research.

This runner uses already completed raw and relative raw gates, builds
economically pre-specified pair, bucket-subset, and leave-one-out candidates,
and runs official Top/Worst evidence with resumable process-level sharding.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


SCRIPT_DIR = Path(__file__).resolve().parent
BACKTEST_ROOT = SCRIPT_DIR.parents[0]
TP_ROOT = BACKTEST_ROOT.parent

import run_eu_small_multifactor_research as base  # noqa: E402
import run_eu_small_validated_gate_research as gate_runner  # noqa: E402
from tp_research.executor import (  # noqa: E402
    build_synergy_candidate_matrix,
    dedupe_official_results,
    incomplete_official_metrics,
    new_wave_id,
    read_official_results,
    shard_metric_names,
)


AD_HOC_ROOT = BACKTEST_ROOT / "runs" / "ad_hoc"
RAW_DIR = AD_HOC_ROOT / "eu_small_validated_gate_20260708_official"
RELATIVE_DIR = AD_HOC_ROOT / "eu_small_relative_variables_20260709"
DEFAULT_RETURNS = TP_ROOT / "00_screen" / "returns.parquet"
OUTPUT_NAME = "eu_small_relative_synergy_20260709"

BUCKET_LIMITS = {
    "revision": 2,
    "pmom": 1,
    "growth": 3,
    "quality_improvement": 4,
    "earnings_yield_improvement": 3,
    "deleveraging": 3,
    "value_improvement": 3,
    "risk_decline": 2,
}
BUCKET_ORDER = list(BUCKET_LIMITS)
RAW_SPEC_BY_SCORE = {spec.score_column: spec for spec in base.RAW_METRICS}


@dataclass(frozen=True)
class Leg:
    metric: str
    label: str
    bucket: str
    source_type: str
    raw_column: str
    family: str
    transform: str
    lag_observations: str
    robust_score: float
    ratio_cagr: float
    top_worst_ratio_return: float
    coverage: float
    economic_role: str


def parse_csv_arg(raw: str | None, default: list[str]) -> list[str]:
    if raw is None or raw.strip().lower() == "all":
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def status_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def raw_bucket(row: pd.Series) -> str:
    raw_column = str(row.get("raw_column", ""))
    family = str(row.get("family", row.get("raw_family", "")))
    if raw_column in {"EPS Revision Ratio", "EPS NTM 3M Growth"}:
        return "revision"
    if raw_column == "PMOM 12M1M":
        return "pmom"
    if family == "growth":
        return "growth"
    return ""


def relative_bucket(row: pd.Series) -> str:
    raw_column = str(row.get("raw_column", ""))
    family = str(row.get("base_family", ""))
    if raw_column in {"Oper Margin", "ROE avg FY0", "Cont Op Earning Margin", "Gross Margin", "FCF Conversion"}:
        return "quality_improvement"
    if raw_column in {"NetDebt to EBITDA exFIN", "Net Debt to Market Cap", "Net Debt to Tot Equity"}:
        return "deleveraging"
    if raw_column in {"Earns Yield FY1", "Earns Yield NTM"}:
        return "earnings_yield_improvement"
    if family == "value":
        return "value_improvement"
    if family == "lowvol":
        return "risk_decline"
    return ""


def economic_role(bucket: str) -> str:
    return {
        "revision": "earnings expectation upgrade",
        "pmom": "price momentum confirmation",
        "growth": "forward growth delivery",
        "quality_improvement": "profitability or margin improvement",
        "earnings_yield_improvement": "valuation becoming cheaper relative to earnings",
        "deleveraging": "balance-sheet risk decline",
        "value_improvement": "valuation multiple becoming cheaper",
        "risk_decline": "realized risk or volatility decline",
    }.get(bucket, bucket)


def select_legs(raw_gate: pd.DataFrame, rel_gate: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    raw_pass = raw_gate[status_bool(raw_gate["pass_gate"])].copy()
    raw_pass["raw_column"] = raw_pass.apply(
        lambda row: RAW_SPEC_BY_SCORE.get(str(row.get("metric", ""))).column
        if str(row.get("metric", "")) in RAW_SPEC_BY_SCORE
        else row.get("raw_column", ""),
        axis=1,
    )
    raw_pass["family"] = raw_pass.apply(
        lambda row: RAW_SPEC_BY_SCORE.get(str(row.get("metric", ""))).family
        if str(row.get("metric", "")) in RAW_SPEC_BY_SCORE
        else row.get("raw_family", row.get("family", "")),
        axis=1,
    )
    raw_pass["bucket"] = raw_pass.apply(raw_bucket, axis=1)
    raw_pass = raw_pass[raw_pass["bucket"].isin(BUCKET_LIMITS)].copy()
    for _, row in raw_pass.iterrows():
        bucket = str(row["bucket"])
        rows.append(
            {
                "metric": row["metric"],
                "label": row.get("label", row["metric"]),
                "bucket": bucket,
                "source_type": "raw",
                "raw_column": row.get("raw_column", ""),
                "family": row.get("family", row.get("raw_family", "")),
                "transform": "raw_level_or_change",
                "lag_observations": "",
                "robust_score": float(row.get("robust_score", np.nan)),
                "ratio_cagr": float(row.get("ratio_cagr", np.nan)),
                "top_worst_ratio_return": float(row.get("top_worst_ratio_return", np.nan)),
                "coverage": float(row.get("coverage", np.nan)),
                "economic_role": economic_role(bucket),
            }
        )

    rel_pass = rel_gate[status_bool(rel_gate["pass_gate"])].copy()
    rel_pass["bucket"] = rel_pass.apply(relative_bucket, axis=1)
    rel_pass = rel_pass[rel_pass["bucket"].isin(BUCKET_LIMITS)].copy()
    for _, row in rel_pass.iterrows():
        bucket = str(row["bucket"])
        rows.append(
            {
                "metric": row["metric"],
                "label": f"{row.get('raw_column', row['metric'])} {row.get('transform', '')} lag{row.get('lag_observations', '')}",
                "bucket": bucket,
                "source_type": "relative",
                "raw_column": row.get("raw_column", ""),
                "family": row.get("base_family", ""),
                "transform": row.get("transform", ""),
                "lag_observations": str(row.get("lag_observations", "")),
                "robust_score": float(row.get("robust_score", np.nan)),
                "ratio_cagr": float(row.get("ratio_cagr", np.nan)),
                "top_worst_ratio_return": float(row.get("top_worst_ratio_return", np.nan)),
                "coverage": float(row.get("coverage", np.nan)),
                "economic_role": economic_role(bucket),
            }
        )

    legs = pd.DataFrame(rows)
    selected = []
    for bucket in BUCKET_ORDER:
        group = legs[legs["bucket"].eq(bucket)].copy()
        if group.empty:
            continue
        group = group.sort_values(["robust_score", "ratio_cagr", "coverage"], ascending=[False, False, False])
        selected.append(group.head(BUCKET_LIMITS[bucket]))
    out = pd.concat(selected, ignore_index=True) if selected else pd.DataFrame()
    return out.sort_values(["bucket", "robust_score"], ascending=[True, False]).reset_index(drop=True)


def full_column() -> str:
    return "eu_small_syn_full_bucket_equal"


def load_research_inputs(raw_dir: Path, relative_dir: Path, legs: pd.DataFrame) -> pd.DataFrame:
    id_cols = [base.DATE_COL, base.ISIN_COL, base.SEDOL_COL, "Name", base.SECTOR_COL, base.MKT_CAP_COL, base.WEIGHT_COL]
    raw_metrics = legs[legs["source_type"].eq("raw")]["metric"].tolist()
    rel_metrics = legs[legs["source_type"].eq("relative")]["metric"].tolist()
    raw_screen_path = raw_dir / "eu_small_validated_gate_screen.parquet"
    rel_screen_path = relative_dir / "eu_small_relative_variable_screen.parquet"
    raw_cols = list(dict.fromkeys(id_cols + raw_metrics))
    rel_cols = list(dict.fromkeys([base.DATE_COL, base.ISIN_COL] + rel_metrics))
    raw_screen = pd.read_parquet(raw_screen_path, columns=[col for col in raw_cols if col in pq.ParquetFile(raw_screen_path).schema_arrow.names])
    rel_screen = pd.read_parquet(rel_screen_path, columns=[col for col in rel_cols if col in pq.ParquetFile(rel_screen_path).schema_arrow.names])
    raw_screen[base.DATE_COL] = pd.to_datetime(raw_screen[base.DATE_COL], errors="coerce")
    rel_screen[base.DATE_COL] = pd.to_datetime(rel_screen[base.DATE_COL], errors="coerce")
    screen = raw_screen.merge(rel_screen, on=[base.DATE_COL, base.ISIN_COL], how="left", validate="one_to_one")
    return screen.sort_values([base.DATE_COL, base.ISIN_COL]).reset_index(drop=True)


def add_candidates(screen: pd.DataFrame, legs: pd.DataFrame) -> tuple[pd.DataFrame, list[base.ModelSpec], pd.DataFrame]:
    leg_meta = legs.set_index("metric").to_dict(orient="index")
    screen, candidate_map = build_synergy_candidate_matrix(
        screen,
        legs[["metric", "bucket"]],
        bucket_order=BUCKET_ORDER,
        prefix="eu_small_syn",
        weighted_scores=lambda frame, components, min_count: base.weighted_scores(
            frame,
            dict(components),
            min_count=min_count,
        ),
        average_scores=lambda frame, columns, min_count: base.average_scores(
            frame,
            list(columns),
            min_count=min_count,
        ),
        subset_sizes=(2, 3),
    )
    specs: list[base.ModelSpec] = []
    for index, row in candidate_map.iterrows():
        candidate_type = str(row["candidate_type"])
        components = dict(row["component_weights"])
        buckets = [item for item in str(row["buckets"]).split("|") if item]
        if candidate_type == "pair":
            label = " + ".join(
                str(leg_meta[item]["label"]) for item in components
            )
            family = "pair_synergy"
            note = " + ".join(buckets)
        elif candidate_type == "bucket_component":
            label = buckets[0]
            family = candidate_type
            note = economic_role(label)
        elif candidate_type == "family_subset":
            label = " + ".join(buckets)
            family = candidate_type
            note = f"{len(buckets)}-bucket subset"
        elif candidate_type == "full_model":
            label = "all selected buckets equal-weight"
            family = candidate_type
            note = "full selected synergy model"
        else:
            left_out = str(row.get("left_out_bucket", ""))
            label = f"full model without {left_out}"
            family = "leave_one_out"
            note = f"leave one bucket out: {left_out}"
        candidate_map.at[index, "label"] = label
        specs.append(
            base.ModelSpec(
                str(row["metric"]),
                label,
                family,
                components,
                note,
            )
        )
    return screen, specs, candidate_map


def build_or_load_screen(
    raw_dir: Path,
    relative_dir: Path,
    returns: pd.DataFrame,
    output_dir: Path,
    force: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[base.ModelSpec], pd.DataFrame, pd.DataFrame]:
    screen_path = output_dir / "eu_small_relative_synergy_screen.parquet"
    specs_path = output_dir / "metric_definitions.json"
    legs_path = output_dir / "selected_legs.csv"
    map_path = output_dir / "candidate_map.csv"
    raw_gate = pd.read_csv(raw_dir / "raw_validation_gate.csv")
    rel_gate = pd.read_csv(relative_dir / "relative_validation_gate.csv")
    legs = select_legs(raw_gate, rel_gate)

    if screen_path.exists() and specs_path.exists() and legs_path.exists() and map_path.exists() and not force:
        screen = pd.read_parquet(screen_path)
        specs = [base.ModelSpec(**item) for item in json.loads(specs_path.read_text(encoding="utf-8"))]
        candidate_map = pd.read_csv(map_path)
        checks = base.construction_checks(screen, returns, pq.ParquetFile(base.DEFAULT_SCREEN).metadata.num_rows)
        diag = base.metric_diagnostics(screen, specs, [])
        return screen, checks, diag, specs, pd.read_csv(legs_path), candidate_map

    screen = load_research_inputs(raw_dir, relative_dir, legs)
    screen, specs, candidate_map = add_candidates(screen, legs)
    checks = base.construction_checks(screen, returns, pq.ParquetFile(base.DEFAULT_SCREEN).metadata.num_rows)
    checks = pd.concat(
        [
            checks,
            pd.DataFrame(
                [
                    {"check": "selected_leg_count", "value": len(legs)},
                    {"check": "candidate_metric_count", "value": len(specs)},
                    {
                        "check": "pair_candidate_count",
                        "value": int(candidate_map.get("candidate_type", pd.Series(dtype=str)).eq("pair").sum()),
                    },
                    {
                        "check": "subset_candidate_count",
                        "value": int(candidate_map.get("candidate_type", pd.Series(dtype=str)).eq("family_subset").sum()),
                    },
                    {
                        "check": "leave_one_out_count",
                        "value": int(candidate_map.get("candidate_type", pd.Series(dtype=str)).eq("leave_one_out").sum()),
                    },
                    {"check": "candidate_rule", "value": "cross-bucket pairs; 2/3-bucket subsets; full bucket equal-weight; leave-one-bucket-out"},
                ]
            ),
        ],
        ignore_index=True,
    )
    diag = base.metric_diagnostics(screen, specs, [])
    screen.to_parquet(screen_path, index=False)
    specs_path.write_text(json.dumps([spec.__dict__ for spec in specs], ensure_ascii=False, indent=2), encoding="utf-8")
    legs.to_csv(legs_path, index=False)
    candidate_map.to_csv(map_path, index=False)
    checks.to_csv(output_dir / "data_construction_checks.csv", index=False)
    diag.to_csv(output_dir / "metric_diagnostics.csv", index=False)
    return screen, checks, diag, specs, legs, candidate_map


def read_existing(paths: list[Path]) -> pd.DataFrame:
    return read_official_results(paths)


def dedupe_results(results: pd.DataFrame) -> pd.DataFrame:
    return dedupe_official_results(results)


def incomplete_metrics(metrics: list[str], completed: pd.DataFrame) -> list[str]:
    return incomplete_official_metrics(metrics, completed)


def shard_metrics(metrics: list[str], workers: int, shard_size: int = 0) -> list[list[str]]:
    return shard_metric_names(metrics, workers, shard_size)


def worker_run(payload: dict[str, object]) -> dict[str, object]:
    output_dir = Path(str(payload["output_dir"]))
    screen_path = Path(str(payload["screen_path"]))
    returns_path = Path(str(payload["returns_path"]))
    metrics = list(payload["metrics"])
    shard_id = int(payload["shard_id"])
    wave = str(payload["wave"])
    shard_dir = output_dir / "parallel_shards" / wave / f"shard_{shard_id:02d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_results = shard_dir / "official_run_results.csv"
    existing_paths = [
        Path(str(payload["main_results_path"])),
        *sorted((output_dir / "parallel_shards").rglob("official_run_results.csv")),
        shard_results,
    ]
    existing = read_existing(existing_paths)
    if not existing.empty:
        existing = existing[existing["metric"].isin(metrics)].copy()
    screen = pd.read_parquet(screen_path)
    returns = base.load_tabular_file(returns_path)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index()
    wave_slug = base.slugify(wave)[-12:] or "manual"
    run_root_name = f"ad_hoc/eusy{wave_slug}_s{shard_id:02d}"
    results = gate_runner.run_official_backtests_incremental(
        screen=screen,
        returns=returns,
        screen_path=screen_path,
        returns_path=returns_path,
        run_root_name=run_root_name,
        metrics=metrics,
        max_runs=payload.get("max_runs"),
        results_path=shard_results,
        existing_results=existing,
    )
    results = dedupe_results(results)
    results.to_csv(shard_results, index=False)
    return {
        "shard_id": shard_id,
        "metrics": len(metrics),
        "rows": len(results),
        "success": int(results["status"].eq("success").sum()) if not results.empty else 0,
        "path": str(shard_results),
    }


def summarize_synergy(
    summary: pd.DataFrame,
    selected_legs: pd.DataFrame,
    candidate_map: pd.DataFrame,
    output_dir: Path,
    raw_dir: Path,
    relative_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw_summary = pd.concat(
        [
            pd.read_csv(raw_dir / "performance_summary.csv"),
            pd.read_csv(relative_dir / "performance_summary.csv"),
        ],
        ignore_index=True,
    )
    leg_top = raw_summary[
        raw_summary["metric"].isin(selected_legs["metric"]) & raw_summary["side"].eq("Top") & raw_summary["status"].eq("success")
    ].drop_duplicates("metric", keep="last")
    leg_score = leg_top.set_index("metric").to_dict(orient="index")
    selected_map = selected_legs.set_index("metric").to_dict(orient="index")
    top = summary[summary["side"].eq("Top") & summary["status"].eq("success")].drop_duplicates("metric", keep="last")
    top_map = top.set_index("metric").to_dict(orient="index")
    rows_pair = []
    rows_subset = []
    for _, meta in candidate_map.iterrows():
        metric = str(meta["metric"])
        if metric not in top_map:
            continue
        row = top_map[metric]
        components = [item for item in str(meta.get("components", "")).split("|") if item]
        component_scores = []
        component_buckets = []
        for component in components:
            if component in leg_score:
                component_scores.append(leg_score[component])
                component_buckets.append(str(selected_map.get(component, {}).get("bucket", "")))
            elif component in top_map:
                component_scores.append(top_map[component])
                component_buckets.append(component)
        max_leg_robust = max([float(item.get("robust_score", np.nan)) for item in component_scores], default=np.nan)
        max_leg_ratio = max([float(item.get("ratio_cagr", np.nan)) for item in component_scores], default=np.nan)
        max_leg_tw = max([float(item.get("top_worst_ratio_return", np.nan)) for item in component_scores], default=np.nan)
        robust = float(row.get("robust_score", np.nan))
        ratio = float(row.get("ratio_cagr", np.nan))
        tw = float(row.get("top_worst_ratio_return", np.nan))
        synergy_score = robust - max_leg_robust if np.isfinite(max_leg_robust) else np.nan
        if np.isfinite(synergy_score) and synergy_score > 0.25 and ratio > 0 and tw > 0 and tw >= max_leg_tw:
            classification = "synergistic"
        elif robust > 0 and ratio > 0 and tw > 0:
            classification = "additive"
        elif robust > 0:
            classification = "redundant"
        else:
            classification = "harmful"
        out = {
            "metric": metric,
            "label": meta.get("label", ""),
            "candidate_type": meta.get("candidate_type", ""),
            "buckets": meta.get("buckets", ""),
            "components": meta.get("components", ""),
            "component_count": meta.get("component_count", np.nan),
            "coverage": row.get("coverage", np.nan),
            "ratio_cagr": ratio,
            "top_worst_ratio_return": tw,
            "ratio_max_drawdown": row.get("ratio_max_drawdown", np.nan),
            "tracking_error": row.get("tracking_error", np.nan),
            "avg_turnover": row.get("avg_turnover", np.nan),
            "robust_score": robust,
            "max_component_robust": max_leg_robust,
            "max_component_ratio_cagr": max_leg_ratio,
            "max_component_top_worst": max_leg_tw,
            "synergy_score": synergy_score,
            "classification": classification,
        }
        if meta.get("candidate_type") == "pair":
            rows_pair.append(out)
        elif meta.get("candidate_type") in {"family_subset", "full_model"}:
            rows_subset.append(out)

    pair = pd.DataFrame(rows_pair)
    if not pair.empty:
        pair = pair.sort_values(["classification", "synergy_score", "robust_score"], ascending=[True, False, False])
    subset = pd.DataFrame(rows_subset)
    if not subset.empty:
        subset = subset.sort_values(["classification", "synergy_score", "robust_score"], ascending=[True, False, False])
    full_metric = full_column()
    loo_rows = []
    full_row = top_map.get(full_metric, {})
    full_robust = float(full_row.get("robust_score", np.nan))
    full_ratio = float(full_row.get("ratio_cagr", np.nan))
    for _, meta in candidate_map[candidate_map["candidate_type"].eq("leave_one_out")].iterrows():
        metric = str(meta["metric"])
        row = top_map.get(metric, {})
        without_robust = float(row.get("robust_score", np.nan))
        without_ratio = float(row.get("ratio_cagr", np.nan))
        left_out = str(meta.get("left_out_bucket", ""))
        contribution = full_robust - without_robust if np.isfinite(full_robust) and np.isfinite(without_robust) else np.nan
        loo_rows.append(
            {
                "metric": metric,
                "left_out_bucket": left_out,
                "full_model_metric": full_metric,
                "full_robust_score": full_robust,
                "without_robust_score": without_robust,
                "loo_contribution": contribution,
                "full_ratio_cagr": full_ratio,
                "without_ratio_cagr": without_ratio,
                "ratio_contribution": full_ratio - without_ratio if np.isfinite(full_ratio) and np.isfinite(without_ratio) else np.nan,
                "classification": "positive_contributor" if np.isfinite(contribution) and contribution > 0 else "weak_or_negative",
            }
        )
    loo = pd.DataFrame(loo_rows)
    if not loo.empty:
        loo = loo.sort_values("loo_contribution", ascending=False)
    claim_frames = []
    if not pair.empty and "classification" in pair.columns:
        claim_frames.append(pair[pair["classification"].eq("synergistic")].head(50))
    if not subset.empty and "classification" in subset.columns:
        claim_frames.append(subset[subset["classification"].eq("synergistic")].head(50))
    claims = pd.concat(claim_frames, ignore_index=True) if claim_frames else pd.DataFrame()
    pair.to_csv(output_dir / "pair_synergy_results.csv", index=False)
    subset.to_csv(output_dir / "family_subset_results.csv", index=False)
    loo.to_csv(output_dir / "leave_one_out_results.csv", index=False)
    claims.to_csv(output_dir / "synergy_claims.csv", index=False)
    return pair, subset, loo, claims


def frame_to_markdown(frame: pd.DataFrame, max_rows: int = 40) -> str:
    return base.frame_to_markdown(frame.head(max_rows))


def write_report(
    output_dir: Path,
    checks: pd.DataFrame,
    selected_legs: pd.DataFrame,
    candidate_map: pd.DataFrame,
    run_results: pd.DataFrame,
    summary: pd.DataFrame,
    pair: pd.DataFrame,
    subset: pd.DataFrame,
    loo: pd.DataFrame,
    claims: pd.DataFrame,
    plot_paths: list[str],
) -> Path:
    lines = [
        "# MSCI Europe Small raw + relative 变量协同研究",
        "",
        f"- 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 证据口径: official exact Top/Worst backtest",
        "- 研究范围: 已通过 raw gate 与 relative gate 的 revision、PMOM、growth、quality improvement、earnings-yield improvement、deleveraging、value improvement、risk decline。",
        f"- 研究目录: `{output_dir}`",
        "",
        "## 数据构造检查",
        "",
        frame_to_markdown(checks, 80),
        "",
        "## 入选单变量腿",
        "",
        frame_to_markdown(selected_legs.sort_values(["bucket", "robust_score"], ascending=[True, False]), 80)
        if not selected_legs.empty
        else "暂无通过 gate 且属于本轮 bucket 的单变量腿。",
        "",
        "## 候选矩阵",
        "",
        frame_to_markdown(candidate_map.groupby("candidate_type").size().reset_index(name="count"), 20)
        if not candidate_map.empty and "candidate_type" in candidate_map.columns
        else "暂无候选矩阵。",
        "",
        "## 官方回测状态",
        "",
        frame_to_markdown(run_results.groupby("status").size().reset_index(name="count"), 20) if not run_results.empty else "暂无。",
        "",
        "## Pair 协同证据",
        "",
        frame_to_markdown(pair.sort_values(["classification", "synergy_score"], ascending=[True, False]), 80) if not pair.empty else "暂无 pair 结果。",
        "",
        "## Family Subset 证据",
        "",
        frame_to_markdown(subset.sort_values(["classification", "synergy_score"], ascending=[True, False]), 80) if not subset.empty else "暂无 subset 结果。",
        "",
        "## Leave-One-Out",
        "",
        frame_to_markdown(loo, 40) if not loo.empty else "暂无 LOO 结果。",
        "",
        "## 可声明 Synergy",
        "",
    ]
    if claims.empty:
        lines.append("当前规则下没有足够证据可声明 `synergistic`，只能讨论 additive/redundant/harmful。")
    else:
        lines.append(frame_to_markdown(claims, 60))
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- 本报告只对已通过单变量 gate 且纳入候选 bucket 的变量做协同判断。",
            "- 没有进入本轮候选 bucket 的变量不应被解释为无效，只是没有纳入这次有先验矩阵。",
            "- synergy 只按官方 evidence 表分类；经济故事本身只作为假设来源。",
            "",
            "## Plotly 输出",
            "",
        ]
    )
    lines.extend([f"- `{path}`" for path in plot_paths] or ["- 未生成 Plotly 输出。"])
    path = output_dir / "eu_small_relative_synergy_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MSCI Europe Small raw + relative synergy official research.")
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--relative-dir", default=str(RELATIVE_DIR))
    parser.add_argument("--returns", default=str(DEFAULT_RETURNS))
    parser.add_argument("--output-dir", default=str(AD_HOC_ROOT / OUTPUT_NAME))
    parser.add_argument("--metrics", default="all")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--force-rebuild", action="store_true")
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--shard-size", type=int, default=0)
    parser.add_argument("--fresh-process-per-batch", action="store_true")
    parser.add_argument("--run-only", action="store_true", help="Only run/write shard official results; skip summary/report generation.")
    parser.add_argument("--direct-worker", action="store_true", help="Run one-worker shards in the current process instead of ProcessPoolExecutor.")
    parser.add_argument("--wave", default="")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    raw_dir = Path(args.raw_dir)
    relative_dir = Path(args.relative_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    returns_path = Path(args.returns)
    returns = base.load_tabular_file(returns_path)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index()
    screen, checks, diag, specs, selected_legs, candidate_map = build_or_load_screen(
        raw_dir,
        relative_dir,
        returns,
        output_dir,
        force=args.force_rebuild,
    )
    screen_path = output_dir / "eu_small_relative_synergy_screen.parquet"
    all_metrics = [spec.column for spec in specs if spec.family != "bucket_component"]
    metrics = parse_csv_arg(args.metrics, all_metrics)
    unknown = sorted(set(metrics).difference(all_metrics))
    if unknown:
        raise ValueError(f"Unknown metrics: {unknown}")

    run_results = pd.DataFrame()
    summary = pd.DataFrame()
    pair = pd.DataFrame()
    subset = pd.DataFrame()
    loo = pd.DataFrame()
    claims = pd.DataFrame()
    plot_paths: list[str] = []
    if not args.build_only:
        main_results = output_dir / "official_run_results.csv"
        shard_paths = sorted((output_dir / "parallel_shards").rglob("official_run_results.csv"))
        completed = read_existing([main_results, *shard_paths])
        remaining = incomplete_metrics(metrics, completed)
        if args.max_runs is not None:
            remaining = remaining[: max(1, (int(args.max_runs) + 1) // 2)]
        workers = max(args.workers, 1)
        shards = shard_metrics(remaining, workers, max(args.shard_size, 0))
        wave = new_wave_id(args.wave)
        print(
            json.dumps(
                {
                    "event": "parallel_start",
                    "workers": workers,
                    "shard_size": max(args.shard_size, 0),
                    "fresh_process_per_batch": bool(args.fresh_process_per_batch),
                    "metric_total": len(metrics),
                    "metric_remaining": len(remaining),
                    "existing_rows": len(completed),
                    "shards": [len(shard) for shard in shards],
                    "resume": bool(args.resume) or True,
                    "max_runs": args.max_runs,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if shards:
            payloads = [
                {
                    "output_dir": str(output_dir),
                    "screen_path": str(screen_path),
                    "returns_path": str(returns_path),
                    "main_results_path": str(main_results),
                    "wave": wave,
                    "shard_id": idx,
                    "metrics": shard,
                    "max_runs": args.max_runs,
                }
                for idx, shard in enumerate(shards)
            ]
            if args.direct_worker and workers == 1:
                for batch_id, payload in enumerate(payloads):
                    try:
                        print(json.dumps({"event": "shard_done", "batch_id": batch_id, **worker_run(payload)}, ensure_ascii=False), flush=True)
                    except Exception as exc:
                        print(
                            json.dumps(
                                {
                                    "event": "shard_failed",
                                    "batch_id": batch_id,
                                    "shard_id": payload.get("shard_id"),
                                    "metrics": len(payload.get("metrics", [])),
                                    "error": f"{type(exc).__name__}: {exc}",
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
            else:
                batches = [payloads] if not args.fresh_process_per_batch else [
                    payloads[idx : idx + workers] for idx in range(0, len(payloads), workers)
                ]
                for batch_id, batch in enumerate(batches):
                    with ProcessPoolExecutor(max_workers=min(workers, len(batch))) as executor:
                        futures = {executor.submit(worker_run, payload): payload for payload in batch}
                        for future in as_completed(futures):
                            payload = futures[future]
                            try:
                                print(json.dumps({"event": "shard_done", "batch_id": batch_id, **future.result()}, ensure_ascii=False), flush=True)
                            except Exception as exc:
                                print(
                                    json.dumps(
                                        {
                                            "event": "shard_failed",
                                            "batch_id": batch_id,
                                            "shard_id": payload.get("shard_id"),
                                            "metrics": len(payload.get("metrics", [])),
                                            "error": f"{type(exc).__name__}: {exc}",
                                        },
                                        ensure_ascii=False,
                                    ),
                                    flush=True,
                                )
        shard_paths = sorted((output_dir / "parallel_shards").rglob("official_run_results.csv"))
        run_results = read_existing([main_results, *shard_paths])
        if args.run_only:
            status_payload = {
                "event": "run_only_complete",
                "output_dir": str(output_dir),
                "benchmark": base.BENCHMARK,
                "candidate_metric_count": int(len(metrics)),
                "expected_run_count": int(2 * len(metrics)),
                "run_count": int(len(run_results)),
                "success_count": int(run_results["status"].eq("success").sum()) if not run_results.empty else 0,
                "skipped_count": int(run_results["status"].eq("skipped").sum()) if not run_results.empty else 0,
                "all_known_run_count": int(len(read_existing([main_results, *shard_paths]))),
                "wave": wave,
            }
            (output_dir / "run_only_status.json").write_text(json.dumps(status_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(status_payload, ensure_ascii=False), flush=True)
            return 0
        run_results.to_csv(main_results, index=False)
        summary = base.summarize_runs(run_results, diag)
        summary.to_csv(output_dir / "performance_summary.csv", index=False)
        pair, subset, loo, claims = summarize_synergy(summary, selected_legs, candidate_map, output_dir, raw_dir, relative_dir)
        plot_paths = base.write_plotly_outputs(summary, run_results, output_dir)
    report = write_report(output_dir, checks, selected_legs, candidate_map, run_results, summary, pair, subset, loo, claims, plot_paths)
    manifest = {
        "output_dir": str(output_dir),
        "research_screen": str(screen_path),
        "report": str(report),
        "benchmark": base.BENCHMARK,
        "selected_leg_count": int(len(selected_legs)),
        "candidate_metric_count": int(len(metrics)),
        "expected_run_count": int(2 * len(metrics)),
        "run_count": int(len(run_results)),
        "success_count": int(run_results["status"].eq("success").sum()) if not run_results.empty else 0,
        "skipped_count": int(run_results["status"].eq("skipped").sum()) if not run_results.empty else 0,
        "synergy_claim_count": int(len(claims)) if not claims.empty else 0,
        "plot_paths": plot_paths,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"event": "complete", **manifest}, ensure_ascii=False), flush=True)
    return 0 if run_results.empty or run_results["status"].isin(["success", "skipped"]).any() else 1


if __name__ == "__main__":
    raise SystemExit(main())

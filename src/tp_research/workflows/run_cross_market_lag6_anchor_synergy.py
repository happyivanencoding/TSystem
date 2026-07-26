"""Test every passed lag-6 relative variable against passed anchor subsets.

The protocol is deliberately staged.  Revision, price momentum, and growth
anchors first receive independent official Top/Worst evidence in the target
market.  Only anchors passing the common gate may enter the combination
matrix.  For each passed lag-6 variable, the matrix exhausts every non-empty
subset of passed anchors and writes direct leave-one-out comparisons.
"""

from __future__ import annotations
from tp_research.runtime import recorded_workflow

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import itertools
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from tp_research.paths import BACKTEST_ROOT, TP_ROOT

from tp_research.executor import (  # noqa: E402
    GateThresholds,
    dedupe_official_results,
    evaluate_official_top_worst_gate,
    incomplete_official_metrics,
    new_wave_id,
    read_official_results,
    shard_metric_names,
    shard_result_path,
)
from tp_research.workflows import run_cross_market_lag6_relative_research as lag6


DATE_COL = lag6.DATE_COL
ISIN_COL = lag6.ISIN_COL
SEDOL_COL = lag6.SEDOL_COL
SECTOR_COL = lag6.SECTOR_COL
MIN_COVERAGE = lag6.MIN_COVERAGE
AD_HOC_ROOT = lag6.AD_HOC_ROOT


@dataclass(frozen=True)
class AnchorSpec:
    key: str
    raw_column: str
    label: str
    economic_role: str


ANCHORS = (
    AnchorSpec(
        key="revision",
        raw_column="EPS Revision Ratio",
        label="EPS Revision Ratio",
        economic_role="analyst earnings-estimate breadth and direction",
    ),
    AnchorSpec(
        key="pmom",
        raw_column="PMOM 12M1M",
        label="PMOM 12M1M",
        economic_role="medium-term price persistence excluding the latest month",
    ),
    AnchorSpec(
        key="growth",
        raw_column="EPS Growth FY1",
        label="EPS Growth FY1",
        economic_role="forward earnings growth",
    ),
)


@dataclass(frozen=True)
class StudyProfile:
    key: str
    output_name: str

    @property
    def market(self) -> lag6.MarketProfile:
        return lag6.PROFILES[self.key]

    @property
    def lag6_run(self) -> Path:
        return AD_HOC_ROOT / self.market.output_name


STUDIES = {
    "nasdaq": StudyProfile(
        key="nasdaq",
        output_name="nasdaq_lag6_anchor_synergy_20260725",
    ),
    "sp500": StudyProfile(
        key="sp500",
        output_name="sp500_lag6_anchor_synergy_20260725",
    ),
    "eu-small": StudyProfile(
        key="eu-small",
        output_name="eu_small_lag6_anchor_synergy_20260725",
    ),
}


def anchor_metric(profile: lag6.MarketProfile, anchor: AnchorSpec) -> str:
    return f"{profile.output_prefix}_anchor_{anchor.key}_score"


def combo_metric(profile: lag6.MarketProfile, components: Sequence[str]) -> str:
    digest = hashlib.sha1("|".join(sorted(components)).encode()).hexdigest()[:12]
    return f"{profile.output_prefix}_lag6arch_{digest}"


def subsets(values: Sequence[AnchorSpec], *, minimum: int = 1) -> Iterable[tuple[AnchorSpec, ...]]:
    for size in range(minimum, len(values) + 1):
        yield from itertools.combinations(values, size)


def json_dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def build_anchor_screen(
    study: StudyProfile,
    canonical_path: Path,
    output_dir: Path,
    *,
    force: bool,
) -> tuple[Path, pd.DataFrame]:
    profile = study.market
    output_path = output_dir / f"{profile.output_prefix}_lag6_anchor_screen.parquet"
    registry_path = output_dir / "anchor_registry.csv"
    if output_path.exists() and registry_path.exists() and not force:
        return output_path, pd.read_csv(registry_path)

    source_gate = pd.read_csv(study.lag6_run / "relative_validation_gate.csv")
    passed = source_gate[source_gate["pass_gate"].fillna(False)].copy()
    lag_metrics = passed["metric"].astype(str).tolist()
    technical = [
        DATE_COL,
        ISIN_COL,
        SEDOL_COL,
        "Name",
        SECTOR_COL,
        lag6.MKT_CAP_COL,
        profile.weight_col,
    ]
    lag_screen = pd.read_parquet(
        study.lag6_run / f"{profile.output_prefix}_lag6_screen.parquet",
        columns=[*technical, *lag_metrics],
    )
    lag_screen[DATE_COL] = pd.to_datetime(lag_screen[DATE_COL], errors="coerce")

    available = set(pq.ParquetFile(canonical_path).schema_arrow.names)
    missing = sorted(
        {DATE_COL, ISIN_COL, *[item.raw_column for item in ANCHORS]}.difference(
            available
        )
    )
    if missing:
        raise KeyError(f"canonical screen missing anchor fields: {missing}")
    raw = pd.read_parquet(
        canonical_path,
        columns=[DATE_COL, ISIN_COL, *[item.raw_column for item in ANCHORS]],
    )
    if ISIN_COL not in raw.columns and raw.index.name == ISIN_COL:
        raw = raw.reset_index()
    raw[DATE_COL] = pd.to_datetime(raw[DATE_COL], errors="coerce")
    raw = raw.drop_duplicates([DATE_COL, ISIN_COL], keep="last")
    screen = lag_screen.merge(
        raw,
        on=[DATE_COL, ISIN_COL],
        how="left",
        validate="one_to_one",
    )

    rows: list[dict[str, object]] = []
    for anchor in ANCHORS:
        metric = anchor_metric(profile, anchor)
        screen[metric] = lag6.score_level(screen, anchor.raw_column, 1.0)
        rows.append(
            {
                "metric": metric,
                "label": anchor.label,
                "candidate_type": "anchor_single",
                "bucket": anchor.key,
                "components": metric,
                "component_count": 1,
                "raw_column": anchor.raw_column,
                "family": anchor.key,
                "source": "canonical_screen",
                "economic_role": anchor.economic_role,
                "trial_role": "anchor_raw_control",
            }
        )
    screen = screen.drop(columns=[item.raw_column for item in ANCHORS])
    registry = pd.DataFrame(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    screen.to_parquet(output_path, index=False)
    registry.to_csv(registry_path, index=False)
    return output_path, registry


def collect_paths(output_dir: Path) -> list[Path]:
    return [
        output_dir / "official_run_results.csv",
        output_dir / "admission_skips.csv",
        *output_dir.glob("parallel_shards/*/shard_*/official_run_results.csv"),
    ]


def write_skips(
    profile: lag6.MarketProfile,
    output_dir: Path,
    metrics: Sequence[str],
    start_dates: Mapping[str, str],
) -> None:
    rows: list[dict[str, object]] = []
    for metric in metrics:
        if str(start_dates.get(metric, "")):
            continue
        for side in ("Top", "Worst"):
            rows.append(
                {
                    "benchmark": profile.benchmark,
                    "metric": metric,
                    "side": side,
                    "top": side == "Top",
                    "start_date": "",
                    "status": "skipped",
                    "message": (
                        "no eligible month satisfies minimum coverage and "
                        "disjoint Top/Worst construction"
                    ),
                    "run_dir": "",
                    "sec_list": "",
                    "weights": "",
                    "exclusions": "",
                    "perf_ptf": "",
                    "perf_bench": "",
                }
            )
    path = output_dir / "admission_skips.csv"
    if rows:
        pd.DataFrame(rows).to_csv(path, index=False)
    elif path.exists():
        path.unlink()


def run_metrics(
    *,
    profile: lag6.MarketProfile,
    screen_path: Path,
    returns_path: Path,
    output_dir: Path,
    metrics: Sequence[str],
    start_dates: Mapping[str, str],
    workers: int,
    stage: str,
) -> list[dict[str, object]]:
    existing = read_official_results(collect_paths(output_dir))
    pending = incomplete_official_metrics(metrics, existing)
    pending = [metric for metric in pending if str(start_dates.get(metric, ""))]
    if not pending:
        return []
    wave = f"{new_wave_id()}_{stage}"
    shards = shard_metric_names(pending, min(workers, len(pending)))
    payloads = [
        {
            "profile": asdict(profile),
            "metrics": shard,
            "screen_path": str(screen_path),
            "returns_path": str(returns_path),
            "shard_path": str(shard_result_path(output_dir, wave, shard_id)),
            "output_dir": str(output_dir),
            "wave": wave,
            "shard_id": shard_id,
            "start_dates": {metric: start_dates[metric] for metric in shard},
        }
        for shard_id, shard in enumerate(shards)
    ]
    if len(payloads) == 1:
        return [lag6.worker_run(payloads[0])]
    records: list[dict[str, object]] = []
    with ProcessPoolExecutor(max_workers=len(payloads)) as executor:
        futures = [executor.submit(lag6.worker_run, payload) for payload in payloads]
        for future in as_completed(futures):
            records.append(future.result())
    return records


def gate_for(
    results: pd.DataFrame,
    diagnostics: pd.DataFrame,
    registry: pd.DataFrame,
    metrics: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected = results[results["metric"].astype(str).isin(metrics)].copy()
    summary = lag6.summarize_runs(selected, diagnostics)
    gate = evaluate_official_top_worst_gate(
        summary,
        diagnostics,
        thresholds=GateThresholds(
            min_coverage=MIN_COVERAGE,
            min_ratio_cagr=0.0,
            min_top_worst_ratio=0.0,
            min_robust_score=0.0,
        ),
        metadata=registry,
        metrics=metrics,
    )
    return summary, gate


def build_combination_matrix(
    study: StudyProfile,
    screen_path: Path,
    output_dir: Path,
    anchor_gate: pd.DataFrame,
    *,
    force: bool,
) -> tuple[Path, pd.DataFrame, list[AnchorSpec]]:
    profile = study.market
    registry_path = output_dir / "candidate_registry.csv"
    if registry_path.exists() and not force:
        registry = pd.read_csv(registry_path)
        passed_keys = registry.loc[
            registry["candidate_type"].eq("anchor_single"),
            "bucket",
        ].astype(str)
        passed_anchors = [item for item in ANCHORS if item.key in set(passed_keys)]
        return screen_path, registry, passed_anchors

    passed_anchor_metrics = set(
        anchor_gate.loc[anchor_gate["pass_gate"].fillna(False), "metric"].astype(str)
    )
    passed_anchors = [
        item
        for item in ANCHORS
        if anchor_metric(profile, item) in passed_anchor_metrics
    ]
    source_gate = pd.read_csv(study.lag6_run / "relative_validation_gate.csv")
    passed_lag = source_gate[source_gate["pass_gate"].fillna(False)].copy()
    lag_metrics = passed_lag["metric"].astype(str).tolist()
    anchor_metrics = [anchor_metric(profile, item) for item in ANCHORS]
    screen = pd.read_parquet(screen_path)
    rows = pd.read_csv(output_dir / "anchor_registry.csv").to_dict("records")
    component_labels = {
        anchor_metric(profile, item): item.label for item in ANCHORS
    }
    component_labels.update(
        passed_lag.set_index("metric")["label"].fillna(
            passed_lag["metric"]
        ).astype(str).to_dict()
    )

    set_to_metric: dict[frozenset[str], str] = {}
    for item in ANCHORS:
        metric = anchor_metric(profile, item)
        set_to_metric[frozenset([metric])] = metric
    for metric in lag_metrics:
        set_to_metric[frozenset([metric])] = metric

    def materialize(components: Sequence[str], candidate_type: str, architecture: str) -> str:
        key = frozenset(components)
        if key in set_to_metric:
            return set_to_metric[key]
        metric = combo_metric(profile, sorted(components))
        data = screen[list(components)].apply(pd.to_numeric, errors="coerce")
        screen[metric] = data.mean(axis=1).where(
            data.notna().sum(axis=1).eq(len(components))
        )
        buckets = [
            next(
                (
                    item.key
                    for item in passed_anchors
                    if anchor_metric(profile, item) == component
                ),
                "lag6_relative",
            )
            for component in components
        ]
        rows.append(
            {
                "metric": metric,
                "label": " + ".join(component_labels[item] for item in components),
                "candidate_type": candidate_type,
                "bucket": "|".join(buckets),
                "components": "|".join(components),
                "component_count": len(components),
                "raw_column": "",
                "family": "lag6_anchor_architecture",
                "source": "gate_passed_components",
                "economic_role": (
                    "joint confirmation across relative improvement, revision, "
                    "price persistence, and/or forward growth"
                ),
                "trial_role": "gate_after_synergy_test",
                "architecture_lag6_metric": architecture,
            }
        )
        set_to_metric[key] = metric
        return metric

    for anchor_subset in subsets(passed_anchors, minimum=2):
        components = [anchor_metric(profile, item) for item in anchor_subset]
        materialize(components, "anchor_subset_control", "anchor_only")
    for lag_metric in lag_metrics:
        for anchor_subset in subsets(passed_anchors):
            components = [
                lag_metric,
                *[anchor_metric(profile, item) for item in anchor_subset],
            ]
            kind = "pair" if len(components) == 2 else "family_subset"
            materialize(components, kind, lag_metric)

    registry = pd.DataFrame(rows).drop_duplicates("metric", keep="last")
    # Failed anchors retain single-variable evidence but are not matrix members.
    registry.loc[
        registry["metric"].isin(anchor_metrics)
        & ~registry["metric"].isin(passed_anchor_metrics),
        "trial_role",
    ] = "failed_anchor_control_not_admitted"
    screen.to_parquet(screen_path, index=False)
    registry.to_csv(registry_path, index=False)
    json_dump(
        output_dir / "metric_definitions.json",
        {
            "score_direction": "higher_is_better",
            "matrix_rule": (
                "one passed lag6 relative variant plus every non-empty subset "
                "of independently passed anchors"
            ),
            "same_raw_different_lags_mutually_exclusive": True,
            "passed_anchors": [asdict(item) for item in passed_anchors],
            "metrics": registry.to_dict("records"),
        },
    )
    return screen_path, registry, passed_anchors


def component_evidence(
    study: StudyProfile,
    anchor_gate: pd.DataFrame,
) -> pd.DataFrame:
    lag_gate = pd.read_csv(study.lag6_run / "relative_validation_gate.csv")
    lag_gate = lag_gate[lag_gate["pass_gate"].fillna(False)].copy()
    lag_gate["component_source"] = "lag6_relative_gate"
    anchor = anchor_gate[anchor_gate["pass_gate"].fillna(False)].copy()
    anchor["component_source"] = "anchor_raw_gate"
    common = [
        "metric",
        "label",
        "ratio_cagr",
        "top_worst_ratio_return",
        "robust_score",
        "ratio_max_drawdown",
        "tracking_error",
        "component_source",
    ]
    return pd.concat(
        [lag_gate.reindex(columns=common), anchor.reindex(columns=common)],
        ignore_index=True,
    ).drop_duplicates("metric", keep="last")


def build_evidence_tables(
    registry: pd.DataFrame,
    gate: pd.DataFrame,
    components: pd.DataFrame,
    passed_anchors: Sequence[AnchorSpec],
    profile: lag6.MarketProfile,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    component_map = components.set_index("metric").to_dict("index")
    gate_map = gate.set_index("metric").to_dict("index")
    all_map = {**component_map, **gate_map}
    set_to_metric: dict[frozenset[str], str] = {}
    for row in registry.itertuples(index=False):
        members = str(row.components).split("|")
        set_to_metric[frozenset(members)] = str(row.metric)
    for metric in components["metric"].astype(str):
        set_to_metric[frozenset([metric])] = metric

    comparison_rows: list[dict[str, object]] = []
    candidates = registry[
        registry["candidate_type"].isin(
            ["pair", "family_subset", "anchor_subset_control"]
        )
    ]
    for row in candidates.itertuples(index=False):
        members = str(row.components).split("|")
        candidate = gate_map.get(str(row.metric), {})
        member_rows = [all_map.get(member, {}) for member in members]
        member_robust = [
            float(item.get("robust_score", np.nan)) for item in member_rows
        ]
        member_ratio = [
            float(item.get("ratio_cagr", np.nan)) for item in member_rows
        ]
        member_tw = [
            float(item.get("top_worst_ratio_return", np.nan))
            for item in member_rows
        ]
        best_robust = np.nanmax(member_robust)
        best_ratio = np.nanmax(member_ratio)
        best_tw = np.nanmax(member_tw)
        robust = float(candidate.get("robust_score", np.nan))
        ratio = float(candidate.get("ratio_cagr", np.nan))
        top_worst = float(candidate.get("top_worst_ratio_return", np.nan))
        passed = bool(candidate.get("pass_gate", False))
        robust_uplift = robust - best_robust
        if (
            passed
            and robust_uplift >= 0.10
            and ratio >= best_ratio + 0.002
            and top_worst >= best_tw
        ):
            classification = "synergistic"
        elif passed and robust >= best_robust and ratio > 0:
            classification = "additive"
        elif not passed or robust < best_robust - 0.10:
            classification = "harmful"
        else:
            classification = "redundant"
        comparison_rows.append(
            {
                "metric": row.metric,
                "label": row.label,
                "candidate_type": row.candidate_type,
                "components": row.components,
                "component_count": row.component_count,
                "architecture_lag6_metric": getattr(
                    row, "architecture_lag6_metric", ""
                ),
                "coverage": candidate.get("coverage", np.nan),
                "ratio_cagr": ratio,
                "top_worst_ratio_return": top_worst,
                "robust_score": robust,
                "pass_gate": passed,
                "best_component_robust_score": best_robust,
                "best_component_ratio_cagr": best_ratio,
                "best_component_top_worst_ratio_return": best_tw,
                "robust_uplift_vs_best_component": robust_uplift,
                "ratio_cagr_uplift_vs_best_component": ratio - best_ratio,
                "top_worst_uplift_vs_best_component": top_worst - best_tw,
                "classification": classification,
            }
        )
    comparisons = pd.DataFrame(comparison_rows)

    passed_anchor_metrics = [
        anchor_metric(profile, item) for item in passed_anchors
    ]
    loo_rows: list[dict[str, object]] = []
    full_lookup: dict[str, str] = {}
    for lag_metric in components.loc[
        components["component_source"].eq("lag6_relative_gate"),
        "metric",
    ].astype(str):
        full_members = frozenset([lag_metric, *passed_anchor_metrics])
        full_metric = set_to_metric.get(full_members)
        if not full_metric or len(full_members) < 2:
            continue
        full_lookup[lag_metric] = full_metric
        full = all_map.get(full_metric, {})
        for left_out in sorted(full_members):
            reduced_members = frozenset(full_members.difference([left_out]))
            reduced_metric = set_to_metric.get(reduced_members)
            reduced = all_map.get(str(reduced_metric), {})
            robust_delta = float(full.get("robust_score", np.nan)) - float(
                reduced.get("robust_score", np.nan)
            )
            ratio_delta = float(full.get("ratio_cagr", np.nan)) - float(
                reduced.get("ratio_cagr", np.nan)
            )
            loo_rows.append(
                {
                    "architecture_lag6_metric": lag_metric,
                    "full_model_metric": full_metric,
                    "left_out_metric": left_out,
                    "reduced_model_metric": reduced_metric,
                    "full_pass_gate": bool(full.get("pass_gate", False)),
                    "reduced_pass_gate": bool(reduced.get("pass_gate", False)),
                    "full_robust_score": full.get("robust_score", np.nan),
                    "reduced_robust_score": reduced.get("robust_score", np.nan),
                    "robust_delta_full_minus_reduced": robust_delta,
                    "ratio_cagr_delta_full_minus_reduced": ratio_delta,
                    "positive_contribution": (
                        bool(full.get("pass_gate", False))
                        and robust_delta >= 0.05
                        and ratio_delta >= 0
                    ),
                }
            )
    loo = pd.DataFrame(loo_rows)

    claims: list[dict[str, object]] = []
    for lag_metric, full_metric in full_lookup.items():
        comparison = comparisons[comparisons["metric"].eq(full_metric)]
        folds = loo[loo["full_model_metric"].eq(full_metric)]
        if comparison.empty:
            continue
        row = comparison.iloc[0]
        all_positive = bool(len(folds) and folds["positive_contribution"].all())
        supported = row["classification"] == "synergistic" and all_positive
        claims.append(
            {
                "metric": full_metric,
                "architecture_lag6_metric": lag_metric,
                "label": row["label"],
                "pair_or_subset_classification": row["classification"],
                "leave_one_out_tests": len(folds),
                "all_leave_one_out_positive": all_positive,
                "synergy_supported": supported,
                "claim": (
                    "official pair/subset and leave-one-out support synergy"
                    if supported
                    else "no synergy claim; evidence is additive, redundant, harmful, or LOO-incomplete"
                ),
            }
        )
    claims_frame = pd.DataFrame(claims)
    pairs = comparisons[comparisons["candidate_type"].eq("pair")].copy()
    subsets_frame = comparisons[
        comparisons["candidate_type"].isin(
            ["family_subset", "anchor_subset_control"]
        )
    ].copy()
    return pairs, subsets_frame, loo, claims_frame


def write_report(
    study: StudyProfile,
    output_dir: Path,
    anchor_gate: pd.DataFrame,
    comparisons: pd.DataFrame,
    loo: pd.DataFrame,
    claims: pd.DataFrame,
) -> Path:
    profile = study.market
    anchor_table = anchor_gate[
        [
            "label",
            "coverage",
            "ratio_cagr",
            "top_worst_ratio_return",
            "robust_score",
            "pass_gate",
            "fail_reasons",
        ]
    ].to_markdown(index=False)
    top = comparisons.sort_values(
        "robust_uplift_vs_best_component",
        ascending=False,
    ).head(30)
    top_table = top[
        [
            "label",
            "ratio_cagr",
            "robust_score",
            "robust_uplift_vs_best_component",
            "classification",
        ]
    ].to_markdown(index=False)
    supported = (
        claims[claims["synergy_supported"]]
        if not claims.empty
        else pd.DataFrame()
    )
    lines = [
        f"# {profile.display_name} lag6 与 anchor 协同补充研究",
        "",
        "## Anchor raw gate",
        "",
        anchor_table,
        "",
        "## 矩阵定义",
        "",
        "对每个已通过独立 raw gate 的 lag6 relative variable，穷尽其与"
        "通过本市场 anchor gate 的所有非空 anchor 子集。组合要求所有 component"
        " 同时非缺失；同一 raw field 的不同 lag 不进入同一架构。",
        "",
        "## Pair / subset",
        "",
        top_table,
        "",
        "## Leave-one-out",
        "",
        f"- 完整架构逐变量 LOO 数：{len(loo)}",
        f"- 正贡献数：{int(loo['positive_contribution'].sum()) if not loo.empty else 0}",
        f"- 同时满足组合与全部 LOO 的 synergy claim：{len(supported)}",
        "",
        "## 解释边界",
        "",
        "分类比较的是同一市场官方 Top/Worst 证据和更强单腿。只有"
        "`synergy_claims.csv` 中 `synergy_supported=True` 的架构允许使用"
        "“协同”一词；其余即使经济故事合理，也只称 additive、redundant、"
        "harmful 或待验证。历史分时期结果仍需下一阶段 LORO 验证。",
    ]
    path = output_dir / f"{profile.output_prefix}_lag6_anchor_synergy_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=sorted(STUDIES), required=True)
    parser.add_argument("--screen", type=Path, default=lag6.DEFAULT_SCREEN)
    parser.add_argument("--returns", type=Path, default=lag6.DEFAULT_RETURNS)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force-build", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


@recorded_workflow
def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    study = STUDIES[args.market]
    profile = study.market
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else (AD_HOC_ROOT / study.output_name).resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    lag6.ensure_input_fingerprints(
        output_dir,
        screen_path=args.screen.resolve(),
        returns_path=args.returns.resolve(),
        registry_source=study.lag6_run / "relative_validation_gate.csv",
    )
    screen_path, anchor_registry = build_anchor_screen(
        study,
        args.screen.resolve(),
        output_dir,
        force=args.force_build,
    )

    anchor_metrics = anchor_registry["metric"].astype(str).tolist()
    _, anchor_diag = lag6.metric_diagnostics(screen_path, anchor_metrics)
    start_dates = (
        anchor_diag.set_index("metric")["first_date"].fillna("").astype(str).to_dict()
    )
    write_skips(profile, output_dir, anchor_metrics, start_dates)
    workers = max(1, int(args.workers))
    worker_results = run_metrics(
        profile=profile,
        screen_path=screen_path,
        returns_path=args.returns.resolve(),
        output_dir=output_dir,
        metrics=anchor_metrics,
        start_dates=start_dates,
        workers=workers,
        stage="anchors",
    )
    results = dedupe_official_results(read_official_results(collect_paths(output_dir)))
    anchor_summary, anchor_gate = gate_for(
        results,
        anchor_diag,
        anchor_registry,
        anchor_metrics,
    )
    anchor_gate.to_csv(output_dir / "anchor_raw_validation_gate.csv", index=False)

    screen_path, registry, passed_anchors = build_combination_matrix(
        study,
        screen_path,
        output_dir,
        anchor_gate,
        force=args.force_build,
    )
    combination_metrics = registry.loc[
        registry["candidate_type"].isin(
            ["pair", "family_subset", "anchor_subset_control"]
        ),
        "metric",
    ].astype(str).tolist()
    all_run_metrics = [*anchor_metrics, *combination_metrics]
    monthly, diagnostics = lag6.metric_diagnostics(screen_path, all_run_metrics)
    monthly.to_csv(output_dir / "candidate_monthly_coverage.csv", index=False)
    diagnostics.to_csv(output_dir / "metric_diagnostics.csv", index=False)
    start_dates = (
        diagnostics.set_index("metric")["first_date"].fillna("").astype(str).to_dict()
    )
    write_skips(profile, output_dir, all_run_metrics, start_dates)
    worker_results.extend(
        run_metrics(
            profile=profile,
            screen_path=screen_path,
            returns_path=args.returns.resolve(),
            output_dir=output_dir,
            metrics=combination_metrics,
            start_dates=start_dates,
            workers=workers,
            stage="combinations",
        )
    )
    results = dedupe_official_results(read_official_results(collect_paths(output_dir)))
    results.to_csv(output_dir / "official_run_results.csv", index=False)
    summary, gate = gate_for(
        results,
        diagnostics,
        registry,
        all_run_metrics,
    )
    summary.to_csv(output_dir / "performance_summary.csv", index=False)
    gate.to_csv(output_dir / "combination_validation_gate.csv", index=False)
    # Preserve the staged anchor gate generated before family construction.
    anchor_summary.to_csv(output_dir / "anchor_performance_summary.csv", index=False)
    components = component_evidence(study, anchor_gate)
    components.to_csv(output_dir / "component_evidence.csv", index=False)
    pairs, family_subsets, loo, claims = build_evidence_tables(
        registry,
        gate,
        components,
        passed_anchors,
        profile,
    )
    pairs.to_csv(output_dir / "pair_synergy_results.csv", index=False)
    family_subsets.to_csv(output_dir / "family_subset_results.csv", index=False)
    loo.to_csv(output_dir / "leave_one_out_results.csv", index=False)
    claims.to_csv(output_dir / "synergy_claims.csv", index=False)
    comparisons = pd.concat([pairs, family_subsets], ignore_index=True)
    report = write_report(
        study,
        output_dir,
        anchor_gate,
        comparisons,
        loo,
        claims,
    )

    completed = {
        (str(row.metric), str(row.side))
        for row in results[
            results["metric"].isin(all_run_metrics)
            & results["status"].isin(["success", "skipped"])
        ].itertuples()
    }
    expected = {
        (metric, side) for metric in all_run_metrics for side in ("Top", "Worst")
    }
    engine = lag6.nav_engine_metadata(
        strictly_after_rebalance=True,
        apply_weights_at_close=True,
    )
    manifest = {
        **engine,
        "status": "complete" if completed == expected else "partial",
        "created_at": datetime.now().isoformat(),
        "study_id": f"{profile.output_prefix}_lag6_anchor_synergy",
        "market": asdict(profile),
        "output_dir": str(output_dir),
        "research_screen": str(screen_path),
        "anchor_candidate_count": len(anchor_metrics),
        "passed_anchor_count": len(passed_anchors),
        "passed_anchors": [item.label for item in passed_anchors],
        "passed_lag6_count": int(
            pd.read_csv(study.lag6_run / "relative_validation_gate.csv")[
                "pass_gate"
            ].sum()
        ),
        "combination_candidate_count": len(combination_metrics),
        "expected_official_runs": len(expected),
        "terminal_official_runs": len(completed),
        "success_count": int(
            results[
                results["metric"].isin(all_run_metrics)
                & results["status"].eq("success")
            ].shape[0]
        ),
        "skipped_count": int(
            results[
                results["metric"].isin(all_run_metrics)
                & results["status"].eq("skipped")
            ].shape[0]
        ),
        "failed_count": int(
            results[
                results["metric"].isin(all_run_metrics)
                & results["status"].eq("failed")
            ].shape[0]
        ),
        "supported_synergy_count": int(
            claims["synergy_supported"].sum() if not claims.empty else 0
        ),
        "worker_results": worker_results,
        "optimizer_used": False,
        "optimizer_objective": "not_applicable_factor_sort_evidence",
        "report": str(report),
    }
    json_dump(output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())

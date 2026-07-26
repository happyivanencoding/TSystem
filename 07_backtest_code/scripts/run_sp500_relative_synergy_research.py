"""
SP500 raw + relative-variable synergy research.

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

import run_sp500_multifactor_research as sp500  # noqa: E402
from tp_research.executor import (  # noqa: E402
    build_synergy_candidate_matrix,
    dedupe_official_results,
    incomplete_official_metrics,
    new_wave_id,
    read_official_results,
    shard_metric_names,
)


sp500.configure_base()
base = sp500.base


AD_HOC_ROOT = BACKTEST_ROOT / "runs" / "ad_hoc"
RAW_DIR = AD_HOC_ROOT / "sp500_raw_validation_20260708"
RAW_GATE = AD_HOC_ROOT / "sp500_validated_family_20260708" / "raw_validation_gate.csv"
RELATIVE_DIR = AD_HOC_ROOT / "sp500_relative_variables_20260709"
DEFAULT_RETURNS = TP_ROOT / "00_screen" / "returns.parquet"
OUTPUT_NAME = "sp500_relative_synergy_20260709"
RAW_SCREEN_FILE = "sp500_multifactor_screen.parquet"
RELATIVE_SCREEN_FILE = "sp500_relative_variable_screen.parquet"
SYNERGY_SCREEN_FILE = "sp500_relative_synergy_screen.parquet"
REPORT_FILE = "sp500_relative_synergy_report.md"
RUN_ROOT_PREFIX = "sp500sy"
SHARD_SCREEN_FILE = "sp500_relative_synergy_shard_screen.parquet"

BUCKET_LIMITS = {
    "revision": 2,
    "pmom": 1,
    "growth": 3,
    "value_level": 1,
    "quality_level": 1,
    "quality_improvement": 4,
    "earnings_yield_improvement": 3,
    "deleveraging": 3,
    "value_improvement": 3,
    "dividend_growth": 1,
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


def parse_side_arg(raw: str | None) -> list[str]:
    if raw is None or raw.strip().lower() in {"", "all"}:
        return ["Top", "Worst"]
    aliases = {"top": "Top", "worst": "Worst"}
    sides = []
    for item in raw.split(","):
        key = item.strip().lower()
        if not key:
            continue
        if key not in aliases:
            raise ValueError(f"Unknown side: {item}")
        sides.append(aliases[key])
    return list(dict.fromkeys(sides))


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
    if raw_column in {"Oper Margin", "ROE avg FY0", "Cont Op Earning Margin", "Gross Margin", "FCF Conversion"}:
        return "quality_level"
    if raw_column in {"NetDebt to EBITDA exFIN", "Net Debt to Market Cap", "Net Debt to Tot Equity"}:
        return "deleveraging"
    if family == "value":
        return "value_level"
    if raw_column in {"DPS 1Y Growth FY1", "DPS 1Y Growth NTM"}:
        return "dividend_growth"
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
        "value_level": "cheap valuation level",
        "quality_level": "profitability, cash conversion, or low leverage level",
        "quality_improvement": "profitability or margin improvement",
        "earnings_yield_improvement": "valuation becoming cheaper relative to earnings",
        "deleveraging": "balance-sheet risk decline",
        "value_improvement": "valuation multiple becoming cheaper",
        "dividend_growth": "sustainable shareholder-return growth",
        "risk_decline": "realized risk or volatility decline",
    }.get(bucket, bucket)


def gate_column(frame: pd.DataFrame, *names: str) -> str:
    for name in names:
        if name in frame.columns:
            return name
    raise KeyError(f"Missing gate column; tried {names}")


def canonical_sp500_metric(metric: object) -> str:
    value = str(metric)
    if value.startswith("eu_small_"):
        return "sp500_" + value[len("eu_small_") :]
    return value


def source_metric(row: pd.Series) -> str:
    explicit = str(row.get("source_metric", ""))
    if explicit and explicit.lower() != "nan":
        return explicit
    metric = str(row.get("metric", ""))
    if str(row.get("source_type", "")) == "raw" and metric.startswith("sp500_"):
        return "eu_small_" + metric[len("sp500_") :]
    return metric


def select_legs(raw_gate: pd.DataFrame, rel_gate: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    raw_pass_col = gate_column(raw_gate, "pass_gate", "passed")
    raw_pass = raw_gate[status_bool(raw_gate[raw_pass_col])].copy()
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
    raw_pass = raw_pass[raw_pass["bucket"].isin(BUCKET_ORDER)].copy()
    for _, row in raw_pass.iterrows():
        bucket = str(row["bucket"])
        original_metric = str(row["metric"])
        rows.append(
            {
                "metric": canonical_sp500_metric(original_metric),
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

    rel_pass_col = gate_column(rel_gate, "pass_gate", "passed")
    rel_pass = rel_gate[status_bool(rel_gate[rel_pass_col])].copy()
    rel_pass["bucket"] = rel_pass.apply(relative_bucket, axis=1)
    rel_pass = rel_pass[rel_pass["bucket"].isin(BUCKET_ORDER)].copy()
    if not rel_pass.empty:
        rel_pass = (
            rel_pass.sort_values(["bucket", "raw_column", "robust_score", "ratio_cagr", "coverage"], ascending=[True, True, False, False, False])
            .drop_duplicates(["bucket", "raw_column"], keep="first")
            .reset_index(drop=True)
        )
    for _, row in rel_pass.iterrows():
        bucket = str(row["bucket"])
        metric = str(row["metric"])
        rows.append(
            {
                "metric": metric,
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
    if legs.empty:
        return legs
    selected = []
    for bucket in BUCKET_ORDER:
        group = legs[legs["bucket"].eq(bucket)].copy()
        if group.empty:
            continue
        group = group.sort_values(["robust_score", "ratio_cagr", "coverage"], ascending=[False, False, False])
        selected.append(group.head(BUCKET_LIMITS[bucket]))
    out = pd.concat(selected, ignore_index=True) if selected else pd.DataFrame()
    if out.empty:
        return out
    out["bucket_order"] = out["bucket"].map({bucket: idx for idx, bucket in enumerate(BUCKET_ORDER)})
    return out.sort_values(["bucket_order", "robust_score"], ascending=[True, False]).drop(columns=["bucket_order"]).reset_index(drop=True)


def full_column() -> str:
    return "sp500_syn_full_bucket_equal"


def individual_full_column() -> str:
    return "sp500_syn_full_individual_equal"


def load_research_inputs(raw_dir: Path, relative_dir: Path, legs: pd.DataFrame) -> pd.DataFrame:
    id_cols = [base.DATE_COL, base.ISIN_COL, base.SEDOL_COL, "Name", base.SECTOR_COL, base.MKT_CAP_COL, base.WEIGHT_COL]
    raw_legs = legs[legs["source_type"].eq("raw")].copy()
    raw_metrics = raw_legs.apply(source_metric, axis=1).tolist()
    rel_metrics = legs[legs["source_type"].eq("relative")]["metric"].tolist()
    raw_screen_path = raw_dir / RAW_SCREEN_FILE
    rel_screen_path = relative_dir / RELATIVE_SCREEN_FILE
    raw_cols = list(dict.fromkeys(id_cols + raw_metrics))
    rel_cols = list(dict.fromkeys([base.DATE_COL, base.ISIN_COL] + rel_metrics))
    raw_screen = pd.read_parquet(raw_screen_path, columns=[col for col in raw_cols if col in pq.ParquetFile(raw_screen_path).schema_arrow.names])
    rel_screen = pd.read_parquet(rel_screen_path, columns=[col for col in rel_cols if col in pq.ParquetFile(rel_screen_path).schema_arrow.names])
    for _, row in raw_legs.iterrows():
        src = source_metric(row)
        dst = str(row["metric"])
        if src in raw_screen.columns and dst not in raw_screen.columns:
            raw_screen[dst] = raw_screen[src]
    raw_screen[base.DATE_COL] = pd.to_datetime(raw_screen[base.DATE_COL], errors="coerce")
    rel_screen[base.DATE_COL] = pd.to_datetime(rel_screen[base.DATE_COL], errors="coerce")
    screen = raw_screen.merge(rel_screen, on=[base.DATE_COL, base.ISIN_COL], how="left", validate="one_to_one")
    return screen.sort_values([base.DATE_COL, base.ISIN_COL]).reset_index(drop=True)


def _series_frame(screen: pd.DataFrame, extra: dict[str, pd.Series], columns: list[str]) -> pd.DataFrame:
    data = {}
    for column in columns:
        if column in extra:
            data[column] = extra[column]
        elif column in screen.columns:
            data[column] = screen[column]
    return pd.DataFrame(data, index=screen.index)


def average_from(screen: pd.DataFrame, extra: dict[str, pd.Series], columns: list[str], min_count: int) -> pd.Series:
    data = _series_frame(screen, extra, columns).apply(pd.to_numeric, errors="coerce")
    if data.empty:
        return pd.Series(np.nan, index=screen.index)
    return data.mean(axis=1, skipna=True).where(data.notna().sum(axis=1) >= min_count)


def weighted_from(screen: pd.DataFrame, extra: dict[str, pd.Series], weights: dict[str, float], min_count: int) -> pd.Series:
    columns = list(weights)
    data = _series_frame(screen, extra, columns).apply(pd.to_numeric, errors="coerce")
    if data.empty:
        return pd.Series(np.nan, index=screen.index)
    weight = pd.Series({column: weights[column] for column in data.columns}, dtype=float)
    valid_weight_sum = data.notna().mul(weight, axis=1).sum(axis=1)
    weighted = data.mul(weight, axis=1).sum(axis=1) / valid_weight_sum.replace(0, np.nan)
    return weighted.where(data.notna().sum(axis=1) >= min_count)


def add_candidates(
    screen: pd.DataFrame,
    legs: pd.DataFrame,
    *,
    materialize: bool = False,
) -> tuple[pd.DataFrame, list[base.ModelSpec], pd.DataFrame]:
    leg_meta = legs.set_index("metric").to_dict(orient="index")
    screen, candidate_map = build_synergy_candidate_matrix(
        screen,
        legs[["metric", "bucket"]],
        bucket_order=BUCKET_ORDER,
        prefix="sp500_syn",
        weighted_scores=lambda frame, components, min_count: weighted_from(
            frame,
            {},
            dict(components),
            min_count=min_count,
        ),
        average_scores=lambda frame, columns, min_count: average_from(
            frame,
            {},
            list(columns),
            min_count=min_count,
        ),
        subset_sizes=(2, 3),
        include_individual_leave_one_out=True,
        materialize=materialize,
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
        elif candidate_type == "leave_one_out":
            left_out = str(row.get("left_out_bucket", ""))
            label = f"full model without {left_out}"
            family = candidate_type
            note = f"leave one bucket out: {left_out}"
        elif candidate_type == "individual_full_model":
            label = "all selected variables equal-weight"
            family = candidate_type
            note = "full selected individual-variable model"
        else:
            left_out = str(row.get("left_out_metric", ""))
            left_label = str(leg_meta.get(left_out, {}).get("label", left_out))
            label = f"individual model without {left_label}"
            family = "leave_one_variable_out"
            note = f"leave one variable out: {left_out}"
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


def candidate_metric_diagnostics(candidate_map: pd.DataFrame, specs: list[base.ModelSpec]) -> pd.DataFrame:
    spec_map = {spec.column: spec for spec in specs}
    rows = []
    for _, row in candidate_map.iterrows():
        metric = str(row["metric"])
        spec = spec_map.get(metric)
        rows.append(
            {
                "metric": metric,
                "label": row.get("label", spec.label if spec else metric),
                "family": row.get("candidate_type", spec.family if spec else ""),
                "role": row.get("candidate_type", ""),
                "direction": "",
                "coverage": np.nan,
                "non_null_rows": np.nan,
                "first_date": "",
                "last_date": "",
                "avg_names_per_month": np.nan,
                "note": spec.note if spec else row.get("buckets", ""),
                "component_count": row.get("component_count", np.nan),
                "buckets": row.get("buckets", ""),
                "components": row.get("components", ""),
            }
        )
    return pd.DataFrame(rows)


def _component_list(row: pd.Series | dict[str, object]) -> list[str]:
    return [item for item in str(row.get("components", "")).split("|") if item]


def candidate_min_count(row: pd.Series | dict[str, object], component_count: int) -> int:
    candidate_type = str(row.get("candidate_type", ""))
    if candidate_type == "pair":
        return 2
    if candidate_type == "bucket_component":
        return 1
    if candidate_type == "family_subset":
        return component_count
    if candidate_type in {
        "full_model",
        "leave_one_out",
        "individual_full_model",
        "leave_one_variable_out",
    }:
        return max(2, min(4, component_count))
    return max(1, component_count)


def official_candidate_metrics(candidate_map: pd.DataFrame) -> list[str]:
    if candidate_map.empty or "candidate_type" not in candidate_map.columns:
        return []
    official_types = {
        "pair",
        "family_subset",
        "full_model",
        "leave_one_out",
        "individual_full_model",
        "leave_one_variable_out",
    }
    return candidate_map[candidate_map["candidate_type"].isin(official_types)]["metric"].astype(str).tolist()


def materialize_candidate_columns(
    screen: pd.DataFrame,
    candidate_map: pd.DataFrame,
    metrics: list[str],
) -> pd.DataFrame:
    candidate_rows = candidate_map.drop_duplicates("metric", keep="last").set_index("metric").to_dict(orient="index")
    extra: dict[str, pd.Series] = {}
    visiting: set[str] = set()

    def ensure(metric: str) -> None:
        if metric in screen.columns or metric in extra:
            return
        if metric in visiting:
            raise ValueError(f"Circular candidate dependency at {metric}")
        if metric not in candidate_rows:
            raise KeyError(f"Candidate dependency {metric} is neither in screen nor candidate_map")
        visiting.add(metric)
        row = candidate_rows[metric]
        components = _component_list(row)
        for component in components:
            if component not in screen.columns and component not in extra:
                ensure(component)
        component_count = len(components)
        min_count = candidate_min_count(row, component_count)
        candidate_type = str(row.get("candidate_type", ""))
        if candidate_type == "bucket_component":
            extra[metric] = average_from(screen, extra, components, min_count=min_count)
        else:
            weight = 1.0 / component_count if component_count else 0.0
            extra[metric] = weighted_from(screen, extra, {component: weight for component in components}, min_count=min_count)
        visiting.remove(metric)

    for metric in metrics:
        ensure(str(metric))
    if not extra:
        return screen
    keep_extra = {name: series for name, series in extra.items() if name not in screen.columns}
    return pd.concat([screen, pd.DataFrame(keep_extra, index=screen.index)], axis=1).copy()


def build_or_load_screen(
    raw_dir: Path,
    raw_gate_path: Path,
    relative_dir: Path,
    returns: pd.DataFrame,
    output_dir: Path,
    force: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[base.ModelSpec], pd.DataFrame, pd.DataFrame]:
    screen_path = output_dir / SYNERGY_SCREEN_FILE
    specs_path = output_dir / "metric_definitions.json"
    legs_path = output_dir / "selected_legs.csv"
    map_path = output_dir / "candidate_map.csv"
    raw_gate = pd.read_csv(raw_gate_path)
    rel_gate = pd.read_csv(relative_dir / "relative_validation_gate.csv")
    legs = select_legs(raw_gate, rel_gate)
    cached_candidate_map = (
        pd.read_csv(map_path)
        if map_path.exists()
        else pd.DataFrame()
    )
    cache_has_individual_loo = (
        not cached_candidate_map.empty
        and "candidate_type" in cached_candidate_map.columns
        and cached_candidate_map["candidate_type"].isin(
            ["individual_full_model", "leave_one_variable_out"]
        ).any()
    )

    if (
        screen_path.exists()
        and specs_path.exists()
        and legs_path.exists()
        and map_path.exists()
        and cache_has_individual_loo
        and not force
    ):
        screen = pd.read_parquet(screen_path)
        specs = [base.ModelSpec(**item) for item in json.loads(specs_path.read_text(encoding="utf-8"))]
        candidate_map = cached_candidate_map
        checks = base.construction_checks(screen, returns, pq.ParquetFile(base.DEFAULT_SCREEN).metadata.num_rows)
        diag_path = output_dir / "metric_diagnostics.csv"
        diag = pd.read_csv(diag_path) if diag_path.exists() else candidate_metric_diagnostics(candidate_map, specs)
        return screen, checks, diag, specs, pd.read_csv(legs_path), candidate_map

    screen = load_research_inputs(raw_dir, relative_dir, legs)
    screen, specs, candidate_map = add_candidates(screen, legs, materialize=False)
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
                    {
                        "check": "leave_one_variable_out_count",
                        "value": int(candidate_map.get("candidate_type", pd.Series(dtype=str)).eq("leave_one_variable_out").sum()),
                    },
                    {
                        "check": "official_candidate_count",
                        "value": int(len(official_candidate_metrics(candidate_map))),
                    },
                    {
                        "check": "expected_official_top_worst_runs",
                        "value": int(2 * len(official_candidate_metrics(candidate_map))),
                    },
                    {
                        "check": "candidate_rule",
                        "value": "cross-bucket pairs; 2/3-bucket subsets; bucket_component dependency; full bucket and full individual models; bucket and individual leave-one-out",
                    },
                    {
                        "check": "sp500_candidate_rule",
                        "value": "raw and relative legs must pass official gate; selected legs are bucket-limited; legacy raw metric aliases are canonicalized to sp500_*",
                    },
                ]
            ),
        ],
        ignore_index=True,
    )
    diag = candidate_metric_diagnostics(candidate_map, specs)
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
    return incomplete_official_metrics(
        metrics,
        completed,
        terminal_failure_pattern="manual hard failure",
    )


def shard_metrics(metrics: list[str], workers: int, shard_size: int = 0) -> list[list[str]]:
    return shard_metric_names(metrics, workers, shard_size)


def worker_run(payload: dict[str, object]) -> dict[str, object]:
    output_dir = Path(str(payload["output_dir"]))
    screen_path = Path(str(payload["screen_path"]))
    map_path = Path(str(payload["map_path"]))
    returns_path = Path(str(payload["returns_path"]))
    metrics = list(payload["metrics"])
    sides = list(payload.get("sides") or ["Top", "Worst"])
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
    candidate_map = pd.read_csv(map_path)
    screen = materialize_candidate_columns(screen, candidate_map, [str(metric) for metric in metrics])
    shard_screen_path = shard_dir / SHARD_SCREEN_FILE
    screen.to_parquet(shard_screen_path, index=False)
    returns = base.load_tabular_file(returns_path)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index()
    wave_slug = base.slugify(wave)[-12:] or "manual"
    run_root_name = f"ad_hoc/{RUN_ROOT_PREFIX}{wave_slug}_s{shard_id:02d}"
    results = sp500.run_official_backtests_incremental(
        screen=screen,
        returns=returns,
        screen_path=shard_screen_path,
        returns_path=returns_path,
        run_root_name=run_root_name,
        metrics=metrics,
        max_runs=payload.get("max_runs"),
        results_path=shard_results,
        existing_results=existing,
        sides=sides,
    )
    results = dedupe_results(results)
    results.to_csv(shard_results, index=False)
    return {
        "shard_id": shard_id,
        "metrics": len(metrics),
        "sides": sides,
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
    alias_map = {
        str(row.get("source_metric")): str(row.get("metric"))
        for _, row in selected_legs.iterrows()
        if str(row.get("source_metric", row.get("metric", ""))) != str(row.get("metric", ""))
    }
    if alias_map:
        alias_rows = raw_summary[raw_summary["metric"].astype(str).isin(alias_map)].copy()
        if not alias_rows.empty:
            alias_rows["metric"] = alias_rows["metric"].astype(str).map(alias_map)
            raw_summary = pd.concat([raw_summary, alias_rows], ignore_index=True)
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
        elif meta.get("candidate_type") in {"family_subset", "full_model", "individual_full_model"}:
            rows_subset.append(out)

    pair = pd.DataFrame(rows_pair)
    if not pair.empty:
        pair = pair.sort_values(["classification", "synergy_score", "robust_score"], ascending=[True, False, False])
    subset = pd.DataFrame(rows_subset)
    if not subset.empty:
        subset = subset.sort_values(["classification", "synergy_score", "robust_score"], ascending=[True, False, False])
    bucket_full_metric = full_column()
    individual_full_metric = individual_full_column()
    loo_rows = []
    loo_mask = candidate_map["candidate_type"].isin(["leave_one_out", "leave_one_variable_out"])
    for _, meta in candidate_map[loo_mask].iterrows():
        metric = str(meta["metric"])
        row = top_map.get(metric, {})
        candidate_type = str(meta.get("candidate_type", ""))
        full_metric = individual_full_metric if candidate_type == "leave_one_variable_out" else bucket_full_metric
        full_row = top_map.get(full_metric, {})
        full_robust = float(full_row.get("robust_score", np.nan))
        full_ratio = float(full_row.get("ratio_cagr", np.nan))
        without_robust = float(row.get("robust_score", np.nan))
        without_ratio = float(row.get("ratio_cagr", np.nan))
        left_out = str(meta.get("left_out_metric", meta.get("left_out_bucket", "")))
        contribution = full_robust - without_robust if np.isfinite(full_robust) and np.isfinite(without_robust) else np.nan
        loo_rows.append(
            {
                "metric": metric,
                "candidate_type": candidate_type,
                "left_out": left_out,
                "left_out_bucket": meta.get("left_out_bucket", ""),
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
        "# SP500 raw + relative 变量协同研究",
        "",
        f"- 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 证据口径: official exact Top/Worst backtest",
        "- 研究范围: 已通过 raw gate 与 relative gate 的 revision、PMOM、growth、value/quality level、quality improvement、earnings-yield improvement、deleveraging、dividend growth、risk decline。",
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
    path = output_dir / REPORT_FILE
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SP500 raw + relative synergy official research.")
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--raw-gate", default=str(RAW_GATE))
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
    parser.add_argument("--sides", default="all", help="Comma-separated sides to run: Top,Worst, or all.")
    parser.add_argument("--wave", default="")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    raw_dir = Path(args.raw_dir)
    raw_gate_path = Path(args.raw_gate)
    relative_dir = Path(args.relative_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    returns_path = Path(args.returns)
    returns = base.load_tabular_file(returns_path)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index()
    screen, checks, diag, specs, selected_legs, candidate_map = build_or_load_screen(
        raw_dir,
        raw_gate_path,
        relative_dir,
        returns,
        output_dir,
        force=args.force_rebuild,
    )
    screen_path = output_dir / SYNERGY_SCREEN_FILE
    all_metrics = official_candidate_metrics(candidate_map)
    metrics = parse_csv_arg(args.metrics, all_metrics)
    sides = parse_side_arg(args.sides)
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
                    "sides": sides,
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
                    "map_path": str(output_dir / "candidate_map.csv"),
                    "returns_path": str(returns_path),
                    "main_results_path": str(main_results),
                    "wave": wave,
                    "shard_id": idx,
                    "metrics": shard,
                    "sides": sides,
                    "max_runs": None,
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
                "sides": sides,
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
    return 0 if run_results.empty or run_results["status"].isin(["success", "skipped"]).all() else 1


if __name__ == "__main__":
    raise SystemExit(main())

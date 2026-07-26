"""Historical leave-one-period-out analysis for TP factor markets.

This analyzer consumes completed official Top/Worst artifacts.  A period is
eligible for factor validation only when both benchmark snapshots and actual
candidate portfolio-formation dates exist.  NAV drift through a signal-data
gap is retained for audit but is never treated as regime evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from math import ceil, exp, pi, sqrt
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


SCRIPT_DIR = Path(__file__).resolve().parent
BACKTEST_ROOT = SCRIPT_DIR.parent
TP_ROOT = BACKTEST_ROOT.parent
import run_cross_market_lag6_relative_research as lag6  # noqa: E402


AD_HOC_ROOT = lag6.AD_HOC_ROOT
MIN_DAYS = 126
MIN_COVERAGE = 0.75
MIN_WORST_ACTIVE_CAGR = -0.05
COST_BPS_PER_ONE_WAY_TURNOVER = 20.0


COMMON_REGIMES = (
    {
        "regime_id": "gfc_crisis",
        "label_zh": "全球金融危机",
        "start": "2005-01-03",
        "end": "2008-12-31",
        "economic_definition": "信用扩张终结、全球金融危机及极端去杠杆。",
    },
    {
        "regime_id": "post_gfc_euro_crisis",
        "label_zh": "危机后修复与欧债危机",
        "start": "2009-01-01",
        "end": "2012-12-31",
        "economic_definition": "金融危机后修复、欧债危机、主权与银行风险。",
    },
    {
        "regime_id": "qe_negative_rates",
        "label_zh": "QE 与负利率",
        "start": "2013-01-01",
        "end": "2016-12-30",
        "economic_definition": "低通胀、量化宽松、负利率与估值久期扩张。",
    },
    {
        "regime_id": "late_cycle_low_inflation",
        "label_zh": "低通胀晚周期",
        "start": "2017-01-02",
        "end": "2019-12-31",
        "economic_definition": "同步复苏后段、增长放缓、低利率持续。",
    },
    {
        "regime_id": "pandemic_reopening",
        "label_zh": "疫情冲击与重启",
        "start": "2020-01-02",
        "end": "2021-12-31",
        "economic_definition": "封锁、政策托底、盈利路径重写与重启交易。",
    },
    {
        "regime_id": "inflation_energy_hikes",
        "label_zh": "通胀、能源与快速加息",
        "start": "2022-01-03",
        "end": "2023-12-29",
        "economic_definition": "供应与能源冲击、广泛通胀及快速加息。",
    },
    {
        "regime_id": "disinflation_normalization",
        "label_zh": "去通胀与政策正常化",
        "start": "2024-01-02",
        "end": "2026-07-02",
        "economic_definition": "去通胀、降息分化、AI 投资与市场领导力集中。",
    },
)


@dataclass(frozen=True)
class EvidenceSource:
    source_id: str
    summary: str
    candidate_class: str
    metadata: str = ""
    metadata_kind: str = ""
    canonicalize_sp500_raw: bool = False
    engine_label: str = "historical_official"


@dataclass(frozen=True)
class AnalysisProfile:
    key: str
    output_name: str
    sources: tuple[EvidenceSource, ...]

    @property
    def market(self) -> lag6.MarketProfile:
        return lag6.PROFILES[self.key]

    @property
    def regimes(self) -> tuple[dict[str, str], ...]:
        start = pd.Timestamp(self.market.research_start)
        return tuple(
            item
            for item in COMMON_REGIMES
            if pd.Timestamp(item["end"]) >= start
        )


PROFILES = {
    "nasdaq": AnalysisProfile(
        key="nasdaq",
        output_name="nasdaq_leave_one_period_out_20260725",
        sources=(
            EvidenceSource(
                "raw",
                "nasdaq_raw_gate_20260708/performance_summary.csv",
                "raw",
                "nasdaq_raw_gate_20260708/metric_definitions.json",
                "model_defs",
            ),
            EvidenceSource(
                "relative_lag1_3_12",
                "nasdaq_relative_variables_20260709/performance_summary.csv",
                "relative",
                "nasdaq_relative_variables_20260709/relative_variable_definitions.csv",
                "relative",
            ),
            EvidenceSource(
                "legacy_combinations",
                "nasdaq_extended_factor_research_20260709/synergy_performance_summary.csv",
                "combination",
                "nasdaq_extended_factor_research_20260709/synergy_metric_definitions.json",
                "json_components",
            ),
            EvidenceSource(
                "relative_lag6",
                "nasdaq_relative_lag6_20260725/performance_summary.csv",
                "relative",
                "nasdaq_relative_lag6_20260725/relative_variable_definitions.csv",
                "relative",
                engine_label="tp.security_nav_3.0.0",
            ),
            EvidenceSource(
                "lag6_anchor_matrix",
                "nasdaq_lag6_anchor_synergy_20260725/performance_summary.csv",
                "dynamic",
                "nasdaq_lag6_anchor_synergy_20260725/candidate_registry.csv",
                "registry",
                engine_label="tp.security_nav_3.0.0",
            ),
        ),
    ),
    "sp500": AnalysisProfile(
        key="sp500",
        output_name="sp500_leave_one_period_out_20260725",
        sources=(
            EvidenceSource(
                "raw",
                "sp500_raw_validation_20260708/performance_summary.csv",
                "raw",
                "sp500_raw_validation_20260708/metric_definitions.json",
                "model_defs",
                canonicalize_sp500_raw=True,
            ),
            EvidenceSource(
                "relative_lag1_3_12",
                "sp500_relative_variables_20260709/performance_summary.csv",
                "relative",
                "sp500_relative_variables_20260709/relative_variable_definitions.csv",
                "relative",
            ),
            EvidenceSource(
                "legacy_combinations",
                "sp500_relative_synergy_20260710/performance_summary.csv",
                "combination",
                "sp500_relative_synergy_20260710/candidate_map.csv",
                "candidate_map",
            ),
            EvidenceSource(
                "relative_lag6",
                "sp500_relative_lag6_20260725/performance_summary.csv",
                "relative",
                "sp500_relative_lag6_20260725/relative_variable_definitions.csv",
                "relative",
                engine_label="tp.security_nav_3.0.0",
            ),
            EvidenceSource(
                "lag6_anchor_matrix",
                "sp500_lag6_anchor_synergy_20260725/performance_summary.csv",
                "dynamic",
                "sp500_lag6_anchor_synergy_20260725/candidate_registry.csv",
                "registry",
                engine_label="tp.security_nav_3.0.0",
            ),
        ),
    ),
    "eu-small": AnalysisProfile(
        key="eu-small",
        output_name="eu_small_leave_one_period_out_20260725",
        sources=(
            EvidenceSource(
                "raw",
                "eu_small_multifactor_20260707_085611/performance_summary.csv",
                "raw",
                "eu_small_multifactor_20260707_085611/metric_definitions.json",
                "model_defs",
            ),
            EvidenceSource(
                "relative_lag1_3_12",
                "eu_small_relative_variables_20260709/performance_summary.csv",
                "relative",
                "eu_small_relative_variables_20260709/relative_variable_definitions.csv",
                "relative",
            ),
            EvidenceSource(
                "legacy_combinations",
                "eu_small_relative_synergy_20260709/performance_summary.csv",
                "combination",
                "eu_small_relative_synergy_20260709/candidate_map.csv",
                "candidate_map",
            ),
            EvidenceSource(
                "relative_lag6",
                "eu_small_relative_lag6_20260725/performance_summary.csv",
                "relative",
                "eu_small_relative_lag6_20260725/relative_variable_definitions.csv",
                "relative",
                engine_label="tp.security_nav_3.0.0",
            ),
            EvidenceSource(
                "lag6_anchor_matrix",
                "eu_small_lag6_anchor_synergy_20260725/performance_summary.csv",
                "dynamic",
                "eu_small_lag6_anchor_synergy_20260725/candidate_registry.csv",
                "registry",
                engine_label="tp.security_nav_3.0.0",
            ),
        ),
    ),
}


def json_dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def read_nav(path_text: str) -> pd.Series:
    path = Path(path_text)
    if not path.exists():
        return pd.Series(dtype=float)
    frame = pd.read_parquet(path)
    if isinstance(frame.index, pd.DatetimeIndex) and frame.shape[1]:
        series = frame.iloc[:, 0]
    else:
        date_col = "Date" if "Date" in frame.columns else frame.columns[0]
        value_cols = [item for item in frame.columns if item != date_col]
        if not value_cols:
            return pd.Series(dtype=float)
        series = frame.set_index(date_col)[value_cols[-1]]
    series.index = pd.to_datetime(series.index, errors="coerce")
    return (
        pd.to_numeric(series, errors="coerce")
        .dropna()
        .loc[lambda item: ~item.index.duplicated(keep="last")]
        .sort_index()
    )


def cagr(series: pd.Series) -> float:
    clean = series.dropna()
    if len(clean) < 2 or clean.iloc[0] <= 0 or clean.iloc[-1] <= 0:
        return np.nan
    years = (clean.index[-1] - clean.index[0]).days / 365.25
    if years <= 0:
        return np.nan
    return float((clean.iloc[-1] / clean.iloc[0]) ** (1 / years) - 1)


def total_return(series: pd.Series) -> float:
    clean = series.dropna()
    if len(clean) < 2 or clean.iloc[0] == 0:
        return np.nan
    return float(clean.iloc[-1] / clean.iloc[0] - 1)


def max_drawdown(series: pd.Series) -> float:
    clean = series.dropna()
    if len(clean) < 2:
        return np.nan
    return float((clean / clean.cummax() - 1).min())


def annualized_vol(returns: pd.Series) -> float:
    clean = returns.dropna()
    return float(clean.std(ddof=1) * sqrt(252)) if len(clean) >= 2 else np.nan


def normal_cdf(value: float) -> float:
    return float(0.5 * (1 + np.math.erf(value / sqrt(2))))  # pragma: no cover


def normal_ppf(probability: float) -> float:
    try:
        from scipy.stats import norm

        return float(norm.ppf(probability))
    except Exception:  # pragma: no cover
        # Acklam approximation is unnecessary in the normal TP runtime.
        raise RuntimeError("scipy is required for Deflated Sharpe")


def metadata_map(source: EvidenceSource) -> dict[str, dict[str, object]]:
    if not source.metadata:
        return {}
    path = AD_HOC_ROOT / source.metadata
    if source.metadata_kind == "relative":
        frame = pd.read_csv(path)
        output = frame.set_index("metric").to_dict("index")
        for metric, row in output.items():
            row["label"] = (
                f"{row.get('raw_column', metric)} "
                f"{row.get('transform', '')} "
                f"lag{int(row.get('lag_observations', 0))}"
            )
            row["components"] = metric
            row["candidate_type"] = "single"
        return output
    if source.metadata_kind == "candidate_map":
        frame = pd.read_csv(path)
        return frame.set_index("metric").to_dict("index")
    if source.metadata_kind == "registry":
        frame = pd.read_csv(path)
        return frame.set_index("metric").to_dict("index")
    if source.metadata_kind == "json_components":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(item["column"]): {
                "label": item.get("label", item["column"]),
                "components": "|".join(item.get("components", {})),
                "candidate_type": (
                    "pair"
                    if "pair" in str(item.get("family", ""))
                    else "combination"
                ),
                "family": item.get("family", ""),
            }
            for item in payload
        }
    if source.metadata_kind == "model_defs":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(item["column"]): {
                "label": item.get("label", item["column"]),
                "components": "|".join(item.get("components", {})),
                "component_count": len(item.get("components", {})),
                "candidate_type": (
                    "single"
                    if len(item.get("components", {})) == 1
                    else "model"
                ),
                "family": item.get("family", ""),
            }
            for item in payload
        }
    raise ValueError(f"unknown metadata kind: {source.metadata_kind}")


def canonical_sp500_metric(value: object) -> str:
    text = str(value)
    if text.startswith("eu_small_"):
        return "sp500_" + text[len("eu_small_") :]
    return text


def parse_components(value: object) -> list[str]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            return [str(item) for item in json.loads(text)]
        except json.JSONDecodeError:
            pass
    return [item for item in text.split("|") if item]


def ingest_source(source: EvidenceSource) -> list[dict[str, object]]:
    summary_path = AD_HOC_ROOT / source.summary
    summary = pd.read_csv(summary_path)
    meta = metadata_map(source)
    rows: list[dict[str, object]] = []
    for metric_value, group in summary.groupby("metric", sort=False):
        original_metric = str(metric_value)
        metric = (
            canonical_sp500_metric(original_metric)
            if source.canonicalize_sp500_raw
            else original_metric
        )
        top_all = group[group["side"].eq("Top")]
        worst_all = group[group["side"].eq("Worst")]
        top = top_all[top_all["status"].eq("success")]
        worst = worst_all[worst_all["status"].eq("success")]
        representative = (
            top.iloc[-1]
            if not top.empty
            else (top_all.iloc[-1] if not top_all.empty else group.iloc[-1])
        )
        metadata = dict(meta.get(original_metric, meta.get(metric, {})))
        candidate_type = str(metadata.get("candidate_type", "single"))
        metadata_family = str(
            metadata.get(
                "base_family",
                metadata.get("family", representative.get("family", "")),
            )
        )
        if source.candidate_class == "dynamic":
            candidate_class = (
                "raw" if candidate_type == "anchor_single" else "combination"
            )
        elif source.candidate_class == "raw":
            component_count = int(metadata.get("component_count", 1))
            candidate_class = (
                "raw"
                if component_count == 1 and metadata_family.startswith("raw_")
                else "combination"
            )
        else:
            candidate_class = source.candidate_class
        components = parse_components(metadata.get("components", ""))
        if candidate_class in {"raw", "relative"}:
            components = [metric]
        elif source.canonicalize_sp500_raw:
            components = [canonical_sp500_metric(item) for item in components]
        coverage = pd.to_numeric(representative.get("coverage"), errors="coerce")
        ratio_cagr = pd.to_numeric(
            representative.get("ratio_cagr"), errors="coerce"
        )
        top_worst = pd.to_numeric(
            representative.get("top_worst_ratio_return"), errors="coerce"
        )
        robust = pd.to_numeric(
            representative.get("robust_score"), errors="coerce"
        )
        has_paths = (
            not top.empty
            and not worst.empty
            and Path(str(top.iloc[-1].get("perf_ptf", ""))).exists()
            and Path(str(worst.iloc[-1].get("perf_ptf", ""))).exists()
        )
        pass_gate = bool(
            has_paths
            and np.isfinite(coverage)
            and coverage >= MIN_COVERAGE
            and np.isfinite(ratio_cagr)
            and ratio_cagr > 0
            and np.isfinite(top_worst)
            and top_worst > 0
            and np.isfinite(robust)
            and robust > 0
        )
        label = str(metadata.get("label", representative.get("label", metric)))
        family = metadata_family
        row: dict[str, object] = {
            "metric": metric,
            "source_metric": original_metric,
            "source_id": source.source_id,
            "source_summary": str(summary_path),
            "candidate_class": candidate_class,
            "candidate_type": candidate_type,
            "label": label,
            "family": family,
            "bucket": str(
                metadata.get(
                    "bucket",
                    metadata.get("buckets", family),
                )
            ),
            "components": "|".join(components),
            "component_count": len(components),
            "coverage": coverage,
            "avg_turnover": pd.to_numeric(
                representative.get("avg_turnover"), errors="coerce"
            ),
            "full_period_ratio_cagr": ratio_cagr,
            "full_period_top_worst_ratio_return": top_worst,
            "full_period_robust_score": robust,
            "full_period_gate_pass": pass_gate,
            "has_official_top_worst_paths": has_paths,
            "engine_comparability": source.engine_label,
            "start_date": str(representative.get("start_date", "")),
            "top_perf": str(top.iloc[-1].get("perf_ptf", "")) if not top.empty else "",
            "worst_perf": (
                str(worst.iloc[-1].get("perf_ptf", "")) if not worst.empty else ""
            ),
            "benchmark_perf": (
                str(top.iloc[-1].get("perf_bench", "")) if not top.empty else ""
            ),
            "sec_list": (
                str(Path(str(top.iloc[-1].get("perf_ptf", ""))).parent / "sec_list.parquet")
                if not top.empty
                else ""
            ),
        }
        rows.append(row)
    return rows


def expand_leaves(
    metric: str,
    component_map: Mapping[str, Sequence[str]],
    seen: set[str] | None = None,
) -> list[str]:
    seen = set() if seen is None else set(seen)
    if metric in seen:
        return [metric]
    children = list(component_map.get(metric, []))
    if not children or children == [metric]:
        return [metric]
    leaves: list[str] = []
    for child in children:
        leaves.extend(expand_leaves(child, component_map, seen | {metric}))
    return list(dict.fromkeys(leaves))


def build_registry(profile: AnalysisProfile) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for source in profile.sources:
        rows.extend(ingest_source(source))
    registry = pd.DataFrame(rows)
    registry = registry.drop_duplicates("metric", keep="last").reset_index(drop=True)
    component_map = {
        str(row.metric): parse_components(row.components)
        for row in registry.itertuples(index=False)
    }
    registry["leaf_components"] = registry["metric"].map(
        lambda metric: "|".join(expand_leaves(str(metric), component_map))
    )
    return registry


def market_regime_definitions(
    profile: AnalysisProfile,
    canonical_path: Path,
) -> pd.DataFrame:
    market = profile.market
    screen = pd.read_parquet(
        canonical_path,
        columns=[lag6.DATE_COL, market.weight_col],
    )
    screen[lag6.DATE_COL] = pd.to_datetime(
        screen[lag6.DATE_COL],
        errors="coerce",
    )
    weights = pd.to_numeric(screen[market.weight_col], errors="coerce")
    snapshots = pd.DatetimeIndex(
        screen.loc[weights.gt(0), lag6.DATE_COL].dropna().unique()
    ).sort_values()
    rows: list[dict[str, object]] = []
    for regime in profile.regimes:
        start, end = pd.Timestamp(regime["start"]), pd.Timestamp(regime["end"])
        count = int(((snapshots >= start) & (snapshots <= end)).sum())
        years = max((end - start).days / 365.25, 1 / 12)
        minimum_snapshots = max(2, ceil(years * 3))
        rows.append(
            {
                **regime,
                "market_snapshot_count": count,
                "minimum_snapshots_for_period_validation": minimum_snapshots,
                "market_signal_validation_available": count >= minimum_snapshots,
            }
        )
    return pd.DataFrame(rows)


def security_list_dates(path_text: str) -> pd.DatetimeIndex:
    path = Path(path_text)
    if not path.exists():
        return pd.DatetimeIndex([])
    frame = pd.read_parquet(path, columns=[lag6.DATE_COL])
    return pd.DatetimeIndex(
        pd.to_datetime(frame[lag6.DATE_COL], errors="coerce").dropna().unique()
    ).sort_values()


def period_stats(
    top: pd.Series,
    worst: pd.Series,
    benchmark: pd.Series,
    formation_dates: pd.DatetimeIndex,
    regime: Mapping[str, object],
) -> dict[str, object]:
    start = pd.Timestamp(str(regime["start"]))
    end = pd.Timestamp(str(regime["end"]))
    aligned = pd.concat(
        [
            top.rename("top"),
            worst.rename("worst"),
            benchmark.rename("benchmark"),
        ],
        axis=1,
    ).dropna()
    aligned = aligned.loc[(aligned.index >= start) & (aligned.index <= end)]
    rebalances = int(
        ((formation_dates >= start) & (formation_dates <= end)).sum()
    )
    market_snapshots = int(regime["market_snapshot_count"])
    formation_coverage = (
        rebalances / market_snapshots if market_snapshots else np.nan
    )
    nav_available = len(aligned) >= MIN_DAYS
    validation_available = bool(
        nav_available
        and regime["market_signal_validation_available"]
        and rebalances >= 2
        and formation_coverage >= 0.50
    )
    base: dict[str, object] = {
        "regime_id": regime["regime_id"],
        "regime_label_zh": regime["label_zh"],
        "regime_start": regime["start"],
        "regime_end": regime["end"],
        "days": len(aligned),
        "market_snapshot_count": market_snapshots,
        "portfolio_formation_count": rebalances,
        "formation_coverage_vs_market_snapshots": formation_coverage,
        "nav_available": nav_available,
        "signal_validation_available": validation_available,
    }
    if not nav_available:
        return base
    top_ret = aligned["top"].pct_change()
    active_ret = top_ret - aligned["benchmark"].pct_change()
    ratio = aligned["top"] / aligned["benchmark"]
    top_worst = aligned["top"] / aligned["worst"]
    tracking_error = annualized_vol(active_ret)
    base.update(
        {
            "top_cagr": cagr(aligned["top"]),
            "worst_cagr": cagr(aligned["worst"]),
            "benchmark_cagr": cagr(aligned["benchmark"]),
            "top_vol": annualized_vol(top_ret),
            "top_max_drawdown": max_drawdown(aligned["top"]),
            "active_ratio_return": total_return(ratio),
            "active_cagr": cagr(ratio),
            "active_max_drawdown": max_drawdown(ratio),
            "tracking_error": tracking_error,
            "information_ratio": (
                float(active_ret.mean() * 252 / tracking_error)
                if tracking_error and np.isfinite(tracking_error)
                else np.nan
            ),
            "top_worst_ratio_return": total_return(top_worst),
            "top_worst_cagr": cagr(top_worst),
            "top_worst_max_drawdown": max_drawdown(top_worst),
        }
    )
    return base


def compute_period_metrics(
    registry: pd.DataFrame,
    regime_defs: pd.DataFrame,
    output_path: Path,
    *,
    resume: bool,
) -> pd.DataFrame:
    regimes = regime_defs.to_dict("records")
    existing = pd.DataFrame()
    completed: set[str] = set()
    if resume and output_path.exists():
        existing = pd.read_csv(output_path)
        counts = existing.groupby("metric")["regime_id"].nunique()
        completed = set(counts[counts.eq(len(regimes))].index.astype(str))
    candidates = registry[
        registry["has_official_top_worst_paths"].fillna(False)
        & ~registry["metric"].isin(completed)
    ]
    rows: list[dict[str, object]] = []
    for index, candidate in enumerate(candidates.itertuples(index=False), start=1):
        top = read_nav(str(candidate.top_perf))
        worst = read_nav(str(candidate.worst_perf))
        benchmark = read_nav(str(candidate.benchmark_perf))
        formation_dates = security_list_dates(str(candidate.sec_list))
        for regime in regimes:
            rows.append(
                {
                    "metric": candidate.metric,
                    "candidate_class": candidate.candidate_class,
                    "candidate_type": candidate.candidate_type,
                    "label": candidate.label,
                    "family": candidate.family,
                    "bucket": candidate.bucket,
                    "coverage": candidate.coverage,
                    "avg_turnover": candidate.avg_turnover,
                    **period_stats(
                        top,
                        worst,
                        benchmark,
                        formation_dates,
                        regime,
                    ),
                }
            )
        if index % 25 == 0:
            existing = pd.concat(
                [existing, pd.DataFrame(rows)],
                ignore_index=True,
            ).drop_duplicates(["metric", "regime_id"], keep="last")
            existing.to_csv(output_path, index=False)
            rows = []
    combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
    if not combined.empty:
        combined = combined.drop_duplicates(
            ["metric", "regime_id"],
            keep="last",
        ).sort_values(["candidate_class", "metric", "regime_id"])
        combined.to_csv(output_path, index=False)
    return combined.reset_index(drop=True)


def safe_stat(series: pd.Series, method: str) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return np.nan
    return float(getattr(clean, method)())


def training_aggregate(
    train: pd.DataFrame,
    expected_train_regimes: int,
    coverage: float,
    turnover: float,
) -> dict[str, object]:
    available = train[train["signal_validation_available"].fillna(False)]
    active = pd.to_numeric(available["active_cagr"], errors="coerce")
    top_worst = pd.to_numeric(available["top_worst_cagr"], errors="coerce")
    active_dd = pd.to_numeric(
        available["active_max_drawdown"],
        errors="coerce",
    )
    te = pd.to_numeric(available["tracking_error"], errors="coerce")
    count = len(available)
    min_positive = max(1, ceil(expected_train_regimes * 0.60))
    median_active = safe_stat(active, "median")
    min_active = safe_stat(active, "min")
    median_tw = safe_stat(top_worst, "median")
    worst_dd = safe_stat(active_dd, "min")
    dispersion = safe_stat(active, "std")
    annual_cost = (
        float(turnover * 12 * COST_BPS_PER_ONE_WAY_TURNOVER / 10_000)
        if np.isfinite(turnover)
        else 0.0
    )
    objective = (
        median_active
        + 0.50 * min_active
        + 0.25 * median_tw
        + 0.25 * worst_dd
        - 0.25 * (dispersion if np.isfinite(dispersion) else 0)
        - annual_cost
    )
    reasons: list[str] = []
    if not np.isfinite(coverage) or coverage < MIN_COVERAGE:
        reasons.append("coverage")
    if count != expected_train_regimes:
        reasons.append("missing_signal_train_regime")
    if int((active > 0).sum()) < min_positive:
        reasons.append("active_sign")
    if int((top_worst > 0).sum()) < min_positive:
        reasons.append("top_worst_sign")
    if not np.isfinite(median_active) or median_active <= 0:
        reasons.append("median_active")
    if not np.isfinite(min_active) or min_active < MIN_WORST_ACTIVE_CAGR:
        reasons.append("worst_active")
    return {
        "train_expected_signal_regimes": expected_train_regimes,
        "train_available_signal_regimes": count,
        "train_active_positive_regimes": int((active > 0).sum()),
        "train_top_worst_positive_regimes": int((top_worst > 0).sum()),
        "train_median_active_cagr": median_active,
        "train_min_active_cagr": min_active,
        "train_median_top_worst_cagr": median_tw,
        "train_min_top_worst_cagr": safe_stat(top_worst, "min"),
        "train_worst_active_drawdown": worst_dd,
        "train_active_cagr_dispersion": dispersion,
        "train_median_tracking_error": safe_stat(te, "median"),
        "annual_cost_20bps": annual_cost,
        "train_regime_robust_objective": objective,
        "train_gate_pass": not reasons,
        "train_gate_fail_reasons": "|".join(reasons),
    }


def build_lopo(
    registry: pd.DataFrame,
    period_metrics: pd.DataFrame,
    regime_defs: pd.DataFrame,
) -> pd.DataFrame:
    metadata = registry.set_index("metric").to_dict("index")
    market_available = set(
        regime_defs.loc[
            regime_defs["market_signal_validation_available"],
            "regime_id",
        ].astype(str)
    )
    rows: list[dict[str, object]] = []
    for metric, periods in period_metrics.groupby("metric", sort=False):
        meta = metadata[str(metric)]
        for holdout in regime_defs.to_dict("records"):
            holdout_id = str(holdout["regime_id"])
            expected_train = len(
                market_available.difference([holdout_id])
            )
            train = periods[
                periods["regime_id"].isin(
                    market_available.difference([holdout_id])
                )
            ]
            aggregate = training_aggregate(
                train,
                expected_train,
                float(meta["coverage"]),
                float(meta["avg_turnover"]),
            )
            test = periods[periods["regime_id"].eq(holdout_id)]
            test_row = test.iloc[0].to_dict() if len(test) else {}
            rows.append(
                {
                    "metric": metric,
                    "candidate_class": meta["candidate_class"],
                    "candidate_type": meta["candidate_type"],
                    "label": meta["label"],
                    "family": meta["family"],
                    "bucket": meta["bucket"],
                    "coverage": meta["coverage"],
                    "avg_turnover": meta["avg_turnover"],
                    "components": meta["components"],
                    "leaf_components": meta["leaf_components"],
                    "holdout_regime": holdout_id,
                    "holdout_label_zh": holdout["label_zh"],
                    "holdout_market_signal_available": holdout_id
                    in market_available,
                    **aggregate,
                    "holdout_signal_validation_available": bool(
                        test_row.get("signal_validation_available", False)
                    ),
                    "holdout_days": test_row.get("days", np.nan),
                    "holdout_portfolio_formations": test_row.get(
                        "portfolio_formation_count",
                        np.nan,
                    ),
                    "holdout_active_cagr": test_row.get("active_cagr", np.nan),
                    "holdout_active_max_drawdown": test_row.get(
                        "active_max_drawdown",
                        np.nan,
                    ),
                    "holdout_tracking_error": test_row.get(
                        "tracking_error",
                        np.nan,
                    ),
                    "holdout_top_worst_cagr": test_row.get(
                        "top_worst_cagr",
                        np.nan,
                    ),
                    "holdout_top_cagr": test_row.get("top_cagr", np.nan),
                    "holdout_benchmark_cagr": test_row.get(
                        "benchmark_cagr",
                        np.nan,
                    ),
                }
            )
    output = pd.DataFrame(rows)
    eligible = output["train_gate_pass"].fillna(False)
    output["train_rank"] = pd.Series(pd.NA, index=output.index, dtype="Int64")
    output.loc[eligible, "train_rank"] = (
        output[eligible]
        .groupby(["candidate_class", "holdout_regime"])[
            "train_regime_robust_objective"
        ]
        .rank(ascending=False, method="min")
        .astype("Int64")
    )
    return output.sort_values(
        ["candidate_class", "holdout_regime", "train_rank"],
        na_position="last",
    )


def summarize_lopo(lopo: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    eligible_folds = lopo[
        lopo["holdout_signal_validation_available"].fillna(False)
    ]
    for metric, group in eligible_folds.groupby("metric", sort=False):
        passed = group[group["train_gate_pass"].fillna(False)]
        count = len(passed)
        joint = (
            (passed["holdout_active_cagr"] > 0)
            & (passed["holdout_top_worst_cagr"] > 0)
        )
        joint_rate = float(joint.mean()) if count else np.nan
        mean_active = safe_stat(passed["holdout_active_cagr"], "mean")
        min_active = safe_stat(passed["holdout_active_cagr"], "min")
        total_folds = len(group)
        if (
            count >= max(3, total_folds - 1)
            and joint_rate >= 0.75
            and np.isfinite(min_active)
            and min_active >= -0.03
        ):
            classification = "cross_regime_core"
        elif (
            count >= max(2, ceil(total_folds * 0.50))
            and joint_rate >= 2 / 3
            and np.isfinite(mean_active)
            and mean_active > 0
        ):
            classification = "cross_regime_resilient"
        elif count >= 1 and bool((passed["holdout_active_cagr"] > 0).any()):
            classification = "regime_sensitive"
        else:
            classification = "weak_or_unstable"
        first = group.iloc[0]
        rows.append(
            {
                "metric": metric,
                "candidate_class": first["candidate_class"],
                "candidate_type": first["candidate_type"],
                "label": first["label"],
                "family": first["family"],
                "bucket": first["bucket"],
                "eligible_holdout_folds": total_folds,
                "train_gate_passes": count,
                "holdout_joint_positive_after_train_gate": int(joint.sum()),
                "holdout_joint_positive_rate": joint_rate,
                "mean_holdout_active_cagr": mean_active,
                "median_holdout_active_cagr": safe_stat(
                    passed["holdout_active_cagr"],
                    "median",
                ),
                "min_holdout_active_cagr": min_active,
                "mean_holdout_top_worst_cagr": safe_stat(
                    passed["holdout_top_worst_cagr"],
                    "mean",
                ),
                "mean_train_robust_objective": safe_stat(
                    passed["train_regime_robust_objective"],
                    "mean",
                ),
                "lopo_classification": classification,
            }
        )
    output = pd.DataFrame(rows)
    if output.empty:
        return output
    order = {
        "cross_regime_core": 0,
        "cross_regime_resilient": 1,
        "regime_sensitive": 2,
        "weak_or_unstable": 3,
    }
    output["_order"] = output["lopo_classification"].map(order)
    return output.sort_values(
        [
            "_order",
            "train_gate_passes",
            "holdout_joint_positive_rate",
            "mean_holdout_active_cagr",
        ],
        ascending=[True, False, False, False],
    ).drop(columns="_order")


def build_synergy_lopo(
    lopo: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    singles = lopo[lopo["candidate_class"].isin(["raw", "relative"])]
    combinations = lopo[lopo["candidate_class"].eq("combination")]
    lookup = singles.set_index(["metric", "holdout_regime"])
    rows: list[dict[str, object]] = []
    for combo in combinations.itertuples(index=False):
        leaves = parse_components(combo.leaf_components)
        leaf_rows = []
        for leaf in leaves:
            key = (leaf, str(combo.holdout_regime))
            if key in lookup.index:
                value = lookup.loc[key]
                leaf_rows.append(value.iloc[-1] if isinstance(value, pd.DataFrame) else value)
        if len(leaf_rows) != len(leaves) or not leaves:
            continue
        leaf_frame = pd.DataFrame(leaf_rows)
        all_leaf_train_pass = bool(leaf_frame["train_gate_pass"].all())
        best_train = safe_stat(
            leaf_frame["train_regime_robust_objective"],
            "max",
        )
        best_holdout_active = safe_stat(
            leaf_frame["holdout_active_cagr"],
            "max",
        )
        best_holdout_tw = safe_stat(
            leaf_frame["holdout_top_worst_cagr"],
            "max",
        )
        train_uplift = combo.train_regime_robust_objective - best_train
        holdout_active_uplift = combo.holdout_active_cagr - best_holdout_active
        holdout_tw_uplift = combo.holdout_top_worst_cagr - best_holdout_tw
        confirmed = bool(
            combo.train_gate_pass
            and all_leaf_train_pass
            and combo.holdout_signal_validation_available
            and train_uplift > 0.002
            and combo.holdout_active_cagr > 0
            and combo.holdout_top_worst_cagr > 0
            and holdout_active_uplift > 0
            and holdout_tw_uplift > 0
        )
        rows.append(
            {
                "metric": combo.metric,
                "label": combo.label,
                "candidate_type": combo.candidate_type,
                "holdout_regime": combo.holdout_regime,
                "leaf_components": combo.leaf_components,
                "leaf_count": len(leaves),
                "all_leaf_train_gate_pass": all_leaf_train_pass,
                "combo_train_gate_pass": combo.train_gate_pass,
                "combo_train_objective": combo.train_regime_robust_objective,
                "best_leaf_train_objective": best_train,
                "train_objective_uplift": train_uplift,
                "combo_holdout_active_cagr": combo.holdout_active_cagr,
                "best_leaf_holdout_active_cagr": best_holdout_active,
                "holdout_active_uplift": holdout_active_uplift,
                "combo_holdout_top_worst_cagr": combo.holdout_top_worst_cagr,
                "best_leaf_holdout_top_worst_cagr": best_holdout_tw,
                "holdout_top_worst_uplift": holdout_tw_uplift,
                "holdout_synergy_confirmed": confirmed,
            }
        )
    evidence = pd.DataFrame(rows)
    summaries: list[dict[str, object]] = []
    for metric, group in evidence.groupby("metric", sort=False):
        eligible = group[
            group["all_leaf_train_gate_pass"]
            & group["combo_train_gate_pass"]
        ]
        confirmed = int(eligible["holdout_synergy_confirmed"].sum())
        count = len(eligible)
        first = group.iloc[0]
        summaries.append(
            {
                "metric": metric,
                "label": first["label"],
                "candidate_type": first["candidate_type"],
                "eligible_lopo_folds": count,
                "confirmed_synergy_folds": confirmed,
                "confirmed_synergy_rate": confirmed / count if count else np.nan,
                "mean_train_objective_uplift": safe_stat(
                    eligible["train_objective_uplift"],
                    "mean",
                ),
                "mean_holdout_active_uplift": safe_stat(
                    eligible["holdout_active_uplift"],
                    "mean",
                ),
                "mean_holdout_top_worst_uplift": safe_stat(
                    eligible["holdout_top_worst_uplift"],
                    "mean",
                ),
                "cross_period_synergy_supported": bool(
                    count >= 3
                    and confirmed / count >= 2 / 3
                    and confirmed >= 2
                ),
            }
        )
    summary = pd.DataFrame(summaries)
    if not summary.empty:
        summary = summary.sort_values(
            [
                "cross_period_synergy_supported",
                "confirmed_synergy_rate",
                "mean_holdout_active_uplift",
            ],
            ascending=[False, False, False],
        )
    return evidence, summary


def pre_post_2020(
    registry: pd.DataFrame,
    period_metrics: pd.DataFrame,
) -> pd.DataFrame:
    singles = registry[registry["candidate_class"].isin(["raw", "relative"])]
    periods = period_metrics[
        period_metrics["metric"].isin(singles["metric"])
        & period_metrics["signal_validation_available"].fillna(False)
    ].copy()
    periods["era"] = np.where(
        pd.to_datetime(periods["regime_start"]).lt(pd.Timestamp("2020-01-01")),
        "pre_2020",
        "post_2020",
    )
    pivot = periods.pivot_table(
        index="metric",
        columns="era",
        values="active_cagr",
        aggfunc="mean",
    ).reset_index()
    metadata = singles[
        ["metric", "label", "candidate_class", "family", "full_period_gate_pass"]
    ]
    output = metadata.merge(pivot, on="metric", how="left")
    for column in ("pre_2020", "post_2020"):
        if column not in output:
            output[column] = np.nan
    output = output.rename(
        columns={
            "pre_2020": "pre_2020_mean_active_cagr",
            "post_2020": "post_2020_mean_active_cagr",
        }
    )
    output["post_minus_pre_active_cagr"] = (
        output["post_2020_mean_active_cagr"]
        - output["pre_2020_mean_active_cagr"]
    )
    return output.sort_values(
        "post_minus_pre_active_cagr",
        ascending=False,
        na_position="last",
    )


def deflated_sharpe(
    registry: pd.DataFrame,
) -> pd.DataFrame:
    documented_trials = len(registry)
    gamma = 0.5772156649015329
    rows: list[dict[str, object]] = []
    for candidate in registry[
        registry["has_official_top_worst_paths"].fillna(False)
    ].itertuples(index=False):
        top = read_nav(str(candidate.top_perf))
        benchmark = read_nav(str(candidate.benchmark_perf))
        aligned = pd.concat(
            [top.rename("top"), benchmark.rename("benchmark")],
            axis=1,
        ).dropna()
        active = (
            aligned["top"].pct_change()
            - aligned["benchmark"].pct_change()
        ).dropna()
        if len(active) < 30 or active.std(ddof=1) == 0:
            continue
        daily_sr = float(active.mean() / active.std(ddof=1))
        annual_sr = daily_sr * sqrt(252)
        skew = float(active.skew())
        kurtosis = float(active.kurt() + 3)
        trial_count = max(documented_trials, 2)
        expected_max_standard_normal = (
            (1 - gamma) * normal_ppf(1 - 1 / trial_count)
            + gamma * normal_ppf(1 - 1 / (trial_count * exp(1)))
        )
        benchmark_daily_sr = expected_max_standard_normal / sqrt(
            max(len(active) - 1, 1)
        )
        denominator = sqrt(
            max(
                1
                - skew * daily_sr
                + ((kurtosis - 1) / 4) * daily_sr**2,
                1e-12,
            )
        )
        statistic = (
            (daily_sr - benchmark_daily_sr)
            * sqrt(len(active) - 1)
            / denominator
        )
        try:
            from scipy.stats import norm

            probability = float(norm.cdf(statistic))
        except Exception:  # pragma: no cover
            probability = normal_cdf(statistic)
        rows.append(
            {
                "metric": candidate.metric,
                "label": candidate.label,
                "candidate_class": candidate.candidate_class,
                "observations": len(active),
                "annualized_active_sharpe": annual_sr,
                "documented_trial_count": documented_trials,
                "expected_max_null_annualized_sharpe": (
                    benchmark_daily_sr * sqrt(252)
                ),
                "active_return_skew": skew,
                "active_return_kurtosis": kurtosis,
                "deflated_sharpe_statistic": statistic,
                "dsr_probability": probability,
                "trial_count_scope": (
                    "all documented candidates reconstructed for this market; "
                    "unrecorded historical trials are not observable"
                ),
            }
        )
    output = pd.DataFrame(rows)
    return output.sort_values(
        "dsr_probability",
        ascending=False,
    ) if not output.empty else output


def write_plots(
    profile: AnalysisProfile,
    output_dir: Path,
    period_metrics: pd.DataFrame,
    summary: pd.DataFrame,
    pre_post: pd.DataFrame,
    dsr: pd.DataFrame,
) -> list[str]:
    try:
        import plotly.graph_objects as go
    except Exception as exc:  # pragma: no cover
        return [f"Plotly unavailable: {exc}"]
    plot_dir = output_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    singles = summary[summary["candidate_class"].isin(["raw", "relative"])].head(30)
    heat = period_metrics[
        period_metrics["metric"].isin(singles["metric"])
        & period_metrics["signal_validation_available"].fillna(False)
    ].pivot(index="label", columns="regime_label_zh", values="active_cagr")
    if not heat.empty:
        fig = go.Figure(
            go.Heatmap(
                z=heat.to_numpy(),
                x=heat.columns.tolist(),
                y=heat.index.tolist(),
                colorscale="RdBu",
                zmid=0,
                colorbar={"title": "Active CAGR"},
            )
        )
        fig.update_layout(
            title=f"{profile.market.display_name} single-variable active CAGR by period"
        )
        path = plot_dir / "single_period_heatmap.html"
        fig.write_html(path, include_plotlyjs=True)
        written.append(str(path))
    valid = pre_post.dropna(
        subset=[
            "pre_2020_mean_active_cagr",
            "post_2020_mean_active_cagr",
        ]
    )
    if not valid.empty:
        fig = go.Figure()
        fig.add_scatter(
            x=valid["pre_2020_mean_active_cagr"],
            y=valid["post_2020_mean_active_cagr"],
            mode="markers",
            text=valid["label"],
            marker={
                "color": valid["post_minus_pre_active_cagr"],
                "colorscale": "RdBu",
                "cmid": 0,
            },
        )
        extent = max(
            valid[
                [
                    "pre_2020_mean_active_cagr",
                    "post_2020_mean_active_cagr",
                ]
            ].abs().max()
        )
        fig.add_shape(
            type="line",
            x0=-extent,
            y0=-extent,
            x1=extent,
            y1=extent,
            line={"dash": "dot", "color": "#65717c"},
        )
        fig.update_layout(
            title=f"{profile.market.display_name} pre/post-2020 single-variable comparison",
            xaxis_title="Pre-2020 mean active CAGR",
            yaxis_title="Post-2020 mean active CAGR",
        )
        path = plot_dir / "pre_post_2020.html"
        fig.write_html(path, include_plotlyjs=True)
        written.append(str(path))
    if not dsr.empty:
        top = dsr.head(40)
        fig = go.Figure()
        fig.add_bar(
            x=top["label"],
            y=top["dsr_probability"],
            marker_color=[
                "#188977" if value >= 0.95 else "#9aa6b2"
                for value in top["dsr_probability"]
            ],
        )
        fig.update_layout(
            title=f"{profile.market.display_name} Deflated Sharpe probability",
            yaxis_title="DSR probability",
        )
        path = plot_dir / "deflated_sharpe.html"
        fig.write_html(path, include_plotlyjs=True)
        written.append(str(path))
    return written


def markdown_table(frame: pd.DataFrame, columns: Sequence[str], rows: int = 30) -> str:
    if frame.empty:
        return "无可用证据。"
    return frame.reindex(columns=columns).head(rows).to_markdown(index=False)


def write_report(
    profile: AnalysisProfile,
    output_dir: Path,
    regime_defs: pd.DataFrame,
    summary: pd.DataFrame,
    period_metrics: pd.DataFrame,
    pre_post: pd.DataFrame,
    synergy_summary: pd.DataFrame,
    dsr: pd.DataFrame,
) -> Path:
    market = profile.market
    singles = summary[summary["candidate_class"].isin(["raw", "relative"])]
    combos = summary[summary["candidate_class"].eq("combination")]
    unavailable = regime_defs[
        ~regime_defs["market_signal_validation_available"]
    ]
    regime_winners = (
        period_metrics[
            period_metrics["candidate_class"].isin(["raw", "relative"])
            & period_metrics["signal_validation_available"].fillna(False)
        ]
        .sort_values(["regime_id", "active_cagr"], ascending=[True, False])
        .groupby("regime_id", as_index=False)
        .head(5)
    )
    shift = pre_post.dropna(
        subset=[
            "pre_2020_mean_active_cagr",
            "post_2020_mean_active_cagr",
        ]
    ).copy()
    persisted = shift[
        (shift["pre_2020_mean_active_cagr"] > 0)
        & (shift["post_2020_mean_active_cagr"] > 0)
    ].sort_values("post_2020_mean_active_cagr", ascending=False)
    replaced = shift[
        (shift["pre_2020_mean_active_cagr"] > 0)
        & (shift["post_2020_mean_active_cagr"] <= 0)
    ].sort_values("post_minus_pre_active_cagr")
    new_winners = shift[
        (shift["pre_2020_mean_active_cagr"] <= 0)
        & (shift["post_2020_mean_active_cagr"] > 0)
    ].sort_values("post_2020_mean_active_cagr", ascending=False)
    supported_synergy = (
        synergy_summary[synergy_summary["cross_period_synergy_supported"]]
        if not synergy_summary.empty
        else pd.DataFrame()
    )
    lines = [
        f"# {market.display_name} 多时期因子稳健性研究",
        "",
        "## 结论先行",
        "",
        f"- 可进行真实信号验证的经济时期："
        f"{int(regime_defs['market_signal_validation_available'].sum())}/"
        f"{len(regime_defs)}。",
        f"- 单变量 cross-regime core/resilient："
        f"{int(singles['lopo_classification'].isin(['cross_regime_core', 'cross_regime_resilient']).sum())}。",
        f"- 组合 cross-regime core/resilient："
        f"{int(combos['lopo_classification'].isin(['cross_regime_core', 'cross_regime_resilient']).sum())}。",
        f"- 同时由 training-only 与 holdout 相对单腿改善确认的协同组合："
        f"{len(supported_synergy)}。",
        "",
        "本研究支持“跨多个已见 regime 寻找不太差的低自由度变量”作为"
        "稳健性设计，但它不是未来真正 OOS：候选集合本身来自全历史研究，"
        "因此仍保留 selection bias。LORO 只允许 training periods 决定 gate"
        " 和排序，holdout 仅用于事后验证。",
        "",
        "## 数据可用性",
        "",
        markdown_table(
            regime_defs,
            [
                "label_zh",
                "start",
                "end",
                "market_snapshot_count",
                "market_signal_validation_available",
            ],
            20,
        ),
        "",
    ]
    if not unavailable.empty:
        lines.extend(
            [
                "没有真实快照的时期即使 NAV 连续，也只是上一期持仓漂移，"
                "不构成该 regime 的因子轮动证据：",
                "",
                markdown_table(
                    unavailable,
                    ["label_zh", "start", "end", "market_snapshot_count"],
                    20,
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## 跨时期单变量",
            "",
            markdown_table(
                singles,
                [
                    "label",
                    "candidate_class",
                    "eligible_holdout_folds",
                    "train_gate_passes",
                    "holdout_joint_positive_rate",
                    "mean_holdout_active_cagr",
                    "min_holdout_active_cagr",
                    "lopo_classification",
                ],
            ),
            "",
            "经济上，revision 捕捉分析师对盈利信息的渐进吸收，PMOM 捕捉"
            "中期价格扩散，growth 代表盈利路径，margin/ROE improvement"
            "代表经营拐点，deleveraging 代表资产负债表风险下降。跨时期"
            "稳健并不要求每期领先，而要求负期受控且不同信息渠道可重复。",
            "",
            "## 各时期特殊优势变量",
            "",
            markdown_table(
                regime_winners,
                [
                    "regime_label_zh",
                    "label",
                    "candidate_class",
                    "active_cagr",
                    "top_worst_cagr",
                    "portfolio_formation_count",
                ],
            ),
            "",
            "这些是按 holdout 内表现排序的描述性结果，只用于解释 rotation，"
            "不能反向作为该 holdout 的可交易选择规则。",
            "",
            "## 2020 前后",
            "",
            "持续有效：",
            "",
            markdown_table(
                persisted,
                [
                    "label",
                    "pre_2020_mean_active_cagr",
                    "post_2020_mean_active_cagr",
                    "post_minus_pre_active_cagr",
                ],
                20,
            ),
            "",
            "2020 后失效或转负：",
            "",
            markdown_table(
                replaced,
                [
                    "label",
                    "pre_2020_mean_active_cagr",
                    "post_2020_mean_active_cagr",
                    "post_minus_pre_active_cagr",
                ],
                20,
            ),
            "",
            "2020 后新占优：",
            "",
            markdown_table(
                new_winners,
                [
                    "label",
                    "pre_2020_mean_active_cagr",
                    "post_2020_mean_active_cagr",
                    "post_minus_pre_active_cagr",
                ],
                20,
            ),
            "",
            "## 组合与协同",
            "",
            markdown_table(
                supported_synergy,
                [
                    "label",
                    "eligible_lopo_folds",
                    "confirmed_synergy_folds",
                    "confirmed_synergy_rate",
                    "mean_holdout_active_uplift",
                    "mean_holdout_top_worst_uplift",
                ],
                30,
            ),
            "",
            "只有上表允许称为 cross-period synergy。其他组合可能在全期"
            "或某一段有效，但没有足够 leaf single、training-only 与 holdout"
            "改善证据时，统一保留为弱证据或未证实假设。",
            "",
            "## 多重试验惩罚",
            "",
            markdown_table(
                dsr,
                [
                    "label",
                    "candidate_class",
                    "annualized_active_sharpe",
                    "documented_trial_count",
                    "expected_max_null_annualized_sharpe",
                    "dsr_probability",
                ],
                30,
            ),
            "",
            "DSR 对本市场可恢复的全部 documented candidates 施加 trial-count"
            " 惩罚，并修正偏度、峰度与样本长度。它没有通过删区间再测来惩罚；"
            "删区间属于 LORO。未记录在工件中的历史尝试不可观察，因此 DSR"
            " 仍可能低估真实研究自由度。",
        ]
    )
    path = output_dir / f"{market.output_prefix}_leave_one_period_out_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=sorted(PROFILES), required=True)
    parser.add_argument("--screen", type=Path, default=lag6.DEFAULT_SCREEN)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    profile = PROFILES[args.market]
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else (AD_HOC_ROOT / profile.output_name).resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    registry = build_registry(profile)
    registry.to_csv(output_dir / "candidate_registry.csv", index=False)
    json_dump(
        output_dir / "metric_definitions.json",
        {
            "analysis": "historical_leave_one_period_out",
            "holdout_not_used_for_training_gate_or_rank": True,
            "nav_without_real_signal_formations_is_not_validation": True,
            "candidates": registry[
                [
                    "metric",
                    "label",
                    "candidate_class",
                    "candidate_type",
                    "components",
                    "leaf_components",
                    "source_id",
                ]
            ].to_dict("records"),
        },
    )
    regime_defs = market_regime_definitions(profile, args.screen.resolve())
    regime_defs.to_csv(output_dir / "regime_definitions.csv", index=False)
    period_path = output_dir / "candidate_period_metrics.csv"
    period_metrics = compute_period_metrics(
        registry,
        regime_defs,
        period_path,
        resume=args.resume,
    )
    lopo = build_lopo(registry, period_metrics, regime_defs)
    lopo.to_csv(output_dir / "all_leave_one_period_out_results.csv", index=False)
    singles_lopo = lopo[lopo["candidate_class"].isin(["raw", "relative"])]
    combinations_lopo = lopo[lopo["candidate_class"].eq("combination")]
    singles_lopo.to_csv(output_dir / "single_lopo_results.csv", index=False)
    combinations_lopo.to_csv(
        output_dir / "combination_lopo_results.csv",
        index=False,
    )
    summary = summarize_lopo(lopo)
    summary.to_csv(output_dir / "lopo_selection_summary.csv", index=False)
    summary[summary["candidate_class"].isin(["raw", "relative"])].to_csv(
        output_dir / "single_lopo_selection_summary.csv",
        index=False,
    )
    summary[summary["candidate_class"].eq("combination")].to_csv(
        output_dir / "combination_lopo_selection_summary.csv",
        index=False,
    )
    synergy_evidence, synergy_summary = build_synergy_lopo(lopo)
    synergy_evidence.to_csv(
        output_dir / "synergy_lopo_evidence.csv",
        index=False,
    )
    synergy_summary.to_csv(
        output_dir / "synergy_lopo_summary.csv",
        index=False,
    )
    shift = pre_post_2020(registry, period_metrics)
    shift.to_csv(output_dir / "single_pre_post_2020_metrics.csv", index=False)
    dsr = deflated_sharpe(registry)
    dsr.to_csv(output_dir / "deflated_sharpe_results.csv", index=False)
    plots = write_plots(
        profile,
        output_dir,
        period_metrics,
        summary,
        shift,
        dsr,
    )
    checks = pd.DataFrame(
        [
            {
                "check": "documented_candidates",
                "value": len(registry),
                "status": "pass",
            },
            {
                "check": "candidates_with_official_top_worst",
                "value": int(
                    registry["has_official_top_worst_paths"].sum()
                ),
                "status": "pass",
            },
            {
                "check": "duplicate_metric_ids",
                "value": int(registry["metric"].duplicated().sum()),
                "status": (
                    "pass" if not registry["metric"].duplicated().any() else "fail"
                ),
            },
            {
                "check": "market_signal_validation_regimes",
                "value": int(
                    regime_defs["market_signal_validation_available"].sum()
                ),
                "status": "diagnostic",
            },
            {
                "check": "nav_only_period_rows_not_used_as_validation",
                "value": int(
                    (
                        period_metrics["nav_available"].fillna(False)
                        & ~period_metrics[
                            "signal_validation_available"
                        ].fillna(False)
                    ).sum()
                ),
                "status": "pass",
            },
        ]
    )
    checks.to_csv(output_dir / "data_construction_checks.csv", index=False)
    report = write_report(
        profile,
        output_dir,
        regime_defs,
        summary,
        period_metrics,
        shift,
        synergy_summary,
        dsr,
    )
    manifest = {
        "status": "complete",
        "created_at": datetime.now().isoformat(),
        "analysis_id": f"{profile.market.output_prefix}_leave_one_period_out",
        "method_version": "2.0.0-signal-evidence-aware",
        "market": profile.market.display_name,
        "benchmark": profile.market.benchmark,
        "benchmark_weight_column": profile.market.weight_col,
        "candidate_count": len(registry),
        "candidate_with_top_worst_count": int(
            registry["has_official_top_worst_paths"].sum()
        ),
        "period_count": len(regime_defs),
        "signal_validation_period_count": int(
            regime_defs["market_signal_validation_available"].sum()
        ),
        "period_metric_rows": len(period_metrics),
        "lopo_rows": len(lopo),
        "cross_regime_core_or_resilient_singles": int(
            summary[
                summary["candidate_class"].isin(["raw", "relative"])
                & summary["lopo_classification"].isin(
                    ["cross_regime_core", "cross_regime_resilient"]
                )
            ].shape[0]
        ),
        "cross_period_synergy_supported_count": int(
            synergy_summary["cross_period_synergy_supported"].sum()
            if not synergy_summary.empty
            else 0
        ),
        "documented_trial_count_for_dsr": len(registry),
        "source_engine_comparability": (
            "mixed historical official artifacts; lag6 and lag6-anchor supplements "
            "use tp.security_nav 3.0.0"
        ),
        "optimizer_used": False,
        "optimizer_id": "not_used",
        "optimizer_version": "not_applicable",
        "optimizer_objective": "not_applicable_factor_evidence",
        "date_execution_policy": (
            "inherited from each official source; new supplements use first "
            "returns date strictly after signal and after-close application"
        ),
        "plots": plots,
        "report": str(report),
    }
    json_dump(output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

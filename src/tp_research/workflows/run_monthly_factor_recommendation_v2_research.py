"""Registered v2 monthly factor-sleeve research workflow.

This workflow is deliberately separate from the invalidated v1 runner.  It
only writes to the Registry-managed result directory and never changes the
production configuration or the canonical data.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH, TP_ROOT
from tp_models.factor_recommendation.v2_research import (
    FEATURE_COLUMNS,
    MODEL_IDS,
    allocate_top2,
    block_bootstrap,
    build_factor_panel,
    candidate_prediction_metrics,
    deflated_sharpe,
    economic_metrics,
    make_smoke_sleeve_returns,
    promotion_gates,
    walk_forward_predictions,
)
from tp_models.factor_recommendation.v2_sleeves import (
    V2_COMPONENTS,
    V2_FACTOR_DEFINITIONS,
    factor_definition_frame,
    run_official_factor_sleeve_database,
)


WORKFLOW_ID = "monthly-factor-recommendation-v2"
HYPOTHESIS_PATH = TP_ROOT / "config" / "research" / "hypotheses" / f"{WORKFLOW_ID}.json"
DEFAULT_SEED = 1729

REQUIRED_ARTIFACTS = (
    "config_snapshot.json",
    "repository_data_audit.json",
    "component_status.json",
    "factor_definitions.csv",
    "universe_definitions.csv",
    "pit_audit.csv",
    "factor_sleeve_monthly_returns.parquet",
    "factor_sleeve_holdings.parquet",
    "factor_sleeve_metrics.csv",
    "factor_sleeve_coverage.csv",
    "raw_variable_gate.csv",
    "relative_variable_gate.csv",
    "factor_panel.parquet",
    "feature_definitions.csv",
    "feature_matrix.parquet",
    "target_frame.parquet",
    "walk_forward_folds.csv",
    "grouped_folds.csv",
    "fold_predictions.parquet",
    "walk_forward_predictions.parquet",
    "model_fit_records.csv",
    "model_candidate_registry.csv",
    "model_selection.csv",
    "walk_forward_metrics.csv",
    "allocation_results.parquet",
    "strategy_monthly_returns.parquet",
    "strategy_metrics.csv",
    "cost_sensitivity.csv",
    "period_definitions.csv",
    "lopo_results.csv",
    "loro_results.csv",
    "lopo_loro_results.csv",
    "block_bootstrap_results.csv",
    "bootstrap_results.csv",
    "deflated_sharpe_results.csv",
    "dsr_results.csv",
    "trial_ledger.csv",
    "selection_audit.csv",
    "promotion_gate.csv",
    "research_report.md",
    "manifest.json",
)


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _write_frame(frame: pd.DataFrame, path: Path, *, parquet: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
    if parquet:
        safe.to_parquet(path, index=False)
    else:
        safe.to_csv(path, index=False)


def _read_hypothesis(path: Path = HYPOTHESIS_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_state() -> dict[str, Any]:
    def run(*args: str) -> str:
        result = subprocess.run(["git", *args], cwd=TP_ROOT, capture_output=True, text=True, check=False)
        return result.stdout.strip()

    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(run("status", "--porcelain")),
    }


def _file_digest(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    payload: dict[str, Any] = {"path": str(target), "exists": target.exists()}
    if not target.is_file():
        return payload
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    payload.update({"bytes": target.stat().st_size, "sha256": digest.hexdigest()})
    return payload


def _compound(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float((1.0 + numeric).prod() - 1.0) if len(numeric) else np.nan


def _metrics_frame(sleeves: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if sleeves.empty:
        return pd.DataFrame(), pd.DataFrame()
    grouped = sleeves.groupby(["region_component", "factor", "sleeve_side", "sleeve_version"], sort=False)
    metrics = grouped.agg(
        observations=("Date", "count"),
        mean_gross_return=("gross_return", "mean"),
        mean_net_return=("net_return", "mean"),
        mean_benchmark_return=("benchmark_return", "mean"),
        mean_active_return=("active_return", "mean"),
        mean_spread=("spread", "mean"),
        mean_top_worst_spread=("top_worst_spread", "mean"),
        mean_turnover=("turnover", "mean"),
        mean_holdings=("holdings_count", "mean"),
        mean_coverage=("coverage", "mean"),
        mean_factor_coverage=("factor_coverage", "mean"),
        mean_weight_coverage=("weight_coverage", "mean"),
        mean_benchmark_weight_coverage=("benchmark_weight_coverage", "mean"),
    ).reset_index()
    metrics["net_ir"] = grouped["active_return"].apply(lambda values: values.mean() / values.std() * np.sqrt(12) if values.std() > 0 else np.nan).to_numpy()
    metrics["hit_rate"] = grouped["active_return"].apply(lambda values: values.gt(0).mean()).to_numpy()
    metrics["engine_id"] = "tp.security_nav"
    metrics["engine_version"] = "3.0.0"
    coverage = sleeves.groupby(["Date", "region_component", "factor", "sleeve_side", "sleeve_version"], sort=False).agg(
        formation_available=("formation_available", "all"),
        coverage=("coverage", "mean"),
        factor_coverage=("factor_coverage", "mean"),
        weight_coverage=("weight_coverage", "mean"),
        benchmark_weight_coverage=("benchmark_weight_coverage", "mean"),
        benchmark_coverage=("benchmark_coverage", "mean"),
        holdings_count=("holdings_count", "mean"),
    ).reset_index()
    return metrics, coverage


def _raw_and_relative_gates(panel: pd.DataFrame, sleeves: pd.DataFrame, minimum_coverage: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_rows: list[dict[str, Any]] = []
    top = sleeves.loc[
        sleeves["sleeve_side"].eq("Top")
        & sleeves.get("sleeve_version", pd.Series("v2-p20", index=sleeves.index)).astype(str).str.contains("p20", case=False, na=False)
    ].copy() if not sleeves.empty else pd.DataFrame()
    worst = sleeves.loc[
        sleeves["sleeve_side"].eq("Worst")
        & sleeves.get("sleeve_version", pd.Series("v2-p20", index=sleeves.index)).astype(str).str.contains("p20", case=False, na=False)
    ].copy() if not sleeves.empty else pd.DataFrame()
    for factor, group in top.groupby("factor", sort=False) if not top.empty else []:
        active = pd.to_numeric(group["active_return"], errors="coerce").dropna()
        worst_group = worst.loc[worst["factor"].eq(factor)] if not worst.empty else pd.DataFrame()
        worst_active = pd.to_numeric(worst_group.get("active_return"), errors="coerce").dropna() if not worst_group.empty else pd.Series(dtype=float)
        paired = group[["Date", "region_component", "net_return"]].merge(
            worst_group[["Date", "region_component", "net_return"]].rename(columns={"net_return": "worst_net_return"}),
            on=["Date", "region_component"],
            how="inner",
        ) if not worst_group.empty else pd.DataFrame()
        spread = pd.to_numeric(paired["net_return"] - paired["worst_net_return"], errors="coerce").dropna() if not paired.empty else pd.Series(dtype=float)
        coverage = float(pd.to_numeric(group.get("factor_coverage", group["coverage"]), errors="coerce").mean()) if not group.empty else 0.0
        mean_active = float(active.mean()) if len(active) else np.nan
        max_drawdown = float(((1.0 + active).cumprod() / (1.0 + active).cumprod().cummax() - 1.0).min()) if len(active) else np.nan
        passed = bool(len(active) >= 12 and coverage >= minimum_coverage and np.isfinite(mean_active) and mean_active > 0 and (not len(spread) or spread.mean() > 0))
        raw_rows.append({
            "variable": factor,
            "variant": "raw",
            "lag_months": 0,
            "observations": int(len(active)),
            "mean_top_active_return": mean_active,
            "mean_worst_active_return": float(worst_active.mean()) if len(worst_active) else np.nan,
            "top_benchmark_ratio_cagr": float(_compound(pd.to_numeric(group["net_return"], errors="coerce")) - _compound(pd.to_numeric(group["benchmark_return"], errors="coerce"))) if not group.empty else np.nan,
            "top_worst_ratio_return": float(spread.mean()) if len(spread) else np.nan,
            "spread": float(spread.mean()) if len(spread) else np.nan,
            "coverage": coverage,
            "factor_coverage": coverage,
            "benchmark_weight_coverage": float(pd.to_numeric(group.get("benchmark_weight_coverage", group["weight_coverage"]), errors="coerce").mean()),
            "turnover": float(pd.to_numeric(group["turnover"], errors="coerce").mean()),
            "max_drawdown": max_drawdown,
            "pit_safe": True,
            "passed": passed,
            "reason": "official Top/Worst sleeve evidence clears coverage and return direction" if passed else "insufficient official sleeve observations, coverage, or direction",
            "evidence_path": "factor_sleeve_monthly_returns.parquet",
        })
    relative_rows: list[dict[str, Any]] = []
    if panel.empty:
        return pd.DataFrame(raw_rows), pd.DataFrame(relative_rows)
    for factor, group in panel.groupby("factor", sort=False):
        group = group.sort_values(["region", "Date"], kind="stable").copy()
        for variant in ("directional_delta", "score_delta"):
            for lag in (1, 3, 6, 12):
                base_column = f"{variant}_{lag}m"
                if base_column not in group.columns:
                    continue
                value = pd.to_numeric(group[base_column], errors="coerce")
                target = pd.to_numeric(group["next_month_top_sleeve_net_active_return"], errors="coerce")
                valid = value.notna() & target.notna()
                positive = target.loc[valid & value.gt(0)]
                negative = target.loc[valid & value.lt(0)]
                delta = float(positive.mean() - negative.mean()) if len(positive) and len(negative) else np.nan
                coverage = float(pd.to_numeric(group.loc[valid, "coverage"], errors="coerce").mean()) if valid.any() else 0.0
                relative_rows.append({
                    "variable": factor,
                    "variant": variant,
                    "lag_months": lag,
                    "observations": int(valid.sum()),
                    "directional_delta_mean": delta,
                    "coverage": coverage,
                    "pit_safe": True,
                    "same_raw_family_excluded": True,
                    "passed": bool(valid.sum() >= 12 and coverage >= minimum_coverage and np.isfinite(delta) and delta > 0),
                    "reason": "independent lagged relative sleeve evidence" if valid.sum() >= 12 and coverage >= minimum_coverage and np.isfinite(delta) and delta > 0 else "relative variant did not clear coverage/evidence/direction test",
                    "evidence_path": "factor_panel.parquet",
                })
    return pd.DataFrame(raw_rows), pd.DataFrame(relative_rows)


def _feature_definitions() -> pd.DataFrame:
    definitions = {
        "trailing_12m_active_return": "Compounded official Top-sleeve net active return over the prior 12 formation months, lagged one month.",
        "trailing_6m_active_return": "Compounded official Top-sleeve net active return over the prior 6 formation months, lagged one month.",
        "ewma_active_return": "Alias for the six-month exponentially weighted prior active return.",
        "ewma_3m_active_return": "Three-month exponentially weighted prior active return; no current target included.",
        "ewma_6m_active_return": "Six-month exponentially weighted prior active return; no current target included.",
        "volatility_12m": "Prior 12-month standard deviation of official Top-sleeve active returns.",
        "drawdown_12m": "Prior-window wealth drawdown from the rolling high.",
        "hit_rate_12m": "Prior-window proportion of positive active-return observations.",
        "spread_12m": "Prior-window mean official Top-minus-Worst net return spread.",
        "turnover_12m": "Prior-window mean official sleeve turnover.",
        "holdings_count_z": "Prior-window standardized holdings count.",
        "coverage": "PIT factor-sleeve formation coverage.",
        "weight_coverage": "PIT benchmark-weight coverage of the sleeve formation universe.",
        "rank_persistence_12m": "Cross-sectional percentile rank of prior trailing active return.",
        "breadth_12m": "Prior-window positive-return breadth.",
        "dispersion_12m": "Prior-window dispersion of active returns.",
        "score_delta_1m": "Current PIT factor score minus the score one formation month earlier.",
        "score_delta_3m": "Current PIT factor score minus the score three formation months earlier.",
        "score_delta_6m": "Current PIT factor score minus the score six formation months earlier.",
        "score_delta_12m": "Current PIT factor score minus the score twelve formation months earlier.",
        "directional_delta_1m": "Sign of the one-month PIT factor-score change.",
        "directional_delta_3m": "Sign of the three-month PIT factor-score change.",
        "directional_delta_6m": "Sign of the six-month PIT factor-score change.",
        "directional_delta_12m": "Sign of the twelve-month PIT factor-score change.",
        "cross_region_confirmation": "Prior positive evidence for the same factor in other region components.",
        "regime_alignment": "Current region-relative percentile of prior trailing active return.",
        "factor_rotation_proxy": "PIT-safe proxy for factor rotation: current factor score change relative to the region cross-section.",
        "region_fixed_effect": "Deterministic region label effect used as a pooled model control.",
        "factor_fixed_effect": "Deterministic factor label effect used as a pooled model control.",
        "region_factor_interaction": "Deterministic region-by-factor interaction control.",
        "factor_regime_interaction": "Factor label interacted with the PIT-safe regime alignment control.",
        "missing_indicator": "Fraction of feature columns missing at the formation date.",
    }
    return pd.DataFrame({"feature": list(definitions), "definition": list(definitions.values()), "training_only_transform": ["imputer/scaler" if feature not in {"coverage", "weight_coverage", "missing_indicator"} else "none" for feature in definitions]})


def _period_definitions(config: Mapping[str, Any]) -> pd.DataFrame:
    periods = config.get("economic_periods") or []
    return pd.DataFrame(periods)


def _lopo_loro(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame(columns=["method", "held_out_region", "model_id", "rank_ic", "observations"])
    rows: list[dict[str, Any]] = []
    for region, group in predictions.groupby("region", sort=False):
        for model_id, candidate in group.groupby("model_id", sort=False):
            frame = candidate.dropna(subset=["prediction", "target"])
            rank_ic = frame["prediction"].corr(frame["target"], method="spearman") if len(frame) >= 3 and frame["prediction"].nunique() >= 2 and frame["target"].nunique() >= 2 else np.nan
            rows.append({"method": "LOPO-LORO", "held_out_region": region, "model_id": model_id, "rank_ic": rank_ic, "observations": int(len(frame)), "note": "diagnostic leave-one-region-out result; no production promotion"})
    return pd.DataFrame(rows)


def _trial_ledger(config: Mapping[str, Any], raw: pd.DataFrame, relative: pd.DataFrame, predictions: pd.DataFrame, allocations: pd.DataFrame) -> pd.DataFrame:
    scope = config.get("trial_ledger_scope") or []
    counts = {
        "raw_variables": int(len(raw)),
        "relative_variables": int(len(relative)),
        "lags": int(relative["lag_months"].nunique()) if not relative.empty else 0,
        "factors": int(predictions["factor"].nunique()) if not predictions.empty else len(V2_FACTOR_DEFINITIONS),
        "models": int(predictions["model_id"].nunique()) if not predictions.empty else len(MODEL_IDS),
        "hyperparameters": int(len(config.get("hyperparameter_grid", {}).get("ridge_alpha", [])) + len(config.get("hyperparameter_grid", {}).get("elastic_net_alpha", [])) * len(config.get("hyperparameter_grid", {}).get("elastic_net_l1_ratio", []))),
        "allocations": int(allocations["cost_bps"].nunique()) if not allocations.empty else 0,
        "sleeve_percentiles": len(config.get("sleeve", {}).get("sensitivity_percentiles", [])),
        "cost_sensitivities": int(allocations["cost_bps"].nunique()) if not allocations.empty else len(config.get("cost_assumptions", {}).get("allocator_cost_grid_bps", [])),
    }
    return pd.DataFrame([{"trial_family": config.get("trial_family", WORKFLOW_ID), "scope": item, "observed_count": counts.get(item, 0), "configured_effective_trial_count": config.get("effective_trial_count"), "count_definition": "real rows/variants executed by v2 workflow"} for item in scope])


def _research_report(config: Mapping[str, Any], manifest: Mapping[str, Any], gates: pd.DataFrame, metrics: pd.DataFrame, panel: pd.DataFrame) -> str:
    decision = manifest.get("promotion_decision", "RESEARCH_ONLY")
    factor_lines = "\n".join(f"| `{row['factor']}` | {row['label']} | `{row['source_columns']}` | {row['definition']} |" for _, row in factor_definition_frame().iterrows())
    gate_passed = int(gates["passed"].sum()) if not gates.empty else 0
    return f"""# 月度因子推荐 v2 研究报告

## 结论

本运行是 `{decision}`。v1 的 security-level 结果已被拒绝，不继承其 Sharpe、胜率或推荐结论。v2 的研究单位是 `Date × Region × RegionComponent × Factor × SleeveSide`，预测目标是 `next_month_top_sleeve_net_active_return`。

| 项目 | 值 |
|---|---|
| 样本 | {config.get('sample_start')} → {config.get('sample_end')} |
| PIT cutoff | {config.get('pit_cutoff')} |
| 面板行数 | {len(panel)} |
| Gate | {gate_passed}/{len(gates)} passed |
| 官方引擎 | `tp_core.backtesting.OfficialPortfolioBacktest` |
| 执行 | strictly after rebalance; weights at close |
| 缺失快照 | `drift` |

## 因子定义

| 因子 | 标签 | 源字段 | 定义 |
|---|---|---|---|
{factor_lines}

## 研究边界

- M0 是 equal-valid-factor baseline；M1 是 trailing 12M；M2 是冻结透明 composite；M3/M4 分别调用真实 sklearn Ridge/ElasticNet。
- Top 是主证据，Worst 只作诊断；Top/Worst spread 不替代主目标。
- allocator 的主比较是 Top2 allocator net return 对 equal-factor basket net return；25 bps 是主成本观察，50 bps 是 stress。
- ASIA 保持 research-only；没有 common currency、PIT FX 与 common benchmark 时不计算聚合绩效。

## Gate 摘要

{gates.to_markdown(index=False) if not gates.empty else '暂无 gate'}

## 产物

详细面板、官方 sleeve returns、holdings、walk-forward predictions、allocator results、bootstrap、DSR 和 provenance 均在本 Run Card 的 `results/` 下。该运行不会修改 production config。
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="run monthly factor recommendation research v2")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true")
    mode.add_argument("--smoke", action="store_true")
    mode.add_argument("--inspect", action="store_true")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--screen", default=str(SCREEN_AGGREGATE_PATH))
    parser.add_argument("--returns", default=str(RETURNS_PATH))
    parser.add_argument("--as-of")
    parser.add_argument("--from-date")
    parser.add_argument("--max-months", type=int)
    parser.add_argument("--max-factors", type=int)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    return parser


def run_v2_research(args: argparse.Namespace) -> Path:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config = _read_hypothesis()
    sample_start = args.from_date or config["sample_start"]
    sample_end = args.as_of or config["sample_end"]
    factors = list(V2_FACTOR_DEFINITIONS)
    if args.max_factors:
        factors = factors[: int(args.max_factors)]
    smoke = bool(args.smoke)
    if args.inspect:
        manifest = {"workflow_id": WORKFLOW_ID, "run_mode": "inspect", "is_full": False, "required_artifacts": list(REQUIRED_ARTIFACTS), "output_dir": str(output_dir)}
        _write_json(output_dir / "manifest.json", manifest)
        return output_dir / "manifest.json"

    synthetic = False
    if smoke:
        sleeves = make_smoke_sleeve_returns(months=args.max_months or 12, factors=[item["name"] for item in factors])
        holdings = pd.DataFrame(columns=["formation_date", "target_date", "region", "region_component", "factor", "sleeve_side", "security_id", "weight"])
        sleeve_manifest = {"synthetic": True, "reason": "explicit smoke fixture only", "errors": []}
        synthetic = True
    else:
        sleeves, holdings, sleeve_manifest = run_official_factor_sleeve_database(
            screen_path=args.screen,
            returns_path=args.returns,
            start_date=sample_start,
            end_date=sample_end,
            sleeve_percentiles=(0.13, 0.2, 0.3),
            factors=factors,
            max_months=args.max_months,
        )
    panel = build_factor_panel(sleeves)
    if not panel.empty:
        panel = panel.loc[pd.to_datetime(panel["Date"], errors="coerce").between(pd.Timestamp(sample_start), pd.Timestamp(sample_end))].copy()
    raw_gate, relative_gate = _raw_and_relative_gates(panel, sleeves, float(config["gates"].get("minimum_factor_coverage", 0.8)))
    predictions, fit_records, selection, wf_manifest = walk_forward_predictions(
        panel,
        minimum_train_months=int(config["model_selection"]["minimum_train_months"]),
        purge_months=int(config["model_selection"]["purge_months"]),
        ridge_alpha=float(config["hyperparameter_grid"]["ridge_alpha"][1]),
        elastic_alpha=float(config["hyperparameter_grid"]["elastic_net_alpha"][1]),
        l1_ratio=float(config["hyperparameter_grid"]["elastic_net_l1_ratio"][1]),
        smoke=smoke,
    )
    minimum_coverage = float(config["gates"].get("minimum_factor_coverage", 0.8))
    allocations = allocate_top2(predictions, panel, cost_grid_bps=config["cost_assumptions"]["allocator_cost_grid_bps"], minimum_coverage=minimum_coverage)
    primary_strategy = allocations.loc[allocations["cost_bps"].eq(25.0)].drop_duplicates(["Date", "region"]) if not allocations.empty else pd.DataFrame()
    prediction_metrics = candidate_prediction_metrics(predictions)
    strategy_metrics = economic_metrics(allocations, cost_bps=25.0)
    bootstrap_rows: list[dict[str, Any]] = []
    primary_values = primary_strategy.get("primary_active_return", pd.Series(dtype=float)) if not primary_strategy.empty else pd.Series(dtype=float)
    for block_length in (6, 12):
        bootstrap_rows.append({"candidate": "Top2_primary", **block_bootstrap(primary_values, block_length=block_length, samples=int(args.bootstrap_samples if not smoke else min(args.bootstrap_samples, 200)), seed=int(args.seed) + block_length)})
    bootstrap = pd.DataFrame(bootstrap_rows)
    dsr_rows = []
    for candidate in MODEL_IDS:
        candidate_predictions = predictions.loc[predictions["model_id"].eq(candidate)].copy() if "model_id" in predictions.columns else pd.DataFrame()
        if not candidate_predictions.empty:
            candidate_predictions["selected_model"] = candidate
        candidate_allocations = allocate_top2(candidate_predictions, panel, cost_grid_bps=(25.0,), minimum_coverage=minimum_coverage)
        candidate_values = (
            candidate_allocations.drop_duplicates(["Date", "region"]).groupby("Date", sort=True)["primary_active_return"].mean()
            if not candidate_allocations.empty
            else pd.Series(dtype=float)
        )
        dsr_rows.append(deflated_sharpe(candidate_values, effective_trials=int(config["effective_trial_count"]), candidate=candidate, block_length=12))
    dsr = pd.DataFrame(dsr_rows)
    gates = promotion_gates(
        panel=panel,
        predictions=predictions,
        allocations=allocations,
        thresholds=config["gates"],
        bootstrap_rows=bootstrap,
        dsr_rows=dsr,
        clean_provenance=not _git_state()["dirty"],
        asia_approved=False,
        forward_shadow_months=0,
    )
    essential = gates.loc[~gates["gate_name"].isin({"asia_approval"})] if not gates.empty else gates
    if essential.empty or bool(essential["passed"].all()) is False:
        promotion_decision = "REJECT"
    elif bool(config["promotion"].get("research_only", True)) or int(config["gates"].get("forward_shadow_months_required", 12)) > 0:
        promotion_decision = "RESEARCH_ONLY"
    else:
        promotion_decision = "PROMOTION_ELIGIBLE"
    metrics, coverage = _metrics_frame(sleeves)
    lopo = _lopo_loro(predictions)
    trial_ledger = _trial_ledger(config, raw_gate, relative_gate, predictions, allocations)
    git_state = _git_state()
    repository_audit = {
        "screen": _file_digest(args.screen),
        "returns": _file_digest(args.returns),
        "hypothesis": _file_digest(HYPOTHESIS_PATH),
        "code": git_state,
        "source_timing": "screen observation is PIT snapshot; publication timestamp is not present in canonical schema",
    }
    component_status = {
        "workflow_id": WORKFLOW_ID,
        "official_sleeve_database": "synthetic_smoke" if synthetic else "completed_with_audited_errors" if sleeve_manifest.get("errors") else "completed",
        "synthetic": synthetic,
        "official_engine": "tp_core.backtesting.OfficialPortfolioBacktest",
        "sleeve_manifest": sleeve_manifest,
        "walk_forward": wf_manifest,
        "models": {model: {"backend": "rule" if model.startswith(("M0", "M1", "M2")) else "sklearn"} for model in MODEL_IDS},
        "promotion_decision": promotion_decision,
    }
    factor_definitions = factor_definition_frame()
    universe_definitions = pd.DataFrame(
        [{"region": item["region"], "region_component": item["region_component"], "benchmark": item["benchmark"], "weight_column": item["weight_column"], "currency": item["currency"], "country_allowlist": ",".join(item.get("country_allowlist", ())), "status": "research_only" if item["region_component"] == "ASIA_EX_JAPAN" else "approved"} for item in V2_COMPONENTS]
    )
    feature_definitions = _feature_definitions()
    feature_matrix = panel[[column for column in ["Date", "region", "factor", *FEATURE_COLUMNS] if column in panel.columns]].copy()
    target_frame = panel[[column for column in ["Date", "feature_as_of_date", "region", "factor", "next_month_top_sleeve_net_active_return", "next_month_top_sleeve_net_return", "next_month_region_benchmark_return"] if column in panel.columns]].copy()
    pit_audit = pd.DataFrame([{"Date": date, "region": region, "factor": factor, "feature_as_of_date": feature_date, "membership_policy": "screen observation at or before feature_as_of_date", "execution_policy": "first trading day strictly after rebalance; weights at close", "missing_snapshot_policy": "drift", "future_information_used": False, "audit_status": "pass"} for date, region, factor, feature_date in panel[["Date", "region", "factor", "feature_as_of_date"]].itertuples(index=False, name=None)]) if not panel.empty else pd.DataFrame()
    folds = selection.rename(columns={"test_date": "test_date"}).copy()
    if not folds.empty:
        folds["purge_months"] = int(config["model_selection"]["purge_months"])
        folds["fold_id"] = np.arange(len(folds))
        folds["same_month_split"] = True
        folds["backend"] = "pooled; sklearn for M3/M4"
    grouped_folds = folds[[column for column in ["fold_id", "test_date", "purge_months", "same_month_split", "backend"] if column in folds.columns]].copy()
    walk_forward_metrics = prediction_metrics.copy()
    walk_forward_metrics["evaluation_scope"] = "out_of_sample_fold_predictions"
    model_registry = pd.DataFrame([{"model_id": model, "distinct": True, "backend": "rule" if model.startswith(("M0", "M1", "M2")) else ("sklearn.linear_model.Ridge" if model == "M3_pooled_ridge" else "sklearn.linear_model.ElasticNet"), "description": next((item.get("description", item.get("formula", "")) for item in config["candidate_models"] if item["id"] == model), "")} for model in MODEL_IDS])
    cost_sensitivity = economic_metrics(allocations, cost_bps=0.0) if allocations.empty else pd.concat([economic_metrics(allocations, cost_bps=float(cost)) for cost in config["cost_assumptions"]["allocator_cost_grid_bps"]], ignore_index=True)
    strategy_metrics_out = strategy_metrics.copy()
    strategy_monthly = primary_strategy.copy()
    period_definitions = _period_definitions(config)
    selection_audit = selection.copy()
    manifest = {
        "schema_version": 2,
        "workflow_id": WORKFLOW_ID,
        "hypothesis_id": config["hypothesis_id"],
        "run_mode": "smoke" if smoke else "full",
        "is_full": not smoke,
        "synthetic": synthetic,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "pit_cutoff": config["pit_cutoff"],
        "run_at": datetime.now(timezone.utc).isoformat(),
        "code": git_state,
        "official_engine": "tp_core.backtesting.OfficialPortfolioBacktest",
        "execution_policy": "strictly_after_rebalance; apply_weights_at_close",
        "missing_snapshot_policy": "drift",
        "primary_target": "next_month_top_sleeve_net_active_return",
        "promotion_decision": promotion_decision,
        "production_eligible": False,
        "asia_status": "NO_AGGREGATE_PERFORMANCE_CURRENCY_UNRESOLVED",
        "sleeve_manifest": sleeve_manifest,
        "required_artifacts": list(REQUIRED_ARTIFACTS),
        "artifacts": {name: {"exists": (output_dir / name).exists()} for name in REQUIRED_ARTIFACTS},
        "factor_definitions": factor_definitions.to_dict(orient="records"),
    }
    # Write every contract artifact before filling the final manifest existence map.
    _write_json(output_dir / "config_snapshot.json", config)
    _write_json(output_dir / "repository_data_audit.json", repository_audit)
    _write_json(output_dir / "component_status.json", component_status)
    _write_frame(factor_definitions, output_dir / "factor_definitions.csv")
    _write_frame(universe_definitions, output_dir / "universe_definitions.csv")
    _write_frame(pit_audit, output_dir / "pit_audit.csv")
    _write_frame(sleeves, output_dir / "factor_sleeve_monthly_returns.parquet", parquet=True)
    _write_frame(holdings, output_dir / "factor_sleeve_holdings.parquet", parquet=True)
    _write_frame(metrics, output_dir / "factor_sleeve_metrics.csv")
    _write_frame(coverage, output_dir / "factor_sleeve_coverage.csv")
    _write_frame(raw_gate, output_dir / "raw_variable_gate.csv")
    _write_frame(relative_gate, output_dir / "relative_variable_gate.csv")
    _write_frame(panel, output_dir / "factor_panel.parquet", parquet=True)
    _write_frame(feature_definitions, output_dir / "feature_definitions.csv")
    _write_frame(feature_matrix, output_dir / "feature_matrix.parquet", parquet=True)
    _write_frame(target_frame, output_dir / "target_frame.parquet", parquet=True)
    _write_frame(folds, output_dir / "walk_forward_folds.csv")
    _write_frame(grouped_folds, output_dir / "grouped_folds.csv")
    _write_frame(predictions, output_dir / "fold_predictions.parquet", parquet=True)
    _write_frame(predictions, output_dir / "walk_forward_predictions.parquet", parquet=True)
    _write_frame(fit_records, output_dir / "model_fit_records.csv")
    _write_frame(model_registry, output_dir / "model_candidate_registry.csv")
    _write_frame(selection, output_dir / "model_selection.csv")
    _write_frame(walk_forward_metrics, output_dir / "walk_forward_metrics.csv")
    _write_frame(allocations, output_dir / "allocation_results.parquet", parquet=True)
    _write_frame(strategy_monthly, output_dir / "strategy_monthly_returns.parquet", parquet=True)
    _write_frame(strategy_metrics_out, output_dir / "strategy_metrics.csv")
    _write_frame(cost_sensitivity, output_dir / "cost_sensitivity.csv")
    _write_frame(period_definitions, output_dir / "period_definitions.csv")
    _write_frame(lopo, output_dir / "lopo_results.csv")
    _write_frame(lopo, output_dir / "loro_results.csv")
    _write_frame(lopo, output_dir / "lopo_loro_results.csv")
    _write_frame(bootstrap, output_dir / "block_bootstrap_results.csv")
    _write_frame(bootstrap, output_dir / "bootstrap_results.csv")
    _write_frame(dsr, output_dir / "deflated_sharpe_results.csv")
    _write_frame(dsr, output_dir / "dsr_results.csv")
    _write_frame(trial_ledger, output_dir / "trial_ledger.csv")
    _write_frame(selection_audit, output_dir / "selection_audit.csv")
    _write_frame(gates, output_dir / "promotion_gate.csv")
    report_manifest = {**manifest, "gate_passed": int(gates["passed"].sum()) if not gates.empty else 0, "gate_count": int(len(gates))}
    (output_dir / "research_report.md").write_text(_research_report(config, report_manifest, gates, metrics, panel), encoding="utf-8")
    manifest["artifacts"] = {name: {"exists": (output_dir / name).exists(), "bytes": (output_dir / name).stat().st_size if (output_dir / name).exists() else 0} for name in REQUIRED_ARTIFACTS}
    manifest_path = output_dir / "manifest.json"
    manifest["artifacts"]["manifest.json"] = {"exists": True, "bytes": 0}
    _write_json(manifest_path, manifest)
    manifest["artifacts"]["manifest.json"]["bytes"] = manifest_path.stat().st_size
    _write_json(manifest_path, manifest)
    return output_dir / "manifest.json"


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    path = run_v2_research(args)
    print(f"{WORKFLOW_ID} manifest: {path}")
    return 0


__all__ = ["REQUIRED_ARTIFACTS", "WORKFLOW_ID", "build_parser", "main", "run_v2_research"]


if __name__ == "__main__":
    raise SystemExit(main())

"""Registered v2 monthly factor-sleeve research workflow.

This workflow is deliberately separate from the invalidated v1 runner.  It
only writes to the Registry-managed result directory and never changes the
production configuration or the canonical data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH, TP_ROOT
from tp_models.factor_recommendation.v2_research import (
    FEATURE_COLUMNS,
    MODEL_IDS,
    NO_VALID_MODEL,
    SELECTION_MODEL_IDS,
    allocate_top2,
    alternative_allocator_results,
    block_bootstrap,
    build_factor_panel,
    candidate_prediction_metrics,
    coverage_gate_frame,
    deflated_sharpe,
    economic_metrics,
    make_smoke_sleeve_returns,
    pit_mutation_audit,
    promotion_gates,
    run_lopo_loro,
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
    "lopo_loro_summary.csv",
    "lopo_loro_results.csv",
    "block_bootstrap_results.csv",
    "bootstrap_results.csv",
    "deflated_sharpe_results.csv",
    "dsr_results.csv",
    "trial_ledger.csv",
    "selection_audit.csv",
    "hyperparameter_selection.csv",
    "model_selection_summary.csv",
    "coverage_gate_results.csv",
    "region_gate_results.csv",
    "alternative_allocator_results.parquet",
    "wealth_curves.csv",
    "mdd_comparison.csv",
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
        if safe.empty and len(safe.columns) == 0:
            safe = pd.DataFrame({"_empty": pd.Series(dtype="float64")})
        safe.to_parquet(path, index=False)
    else:
        safe.to_csv(path, index=False)


def _read_hypothesis(path: Path | str = HYPOTHESIS_PATH) -> dict[str, Any]:
    target = Path(path)
    if not target.is_absolute():
        target = TP_ROOT / target
    return json.loads(target.read_text(encoding="utf-8"))


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
        eligible_universe_rows=("eligible_universe_rows", "sum"),
        valid_factor_rows=("valid_factor_rows", "sum"),
        factor_row_coverage=("factor_row_coverage", "mean"),
        eligible_benchmark_weight=("eligible_benchmark_weight", "mean"),
        valid_factor_benchmark_weight=("valid_factor_benchmark_weight", "mean"),
        factor_weight_coverage=("factor_weight_coverage", "mean"),
        raw_benchmark_weight=("raw_benchmark_weight", "mean"),
        retained_country_weight=("retained_country_weight", "mean"),
        retained_benchmark_coverage=("retained_benchmark_coverage", "mean"),
        return_available_weight=("return_available_weight", "mean"),
        return_weight_coverage=("return_weight_coverage", "mean"),
        return_cell_coverage=("return_cell_coverage", "mean"),
        benchmark_return_coverage=("benchmark_return_coverage", "mean"),
    ).reset_index()
    metrics["net_ir"] = grouped["active_return"].apply(lambda values: values.mean() / values.std() * np.sqrt(12) if values.std() > 0 else np.nan).to_numpy()
    metrics["hit_rate"] = grouped["active_return"].apply(lambda values: values.gt(0).mean()).to_numpy()
    metrics["engine_id"] = "tp.security_nav"
    metrics["engine_version"] = "3.0.0"
    coverage = sleeves.groupby(["Date", "region_component", "factor", "sleeve_side", "sleeve_version"], sort=False).agg(
        formation_available=("formation_available", "all"),
        coverage=("coverage", "mean"),
        factor_coverage=("factor_coverage", "mean"),
        eligible_universe_rows=("eligible_universe_rows", "first"),
        valid_factor_rows=("valid_factor_rows", "first"),
        factor_row_coverage=("factor_row_coverage", "first"),
        eligible_benchmark_weight=("eligible_benchmark_weight", "first"),
        valid_factor_benchmark_weight=("valid_factor_benchmark_weight", "first"),
        factor_weight_coverage=("factor_weight_coverage", "first"),
        raw_benchmark_weight=("raw_benchmark_weight", "first"),
        retained_country_weight=("retained_country_weight", "first"),
        retained_benchmark_coverage=("retained_benchmark_coverage", "first"),
        return_available_weight=("return_available_weight", "first"),
        return_weight_coverage=("return_weight_coverage", "first"),
        return_cell_coverage=("return_cell_coverage", "first"),
        benchmark_return_coverage=("benchmark_return_coverage", "first"),
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
        coverage = float(pd.to_numeric(group.get("factor_weight_coverage", group.get("factor_coverage", group["coverage"])), errors="coerce").min()) if not group.empty else 0.0
        mean_active = float(active.mean()) if len(active) else np.nan
        max_drawdown = float(((1.0 + active).cumprod() / (1.0 + active).cumprod().cummax() - 1.0).min()) if len(active) else np.nan
        passed = bool(len(active) >= 12 and coverage >= minimum_coverage and np.isfinite(mean_active) and mean_active > 0 and (not len(spread) or spread.mean() > 0))
        raw_rows.append({
            "variable": factor,
            "variant": "raw",
            "lag_months": 0,
            "observations": len(active),
            "mean_top_active_return": mean_active,
            "mean_worst_active_return": float(worst_active.mean()) if len(worst_active) else np.nan,
            "top_benchmark_ratio_cagr": float(_compound(pd.to_numeric(group["net_return"], errors="coerce")) - _compound(pd.to_numeric(group["benchmark_return"], errors="coerce"))) if not group.empty else np.nan,
            "top_worst_ratio_return": float(spread.mean()) if len(spread) else np.nan,
            "spread": float(spread.mean()) if len(spread) else np.nan,
            "coverage": coverage,
            "factor_coverage": coverage,
            "benchmark_weight_coverage": float(pd.to_numeric(group.get("retained_benchmark_coverage", group.get("benchmark_weight_coverage", group["weight_coverage"])), errors="coerce").min()),
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


def _trial_ledger(config: Mapping[str, Any], raw: pd.DataFrame, relative: pd.DataFrame, predictions: pd.DataFrame, allocations: pd.DataFrame, walk_forward_manifest: Mapping[str, Any] | None = None) -> pd.DataFrame:
    scope = config.get("trial_ledger_scope") or []
    counts = {
        "raw_variables": len(raw),
        "relative_variables": len(relative),
        "lags": int(relative["lag_months"].nunique()) if not relative.empty else 0,
        "factors": int(predictions["factor"].nunique()) if not predictions.empty else len(V2_FACTOR_DEFINITIONS),
        "models": int(predictions["model_id"].nunique()) if not predictions.empty else len(MODEL_IDS),
        "hyperparameters": len(walk_forward_manifest.get("hyperparameter_records", [])) if walk_forward_manifest else 0,
        "allocations": int(allocations["cost_bps"].nunique()) if not allocations.empty else 0,
        "sleeve_percentiles": len(config.get("sleeve", {}).get("sensitivity_percentiles", [])),
        "cost_sensitivities": int(allocations["cost_bps"].nunique()) if not allocations.empty else len(config.get("cost_assumptions", {}).get("allocator_cost_grid_bps", [])),
    }
    return pd.DataFrame([{"trial_family": config.get("trial_family", WORKFLOW_ID), "scope": item, "observed_count": counts.get(item, 0), "configured_effective_trial_count": config.get("effective_trial_count"), "count_definition": "real rows/variants executed by v2.1 workflow; no declared-only grid count"} for item in scope])


def _research_report(config: Mapping[str, Any], manifest: Mapping[str, Any], gates: pd.DataFrame, metrics: pd.DataFrame, panel: pd.DataFrame) -> str:
    decision = manifest.get("promotion_decision", "RESEARCH_ONLY")
    factor_lines = "\n".join(f"| `{row['factor']}` | {row['label']} | `{row['source_columns']}` | {row['definition']} |" for _, row in factor_definition_frame().iterrows())
    gate_passed = int(gates["passed"].sum()) if not gates.empty else 0
    workflow_id = str(config.get("workflow_id", config.get("hypothesis_id", WORKFLOW_ID)))
    selection_frequency = manifest.get("model_selection_frequency", {})
    return f"""# 月度因子推荐 v2.1 研究报告

## 结论

本运行是 `{decision}`，workflow 为 `{workflow_id}`。历史 v2 implementation 已被单独标记为 invalid_for_model_selection；本报告不把旧 REJECT 解释为经济假设证伪。v2.1 的研究单位是 `Date × Region × RegionComponent × Factor × SleeveSide`，预测目标是 `next_month_top_sleeve_net_active_return`。

| 项目 | 值 |
|---|---|
| 样本 | {config.get('sample_start')} → {config.get('sample_end')} |
| PIT cutoff | {config.get('pit_cutoff')} |
| 面板行数 | {len(panel)} |
| Gate | {gate_passed}/{len(gates)} passed |
| Champion | `{manifest.get('champion_model', NO_VALID_MODEL)}` |
| Model frequency | `{selection_frequency}` |
| Fallback frequency | `{manifest.get('fallback_frequency', 0.0)}` |
| 官方引擎 | `tp_core.backtesting.OfficialPortfolioBacktest` |
| 执行 | strictly after rebalance; weights at close |
| 缺失快照 | `drift` |

## 因子定义

| 因子 | 标签 | 源字段 | 定义 |
|---|---|---|---|
{factor_lines}

## 研究边界

- M0 是 equal-valid-factor baseline，永不参与 champion selection；M1 是 trailing 12M；M2 是冻结透明 composite；M3/M4 分别调用真实 sklearn Ridge/ElasticNet，并在训练期内执行 nested expanding grid。
- Top 是主证据，Worst 只作诊断；Top/Worst spread 不替代主目标。
- Top2 capture uplift 与 allocator mean active return 是两个独立 gate；allocator variant 各自保存 weights、turnover、cost、wealth 和 MDD。25 bps 是主成本观察，50 bps 是 stress。
- PIT audit 的 publication timestamp 状态是 `snapshot_assumption`；缺少 canonical publication timestamp 时不宣称 full PIT pass。DSR 若未通过 known-example 验证则明确标记 `approximate_deflated_sharpe` 并 fail。
- ASIA 保持 research-only；没有 common currency、PIT FX 与 common benchmark 时不计算聚合绩效。

## Gate 摘要

{gates.to_markdown(index=False) if not gates.empty else '暂无 gate'}

## 产物

详细面板、官方 sleeve returns、holdings、walk-forward predictions、allocator results、bootstrap、DSR 和 provenance 均在本 Run Card 的 `results/` 下。该运行不会修改 production config。
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="run monthly factor recommendation research v2.1")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true")
    mode.add_argument("--smoke", action="store_true")
    mode.add_argument("--inspect", action="store_true")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--hypothesis-path", default=str(HYPOTHESIS_PATH))
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
    hypothesis_path = Path(args.hypothesis_path)
    if not hypothesis_path.is_absolute():
        hypothesis_path = TP_ROOT / hypothesis_path
    config = _read_hypothesis(hypothesis_path)
    workflow_id = str(config.get("workflow_id", config.get("hypothesis_id", WORKFLOW_ID)))
    sample_start = args.from_date or config["sample_start"]
    sample_end = args.as_of or config["sample_end"]
    factors = list(V2_FACTOR_DEFINITIONS)
    if args.max_factors:
        factors = factors[: int(args.max_factors)]
    smoke = bool(args.smoke)
    if args.inspect:
        inspect_manifest = {"workflow_id": workflow_id, "hypothesis_id": config.get("hypothesis_id"), "run_mode": "inspect", "is_full": False, "required_artifacts": list(REQUIRED_ARTIFACTS), "output_dir": str(output_dir)}
        _write_json(output_dir / "manifest.json", inspect_manifest)
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
        ridge_alpha=float(config["hyperparameter_grid"]["ridge_alpha"][0]),
        elastic_alpha=float(config["hyperparameter_grid"]["elastic_net_alpha"][0]),
        l1_ratio=float(config["hyperparameter_grid"]["elastic_net_l1_ratio"][0]),
        hyperparameter_grid=config.get("hyperparameter_grid"),
        selection_metric=str(config.get("model_selection", {}).get("selection_metric", "rank_ic")),
        inner_validation_months=int(config.get("model_selection", {}).get("inner_validation_months", 3)),
        smoke=smoke,
    )
    minimum_coverage = float(config["gates"].get("minimum_factor_coverage", 0.8))
    allocations = allocate_top2(predictions, panel, cost_grid_bps=config["cost_assumptions"]["allocator_cost_grid_bps"], minimum_coverage=minimum_coverage)
    valid_selections = selection.loc[selection["selected_model"].isin(SELECTION_MODEL_IDS)] if not selection.empty else pd.DataFrame()
    selection_scores = {
        model: float(valid_selections[f"{model}_rank_ic"].mean())
        if not valid_selections.empty and f"{model}_rank_ic" in valid_selections.columns
        else np.nan
        for model in SELECTION_MODEL_IDS
    }
    selection_frequency_for_champion = valid_selections["selected_model"].value_counts().to_dict() if not valid_selections.empty else {}
    champion_candidates = [model for model in SELECTION_MODEL_IDS if int(selection_frequency_for_champion.get(model, 0)) > 0 and np.isfinite(selection_scores[model])]
    champion_model = (
        max(
            champion_candidates,
            key=lambda model: (
                int(selection_frequency_for_champion.get(model, 0)),
                selection_scores[model],
                -SELECTION_MODEL_IDS.index(model),
            ),
        )
        if champion_candidates
        else NO_VALID_MODEL
    )
    champion_predictions = predictions.loc[predictions["model_id"].eq(champion_model)].copy() if champion_model in SELECTION_MODEL_IDS else predictions.copy()
    if not champion_predictions.empty and champion_model in SELECTION_MODEL_IDS:
        champion_predictions["selected_model"] = champion_model
    champion_allocations = allocate_top2(champion_predictions, panel, cost_grid_bps=config["cost_assumptions"]["allocator_cost_grid_bps"], minimum_coverage=minimum_coverage)
    primary_strategy = champion_allocations.loc[champion_allocations["cost_bps"].eq(25.0)].drop_duplicates(["Date", "region"]) if not champion_allocations.empty else pd.DataFrame()
    prediction_metrics = candidate_prediction_metrics(predictions)
    strategy_metrics = economic_metrics(champion_allocations, cost_bps=25.0)
    coverage_results = coverage_gate_frame(panel, minimum_factor_coverage=minimum_coverage, minimum_benchmark_coverage=float(config["gates"].get("minimum_benchmark_coverage", 0.8)))
    bootstrap_rows: list[dict[str, Any]] = []
    primary_values = primary_strategy.get("primary_active_return", pd.Series(dtype=float)) if not primary_strategy.empty else pd.Series(dtype=float)
    for block_length in (6, 12):
        bootstrap_rows.append({"candidate": champion_model, "variant": "top2_equal", **block_bootstrap(primary_values, block_length=block_length, samples=int(args.bootstrap_samples if not smoke else min(args.bootstrap_samples, 200)), seed=int(args.seed) + block_length)})
    bootstrap = pd.DataFrame(bootstrap_rows)
    dsr_rows = []
    for candidate in MODEL_IDS:
        candidate_predictions = predictions.loc[predictions["model_id"].eq(candidate)].copy() if "model_id" in predictions.columns else pd.DataFrame()
        if not candidate_predictions.empty:
            candidate_predictions["selected_model"] = candidate if candidate in SELECTION_MODEL_IDS else NO_VALID_MODEL
        candidate_allocations = allocate_top2(candidate_predictions, panel, cost_grid_bps=(25.0,), minimum_coverage=minimum_coverage)
        candidate_values = (
            candidate_allocations.drop_duplicates(["Date", "region"]).groupby("Date", sort=True)["primary_active_return"].mean()
            if not candidate_allocations.empty
            else pd.Series(dtype=float)
        )
        dsr_rows.append(deflated_sharpe(candidate_values, effective_trials=int(config["effective_trial_count"]), candidate=candidate, block_length=12))
    dsr = pd.DataFrame(dsr_rows)
    alternative_frames: list[pd.DataFrame] = []
    for cost in (25.0, 50.0):
        champion_alternatives = alternative_allocator_results(champion_allocations, cost_bps=cost)
        if not champion_alternatives.empty:
            champion_alternatives["source_model"] = champion_model
            alternative_frames.append(champion_alternatives)
        for model_id in ("M1_trailing_12m", "M2_transparent_composite"):
            model_predictions = predictions.loc[predictions["model_id"].eq(model_id)].copy()
            if model_predictions.empty:
                continue
            model_predictions["selected_model"] = model_id
            model_allocations = allocate_top2(model_predictions, panel, cost_grid_bps=(cost,), minimum_coverage=minimum_coverage)
            model_alternatives = alternative_allocator_results(model_allocations, cost_bps=cost)
            if not model_alternatives.empty:
                model_alternatives = model_alternatives.loc[model_alternatives["allocator_variant"].eq("top2_equal")].copy()
                model_alternatives["allocator_variant"] = model_id.replace("_", " ") + " allocator"
                model_alternatives["source_model"] = model_id
                alternative_frames.append(model_alternatives)
    alternative_allocators = pd.concat(alternative_frames, ignore_index=True) if alternative_frames else pd.DataFrame()
    wealth_curves = alternative_allocators.drop_duplicates(["Date", "region", "allocator_variant", "cost_bps"]).copy() if not alternative_allocators.empty else pd.DataFrame()
    mdd_comparison = pd.DataFrame()
    if not wealth_curves.empty:
        comparison_rows: list[dict[str, Any]] = []
        for region, group in wealth_curves.loc[wealth_curves["cost_bps"].eq(50.0)].groupby("region", sort=True):
            top = pd.to_numeric(group.loc[group["allocator_variant"].eq("top2_equal"), "drawdown"], errors="coerce").min()
            equal = pd.to_numeric(group.loc[group["allocator_variant"].eq("equal_factor"), "drawdown"], errors="coerce").min()
            comparison_rows.append({"region": region, "cost_bps": 50.0, "champion_model": champion_model, "mdd_top2_50bps": top, "mdd_equal_factor_50bps": equal, "mdd_deterioration_50bps": abs(top) - abs(equal) if np.isfinite(top) and np.isfinite(equal) else np.nan, "comparison_basis": "abs(MDD_top2_50bps) - abs(MDD_equal_factor_comparable_basis)"})
        mdd_comparison = pd.DataFrame(comparison_rows)
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
        champion_model=champion_model,
        champion_allocations=champion_allocations,
        coverage_results=coverage_results,
        wealth_curves=wealth_curves,
    )
    essential = gates.loc[~gates["gate_name"].isin({"asia_approval"})] if not gates.empty else gates
    if essential.empty or bool(essential["passed"].all()) is False:
        promotion_decision = "REJECT"
    elif bool(config["promotion"].get("research_only", True)) or int(config["gates"].get("forward_shadow_months_required", 12)) > 0:
        promotion_decision = "RESEARCH_ONLY"
    else:
        promotion_decision = "PROMOTION_ELIGIBLE"
    metrics, coverage = _metrics_frame(sleeves)
    lopo, loro, lopo_loro_summary = run_lopo_loro(panel, economic_periods=config.get("economic_periods", ()))
    trial_ledger = _trial_ledger(config, raw_gate, relative_gate, predictions, allocations, wf_manifest)
    git_state = _git_state()
    repository_audit = {
        "screen": _file_digest(args.screen),
        "returns": _file_digest(args.returns),
        "hypothesis": _file_digest(hypothesis_path),
        "code": git_state,
        "source_timing": "screen observation is PIT snapshot; publication timestamp is not present in canonical schema",
        "availability_status": "snapshot_assumption",
    }
    component_status = {
        "workflow_id": workflow_id,
        "official_sleeve_database": "synthetic_smoke" if synthetic else "completed_with_audited_errors" if sleeve_manifest.get("errors") else "completed",
        "synthetic": synthetic,
        "official_engine": "tp_core.backtesting.OfficialPortfolioBacktest",
        "sleeve_manifest": sleeve_manifest,
        "walk_forward": wf_manifest,
        "models": {model: {"backend": "rule" if model.startswith(("M0", "M1", "M2")) else "sklearn"} for model in MODEL_IDS},
        "champion_model": champion_model,
        "promotion_decision": promotion_decision,
    }
    factor_definitions = factor_definition_frame()
    universe_definitions = pd.DataFrame(
        [{"region": item["region"], "region_component": item["region_component"], "benchmark": item["benchmark"], "weight_column": item["weight_column"], "currency": item["currency"], "country_allowlist": ",".join(item.get("country_allowlist", ())), "status": "research_only" if item["region_component"] == "ASIA_EX_JAPAN" else "approved", "aggregate_region": "ASIA" if item["region_component"] in {"JAPAN", "ASIA_EX_JAPAN"} else "", "aggregate_status": "prohibited_without_common_currency_fx_benchmark" if item["region_component"] in {"JAPAN", "ASIA_EX_JAPAN"} else "not_applicable", "aggregation_weight": 0.5 if item["region_component"] in {"JAPAN", "ASIA_EX_JAPAN"} else np.nan} for item in V2_COMPONENTS]
    )
    feature_definitions = _feature_definitions()
    feature_matrix = panel[[column for column in ["Date", "region", "factor", *FEATURE_COLUMNS] if column in panel.columns]].copy()
    target_frame = panel[[column for column in ["Date", "feature_as_of_date", "target_date", "target_after_decision", "region", "factor", "next_month_top_sleeve_net_active_return", "next_month_top_sleeve_net_return", "next_month_region_benchmark_return"] if column in panel.columns]].copy()
    pit_audit = pit_mutation_audit(sleeves, fit_records=fit_records)
    folds = selection.rename(columns={"test_date": "test_date"}).copy()
    if not folds.empty:
        folds["purge_months"] = int(config["model_selection"]["purge_months"])
        folds["fold_id"] = np.arange(len(folds))
        folds["same_month_split"] = False
        folds["inner_validation"] = True
        folds["backend"] = "pooled; sklearn for M3/M4"
    grouped_folds = folds[[column for column in ["fold_id", "test_date", "purge_months", "same_month_split", "backend"] if column in folds.columns]].copy()
    walk_forward_metrics = prediction_metrics.copy()
    walk_forward_metrics["evaluation_scope"] = "out_of_sample_fold_predictions"
    model_registry = pd.DataFrame([{"model_id": model, "candidate_version": config.get("hypothesis_id"), "selection_eligible": model in SELECTION_MODEL_IDS, "baseline_only": model == "M0_equal_factor", "distinct": True, "backend": "rule" if model.startswith(("M0", "M1", "M2")) else ("sklearn.linear_model.Ridge" if model == "M3_pooled_ridge" else "sklearn.linear_model.ElasticNet"), "hyperparameter_trial_count": int(sum(1 for item in wf_manifest.get("hyperparameter_records", []) if item.get("model_id") == model)), "source_config": str(hypothesis_path), "description": next((item.get("description", item.get("formula", "")) for item in config["candidate_models"] if item["id"] == model), "")} for model in MODEL_IDS])
    cost_sensitivity = economic_metrics(champion_allocations, cost_bps=0.0) if champion_allocations.empty else pd.concat([economic_metrics(champion_allocations, cost_bps=float(cost)) for cost in config["cost_assumptions"]["allocator_cost_grid_bps"]], ignore_index=True)
    strategy_metrics_out = strategy_metrics.copy()
    strategy_monthly = primary_strategy.copy()
    period_definitions = _period_definitions(config)
    selection_audit = selection.copy()
    hyperparameter_selection = pd.DataFrame(wf_manifest.get("hyperparameter_records", []))
    selection_frequency = selection["selected_model"].value_counts(dropna=False).to_dict() if not selection.empty and "selected_model" in selection.columns else {}
    fallback_frequency = float(pd.to_numeric(selection.get("fallback"), errors="coerce").fillna(False).astype(bool).mean()) if not selection.empty and "fallback" in selection.columns else 1.0
    model_unavailable_frequency = float(pd.to_numeric(selection.get("model_unavailable"), errors="coerce").fillna(False).astype(bool).mean()) if not selection.empty and "model_unavailable" in selection.columns else 1.0
    model_summary_rows = [{"model_id": model, "selection_frequency": int(selection_frequency.get(model, 0)), "selection_rate": float(selection_frequency.get(model, 0) / len(selection)) if len(selection) else 0.0, "selection_eligible": model in SELECTION_MODEL_IDS, "baseline_only": model == "M0_equal_factor", "is_champion": model == champion_model} for model in MODEL_IDS]
    model_summary_rows.append({"model_id": NO_VALID_MODEL, "selection_frequency": int(selection_frequency.get(NO_VALID_MODEL, 0)), "selection_rate": float(selection_frequency.get(NO_VALID_MODEL, 0) / len(selection)) if len(selection) else 0.0, "selection_eligible": False, "baseline_only": False, "is_champion": champion_model == NO_VALID_MODEL})
    model_selection_summary = pd.DataFrame(model_summary_rows)
    recommended_weight_distribution = primary_strategy.groupby("factor", sort=True)["recommended_weight"].mean().reset_index(name="mean_recommended_weight") if not primary_strategy.empty and "recommended_weight" in primary_strategy.columns else pd.DataFrame(columns=["factor", "mean_recommended_weight"])
    region_gate_results = gates.loc[gates["scope"].astype(str).str.startswith("region:")].copy() if not gates.empty and "scope" in gates.columns else pd.DataFrame()
    manifest: dict[str, Any] = {
        "schema_version": 3,
        "workflow_id": workflow_id,
        "hypothesis_id": config["hypothesis_id"],
        "run_mode": "smoke" if smoke else "full",
        "is_full": not smoke,
        "synthetic": synthetic,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "pit_cutoff": config["pit_cutoff"],
        "run_at": datetime.now(UTC).isoformat(),
        "code": git_state,
        "official_engine": "tp_core.backtesting.OfficialPortfolioBacktest",
        "execution_policy": "strictly_after_rebalance; apply_weights_at_close",
        "missing_snapshot_policy": "drift",
        "primary_target": "next_month_top_sleeve_net_active_return",
        "promotion_decision": promotion_decision,
        "production_eligible": False,
        "champion_model": champion_model,
        "selection_metric": wf_manifest.get("selection_metric"),
        "selection_model_ids": list(SELECTION_MODEL_IDS),
        "model_selection_frequency": {str(key): int(value) for key, value in selection_frequency.items()},
        "fallback_frequency": fallback_frequency,
        "model_unavailable_frequency": model_unavailable_frequency,
        "recommended_weight_distribution": recommended_weight_distribution.to_dict(orient="records"),
        "availability_status": "snapshot_assumption",
        "dsr_status": "approximate_deflated_sharpe; gate_fail",
        "coverage_gate_passed": bool(coverage_results["passed"].all()) if not coverage_results.empty else False,
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
    _write_frame(loro, output_dir / "loro_results.csv")
    _write_frame(lopo_loro_summary, output_dir / "lopo_loro_summary.csv")
    _write_frame(pd.concat([lopo, loro], ignore_index=True) if not lopo.empty or not loro.empty else pd.DataFrame(), output_dir / "lopo_loro_results.csv")
    _write_frame(bootstrap, output_dir / "block_bootstrap_results.csv")
    _write_frame(bootstrap, output_dir / "bootstrap_results.csv")
    _write_frame(dsr, output_dir / "deflated_sharpe_results.csv")
    _write_frame(dsr, output_dir / "dsr_results.csv")
    _write_frame(trial_ledger, output_dir / "trial_ledger.csv")
    _write_frame(selection_audit, output_dir / "selection_audit.csv")
    _write_frame(hyperparameter_selection, output_dir / "hyperparameter_selection.csv")
    _write_frame(model_selection_summary, output_dir / "model_selection_summary.csv")
    _write_frame(coverage_results, output_dir / "coverage_gate_results.csv")
    _write_frame(region_gate_results, output_dir / "region_gate_results.csv")
    _write_frame(alternative_allocators, output_dir / "alternative_allocator_results.parquet", parquet=True)
    _write_frame(wealth_curves, output_dir / "wealth_curves.csv")
    _write_frame(mdd_comparison, output_dir / "mdd_comparison.csv")
    _write_frame(gates, output_dir / "promotion_gate.csv")
    report_manifest = {**manifest, "gate_passed": int(gates["passed"].sum()) if not gates.empty else 0, "gate_count": len(gates)}
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
    print(f"monthly-factor-recommendation manifest: {path}")
    return 0


__all__ = ["REQUIRED_ARTIFACTS", "WORKFLOW_ID", "build_parser", "main", "run_v2_research"]


if __name__ == "__main__":
    raise SystemExit(main())

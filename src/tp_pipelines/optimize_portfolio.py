"""从候选池生成目标组合权重。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from tp_portfolio import (
    OPTIMIZER_ID,
    OPTIMIZER_VERSION,
    GroupConstraint,
    OptimizerConfig,
    OptimizerObjective,
    optimize_portfolio as run_optimizer,
)
from tp_core.portfolio_weights import (
    cap_and_redistribute_weights,
    normalize_long_only_weights,
)

from .common import CANDIDATES_DIR, PORTFOLIOS_DIR, StepManifest, path_profile, summarize_frame


DEFAULT_CANDIDATES = CANDIDATES_DIR / "latest_candidates.parquet"
DEFAULT_OUTPUT = PORTFOLIOS_DIR / "latest_target_weights.parquet"

def _read_old_weights(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path)
    elif path.suffix.lower() in {".xlsx", ".xls"}:
        frame = pd.read_excel(path)
    else:
        frame = pd.read_csv(path)
    if "Company SEDOL" not in frame.columns:
        raise ValueError("old_portfolio 必须包含 Company SEDOL")
    weight_col = "Weight" if "Weight" in frame.columns else "target_weight" if "target_weight" in frame.columns else None
    if weight_col is None:
        raise ValueError("old_portfolio 必须包含 Weight 或 target_weight")
    return frame[["Company SEDOL", weight_col]].rename(columns={weight_col: "old_weight"})


def _benchmark_weights(frame: pd.DataFrame) -> pd.Series:
    weight_col = "Weight in MSCI WORLD" if "Weight in MSCI WORLD" in frame.columns else None
    if weight_col is None:
        weight_col = next((column for column in frame.columns if column.startswith("Weight in ")), None)
    if weight_col is None:
        return pd.Series(1.0 / len(frame), index=frame.index)
    weights = pd.to_numeric(frame[weight_col], errors="coerce").fillna(0.0).clip(lower=0.0)
    return normalize_long_only_weights(weights, allow_equal_fallback=True)


def _tilted_group_targets(
    frame: pd.DataFrame,
    *,
    group_col: str,
    benchmark_weights: pd.Series,
    tilt_col: str | None,
    tilt_strength: float,
) -> dict[str, float]:
    if group_col not in frame.columns:
        return {}
    tmp = frame[[group_col]].copy()
    tmp["benchmark_weight"] = benchmark_weights.to_numpy()
    if tilt_col and tilt_col in frame.columns:
        tmp["tilt_score"] = pd.to_numeric(frame[tilt_col], errors="coerce").fillna(0.5)
    else:
        tmp["tilt_score"] = 0.5
    tmp = tmp[tmp[group_col].notna()].copy()
    if tmp.empty:
        return {}
    grouped = tmp.groupby(group_col, dropna=True).agg(
        benchmark_weight=("benchmark_weight", "sum"),
        tilt_score=("tilt_score", "mean"),
    )
    grouped["target"] = grouped["benchmark_weight"] * (1.0 + tilt_strength * (grouped["tilt_score"] - 0.5) * 2.0)
    grouped["target"] = grouped["target"].clip(lower=0.0)
    total = float(grouped["target"].sum())
    if total <= 0:
        return {}
    return (grouped["target"] / total).to_dict()


def _constrained_weights(
    selected: pd.DataFrame,
    *,
    max_weight: float | None,
    min_weight: float,
    old_portfolio: Path | None,
    benchmark_active_limit: float,
    country_margin: float,
    sector_margin: float,
    max_turnover: float | None,
    transaction_cost: float,
    country_tilt_strength: float,
    sector_tilt_strength: float,
) -> tuple[pd.Series, dict[str, object]]:
    n = len(selected)
    if max_weight is not None and n * max_weight < 1.0:
        raise ValueError(f"max_weight={max_weight} 对 {n} 只证券不可行")
    if min_weight and n * min_weight > 1.0:
        raise ValueError(f"min_weight={min_weight} 对 {n} 只证券不可行")

    benchmark = _benchmark_weights(selected)
    score = pd.to_numeric(selected["composite_score"], errors="coerce").fillna(0.0).clip(lower=0.0)
    if float(score.max()) > 0:
        score = score / float(score.max())
    risk_source = selected["risk_budget_multiplier"] if "risk_budget_multiplier" in selected.columns else pd.Series(1.0, index=selected.index)
    risk_budget = float(pd.to_numeric(risk_source, errors="coerce").fillna(1.0).mean())
    risk_budget = max(0.7, min(1.3, risk_budget))
    active_limit = benchmark_active_limit * risk_budget
    effective_country_margin = country_margin * risk_budget
    effective_sector_margin = sector_margin * risk_budget
    effective_turnover = max_turnover * risk_budget if max_turnover is not None else None
    base_active_limit = active_limit
    base_country_margin = effective_country_margin
    base_sector_margin = effective_sector_margin
    base_turnover = effective_turnover

    old = benchmark.copy()
    external_old_weight = 0.0
    if old_portfolio is not None:
        old_frame = _read_old_weights(old_portfolio)
        old_frame["old_weight"] = pd.to_numeric(
            old_frame["old_weight"],
            errors="coerce",
        ).fillna(0.0).clip(lower=0.0)
        if float(old_frame["old_weight"].sum()) > 0:
            old_frame["old_weight"] /= float(old_frame["old_weight"].sum())
        old = selected[["Company SEDOL"]].merge(old_frame, on="Company SEDOL", how="left")["old_weight"]
        old = pd.to_numeric(old, errors="coerce").fillna(0.0)
        external_old_weight = max(0.0, 1.0 - float(old.sum()))

    country_targets = _tilted_group_targets(
        selected,
        group_col="country_model_region",
        benchmark_weights=benchmark,
        tilt_col="country_score_pct",
        tilt_strength=country_tilt_strength,
    )
    sector_targets = _tilted_group_targets(
        selected,
        group_col="sector_key",
        benchmark_weights=benchmark,
        tilt_col="sector_score_pct",
        tilt_strength=sector_tilt_strength,
    )

    attempts: list[dict[str, object]] = []
    last_error: Exception | None = None
    active_penalty = 5.0 / risk_budget
    lower = np.full(n, float(min_weight))
    upper = np.full(n, float(max_weight) if max_weight is not None else 1.0)

    for relaxation in (1.0, 1.5, 2.25, 3.375, 5.0, 10.0):
        active_limit = min(1.0, base_active_limit * relaxation)
        effective_country_margin = min(1.0, base_country_margin * relaxation)
        effective_sector_margin = min(1.0, base_sector_margin * relaxation)
        effective_turnover = (
            min(2.0, base_turnover * relaxation)
            if base_turnover is not None
            else None
        )
        constraints = []
        if country_targets:
            constraints.append(
                GroupConstraint.around_targets(
                    name="country",
                    group_col="country_model_region",
                    targets=country_targets,
                    margin=effective_country_margin,
                )
            )
        if sector_targets:
            constraints.append(
                GroupConstraint.around_targets(
                    name="sector",
                    group_col="sector_key",
                    targets=sector_targets,
                    margin=effective_sector_margin,
                )
            )
        try:
            result = run_optimizer(
                selected,
                id_col="Company SEDOL",
                benchmark_weights=benchmark,
                scores=score,
                covariance=np.eye(n),
                current_weights=old,
                external_current_weight=external_old_weight,
                lower_bounds=lower,
                upper_bounds=upper,
                group_constraints=constraints,
                config=OptimizerConfig(
                    objective=OptimizerObjective.BLENDED,
                    score_weight=1.0,
                    tracking_error_weight=0.0,
                    turnover_weight=float(transaction_cost),
                    active_weight_penalty=active_penalty,
                    max_active_weight=active_limit,
                    max_turnover=effective_turnover,
                ),
            )
        except (RuntimeError, ValueError) as exc:
            last_error = exc
            attempts.append(
                {
                    "relaxation": relaxation,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        attempts.append(
            {
                "relaxation": relaxation,
                "status": result.status,
                "solver": result.solver,
            }
        )
        audit = {
            **result.audit,
            **result.metadata,
            "constraint_relaxation": relaxation,
            "attempts": attempts,
            "risk_budget_multiplier": risk_budget,
            "benchmark_active_limit": active_limit,
            "max_turnover": effective_turnover,
            "transaction_cost": transaction_cost,
            "external_current_weight": external_old_weight,
        }
        return result.weights, audit

    raise RuntimeError("constrained portfolio optimization failed") from last_error


def optimize_portfolio(
    *,
    candidates_path: Path,
    output: Path,
    method: str,
    max_weight: float | None,
    min_weight: float,
    region: str | None,
    old_portfolio: Path | None,
    benchmark_active_limit: float,
    country_margin: float,
    sector_margin: float,
    max_turnover: float | None,
    transaction_cost: float,
    country_tilt_strength: float,
    sector_tilt_strength: float,
) -> pd.DataFrame:
    candidates = pd.read_parquet(candidates_path)
    if "selected" not in candidates.columns:
        raise ValueError("候选池缺少 selected 列")
    selected = candidates[candidates["selected"].fillna(False)].copy()
    if region:
        selected = selected[selected["region"].astype("string").eq(region)].copy()
    if selected.empty:
        raise ValueError("没有可用于组合优化的候选证券")
    if "sector_region_key" in selected.columns and "sector_code" in selected.columns:
        selected["sector_key"] = selected["sector_region_key"].astype("string") + "_" + selected["sector_code"].astype("string")
    else:
        selected["sector_key"] = pd.NA

    if method == "equal_weight":
        raw = pd.Series(1.0, index=selected.index)
        selected["target_weight"] = cap_and_redistribute_weights(raw, max_weight)
        constraint_audit = {
            "method": method,
            "optimizer_id": OPTIMIZER_ID,
            "optimizer_version": OPTIMIZER_VERSION,
            "objective": method,
            "solver": "closed_form",
        }
    elif method == "score_weight":
        raw = selected["composite_score"]
        selected["target_weight"] = cap_and_redistribute_weights(
            raw,
            max_weight,
            allow_equal_fallback=True,
        )
        constraint_audit = {
            "method": method,
            "optimizer_id": OPTIMIZER_ID,
            "optimizer_version": OPTIMIZER_VERSION,
            "objective": method,
            "solver": "closed_form",
        }
    elif method == "constrained":
        selected["target_weight"], constraint_audit = _constrained_weights(
            selected,
            max_weight=max_weight,
            min_weight=min_weight,
            old_portfolio=old_portfolio,
            benchmark_active_limit=benchmark_active_limit,
            country_margin=country_margin,
            sector_margin=sector_margin,
            max_turnover=max_turnover,
            transaction_cost=transaction_cost,
            country_tilt_strength=country_tilt_strength,
            sector_tilt_strength=sector_tilt_strength,
        )
    else:
        raise ValueError(f"未知优化方法: {method}")

    selected["optimizer_method"] = method
    selected["optimizer_id"] = constraint_audit.get("optimizer_id", OPTIMIZER_ID)
    selected["optimizer_version"] = constraint_audit.get(
        "optimizer_version",
        OPTIMIZER_VERSION,
    )
    selected["optimizer_objective"] = constraint_audit.get("objective", method)
    selected["optimizer_solver"] = constraint_audit.get(
        "solver",
        constraint_audit.get("solver_backend", "unknown"),
    )
    selected["max_weight"] = max_weight
    selected["min_weight"] = min_weight
    selected["source_candidates"] = str(candidates_path)
    selected["benchmark_weight"] = _benchmark_weights(selected)
    selected["active_weight"] = selected["target_weight"] - selected["benchmark_weight"]

    if old_portfolio is not None:
        old = _read_old_weights(old_portfolio)
        selected = selected.merge(old, on="Company SEDOL", how="left")
        selected["old_weight"] = selected["old_weight"].fillna(0.0)
        selected["name_level_turnover"] = (selected["target_weight"] - selected["old_weight"]).abs()
        selected.attrs["turnover"] = float(turnover_metric(selected["target_weight"].to_numpy(), selected["old_weight"].to_numpy()))
    else:
        selected["old_weight"] = pd.NA
        selected["name_level_turnover"] = pd.NA

    columns = [
        "candidate_date",
        "Company SEDOL",
        "ISIN",
        "Company Name",
        "Name",
        "region",
        "target_weight",
        "old_weight",
        "name_level_turnover",
        "composite_score",
        "rank",
        "rank_pct",
        "ml_score_pct",
        "technical_score_pct",
        "technical_signal_count",
        "security_alpha_score",
        "allocation_score_pct",
        "country_model_region",
        "country_score_pct",
        "country_recommendation",
        "sector_key",
        "sector_score_pct",
        "sector_recommendation",
        "risk_budget_multiplier",
        "benchmark_weight",
        "active_weight",
        "optimizer_method",
        "optimizer_id",
        "optimizer_version",
        "optimizer_objective",
        "optimizer_solver",
        "max_weight",
        "min_weight",
        "source_candidates",
    ]
    keep = [column for column in columns if column in selected.columns]
    output_frame = selected[keep].sort_values("target_weight", ascending=False).copy()
    output.parent.mkdir(parents=True, exist_ok=True)
    output_frame.to_parquet(output, index=False)
    output_frame.attrs["turnover"] = selected.attrs.get("turnover")
    output_frame.attrs["constraint_audit"] = constraint_audit
    return output_frame


def run_optimize_portfolio(args: argparse.Namespace) -> Path:
    manifest = StepManifest("optimize_portfolio", vars(args).copy())
    manifest.inputs = {
        "candidates": path_profile(args.candidates, parquet=True),
        "old_portfolio": path_profile(args.old_portfolio) if args.old_portfolio else None,
    }
    try:
        frame = optimize_portfolio(
            candidates_path=Path(args.candidates),
            output=Path(args.output),
            method=args.method,
            max_weight=args.max_weight,
            min_weight=args.min_weight,
            region=args.region,
            old_portfolio=Path(args.old_portfolio) if args.old_portfolio else None,
            benchmark_active_limit=args.benchmark_active_limit,
            country_margin=args.country_margin,
            sector_margin=args.sector_margin,
            max_turnover=args.max_turnover,
            transaction_cost=args.transaction_cost,
            country_tilt_strength=args.country_tilt_strength,
            sector_tilt_strength=args.sector_tilt_strength,
        )
        total_weight = float(pd.to_numeric(frame["target_weight"], errors="coerce").sum())
        max_actual_weight = float(pd.to_numeric(frame["target_weight"], errors="coerce").max())
        duplicate_count = int(frame.duplicated(subset=["candidate_date", "Company SEDOL"], keep=False).sum())
        manifest.outputs = {"target_weights": path_profile(args.output, parquet=True)}
        manifest.details["portfolio_summary"] = summarize_frame(frame, date_column="candidate_date")
        manifest.details["constraint_audit"] = frame.attrs.get("constraint_audit")
        if frame.attrs.get("turnover") is not None:
            manifest.details["turnover"] = frame.attrs["turnover"]
        manifest.add_validation("portfolio_non_empty", not frame.empty, "目标组合非空")
        manifest.add_validation("portfolio_keys_unique", duplicate_count == 0, "目标组合主键无重复", {"duplicate_rows": duplicate_count})
        manifest.add_validation("weights_sum_to_one", abs(total_weight - 1.0) < 1e-8, "目标权重合计为 1", {"total_weight": total_weight})
        if args.max_weight is not None:
            manifest.add_validation(
                "max_weight_respected",
                max_actual_weight <= args.max_weight + 1e-12,
                "单股上限满足",
                {"max_actual_weight": max_actual_weight, "max_weight": args.max_weight},
            )
        return manifest.write("success")
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从候选池生成目标组合权重")
    parser.add_argument("--as-of", help="记录目标日期；候选池本身已包含 candidate_date")
    parser.add_argument("--candidates", default=str(DEFAULT_CANDIDATES), help="候选池 parquet")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="目标权重 parquet")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    parser.add_argument("--method", choices=["constrained", "score_weight", "equal_weight"], default="constrained", help="组合优化方法")
    parser.add_argument("--max-weight", type=float, default=0.05, help="单股权重上限；传空无法表达，默认 5%%")
    parser.add_argument("--min-weight", type=float, default=0.0, help="单股权重下限")
    parser.add_argument("--benchmark-active-limit", type=float, default=0.03, help="单股相对 benchmark 最大主动偏离")
    parser.add_argument("--country-margin", type=float, default=0.05, help="国家/区域配置相对目标允许偏离")
    parser.add_argument("--sector-margin", type=float, default=0.04, help="行业配置相对目标允许偏离")
    parser.add_argument("--max-turnover", type=float, help="相对旧组合最大换手；未传则只审计不约束")
    parser.add_argument("--transaction-cost", type=float, default=0.001, help="换手惩罚系数")
    parser.add_argument("--country-tilt-strength", type=float, default=0.15, help="Country 分数对国家目标的倾斜强度")
    parser.add_argument("--sector-tilt-strength", type=float, default=0.10, help="Sector 分数对行业目标的倾斜强度")
    parser.add_argument("--region", help="只优化某一区域")
    parser.add_argument("--old-portfolio", help="旧组合文件，可为 parquet/csv/xlsx，用于估算换手")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest_path = run_optimize_portfolio(args)
    print(f"optimize_portfolio manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

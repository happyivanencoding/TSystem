"""从候选池生成目标组合权重。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd

from optimiser import turnover as turnover_metric

from .common import CANDIDATES_DIR, PORTFOLIOS_DIR, StepManifest, path_profile, summarize_frame


DEFAULT_CANDIDATES = CANDIDATES_DIR / "latest_candidates.parquet"
DEFAULT_OUTPUT = PORTFOLIOS_DIR / "latest_target_weights.parquet"


def _normalize_weights(raw: pd.Series) -> pd.Series:
    values = pd.to_numeric(raw, errors="coerce").fillna(0.0).clip(lower=0.0)
    if values.sum() <= 0:
        return pd.Series(1.0 / len(values), index=values.index)
    return values / values.sum()


def _apply_max_weight(weights: pd.Series, max_weight: float | None) -> pd.Series:
    if max_weight is None:
        return weights / weights.sum()
    if len(weights) * max_weight < 1.0:
        raise ValueError(f"max_weight={max_weight} 对 {len(weights)} 只证券不可行")

    result = weights.copy()
    for _ in range(100):
        over = result > max_weight
        if not over.any():
            break
        capped_sum = float(over.sum() * max_weight)
        remaining = 1.0 - capped_sum
        result.loc[over] = max_weight
        under = ~over
        if under.any():
            result.loc[under] = _normalize_weights(weights.loc[under]) * remaining
    return result / result.sum()


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


def optimize_portfolio(
    *,
    candidates_path: Path,
    output: Path,
    method: str,
    max_weight: float | None,
    region: str | None,
    old_portfolio: Path | None,
) -> pd.DataFrame:
    candidates = pd.read_parquet(candidates_path)
    if "selected" not in candidates.columns:
        raise ValueError("候选池缺少 selected 列")
    selected = candidates[candidates["selected"].fillna(False)].copy()
    if region:
        selected = selected[selected["region"].astype("string").eq(region)].copy()
    if selected.empty:
        raise ValueError("没有可用于组合优化的候选证券")

    if method == "equal_weight":
        raw = pd.Series(1.0, index=selected.index)
    elif method == "score_weight":
        raw = selected["composite_score"]
    else:
        raise ValueError(f"未知优化方法: {method}")

    selected["target_weight"] = _apply_max_weight(_normalize_weights(raw), max_weight)
    selected["optimizer_method"] = method
    selected["max_weight"] = max_weight
    selected["source_candidates"] = str(candidates_path)

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
        "optimizer_method",
        "max_weight",
        "source_candidates",
    ]
    keep = [column for column in columns if column in selected.columns]
    output_frame = selected[keep].sort_values("target_weight", ascending=False).copy()
    output.parent.mkdir(parents=True, exist_ok=True)
    output_frame.to_parquet(output, index=False)
    output_frame.attrs["turnover"] = selected.attrs.get("turnover")
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
            region=args.region,
            old_portfolio=Path(args.old_portfolio) if args.old_portfolio else None,
        )
        total_weight = float(pd.to_numeric(frame["target_weight"], errors="coerce").sum())
        max_actual_weight = float(pd.to_numeric(frame["target_weight"], errors="coerce").max())
        duplicate_count = int(frame.duplicated(subset=["candidate_date", "Company SEDOL"], keep=False).sum())
        manifest.outputs = {"target_weights": path_profile(args.output, parquet=True)}
        manifest.details["portfolio_summary"] = summarize_frame(frame, date_column="candidate_date")
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
    parser.add_argument("--method", choices=["score_weight", "equal_weight"], default="score_weight", help="baseline 优化方法")
    parser.add_argument("--max-weight", type=float, default=0.05, help="单股权重上限；传空无法表达，默认 5%%")
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

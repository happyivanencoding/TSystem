"""
Build and officially backtest Nasdaq same-security relative-change variables.

Absolute level variables are converted into new raw variables using:
- directional_delta: direction-normalized level change versus the same security lag
- score_delta: current neutralized score minus the same security lagged score

Each relative variant is then tested through the same official Top/Worst gate
used for level raw variables.
"""

from __future__ import annotations

import argparse
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

import run_nasdaq_multifactor_research as base  # noqa: E402
from tp_research.executor import (  # noqa: E402
    GateThresholds,
    RelativeLevelSpec,
    build_same_security_relative_variables,
    evaluate_official_top_worst_gate,
)


AD_HOC_ROOT = BACKTEST_ROOT / "runs" / "ad_hoc"
DEFAULT_LEVEL_GATE = AD_HOC_ROOT / "nasdaq_raw_gate_20260708" / "raw_validation_gate.csv"
CHANGE_LIKE_TOKENS = ("growth", "revision", "pmom", "total return", "cagr")


def parse_csv_arg(raw: str | None, default: list[str]) -> list[str]:
    if raw is None or raw.strip().lower() == "all":
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_lags(raw: str) -> list[int]:
    lags: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        lag = int(item)
        if lag <= 0:
            raise ValueError(f"Lag must be positive: {lag}")
        lags.append(lag)
    return sorted(set(lags))


def raw_source(spec: base.RawMetricSpec) -> str:
    text = f"{spec.column} {spec.note}"
    if "CIQ" in text:
        return "CIQ"
    if spec.family in {"lowvol", "momentum"} or "drawdown" in spec.column.lower() or "vol" in spec.column.lower():
        return "local_derived_or_market"
    return "FactSet_or_database"


def select_level_specs(columns: set[str]) -> list[base.RawMetricSpec]:
    specs = []
    for spec in base.RAW_METRICS:
        name = spec.column.lower()
        if spec.column not in columns:
            continue
        if any(token in name for token in CHANGE_LIKE_TOKENS):
            continue
        specs.append(spec)
    return specs


def relative_column(spec: base.RawMetricSpec, transform: str, lag: int) -> str:
    prefix = "reldelta" if transform == "directional_delta" else "relrank"
    return f"nasdaq_{prefix}_{base.slugify(spec.family)}_{base.slugify(spec.column)}_lag{lag}_score"


def meta_row(spec: base.RawMetricSpec, metric: str, transform: str, lag: int) -> dict[str, object]:
    return {
        "metric": metric,
        "raw_column": spec.column,
        "base_family": spec.family,
        "role": spec.role,
        "source": raw_source(spec),
        "base_direction": spec.direction,
        "transform": transform,
        "lag_observations": lag,
        "economic_read": economic_read(spec, transform, lag),
        "base_note": spec.note,
    }


def economic_read(spec: base.RawMetricSpec, transform: str, lag: int) -> str:
    if transform == "score_delta":
        return f"relative peer-rank improvement over {lag} screen observations"
    if spec.direction > 0:
        return f"improvement over {lag} screen observations"
    return f"decline in a lower-is-better level over {lag} screen observations"


def build_relative_screen(
    screen_path: Path,
    returns: pd.DataFrame,
    output_dir: Path,
    *,
    lags: list[int],
    transforms: list[str],
    force: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[base.ModelSpec], pd.DataFrame]:
    output_path = output_dir / "nasdaq_relative_variable_screen.parquet"
    specs_path = output_dir / "metric_definitions.json"
    meta_path = output_dir / "relative_variable_definitions.csv"
    if output_path.exists() and specs_path.exists() and meta_path.exists() and not force:
        screen = pd.read_parquet(output_path)
        definitions = json.loads(specs_path.read_text(encoding="utf-8"))
        metrics = [base.ModelSpec(**item) for item in definitions]
        meta = pd.read_csv(meta_path)
        checks = base.construction_checks(screen, returns, pq.ParquetFile(screen_path).metadata.num_rows)
        diag = relative_diagnostics(screen, metrics, meta)
        return screen, checks, diag, metrics, meta

    columns = base.available_columns(screen_path)
    level_specs = select_level_specs(columns)
    required = [
        base.DATE_COL,
        base.ISIN_COL,
        base.SEDOL_COL,
        "Name",
        base.SECTOR_COL,
        base.MKT_CAP_COL,
        base.WEIGHT_COL,
    ]
    read_columns = list(dict.fromkeys(base.existing(required, columns) + [spec.column for spec in level_specs]))
    missing_required = sorted(set(required).difference(read_columns))
    if missing_required:
        raise ValueError(f"Missing required screen columns: {missing_required}")

    screen = pd.read_parquet(screen_path, columns=read_columns)
    if base.ISIN_COL not in screen.columns and screen.index.name == base.ISIN_COL:
        screen = screen.reset_index()
    if base.ISIN_COL not in screen.columns and "__index_level_0__" in screen.columns:
        screen = screen.rename(columns={"__index_level_0__": base.ISIN_COL})
    screen[base.DATE_COL] = pd.to_datetime(screen[base.DATE_COL], errors="coerce")
    screen = screen[pd.to_numeric(screen[base.WEIGHT_COL], errors="coerce").fillna(0) > 0].copy()
    screen = screen.dropna(subset=[base.DATE_COL, base.ISIN_COL, base.SEDOL_COL, base.SECTOR_COL])
    screen = screen.sort_values([base.ISIN_COL, base.DATE_COL]).reset_index(drop=True)

    spec_lookup = {spec.column: spec for spec in level_specs}
    screen, definitions = build_same_security_relative_variables(
        screen,
        [
            RelativeLevelSpec(
                raw_column=spec.column,
                score_column=spec.score_column,
                family=spec.family,
                direction=spec.direction,
                role=spec.role,
                source=raw_source(spec),
                note=spec.note,
            )
            for spec in level_specs
        ],
        lags=lags,
        transforms=transforms,
        date_col=base.DATE_COL,
        security_col=base.ISIN_COL,
        sector_col=base.SECTOR_COL,
        raw_score=lambda frame, spec: base.score_raw_metric(
            frame,
            spec_lookup[spec.raw_column],
        ),
        winsorize=base.winsorize_by_date,
        sector_score=base.sector_rank_score,
        column_name=lambda spec, transform, lag: relative_column(
            spec_lookup[spec.raw_column],
            transform,
            lag,
        ),
    )
    metrics: list[base.ModelSpec] = []
    meta_rows: list[dict[str, object]] = []
    for _, definition in definitions.iterrows():
        spec = spec_lookup[str(definition["raw_column"])]
        transform = str(definition["transform"])
        lag = int(definition["lag_observations"])
        column = str(definition["metric"])
        metrics.append(
            base.ModelSpec(
                column=column,
                label=(
                    f"{spec.family}: d{lag} {spec.column}"
                    if transform == "directional_delta"
                    else f"{spec.family}: rank d{lag} {spec.column}"
                ),
                family=f"relative_{spec.family}",
                components={
                    (
                        spec.column
                        if transform == "directional_delta"
                        else spec.score_column
                    ): (
                        float(spec.direction)
                        if transform == "directional_delta"
                        else 1.0
                    )
                },
                note=(
                    f"direction-adjusted level change versus lag {lag} "
                    "screen observations"
                    if transform == "directional_delta"
                    else f"sector-rank score change versus lag {lag} "
                    "screen observations"
                ),
            )
        )
        meta_rows.append(meta_row(spec, column, transform, lag))
    meta = pd.DataFrame(meta_rows)
    checks = base.construction_checks(screen, returns, pq.ParquetFile(screen_path).metadata.num_rows)
    checks = pd.concat(
        [
            checks,
            pd.DataFrame(
                [
                    {"check": "absolute_level_candidate_count", "value": len(level_specs)},
                    {"check": "relative_metric_count", "value": len(metrics)},
                    {"check": "lag_observations", "value": ",".join(map(str, lags))},
                    {"check": "transform_types", "value": ",".join(transforms)},
                    {
                        "check": "relative_signal_rule",
                        "value": "same-security lagged observation; current minus lag after higher-is-better direction normalization",
                    },
                ]
            ),
        ],
        ignore_index=True,
    )
    diag = relative_diagnostics(screen, metrics, meta)
    screen.to_parquet(output_path, index=False)
    specs_path.write_text(json.dumps([metric.__dict__ for metric in metrics], ensure_ascii=False, indent=2), encoding="utf-8")
    meta.to_csv(meta_path, index=False)
    return screen, checks, diag, metrics, meta


def relative_diagnostics(screen: pd.DataFrame, metrics: list[base.ModelSpec], meta: pd.DataFrame) -> pd.DataFrame:
    diag = base.metric_diagnostics(screen, metrics, [])
    if diag.empty or meta.empty:
        return diag
    return diag.merge(meta, on="metric", how="left")


def relative_gate_table(
    summary: pd.DataFrame,
    metric_diag: pd.DataFrame,
    meta: pd.DataFrame,
    *,
    min_coverage: float,
    min_ratio_cagr: float,
    min_top_worst_ratio: float,
    min_robust_score: float,
) -> pd.DataFrame:
    gate = evaluate_official_top_worst_gate(
        summary,
        metric_diag,
        thresholds=GateThresholds(
            min_coverage=min_coverage,
            min_ratio_cagr=min_ratio_cagr,
            min_top_worst_ratio=min_top_worst_ratio,
            min_robust_score=min_robust_score,
        ),
        metadata=meta,
        metrics=meta["metric"].astype(str),
    )
    if not gate.empty:
        gate["top_success"] = gate["official_top_complete"]
        gate["worst_success"] = gate["official_worst_complete"]
    return gate


def compare_with_level_gate(relative_gate: pd.DataFrame, level_gate_path: Path, output_dir: Path) -> pd.DataFrame:
    if relative_gate.empty or not level_gate_path.exists():
        return pd.DataFrame()
    level = pd.read_csv(level_gate_path)
    level_key = "raw_column" if "raw_column" in level.columns else "raw_variable" if "raw_variable" in level.columns else ""
    if not level_key:
        return pd.DataFrame()
    level = level.rename(columns={level_key: "raw_column"}).copy()
    if "pass_gate" not in level.columns and "passed" in level.columns:
        level["pass_gate"] = level["passed"].astype(bool)
    if "ratio_cagr" not in level.columns and "top_ratio_cagr" in level.columns:
        level["ratio_cagr"] = level["top_ratio_cagr"]
    level_top = level.drop_duplicates("raw_column", keep="first").copy()
    rel_best = (
        relative_gate.sort_values(["pass_gate", "robust_score", "ratio_cagr"], ascending=[False, False, False])
        .drop_duplicates("raw_column", keep="first")
        .copy()
    )
    rel_cols = [
        "raw_column",
        "base_family",
        "metric",
        "transform",
        "lag_observations",
        "coverage",
        "ratio_cagr",
        "top_worst_ratio_return",
        "robust_score",
        "pass_gate",
    ]
    rel_best = rel_best[[col for col in rel_cols if col in rel_best.columns]].rename(
        columns={
            "metric": "best_relative_metric",
            "base_family": "family",
            "coverage": "relative_coverage",
            "ratio_cagr": "relative_ratio_cagr",
            "top_worst_ratio_return": "relative_top_worst_ratio_return",
            "robust_score": "relative_robust_score",
            "pass_gate": "relative_pass_gate",
        }
    )
    level_cols = [
        "raw_column",
        "metric",
        "coverage",
        "ratio_cagr",
        "top_worst_ratio_return",
        "robust_score",
        "pass_gate",
    ]
    level_top = level_top[[col for col in level_cols if col in level_top.columns]].rename(
        columns={
            "metric": "level_metric",
            "coverage": "level_coverage",
            "ratio_cagr": "level_ratio_cagr",
            "top_worst_ratio_return": "level_top_worst_ratio_return",
            "robust_score": "level_robust_score",
            "pass_gate": "level_pass_gate",
        }
    )
    out = rel_best.merge(level_top, on="raw_column", how="left")
    out["relative_minus_level_robust"] = out["relative_robust_score"] - out["level_robust_score"]
    out["relative_minus_level_ratio_cagr"] = out["relative_ratio_cagr"] - out["level_ratio_cagr"]
    out["relative_improves_level"] = out["relative_minus_level_robust"] > 0
    out = out.sort_values(["relative_pass_gate", "relative_minus_level_robust"], ascending=[False, False])
    out.to_csv(output_dir / "relative_vs_level_comparison.csv", index=False)
    return out.reset_index(drop=True)


def write_report(
    *,
    output_dir: Path,
    checks: pd.DataFrame,
    metric_diag: pd.DataFrame,
    run_results: pd.DataFrame,
    summary: pd.DataFrame,
    gate: pd.DataFrame,
    comparison: pd.DataFrame,
    plot_paths: list[str],
    args: argparse.Namespace,
) -> Path:
    top_summary = pd.DataFrame()
    if not summary.empty and "robust_score" in summary.columns:
        top_summary = summary[(summary["status"].eq("success")) & (summary["side"].eq("Top"))].sort_values(
            "robust_score", ascending=False
        )
    passed = gate[gate["pass_gate"].eq(True)].copy() if not gate.empty and "pass_gate" in gate.columns else pd.DataFrame()
    lines = [
        "# Nasdaq 相对 raw variable 官方回测研究",
        "",
        f"- 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 证据口径: official exact Top/Worst backtest",
        "- 研究问题: 绝对水平变量是否应转成同一股票历史变化或同业排名改善后再进入 gate",
        f"- Universe / Benchmark: `{base.BENCHMARK}`",
        f"- 研究目录: `{output_dir}`",
        f"- lag observations: `{args.lags}`",
        f"- transforms: `{args.transforms}`",
        "",
        "## 数据构造检查",
        "",
        base.frame_to_markdown(checks),
        "",
        "## 相对变量定义与覆盖",
        "",
        base.frame_to_markdown(metric_diag.sort_values(["base_family", "raw_column", "transform", "lag_observations"]), max_rows=260)
        if not metric_diag.empty
        else "暂无变量定义。",
        "",
        "## 官方回测运行状态",
        "",
        base.frame_to_markdown(run_results[["metric", "side", "start_date", "status", "message", "run_dir"]], max_rows=360)
        if not run_results.empty
        else "暂无回测运行。",
        "",
        "## Relative Gate 结果",
        "",
        base.frame_to_markdown(gate, max_rows=180) if not gate.empty else "暂无 gate 结果。",
        "",
        "## 稳健性排序 Top 相对变量",
        "",
    ]
    if top_summary.empty:
        lines.append("暂无成功回测可汇总。")
    else:
        display_cols = [
            "metric",
            "raw_column",
            "base_family",
            "transform",
            "lag_observations",
            "coverage",
            "start_date",
            "ratio_cagr",
            "ratio_max_drawdown",
            "tracking_error",
            "rolling_3y_min_ratio_cagr",
            "annual_active_hit_rate",
            "top_worst_ratio_return",
            "worst_ratio_return",
            "avg_turnover",
            "robust_score",
        ]
        merged = top_summary.merge(metric_diag.drop_duplicates("metric"), on="metric", how="left", suffixes=("", "_diag"))
        lines.append(base.frame_to_markdown(merged[[col for col in display_cols if col in merged.columns]], max_rows=120))

    lines.extend(["", "## 与原始水平变量对照", ""])
    if comparison.empty:
        lines.append("未生成对照表；可能没有提供 raw-level gate 文件。")
    else:
        display_cols = [
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
        ]
        lines.append(base.frame_to_markdown(comparison[[col for col in display_cols if col in comparison.columns]], max_rows=120))

    lines.extend(["", "## 初步结论", ""])
    if passed.empty:
        lines.extend(
            [
                "- 按当前 gate，没有相对变量同时通过 coverage、Top/Benchmark ratio CAGR、Top/Worst ratio 和 robust score。",
                "- 相对变量只能作为诊断或后续候选，不能进入 validated family，也不能据此声明协同。",
            ]
        )
    else:
        fam_counts = passed.groupby("base_family", dropna=False).size().sort_values(ascending=False)
        lines.extend(
            [
                f"- 通过 gate 的相对变量数量: {len(passed)}。",
                f"- 通过数量最多的 family: {', '.join(f'{idx}={val}' for idx, val in fam_counts.items())}。",
                f"- 当前最稳健相对变量: `{passed.iloc[0]['metric']}`，原始字段 `{passed.iloc[0]['raw_column']}`。",
                "- 这些变量只是新的 raw variable 通过 gate；是否有协同，必须继续看 pair / subset / leave-one-out official evidence。",
            ]
        )
    lines.extend(["", "## Plotly 输出", ""])
    lines.extend([f"- `{path}`" for path in plot_paths] or ["- 未生成 Plotly 输出。"])
    report_path = output_dir / "nasdaq_relative_variable_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and backtest Nasdaq relative-change variables.")
    parser.add_argument("--screen", default=str(base.DEFAULT_SCREEN))
    parser.add_argument("--returns", default=str(base.DEFAULT_RETURNS))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--lags", default="1,3,12", help="Comma-separated same-security lag observations.")
    parser.add_argument("--transforms", default="directional_delta,score_delta")
    parser.add_argument("--metrics", default="all", help="Comma-separated metric columns, or all.")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--force-rebuild", action="store_true")
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--level-gate", default=str(DEFAULT_LEVEL_GATE))
    parser.add_argument("--gate-coverage", type=float, default=0.75)
    parser.add_argument("--gate-ratio-cagr", type=float, default=0.0)
    parser.add_argument("--gate-top-worst-ratio", type=float, default=0.0)
    parser.add_argument("--gate-robust-score", type=float, default=0.0)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    screen_path = Path(args.screen)
    returns_path = Path(args.returns)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else AD_HOC_ROOT / f"nasdaq_relative_variables_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    lags = parse_lags(args.lags)
    transforms = parse_csv_arg(args.transforms, ["directional_delta", "score_delta"])
    unknown_transforms = sorted(set(transforms).difference({"directional_delta", "score_delta"}))
    if unknown_transforms:
        raise ValueError(f"Unknown transforms: {unknown_transforms}")

    returns = base.load_tabular_file(returns_path)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index()
    screen, checks, metric_diag, metric_specs, meta = build_relative_screen(
        screen_path,
        returns,
        output_dir,
        lags=lags,
        transforms=transforms,
        force=args.force_rebuild,
    )
    research_screen_path = output_dir / "nasdaq_relative_variable_screen.parquet"
    checks.to_csv(output_dir / "data_construction_checks.csv", index=False)
    metric_diag.to_csv(output_dir / "metric_diagnostics.csv", index=False)

    all_metrics = [spec.column for spec in metric_specs if spec.column in screen.columns]
    metric_columns = parse_csv_arg(args.metrics, all_metrics)
    unknown = sorted(set(metric_columns).difference(all_metrics))
    if unknown:
        raise ValueError(f"Unknown metrics: {unknown}")

    run_results = pd.DataFrame()
    summary = pd.DataFrame()
    gate = pd.DataFrame()
    comparison = pd.DataFrame()
    plot_paths: list[str] = []
    if not args.build_only:
        try:
            run_root_name = output_dir.resolve().relative_to((BACKTEST_ROOT / "runs").resolve()).as_posix()
        except ValueError:
            run_root_name = f"ad_hoc/{base.slugify(output_dir.name)}"
        existing_results = None
        existing_results_path = output_dir / "official_run_results.csv"
        if args.resume and existing_results_path.exists():
            existing_results = pd.read_csv(existing_results_path)
        run_results = base.run_official_backtests(
            screen=screen,
            returns=returns,
            screen_path=research_screen_path,
            returns_path=returns_path,
            run_root_name=run_root_name,
            metrics=metric_columns,
            max_runs=args.max_runs,
            progress_path=existing_results_path,
            existing_results=existing_results,
        )
        run_results.to_csv(output_dir / "official_run_results.csv", index=False)
        summary = base.summarize_runs(run_results, metric_diag)
        summary.to_csv(output_dir / "performance_summary.csv", index=False)
        gate = relative_gate_table(
            summary,
            metric_diag,
            meta,
            min_coverage=args.gate_coverage,
            min_ratio_cagr=args.gate_ratio_cagr,
            min_top_worst_ratio=args.gate_top_worst_ratio,
            min_robust_score=args.gate_robust_score,
        )
        gate.to_csv(output_dir / "relative_validation_gate.csv", index=False)
        comparison = compare_with_level_gate(gate, Path(args.level_gate), output_dir)
        plot_paths = base.write_plotly_outputs(summary, run_results, output_dir)

    report_path = write_report(
        output_dir=output_dir,
        checks=checks,
        metric_diag=metric_diag,
        run_results=run_results,
        summary=summary,
        gate=gate,
        comparison=comparison,
        plot_paths=plot_paths,
        args=args,
    )
    manifest = {
        "output_dir": str(output_dir),
        "research_screen": str(research_screen_path),
        "report": str(report_path),
        "benchmark": base.BENCHMARK,
        "lags": lags,
        "transforms": transforms,
        "metrics": metric_columns,
        "build_only": bool(args.build_only),
        "resume": bool(args.resume),
        "expected_run_count": int(2 * len(metric_columns)),
        "run_count": int(len(run_results)),
        "success_count": int(run_results["status"].eq("success").sum()) if not run_results.empty else 0,
        "gate_pass_count": int(gate["pass_gate"].sum()) if not gate.empty and "pass_gate" in gate.columns else 0,
        "gate_total_count": int(len(gate)) if not gate.empty else 0,
        "plot_paths": plot_paths,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if run_results.empty or run_results["status"].eq("success").any() else 1


if __name__ == "__main__":
    raise SystemExit(main())

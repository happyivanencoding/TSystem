"""Research runner for SP500 rebuilt six-family factor combinations."""

from __future__ import annotations

import argparse
from datetime import datetime
from itertools import combinations
import json
from pathlib import Path
import sys
from typing import Iterable

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
BACKTEST_ROOT = SCRIPT_DIR.parents[0]
TP_ROOT = BACKTEST_ROOT.parent

for path in (SCRIPT_DIR, TP_ROOT, BACKTEST_ROOT, BACKTEST_ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_eu_small_multifactor_research as base  # noqa: E402
from backtest_code.research.executor import (  # noqa: E402
    GateThresholds,
    evaluate_official_top_worst_gate,
)
from tp_core.backtesting import nav_engine_metadata  # noqa: E402


BENCHMARK = "SP500"
WEIGHT_COL = f"Weight in {BENCHMARK}"
AD_HOC_ROOT = BACKTEST_ROOT / "runs" / "ad_hoc"
FAMILIES = ("growth", "value", "quality", "lowvol", "momentum", "dividend")


def configure_base() -> None:
    base.BENCHMARK = BENCHMARK
    base.WEIGHT_COL = WEIGHT_COL
    base.AD_HOC_ROOT = AD_HOC_ROOT


def combo_column(families: tuple[str, ...]) -> str:
    return "sp500_mf_" + "_".join(families)


def add_family_combinations(
    screen: pd.DataFrame,
    metric_specs: list[base.ModelSpec],
    families: tuple[str, ...] = FAMILIES,
) -> list[base.ModelSpec]:
    family_scores = {family: f"eu_small_{family}_rebuilt" for family in FAMILIES}
    missing = [family_scores[family] for family in families if family_scores[family] not in screen.columns]
    if missing:
        raise ValueError(f"Missing rebuilt family columns: {missing}")

    specs = list(metric_specs)
    existing_metrics = {spec.column for spec in specs}
    for size in range(1, len(families) + 1):
        for subset in combinations(families, size):
            column = combo_column(subset)
            components = {family_scores[family]: 1.0 / size for family in subset}
            min_count = 1 if size == 1 else min(size, 4)
            screen[column] = base.weighted_scores(screen, components, min_count)
            if column in existing_metrics:
                continue
            specs.append(
                base.ModelSpec(
                    column=column,
                    label=" + ".join(subset),
                    family=f"sp500_combo_{size}",
                    components=components,
                    note="equal-weight rebuilt-family subset combination",
                )
            )
            existing_metrics.add(column)
    return specs


def frame_to_markdown(frame: pd.DataFrame, *, max_rows: int | None = None) -> str:
    return base.frame_to_markdown(frame, max_rows=max_rows)


def write_sp500_report(
    *,
    output_dir: Path,
    checks: pd.DataFrame,
    metric_diag: pd.DataFrame,
    run_results: pd.DataFrame,
    summary: pd.DataFrame,
    plot_paths: list[str],
    metric_columns: list[str],
    args: argparse.Namespace,
) -> Path:
    top_summary = pd.DataFrame()
    if not summary.empty and "robust_score" in summary.columns:
        top_summary = summary[(summary["status"].eq("success")) & (summary["side"].eq("Top"))].sort_values(
            "robust_score", ascending=False
        )

    combo_diag = metric_diag[metric_diag["family"].astype(str).str.startswith("sp500_combo")].copy()
    lines = [
        "# SP500 六因子全组合模型研究报告",
        "",
        f"- 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 证据口径: official exact backtest",
        f"- 模式: {'smoke' if args.smoke else 'full'}",
        f"- Universe / Benchmark: `{BENCHMARK}`",
        f"- 研究目录: `{output_dir}`",
        f"- 计划回测 metric 数: {len(metric_columns)}；Top/Worst 计划 run 数: {2 * len(metric_columns)}",
        "",
        "## 数据构造检查",
        "",
        frame_to_markdown(checks),
        "",
        "## SP500 组合定义与覆盖",
        "",
        frame_to_markdown(combo_diag.sort_values(["family", "coverage"], ascending=[True, False]), max_rows=90)
        if not combo_diag.empty
        else "暂无组合定义。",
        "",
        "## 全部因子覆盖与定义",
        "",
        frame_to_markdown(metric_diag.sort_values(["family", "coverage"], ascending=[True, False]), max_rows=140),
        "",
        "## 回测运行状态",
        "",
        frame_to_markdown(run_results[["metric", "side", "start_date", "status", "message", "run_dir"]], max_rows=180)
        if not run_results.empty
        else "暂无回测运行。",
        "",
        "## 稳健性排序",
        "",
    ]

    if top_summary.empty:
        lines.append("暂无成功回测可汇总。")
    else:
        display_cols = [
            "metric",
            "family",
            "coverage",
            "start_date",
            "cagr",
            "vol",
            "max_drawdown",
            "ratio_cagr",
            "ratio_max_drawdown",
            "tracking_error",
            "rolling_3y_min_ratio_cagr",
            "annual_active_hit_rate",
            "top_worst_ratio_return",
            "top_worst_ratio_max_drawdown",
            "worst_ratio_return",
            "avg_holdings",
            "avg_turnover",
            "robust_score",
        ]
        cols = [col for col in display_cols if col in top_summary.columns]
        lines.append(frame_to_markdown(top_summary[cols], max_rows=80))
        best = top_summary.iloc[0]
        combo_only = top_summary[top_summary["metric"].astype(str).str.startswith("sp500_mf_")]
        if not combo_only.empty:
            combo_best = combo_only.iloc[0]
            lines.extend(
                [
                    "",
                    "## 初步结论",
                    "",
                    f"- 全部候选中稳健性排序第一: `{best['metric']}`。",
                    f"- SP500 全组合中稳健性排序第一: `{combo_best['metric']}`。",
                    "- robust_score 优先惩罚 Top/Benchmark ratio 回撤、tracking error 和滚动 3 年失效，再看 Top/Worst 分化。",
                    "- existing style/database 因子只作为比较锚；最终候选优先看重建 family 组合。",
                ]
            )

    lines.extend(["", "## Plotly 输出", ""])
    lines.extend([f"- `{path}`" for path in plot_paths] or ["- 未生成 Plotly 输出。"])
    report_path = output_dir / "sp500_multifactor_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def parse_metric_set(raw: str | None, default: list[str]) -> list[str]:
    return base.parse_csv_arg(raw, default)


def raw_metric_specs(metric_specs: list[base.ModelSpec]) -> list[base.ModelSpec]:
    return [spec for spec in metric_specs if spec.family.startswith("raw_") and spec.column]


def resolve_summary_path(raw: str) -> Path:
    path = Path(raw)
    return path / "performance_summary.csv" if path.is_dir() else path


def apply_validated_family_components(
    *,
    screen: pd.DataFrame,
    metric_specs: list[base.ModelSpec],
    metric_diag: pd.DataFrame,
    validation_summary_path: Path,
    min_coverage: float,
    min_robust_score: float,
    min_ratio_cagr: float,
    min_top_worst_ratio: float,
    output_dir: Path,
) -> list[base.ModelSpec]:
    validation = pd.read_csv(validation_summary_path)
    passing: dict[str, list[base.ModelSpec]] = {family: [] for family in FAMILIES}

    raw_specs = raw_metric_specs(metric_specs)
    raw_by_column = {spec.column: spec for spec in raw_specs}
    metadata = pd.DataFrame(
        [
            {
                "metric": spec.column,
                "family": spec.family.removeprefix("raw_"),
                "label": spec.label,
                "note": spec.note,
            }
            for spec in raw_specs
        ]
    )
    gate = evaluate_official_top_worst_gate(
        validation,
        metric_diag,
        thresholds=GateThresholds(
            min_coverage=min_coverage,
            min_ratio_cagr=min_ratio_cagr,
            min_top_worst_ratio=min_top_worst_ratio,
            min_robust_score=min_robust_score,
        ),
        metadata=metadata,
        metrics=raw_by_column,
    )
    gate["passed"] = gate["pass_gate"] if not gate.empty else False
    for _, row in gate[gate["passed"].astype(bool)].iterrows():
        spec = raw_by_column.get(str(row["metric"]))
        if spec is not None:
            passing.setdefault(str(row["family"]), []).append(spec)

    gate.sort_values(
        ["family", "passed", "robust_score"],
        ascending=[True, False, False],
    ).to_csv(
        output_dir / "raw_validation_gate.csv",
        index=False,
    )

    specs_by_column = {
        spec.column: spec
        for spec in metric_specs
        if spec.column not in {f"eu_small_{family}_rebuilt" for family in FAMILIES}
        and not spec.column.startswith("sp500_mf_")
    }
    min_counts = {"growth": 3, "value": 4, "quality": 2, "lowvol": 2, "momentum": 2, "dividend": 2}
    for family in FAMILIES:
        selected = passing.get(family, [])
        columns = [spec.column for spec in selected]
        score_col = f"eu_small_{family}_rebuilt"
        min_count = max(1, min(min_counts[family], len(columns))) if columns else 1
        screen[score_col] = base.average_scores(screen, columns, min_count) if columns else pd.NA
        specs_by_column[score_col] = base.ModelSpec(
            score_col,
            f"{family} validated rebuilt",
            f"validated_{family}",
            {column: 1.0 for column in columns},
            f"raw-validated average; {len(columns)} components passed gate",
        )
    return list(specs_by_column.values())


def enabled_families(metric_specs: list[base.ModelSpec]) -> tuple[str, ...]:
    specs = {spec.column: spec for spec in metric_specs}
    enabled = []
    for family in FAMILIES:
        spec = specs.get(f"eu_small_{family}_rebuilt")
        if spec is not None and spec.components:
            enabled.append(family)
    return tuple(enabled)


def run_official_backtests_incremental(
    *,
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    screen_path: Path,
    returns_path: Path,
    run_root_name: str,
    metrics: list[str],
    max_runs: int | None,
    results_path: Path,
    existing_results: pd.DataFrame | None = None,
    sides: list[str] | None = None,
) -> pd.DataFrame:
    service = base.BacktestService()
    selected_sides = {str(side).strip().title() for side in sides} if sides else {"Top", "Worst"}
    side_pairs = [(side, top) for side, top in (("Top", True), ("Worst", False)) if side in selected_sides]
    completed_pairs: set[tuple[str, str]] = set()
    records = []
    if existing_results is not None and not existing_results.empty:
        reusable = existing_results[existing_results["status"].isin(["success", "skipped"])].copy()
        for _, row in reusable.iterrows():
            completed_pairs.add((str(row["metric"]), str(row["side"])))
        records.extend(reusable.to_dict("records"))
    launched = 0

    def flush() -> None:
        pd.DataFrame(records).to_csv(results_path, index=False)

    flush()
    for metric in metrics:
        if metric not in screen.columns:
            continue
        start = base.first_eligible_start(screen, metric)
        for side, top in side_pairs:
            if (metric, side) in completed_pairs:
                continue
            if max_runs is not None and launched >= max_runs:
                flush()
                return pd.DataFrame(records)
            record = {
                "benchmark": BENCHMARK,
                "metric": metric,
                "side": side,
                "top": top,
                "start_date": start.strftime("%Y-%m-%d") if start is not None else "",
                "status": "skipped",
                "message": "no eligible benchmark/signal intersection",
                "run_dir": "",
            }
            if start is None:
                records.append(record)
                completed_pairs.add((metric, side))
                flush()
                continue

            settings = base.load_settings("default")
            settings.user.name = f"{run_root_name}/official_runs"
            settings.paths.screen = str(screen_path)
            settings.paths.returns = str(returns_path)
            settings.run.mode = "research"
            settings.run.ptf_name = f"SP500_{base.slugify(metric)}_{side.upper()}"
            settings.run.bench = BENCHMARK
            settings.run.metrics = [metric]
            settings.run.percentile = base.PERCENTILE
            settings.run.top = top
            settings.run.ponderation = "Racine cube"
            settings.run.esg_exclusion = 0.0
            settings.run.cut_mkt_cap = 0.0
            settings.run.score_neutral = "ICB 19"
            settings.run.weight_neutral = "ICB 19"
            settings.run.max_weight = 1.0
            settings.run.fill_method = "drift"
            settings.run.start_date = start.strftime("%Y-%m-%d")
            settings.run.screen_start_date = None
            settings.run.mode_monthly_prod = False

            record.update(base.run_single_official_engine(service, settings, screen=screen, returns=returns, side=side))
            records.append(record)
            completed_pairs.add((metric, side))
            launched += 1
            flush()
    return pd.DataFrame(records)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and backtest SP500 rebuilt factor combinations.")
    parser.add_argument("--screen", default=str(base.DEFAULT_SCREEN))
    parser.add_argument("--returns", default=str(base.DEFAULT_RETURNS))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--metrics", default="all", help="Comma-separated metric columns, or all.")
    parser.add_argument("--smoke", action="store_true", help="Only run the six-factor full combination Top/Worst.")
    parser.add_argument("--build-only", action="store_true", help="Build diagnostics and factor screen without official backtests.")
    parser.add_argument("--force-rebuild", action="store_true", help="Rebuild research screen if it already exists.")
    parser.add_argument("--max-runs", type=int, default=None, help="Optional cap on official runs.")
    parser.add_argument("--resume", action="store_true", help="Reuse successful official runs already listed in output-dir.")
    parser.add_argument("--candidate-only", action="store_true", help="Run only rebuilt SP500 family combinations, excluding database anchors.")
    parser.add_argument("--raw-only", action="store_true", help="Run only raw rebuilt-variable scores.")
    parser.add_argument("--validated-from", default="", help="Raw-variable performance_summary.csv or its run directory.")
    parser.add_argument("--min-raw-coverage", type=float, default=0.75)
    parser.add_argument("--min-raw-robust-score", type=float, default=0.0)
    parser.add_argument("--min-raw-ratio-cagr", type=float, default=0.0)
    parser.add_argument("--min-raw-top-worst-ratio", type=float, default=0.0)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    configure_base()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    screen_path = Path(args.screen)
    returns_path = Path(args.returns)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else AD_HOC_ROOT / f"sp500_multifactor_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    returns = base.load_tabular_file(returns_path)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index()
    screen, checks, _, metric_specs = base.build_research_screen(screen_path, returns, output_dir, force=args.force_rebuild)
    metric_specs = list({spec.column: spec for spec in metric_specs}.values())
    metric_diag = base.metric_diagnostics(screen, metric_specs, list(base.RAW_METRICS)).drop_duplicates("metric", keep="last")
    if args.validated_from:
        metric_specs = apply_validated_family_components(
            screen=screen,
            metric_specs=metric_specs,
            metric_diag=metric_diag,
            validation_summary_path=resolve_summary_path(args.validated_from),
            min_coverage=args.min_raw_coverage,
            min_robust_score=args.min_raw_robust_score,
            min_ratio_cagr=args.min_raw_ratio_cagr,
            min_top_worst_ratio=args.min_raw_top_worst_ratio,
            output_dir=output_dir,
        )
    combo_families = enabled_families(metric_specs) if args.validated_from else FAMILIES
    metric_specs = add_family_combinations(screen, metric_specs, combo_families)
    metric_specs = list({spec.column: spec for spec in metric_specs}.values())

    research_screen_path = output_dir / "sp500_multifactor_screen.parquet"
    screen.to_parquet(research_screen_path, index=False)
    (output_dir / "metric_definitions.json").write_text(
        json.dumps([metric.__dict__ for metric in metric_specs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    metric_diag = base.metric_diagnostics(screen, metric_specs, list(base.RAW_METRICS)).drop_duplicates("metric", keep="last")
    checks.to_csv(output_dir / "data_construction_checks.csv", index=False)
    metric_diag.to_csv(output_dir / "metric_diagnostics.csv", index=False)

    combo_metrics = [spec.column for spec in metric_specs if spec.column.startswith("sp500_mf_")]
    raw_metrics = [spec.column for spec in raw_metric_specs(metric_specs) if spec.column in screen.columns]
    all_metrics = raw_metrics if args.raw_only else combo_metrics if args.candidate_only else [spec.column for spec in metric_specs if spec.column in screen.columns]
    metric_columns = [combo_column(FAMILIES)] if args.smoke else parse_metric_set(args.metrics, all_metrics)
    unknown = sorted(set(metric_columns).difference(all_metrics))
    if unknown:
        raise ValueError(f"Unknown metrics: {unknown}")

    run_results = pd.DataFrame()
    summary = pd.DataFrame()
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
        run_results = run_official_backtests_incremental(
            screen=screen,
            returns=returns,
            screen_path=research_screen_path,
            returns_path=returns_path,
            run_root_name=run_root_name,
            metrics=metric_columns,
            max_runs=args.max_runs,
            results_path=existing_results_path,
            existing_results=existing_results,
        )
        run_results.to_csv(output_dir / "official_run_results.csv", index=False)
        summary = base.summarize_runs(run_results, metric_diag)
        summary.to_csv(output_dir / "performance_summary.csv", index=False)
        plot_paths = base.write_plotly_outputs(summary, run_results, output_dir)

    report_path = write_sp500_report(
        output_dir=output_dir,
        checks=checks,
        metric_diag=metric_diag,
        run_results=run_results,
        summary=summary,
        plot_paths=plot_paths,
        metric_columns=metric_columns,
        args=args,
    )
    manifest = {
        **nav_engine_metadata(
            strictly_after_rebalance=True,
            apply_weights_at_close=True,
        ),
        "output_dir": str(output_dir),
        "research_screen": str(research_screen_path),
        "report": str(report_path),
        "benchmark": BENCHMARK,
        "metrics": metric_columns,
        "smoke": bool(args.smoke),
        "build_only": bool(args.build_only),
        "resume": bool(args.resume),
        "candidate_only": bool(args.candidate_only),
        "raw_only": bool(args.raw_only),
        "validated_from": str(args.validated_from),
        "raw_gate": {
            "min_coverage": args.min_raw_coverage,
            "min_robust_score": args.min_raw_robust_score,
            "min_ratio_cagr": args.min_raw_ratio_cagr,
            "min_top_worst_ratio": args.min_raw_top_worst_ratio,
        },
        "expected_run_count": int(2 * len(metric_columns)),
        "run_count": int(len(run_results)),
        "success_count": int(run_results["status"].eq("success").sum()) if not run_results.empty else 0,
        "plot_paths": plot_paths,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if run_results.empty or run_results["status"].eq("success").any() else 1


if __name__ == "__main__":
    raise SystemExit(main())

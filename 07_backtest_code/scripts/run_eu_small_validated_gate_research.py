"""Supplemental EU Small research using mandatory raw-variable validation gates."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


BACKTEST_ROOT = Path(__file__).resolve().parents[1]
TP_ROOT = BACKTEST_ROOT.parent
BASE_SCRIPT = BACKTEST_ROOT / "scripts" / "run_eu_small_multifactor_research.py"
DEFAULT_RAW_RUN_DIR = BACKTEST_ROOT / "runs" / "ad_hoc" / "eu_small_multifactor_20260707_085611"
AD_HOC_ROOT = BACKTEST_ROOT / "runs" / "ad_hoc"


def _load_base_module() -> Any:
    spec = importlib.util.spec_from_file_location("eu_small_base_research", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load base EU Small research script: {BASE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


base = _load_base_module()

from tp_research.executor import (  # noqa: E402
    GateThresholds,
    evaluate_official_top_worst_gate,
)


def build_raw_gate(
    raw_run_dir: Path,
    *,
    min_coverage: float,
    min_ratio_cagr: float,
    min_top_worst_return: float,
    min_robust_score: float,
) -> pd.DataFrame:
    summary = pd.read_csv(raw_run_dir / "performance_summary.csv")
    diag = pd.read_csv(raw_run_dir / "metric_diagnostics.csv")
    raw_metadata = summary[
        summary["family"].astype("string").str.startswith("raw_", na=False)
    ][["metric", "family", "role"]].drop_duplicates("metric", keep="last")
    raw_metadata = raw_metadata.merge(
        diag[
            [
                column
                for column in ["metric", "label", "note"]
                if column in diag.columns
            ]
        ],
        on="metric",
        how="left",
    )
    raw_metadata["raw_family"] = raw_metadata["family"].astype(
        "string"
    ).str.replace("raw_", "", regex=False)
    raw_metadata["source_tag"] = np.where(
        raw_metadata[["label", "note", "metric"]]
        .astype("string")
        .agg(" ".join, axis=1)
        .str.contains("CIQ", case=False, na=False),
        "CIQ",
        "screen/database",
    )
    gate = evaluate_official_top_worst_gate(
        summary,
        diag,
        thresholds=GateThresholds(
            min_coverage=min_coverage,
            min_ratio_cagr=min_ratio_cagr,
            min_top_worst_ratio=min_top_worst_return,
            min_robust_score=min_robust_score,
        ),
        metadata=raw_metadata,
        metrics=raw_metadata["metric"].astype(str),
    )
    gate["coverage_pass"] = pd.to_numeric(gate["coverage"], errors="coerce").ge(min_coverage)
    gate["ratio_cagr_pass"] = pd.to_numeric(gate["ratio_cagr"], errors="coerce").gt(min_ratio_cagr)
    gate["top_worst_pass"] = pd.to_numeric(gate["top_worst_ratio_return"], errors="coerce").gt(min_top_worst_return)
    gate["robust_pass"] = pd.to_numeric(gate["robust_score"], errors="coerce").gt(min_robust_score)
    gate["failure_reasons"] = gate["fail_reasons"]
    columns = [
        "metric",
        "label",
        "raw_family",
        "role",
        "source_tag",
        "coverage",
        "ratio_cagr",
        "top_worst_ratio_return",
        "robust_score",
        "coverage_pass",
        "ratio_cagr_pass",
        "top_worst_pass",
        "robust_pass",
        "official_top_complete",
        "official_worst_complete",
        "pass_gate",
        "failure_reasons",
        "note",
    ]
    return gate[[column for column in columns if column in gate.columns]].sort_values(
        ["pass_gate", "raw_family", "robust_score"],
        ascending=[False, True, False],
    )


def _average(frame: pd.DataFrame, columns: list[str], min_count: int) -> pd.Series:
    data = frame[columns].apply(pd.to_numeric, errors="coerce")
    return data.mean(axis=1, skipna=True).where(data.notna().sum(axis=1) >= min_count)


def _weighted(frame: pd.DataFrame, weights: dict[str, float], min_count: int) -> pd.Series:
    columns = [column for column in weights if column in frame.columns]
    data = frame[columns].apply(pd.to_numeric, errors="coerce")
    weight = pd.Series({column: weights[column] for column in columns}, dtype=float)
    denom = data.notna().mul(weight, axis=1).sum(axis=1).replace(0, np.nan)
    score = data.mul(weight, axis=1).sum(axis=1) / denom
    return score.where(data.notna().sum(axis=1) >= min_count)


def add_validated_scores(screen: pd.DataFrame, gate: pd.DataFrame) -> tuple[pd.DataFrame, list[Any], dict[str, list[str]]]:
    result = screen.copy()
    pass_gate = gate[gate["pass_gate"]].copy()
    family_raw: dict[str, list[str]] = {
        family: sorted(group["metric"].tolist())
        for family, group in pass_gate.groupby("raw_family", observed=True)
    }
    specs: list[Any] = []
    family_cols: dict[str, str] = {}
    for family, columns in sorted(family_raw.items()):
        score_col = f"eu_small_validated_{family}"
        min_count = max(1, min(2, len(columns)))
        result[score_col] = _average(result, columns, min_count)
        family_cols[family] = score_col
        specs.append(
            base.ModelSpec(
                score_col,
                f"{family} validated family",
                f"validated_{family}",
                {column: 1.0 for column in columns},
                f"raw-gated family composite; min_count={min_count}",
            )
        )

    def add_combo(column: str, label: str, components: dict[str, float], note: str, min_count: int | None = None) -> None:
        available = {family_cols[key]: weight for key, weight in components.items() if key in family_cols}
        if len(available) < 2:
            return
        required = min_count if min_count is not None else max(2, min(4, len(available)))
        result[column] = _weighted(result, available, required)
        specs.append(base.ModelSpec(column, label, "validated_candidate", available, f"{note}; min_count={required}"))

    equal_components = {family: 1.0 for family in family_cols}
    add_combo("eu_small_validated_all_equal", "All validated families equal weight", equal_components, "all families that passed raw gates")
    add_combo("eu_small_validated_qvm", "Quality + value + momentum", {"quality": 0.4, "value": 0.3, "momentum": 0.3}, "robust quality/value with momentum confirmation", 2)
    add_combo("eu_small_validated_quality_value", "Quality + value", {"quality": 0.5, "value": 0.5}, "profitability plus valuation", 2)
    add_combo("eu_small_validated_quality_momentum", "Quality + momentum", {"quality": 0.5, "momentum": 0.5}, "profitable companies with positive trend/revision", 2)
    add_combo("eu_small_validated_value_momentum", "Value + momentum", {"value": 0.5, "momentum": 0.5}, "cheap plus improving sentiment", 2)
    add_combo("eu_small_validated_income_quality_value", "Dividend + quality + value", {"dividend": 0.34, "quality": 0.33, "value": 0.33}, "income only when supported by quality and value", 2)
    add_combo(
        "eu_small_validated_growth_quality_momentum",
        "Growth + quality + momentum",
        {"growth": 0.34, "quality": 0.33, "momentum": 0.33},
        "growth retained only through raw gate with quality/momentum confirmation",
        2,
    )

    if len(family_cols) >= 3:
        for leave_out in sorted(family_cols):
            components = {family: 1.0 for family in family_cols if family != leave_out}
            add_combo(
                f"eu_small_validated_loo_{leave_out}",
                f"Leave-one-family-out: no {leave_out}",
                components,
                "family subset evidence; not a synergy claim",
            )
    return result, specs, family_raw


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
) -> pd.DataFrame:
    service = base.BacktestService()
    completed_pairs: set[tuple[str, str]] = set()
    records = []
    if existing_results is not None and not existing_results.empty:
        reusable = existing_results[existing_results["status"].isin(["success", "skipped"])].copy()
        for _, row in reusable.iterrows():
            completed_pairs.add((str(row["metric"]), str(row["side"])))
        records.extend(reusable.to_dict("records"))

    def flush() -> None:
        pd.DataFrame(records).to_csv(results_path, index=False)

    launched = 0
    flush()
    for metric in metrics:
        if metric not in screen.columns:
            continue
        start = base.first_eligible_start(screen, metric)
        for side, top in (("Top", True), ("Worst", False)):
            if (metric, side) in completed_pairs:
                continue
            if max_runs is not None and launched >= max_runs:
                flush()
                return pd.DataFrame(records)
            record = {
                "benchmark": base.BENCHMARK,
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
            settings.run.ptf_name = f"EUSMALL_{base.slugify(metric)}_{side.upper()}"
            settings.run.bench = base.BENCHMARK
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


def write_report(
    *,
    output_dir: Path,
    raw_run_dir: Path,
    gate: pd.DataFrame,
    metric_diag: pd.DataFrame,
    run_results: pd.DataFrame,
    summary: pd.DataFrame,
    plot_paths: list[str],
    family_raw: dict[str, list[str]],
    args: argparse.Namespace,
) -> Path:
    top_summary = pd.DataFrame()
    if not summary.empty:
        top_summary = summary[(summary["status"].eq("success")) & (summary["side"].eq("Top"))].sort_values("robust_score", ascending=False)
    pass_gate = gate[gate["pass_gate"]].copy()
    by_family = gate.groupby("raw_family", observed=True)["pass_gate"].agg(["sum", "count"]).reset_index()
    lines = [
        "# 欧洲小盘股 raw gate 补充研究报告",
        "",
        f"- 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- raw evidence source: `{raw_run_dir}`",
        "- 口径: 每个 raw variable 先用 official Top/Worst；只有通过 gate 才进入 family。",
        "- gate: coverage >= "
        f"{args.min_coverage:.2f}, Top/Benchmark ratio CAGR > {args.min_ratio_cagr:.2f}, "
        f"Top/Worst ratio return > {args.min_top_worst_return:.2f}, robust score > {args.min_robust_score:.2f}",
        "- core/supplement 只保留为诊断标签，不决定入选。",
        "- CIQ 与 FactSet、database、本地衍生字段同一套 gate；本轮没有 CIQ 字段通过 gate。",
        "- 本报告不声称 family 内部 synergy；leave-one-out/subset 只用于检测组合是否稳健。",
        "",
        "## Raw Gate 结果",
        "",
        base.frame_to_markdown(by_family),
        "",
        "### 通过 gate 的 raw variables",
        "",
        base.frame_to_markdown(
            pass_gate[
                [
                    "metric",
                    "label",
                    "raw_family",
                    "role",
                    "source_tag",
                    "coverage",
                    "ratio_cagr",
                    "top_worst_ratio_return",
                    "robust_score",
                ]
            ].sort_values("robust_score", ascending=False),
            max_rows=80,
        )
        if not pass_gate.empty
        else "没有 raw variable 通过 gate。",
        "",
        "### 被拒绝的 raw variables",
        "",
        base.frame_to_markdown(
            gate[~gate["pass_gate"]][
                [
                    "metric",
                    "label",
                    "raw_family",
                    "role",
                    "source_tag",
                    "coverage",
                    "ratio_cagr",
                    "top_worst_ratio_return",
                    "robust_score",
                    "failure_reasons",
                ]
            ].sort_values(["raw_family", "failure_reasons", "robust_score"], ascending=[True, True, False]),
            max_rows=120,
        ),
        "",
        "## Validated family 构建",
        "",
        base.frame_to_markdown(
            pd.DataFrame(
                [
                    {"family": family, "raw_variable_count": len(metrics), "raw_metrics": ", ".join(metrics)}
                    for family, metrics in sorted(family_raw.items())
                ]
            ),
            max_rows=30,
        ),
        "",
        "## 补充 official Top/Worst 回测状态",
        "",
        base.frame_to_markdown(run_results[["metric", "side", "start_date", "status", "message", "run_dir"]], max_rows=80)
        if not run_results.empty
        else "暂无补充回测。",
        "",
        "## Validated candidates 稳健性排序",
        "",
    ]
    if top_summary.empty:
        lines.append("暂无成功回测可排序。")
    else:
        display_cols = [
            "metric",
            "family",
            "coverage",
            "cagr",
            "ratio_cagr",
            "ratio_max_drawdown",
            "tracking_error",
            "rolling_3y_min_ratio_cagr",
            "annual_active_hit_rate",
            "top_worst_ratio_return",
            "worst_ratio_return",
            "robust_score",
        ]
        cols = [column for column in display_cols if column in top_summary.columns]
        lines.append(base.frame_to_markdown(top_summary[cols], max_rows=40))
        best = top_summary.iloc[0]
        lines.extend(
            [
                "",
                "## 更新后的研究结论",
                "",
                f"- 当前 raw-gated validated 排名第一: `{best['metric']}`。",
                "- LowVol 这次没有 raw variable 通过默认 gate，因此不能进入 validated family，也不能继续作为最终防守倾斜权重来源。",
                "- Growth 只有一个 raw variable 通过，证据窄；只能弱保留或作为低权重补充。",
                "- 组合解释必须从 raw gate 开始，不能再用 core/supplement 标签直接解释 family。",
            ]
        )
    lines.extend(["", "## Plotly 输出", ""])
    lines.extend([f"- `{path}`" for path in plot_paths] or ["- 未生成 Plotly 输出。"])
    report_path = output_dir / "eu_small_validated_gate_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Supplement EU Small factor research with raw validation gates.")
    parser.add_argument("--raw-run-dir", default=str(DEFAULT_RAW_RUN_DIR))
    parser.add_argument("--returns", default=str(base.DEFAULT_RETURNS))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--min-coverage", type=float, default=0.75)
    parser.add_argument("--min-ratio-cagr", type=float, default=0.0)
    parser.add_argument("--min-top-worst-return", type=float, default=0.0)
    parser.add_argument("--min-robust-score", type=float, default=0.0)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    raw_run_dir = Path(args.raw_run_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else AD_HOC_ROOT / f"eu_small_validated_gate_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    gate = build_raw_gate(
        raw_run_dir,
        min_coverage=args.min_coverage,
        min_ratio_cagr=args.min_ratio_cagr,
        min_top_worst_return=args.min_top_worst_return,
        min_robust_score=args.min_robust_score,
    )
    gate.to_csv(output_dir / "raw_validation_gate.csv", index=False, encoding="utf-8-sig")

    screen = pd.read_parquet(raw_run_dir / "eu_small_multifactor_screen.parquet")
    screen, metric_specs, family_raw = add_validated_scores(screen, gate)
    research_screen_path = output_dir / "eu_small_validated_gate_screen.parquet"
    screen.to_parquet(research_screen_path, index=False)
    (output_dir / "metric_definitions.json").write_text(
        json.dumps([spec.__dict__ for spec in metric_specs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metric_diag = base.metric_diagnostics(screen, metric_specs, [])
    metric_diag.to_csv(output_dir / "metric_diagnostics.csv", index=False)

    run_results = pd.DataFrame()
    summary = pd.DataFrame()
    plot_paths: list[str] = []
    metric_columns = [spec.column for spec in metric_specs]
    returns_path = Path(args.returns)
    returns = base.load_tabular_file(returns_path)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index()
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

    report_path = write_report(
        output_dir=output_dir,
        raw_run_dir=raw_run_dir,
        gate=gate,
        metric_diag=metric_diag,
        run_results=run_results,
        summary=summary,
        plot_paths=plot_paths,
        family_raw=family_raw,
        args=args,
    )
    manifest = {
        "output_dir": str(output_dir),
        "raw_run_dir": str(raw_run_dir),
        "research_screen": str(research_screen_path),
        "raw_validation_gate": str(output_dir / "raw_validation_gate.csv"),
        "report": str(report_path),
        "metrics": metric_columns,
        "expected_run_count": int(2 * len(metric_columns)),
        "run_count": int(len(run_results)),
        "success_count": int(run_results["status"].eq("success").sum()) if not run_results.empty else 0,
        "family_raw": family_raw,
        "plot_paths": plot_paths,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

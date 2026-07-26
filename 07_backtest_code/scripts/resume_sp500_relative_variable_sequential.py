"""Sequential resume/finalize path for SP500 relative-variable official runs."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Iterable

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
BACKTEST_ROOT = SCRIPT_DIR.parents[0]
TP_ROOT = BACKTEST_ROOT.parent

import run_sp500_multifactor_research as sp500  # noqa: E402
import run_sp500_relative_variable_parallel as parallel  # noqa: E402
import run_sp500_relative_variable_research as relsp  # noqa: E402


relsp.configure()
base = sp500.base
rel = relsp.rel


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sequentially resume SP500 relative-variable official runs.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--returns", default=str(base.DEFAULT_RETURNS))
    parser.add_argument("--wave", default="")
    parser.add_argument("--metrics", default="all")
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--level-gate", default=str(rel.DEFAULT_LEVEL_GATE))
    parser.add_argument("--gate-coverage", type=float, default=0.75)
    parser.add_argument("--gate-ratio-cagr", type=float, default=0.0)
    parser.add_argument("--gate-top-worst-ratio", type=float, default=0.0)
    parser.add_argument("--gate-robust-score", type=float, default=0.0)
    return parser


def finalize(
    *,
    output_dir: Path,
    returns_path: Path,
    level_gate: Path,
    gate_coverage: float,
    gate_ratio_cagr: float,
    gate_top_worst_ratio: float,
    gate_robust_score: float,
    wave: str,
) -> dict[str, object]:
    main_results_path = output_dir / "official_run_results.csv"
    shard_paths = sorted((output_dir / "parallel_shards").rglob("official_run_results.csv"))
    run_results = parallel.load_completed([main_results_path, *shard_paths])
    run_results.to_csv(main_results_path, index=False)
    metric_diag = pd.read_csv(output_dir / "metric_diagnostics.csv")
    meta = pd.read_csv(output_dir / "relative_variable_definitions.csv")
    checks = pd.read_csv(output_dir / "data_construction_checks.csv")
    summary = base.summarize_runs(run_results, metric_diag)
    summary.to_csv(output_dir / "performance_summary.csv", index=False)
    gate = rel.relative_gate_table(
        summary,
        metric_diag,
        meta,
        min_coverage=gate_coverage,
        min_ratio_cagr=gate_ratio_cagr,
        min_top_worst_ratio=gate_top_worst_ratio,
        min_robust_score=gate_robust_score,
    )
    gate.to_csv(output_dir / "relative_validation_gate.csv", index=False)
    comparison = rel.compare_with_level_gate(gate, level_gate, output_dir)
    plot_paths = base.write_plotly_outputs(summary, run_results, output_dir)
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    report_args = argparse.Namespace(
        lags=",".join(map(str, manifest.get("lags", []))),
        transforms=",".join(manifest.get("transforms", [])),
    )
    report_path = rel.write_report(
        output_dir=output_dir,
        checks=checks,
        metric_diag=metric_diag,
        run_results=run_results,
        summary=summary,
        gate=gate,
        comparison=comparison,
        plot_paths=plot_paths,
        args=report_args,
    )
    manifest.update(
        {
            "output_dir": str(output_dir),
            "research_screen": str(output_dir / "sp500_relative_variable_screen.parquet"),
            "report": str(report_path),
            "benchmark": base.BENCHMARK,
            "sequential_resume_wave": wave,
            "sequential_resume_last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "expected_run_count": int(2 * len(json.loads((output_dir / "metric_definitions.json").read_text(encoding="utf-8")))),
            "run_count": int(len(run_results)),
            "success_count": int(run_results["status"].eq("success").sum()) if not run_results.empty else 0,
            "gate_pass_count": int(gate["pass_gate"].sum()) if not gate.empty and "pass_gate" in gate.columns else 0,
            "gate_total_count": int(len(gate)) if not gate.empty else 0,
            "plot_paths": plot_paths,
            "returns": str(returns_path),
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    output_dir = Path(args.output_dir)
    screen_path = output_dir / "sp500_relative_variable_screen.parquet"
    returns_path = Path(args.returns)
    if not screen_path.exists():
        raise FileNotFoundError(f"Missing research screen: {screen_path}")

    metric_specs = parallel.load_metric_specs(output_dir)
    all_metrics = [spec.column for spec in metric_specs]
    metrics = parallel.parse_csv_arg(args.metrics, all_metrics)
    unknown = sorted(set(metrics).difference(all_metrics))
    if unknown:
        raise ValueError(f"Unknown metrics: {unknown}")

    main_results_path = output_dir / "official_run_results.csv"
    shard_paths = sorted((output_dir / "parallel_shards").rglob("official_run_results.csv"))
    completed = parallel.load_completed([main_results_path, *shard_paths])
    completed.to_csv(main_results_path, index=False)
    remaining = parallel.incomplete_metrics(metrics, completed)
    wave = args.wave.strip() or datetime.now().strftime("seq_%Y%m%d_%H%M%S")
    print(
        json.dumps(
            {
                "event": "sequential_resume_start",
                "metric_total": len(metrics),
                "metric_remaining": len(remaining),
                "existing_rows": len(completed),
                "wave": wave,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    if remaining:
        returns = base.load_tabular_file(returns_path)
        returns.index = pd.to_datetime(returns.index, errors="coerce")
        returns = returns.sort_index()
        screen = pd.read_parquet(screen_path)
        sp500.run_official_backtests_incremental(
            screen=screen,
            returns=returns,
            screen_path=screen_path,
            returns_path=returns_path,
            run_root_name=f"ad_hoc/sp500_rv_{wave}",
            metrics=remaining,
            max_runs=args.max_runs,
            results_path=main_results_path,
            existing_results=completed,
        )

    manifest = finalize(
        output_dir=output_dir,
        returns_path=returns_path,
        level_gate=Path(args.level_gate),
        gate_coverage=args.gate_coverage,
        gate_ratio_cagr=args.gate_ratio_cagr,
        gate_top_worst_ratio=args.gate_top_worst_ratio,
        gate_robust_score=args.gate_robust_score,
        wave=wave,
    )
    print(json.dumps({"event": "sequential_resume_complete", **manifest}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

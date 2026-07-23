"""Parallel official Top/Worst launcher for SP500 relative variables."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
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

import run_sp500_multifactor_research as sp500  # noqa: E402
import run_sp500_relative_variable_research as relsp  # noqa: E402
from backtest_code.research.executor import (  # noqa: E402
    dedupe_official_results,
    incomplete_official_metrics,
    read_official_results,
    shard_metric_names,
)


relsp.configure()
base = sp500.base
rel = relsp.rel


def parse_csv_arg(raw: str | None, default: list[str]) -> list[str]:
    if raw is None or raw.strip().lower() == "all":
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def load_metric_specs(output_dir: Path) -> list[base.ModelSpec]:
    definitions = json.loads((output_dir / "metric_definitions.json").read_text(encoding="utf-8"))
    return [base.ModelSpec(**item) for item in definitions]


def dedupe_results(results: pd.DataFrame) -> pd.DataFrame:
    if results.empty or not {"metric", "side", "status"}.issubset(results.columns):
        return results
    status_rank = {"success": 3, "skipped": 2, "failed": 1}
    out = results.copy()
    out["_status_rank"] = out["status"].map(status_rank).fillna(0)
    out["_order"] = range(len(out))
    out = out.sort_values(["metric", "side", "_status_rank", "_order"], ascending=[True, True, False, True])
    out = out.drop_duplicates(["metric", "side"], keep="first")
    return out.drop(columns=["_status_rank", "_order"]).sort_values(["metric", "side"]).reset_index(drop=True)


def load_completed(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        if path.exists() and path.stat().st_size > 0:
            try:
                frames.append(pd.read_csv(path))
            except pd.errors.EmptyDataError:
                continue
    return dedupe_results(pd.concat(frames, ignore_index=True)) if frames else pd.DataFrame()


def incomplete_metrics(metrics: list[str], completed: pd.DataFrame) -> list[str]:
    if completed.empty:
        return list(metrics)
    done = set(
        (str(row["metric"]), str(row["side"]))
        for _, row in completed[completed["status"].isin(["success", "skipped"])].iterrows()
    )
    return [metric for metric in metrics if (metric, "Top") not in done or (metric, "Worst") not in done]


def shard_metrics(metrics: list[str], workers: int) -> list[list[str]]:
    shards = [[] for _ in range(max(workers, 1))]
    for idx, metric in enumerate(metrics):
        shards[idx % len(shards)].append(metric)
    return [shard for shard in shards if shard]


dedupe_results = dedupe_official_results
load_completed = read_official_results
incomplete_metrics = incomplete_official_metrics
shard_metrics = shard_metric_names


def worker_run(payload: dict[str, object]) -> dict[str, object]:
    output_dir = Path(str(payload["output_dir"]))
    screen_path = Path(str(payload["screen_path"]))
    returns_path = Path(str(payload["returns_path"]))
    wave = str(payload["wave"])
    shard_id = int(payload["shard_id"])
    metrics = list(payload["metrics"])
    existing_results_path = Path(str(payload["existing_results_path"]))
    shard_dir = output_dir / "parallel_shards" / wave / f"shard_{shard_id:02d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_results_path = shard_dir / "official_run_results.csv"

    existing_frames = []
    for path in (existing_results_path, shard_results_path):
        if path.exists() and path.stat().st_size > 0:
            try:
                existing_frames.append(pd.read_csv(path))
            except pd.errors.EmptyDataError:
                pass
    existing = pd.DataFrame()
    if existing_frames:
        existing = dedupe_results(pd.concat(existing_frames, ignore_index=True))
        existing = existing[existing["metric"].isin(metrics)].copy()

    screen = pd.read_parquet(screen_path)
    returns = base.load_tabular_file(returns_path)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index()
    run_root_name = f"ad_hoc/sp500_rv_{wave}_s{shard_id:02d}"
    results = sp500.run_official_backtests_incremental(
        screen=screen,
        returns=returns,
        screen_path=screen_path,
        returns_path=returns_path,
        run_root_name=run_root_name,
        metrics=metrics,
        max_runs=None,
        results_path=shard_results_path,
        existing_results=existing,
    )
    results = dedupe_results(results)
    results.to_csv(shard_results_path, index=False)
    return {
        "shard_id": shard_id,
        "metrics": len(metrics),
        "rows": len(results),
        "success": int(results["status"].eq("success").sum()) if not results.empty else 0,
        "path": str(shard_results_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parallel official backtests for SP500 relative variables.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--returns", default=str(base.DEFAULT_RETURNS))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--wave", default="")
    parser.add_argument("--metrics", default="all")
    parser.add_argument("--level-gate", default=str(rel.DEFAULT_LEVEL_GATE))
    parser.add_argument("--gate-coverage", type=float, default=0.75)
    parser.add_argument("--gate-ratio-cagr", type=float, default=0.0)
    parser.add_argument("--gate-top-worst-ratio", type=float, default=0.0)
    parser.add_argument("--gate-robust-score", type=float, default=0.0)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    output_dir = Path(args.output_dir)
    screen_path = output_dir / "sp500_relative_variable_screen.parquet"
    returns_path = Path(args.returns)
    if not screen_path.exists():
        raise FileNotFoundError(f"Missing research screen: {screen_path}")

    metric_specs = load_metric_specs(output_dir)
    all_metrics = [spec.column for spec in metric_specs]
    metrics = parse_csv_arg(args.metrics, all_metrics)
    unknown = sorted(set(metrics).difference(all_metrics))
    if unknown:
        raise ValueError(f"Unknown metrics: {unknown}")

    main_results_path = output_dir / "official_run_results.csv"
    shard_paths = sorted((output_dir / "parallel_shards").rglob("official_run_results.csv"))
    completed = load_completed([main_results_path, *shard_paths])
    remaining = incomplete_metrics(metrics, completed)
    shards = shard_metrics(remaining, max(args.workers, 1))
    wave = args.wave.strip() or datetime.now().strftime("wave_%Y%m%d_%H%M%S")
    print(
        json.dumps(
            {
                "event": "parallel_start",
                "workers": max(args.workers, 1),
                "metric_total": len(metrics),
                "metric_remaining": len(remaining),
                "existing_rows": len(completed),
                "wave": wave,
                "shards": [len(shard) for shard in shards],
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
                "returns_path": str(returns_path),
                "existing_results_path": str(main_results_path),
                "wave": wave,
                "shard_id": idx,
                "metrics": shard,
            }
            for idx, shard in enumerate(shards)
        ]
        with ProcessPoolExecutor(max_workers=max(args.workers, 1)) as executor:
            futures = [executor.submit(worker_run, payload) for payload in payloads]
            for future in as_completed(futures):
                print(json.dumps({"event": "shard_done", **future.result()}, ensure_ascii=False), flush=True)

    shard_paths = sorted((output_dir / "parallel_shards").rglob("official_run_results.csv"))
    run_results = load_completed([main_results_path, *shard_paths])
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
        min_coverage=args.gate_coverage,
        min_ratio_cagr=args.gate_ratio_cagr,
        min_top_worst_ratio=args.gate_top_worst_ratio,
        min_robust_score=args.gate_robust_score,
    )
    gate.to_csv(output_dir / "relative_validation_gate.csv", index=False)
    comparison = rel.compare_with_level_gate(gate, Path(args.level_gate), output_dir)
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
            "research_screen": str(screen_path),
            "report": str(report_path),
            "benchmark": base.BENCHMARK,
            "parallel_workers": max(args.workers, 1),
            "parallel_wave": wave,
            "parallel_last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "expected_run_count": int(2 * len(metrics)),
            "run_count": int(len(run_results)),
            "success_count": int(run_results["status"].eq("success").sum()) if not run_results.empty else 0,
            "gate_pass_count": int(gate["pass_gate"].sum()) if not gate.empty and "pass_gate" in gate.columns else 0,
            "gate_total_count": int(len(gate)) if not gate.empty else 0,
            "plot_paths": plot_paths,
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"event": "parallel_complete", **manifest}, ensure_ascii=False), flush=True)
    return 0 if run_results.empty or run_results["status"].eq("success").any() else 1


if __name__ == "__main__":
    raise SystemExit(main())

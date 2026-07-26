"""Crash-tolerant full resume loop for SP500 relative-synergy official runs."""

from __future__ import annotations
from tp_research.runtime import recorded_workflow

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Iterable


from tp_research.paths import BACKTEST_ROOT, TP_ROOT

DEFAULT_OUTPUT_DIR = (
    BACKTEST_ROOT / "runs" / "ad_hoc" / "sp500_relative_synergy_20260710"
)
RUNNER_MODULE = "tp_research.workflows.run_sp500_relative_synergy_research"
SIDES = ("Top", "Worst")
DONE_STATUSES = {"success", "skipped"}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def candidate_metrics(output_dir: Path) -> list[str]:
    path = output_dir / "candidate_map.csv"
    rows = read_csv_rows(path)
    metrics = []
    seen = set()
    for row in rows:
        metric = str(row.get("metric", "")).strip()
        if metric and metric not in seen:
            seen.add(metric)
            metrics.append(metric)
    if not metrics:
        raise FileNotFoundError(f"No candidate metrics found in {path}")
    return metrics


def completed_pairs(output_dir: Path) -> dict[tuple[str, str], str]:
    paths = [output_dir / "official_run_results.csv"]
    shard_root = output_dir / "parallel_shards"
    if shard_root.exists():
        paths.extend(sorted(shard_root.rglob("official_run_results.csv")))
    rank = {"success": 3, "skipped": 2, "failed": 1}
    done: dict[tuple[str, str], tuple[int, str]] = {}
    for path in paths:
        for row in read_csv_rows(path):
            metric = str(row.get("metric", "")).strip()
            side = str(row.get("side", "")).strip()
            status = str(row.get("status", "")).strip()
            if not metric or side not in SIDES:
                continue
            key = (metric, side)
            item = (rank.get(status, 0), status)
            if key not in done or item[0] > done[key][0]:
                done[key] = item
    return {key: status for key, (_, status) in done.items()}


def incomplete_metrics(metrics: list[str], pairs: dict[tuple[str, str], str]) -> list[str]:
    remaining = []
    for metric in metrics:
        if any(pairs.get((metric, side)) not in DONE_STATUSES for side in SIDES):
            remaining.append(metric)
    return remaining


def progress_payload(output_dir: Path, metrics: list[str]) -> dict[str, object]:
    pairs = completed_pairs(output_dir)
    remaining = incomplete_metrics(metrics, pairs)
    done_rows = sum(1 for status in pairs.values() if status in DONE_STATUSES)
    expected_rows = len(metrics) * len(SIDES)
    return {
        "event": "sp500_synergy_loop_progress",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "output_dir": str(output_dir),
        "metric_total": len(metrics),
        "metric_done": len(metrics) - len(remaining),
        "metric_remaining": len(remaining),
        "done_rows": done_rows,
        "expected_rows": expected_rows,
        "percent": round(100.0 * done_rows / expected_rows, 4) if expected_rows else 0.0,
        "next_metric": remaining[0] if remaining else "",
    }


def run_one_metric(
    *,
    output_dir: Path,
    metric: str,
    wave_prefix: str,
    sequence: int,
    timeout_seconds: int,
    logs_dir: Path,
) -> subprocess.CompletedProcess[str]:
    wave = f"{wave_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{sequence:05d}"
    log_path = logs_dir / f"{wave}_{metric}.log"
    cmd = [
        sys.executable,
        "-m",
        RUNNER_MODULE,
        "--output-dir",
        str(output_dir),
        "--metrics",
        metric,
        "--workers",
        "1",
        "--shard-size",
        "1",
        "--direct-worker",
        "--run-only",
        "--resume",
        "--wave",
        wave,
    ]
    with log_path.open("w", encoding="utf-8") as log:
        log.write(json.dumps({"event": "metric_start", "metric": metric, "wave": wave, "cmd": cmd}, ensure_ascii=False) + "\n")
        log.flush()
        result = subprocess.run(
            cmd,
            cwd=str(TP_ROOT),
            text=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
        )
        log.write(json.dumps({"event": "metric_exit", "metric": metric, "wave": wave, "returncode": result.returncode}, ensure_ascii=False) + "\n")
    return result


def finalize(output_dir: Path, wave_prefix: str, timeout_seconds: int) -> int:
    wave = f"{wave_prefix}_finalize_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    cmd = [
        sys.executable,
        "-m",
        RUNNER_MODULE,
        "--output-dir",
        str(output_dir),
        "--workers",
        "1",
        "--shard-size",
        "1",
        "--resume",
        "--wave",
        wave,
    ]
    result = subprocess.run(
        cmd,
        cwd=str(TP_ROOT),
        timeout=timeout_seconds if timeout_seconds > 0 else None,
    )
    return int(result.returncode)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run all incomplete SP500 relative-synergy metrics one process at a time.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--wave-prefix", default="wave_20260710_sp500_synergy_loop")
    parser.add_argument("--limit", type=int, default=0, help="Maximum metrics to launch in this invocation; 0 means all.")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--metric-timeout-seconds", type=int, default=900)
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    return parser


@recorded_workflow
def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    output_dir = Path(args.output_dir)
    logs_dir = output_dir / "resume_full_loop_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    metrics = candidate_metrics(output_dir)
    launched = 0
    failures: list[dict[str, object]] = []
    while True:
        progress = progress_payload(output_dir, metrics)
        print(json.dumps(progress, ensure_ascii=False), flush=True)
        if not progress["metric_remaining"]:
            if args.finalize:
                rc = finalize(output_dir, args.wave_prefix, args.metric_timeout_seconds * 3)
                print(json.dumps({"event": "sp500_synergy_loop_finalize_exit", "returncode": rc}, ensure_ascii=False), flush=True)
                return rc
            return 0
        if args.limit and launched >= args.limit:
            return 0

        metric = str(progress["next_metric"])
        success = False
        for attempt in range(1, max(1, args.retries) + 1):
            print(
                json.dumps(
                    {"event": "sp500_synergy_loop_metric_attempt", "metric": metric, "attempt": attempt, "launched": launched + 1},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            try:
                result = run_one_metric(
                    output_dir=output_dir,
                    metric=metric,
                    wave_prefix=args.wave_prefix,
                    sequence=launched + 1,
                    timeout_seconds=args.metric_timeout_seconds,
                    logs_dir=logs_dir,
                )
                if result.returncode != 0:
                    failures.append({"metric": metric, "attempt": attempt, "returncode": result.returncode})
            except subprocess.TimeoutExpired:
                failures.append({"metric": metric, "attempt": attempt, "returncode": "timeout"})
            pairs = completed_pairs(output_dir)
            if all(pairs.get((metric, side)) in DONE_STATUSES for side in SIDES):
                success = True
                break
            time.sleep(max(0.0, float(args.sleep_seconds)))
        launched += 1
        if not success:
            payload = {"event": "sp500_synergy_loop_metric_incomplete_after_retries", "metric": metric, "failures": failures[-args.retries :]}
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            if args.stop_on_failure:
                (logs_dir / "last_failure.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                return 2
        time.sleep(max(0.0, float(args.sleep_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())

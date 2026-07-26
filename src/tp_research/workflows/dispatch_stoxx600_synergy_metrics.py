from __future__ import annotations
from tp_research.runtime import recorded_workflow

import argparse
import glob
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd


from tp_core.workspace import RESEARCH_RUNS_DIR

RUNNER_MODULE = "tp_research.workflows.run_stoxx600_relative_synergy_research"
OUT_DIR = RESEARCH_RUNS_DIR / "ad_hoc" / "stoxx600_relative_synergy_20260709"


def deduped_status(output_dir: Path) -> tuple[pd.DataFrame, list[str]]:
    candidate_map = pd.read_csv(output_dir / "candidate_map.csv")
    all_metrics = [
        str(metric)
        for metric in candidate_map.loc[candidate_map["candidate_type"] != "bucket_component", "metric"].tolist()
    ]
    paths = [output_dir / "official_run_results.csv"]
    paths.extend(Path(path) for path in glob.glob(str(output_dir / "parallel_shards" / "**" / "official_run_results.csv"), recursive=True))
    frames: list[pd.DataFrame] = []
    for path in paths:
        if path.exists() and path.stat().st_size:
            try:
                frames.append(pd.read_csv(path))
            except Exception:
                pass
    if frames:
        results = pd.concat(frames, ignore_index=True)
    else:
        results = pd.DataFrame(columns=["metric", "side", "status"])
    if not results.empty:
        rank = {"success": 3, "skipped": 2, "failed": 1}
        results = results.copy()
        results["_rank"] = results["status"].map(rank).fillna(0)
        results["_order"] = range(len(results))
        results = results.sort_values(["metric", "side", "_rank", "_order"], ascending=[True, True, False, True])
        results = results.drop_duplicates(["metric", "side"], keep="first").drop(columns=["_rank", "_order"])
    done = {
        (str(row["metric"]), str(row["side"]))
        for _, row in results[results["status"].isin(["success", "skipped"])].iterrows()
    }
    remaining = [metric for metric in all_metrics if (metric, "Top") not in done or (metric, "Worst") not in done]
    return results, remaining


def run_metric(metric: str, output_dir: Path, batch: int, slot: int) -> subprocess.Popen:
    wave = f"wave_20260710_dispatch_{batch:03d}_{slot:02d}"
    stdout = output_dir / f"dispatch_{batch:03d}_{slot:02d}_stdout.log"
    stderr = output_dir / f"dispatch_{batch:03d}_{slot:02d}_stderr.log"
    for path in (stdout, stderr):
        path.unlink(missing_ok=True)
    args = [
        sys.executable,
        "-m",
        RUNNER_MODULE,
        "--workers",
        "1",
        "--metrics",
        metric,
        "--wave",
        wave,
        "--no-pool",
    ]
    return subprocess.Popen(args, cwd=str(REPO), stdout=stdout.open("w", encoding="utf-8"), stderr=stderr.open("w", encoding="utf-8"))


@recorded_workflow
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--sleep", type=float, default=2.0)
    parser.add_argument("--max-batches", type=int, default=100)
    parser.add_argument("--output-dir", default=str(OUT_DIR))
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    for batch in range(1, args.max_batches + 1):
        results, remaining = deduped_status(output_dir)
        done_count = int(results["status"].isin(["success", "skipped"]).sum()) if not results.empty else 0
        print(
            {
                "event": "batch_start",
                "batch": batch,
                "done_sides": done_count,
                "remaining_metrics": len(remaining),
            },
            flush=True,
        )
        if not remaining:
            break
        metrics = remaining[: max(1, args.batch_size)]
        procs = [(metric, run_metric(metric, output_dir, batch, idx + 1)) for idx, metric in enumerate(metrics)]
        while procs:
            alive = []
            for metric, proc in procs:
                code = proc.poll()
                if code is None:
                    alive.append((metric, proc))
                else:
                    print({"event": "metric_done", "batch": batch, "metric": metric, "exit": code}, flush=True)
            procs = alive
            if procs:
                time.sleep(args.sleep)
    results, remaining = deduped_status(output_dir)
    print(
        {
            "event": "dispatch_done",
            "done_sides": int(results["status"].isin(["success", "skipped"]).sum()) if not results.empty else 0,
            "remaining_metrics": len(remaining),
        },
        flush=True,
    )
    if not remaining:
        subprocess.run(
            [
                sys.executable,
                "-m",
                RUNNER_MODULE,
                "--workers",
                "1",
                "--wave",
                "wave_20260710_final_summarize",
            ],
            cwd=str(REPO),
            check=False,
        )
    return 0 if not remaining else 1


if __name__ == "__main__":
    raise SystemExit(main())

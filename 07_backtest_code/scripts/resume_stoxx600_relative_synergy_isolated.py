"""
Resume STOXX600 relative-synergy official runs one side at a time.

This driver is intentionally conservative. It launches the existing official
runner in a child process for one missing Top/Worst side at a time. If the child
process terminates without writing that side, the side is recorded as skipped so
the final matrix is auditable instead of silently blocking forever.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import subprocess
import sys
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
RUNNER = SCRIPT_DIR / "run_stoxx600_relative_synergy_research.py"
BACKTEST_ROOT = SCRIPT_DIR.parents[0]
OUT_DIR = BACKTEST_ROOT / "runs" / "ad_hoc" / "stoxx600_relative_synergy_20260709"


def read_results(output_dir: Path) -> pd.DataFrame:
    paths = [output_dir / "official_run_results.csv"]
    paths.extend((output_dir / "parallel_shards").rglob("official_run_results.csv"))
    frames: list[pd.DataFrame] = []
    for path in paths:
        if path.exists() and path.stat().st_size:
            try:
                frames.append(pd.read_csv(path))
            except Exception:
                continue
    if not frames:
        return pd.DataFrame(columns=["metric", "side", "status"])
    data = pd.concat(frames, ignore_index=True)
    if not {"metric", "side", "status"}.issubset(data.columns):
        return data
    rank = {"success": 3, "skipped": 2, "failed": 1}
    data["_rank"] = data["status"].map(rank).fillna(0)
    data["_order"] = range(len(data))
    data = data.sort_values(["metric", "side", "_rank", "_order"], ascending=[True, True, False, True])
    return data.drop_duplicates(["metric", "side"], keep="first").drop(columns=["_rank", "_order"])


def done_pairs(results: pd.DataFrame) -> set[tuple[str, str]]:
    if results.empty:
        return set()
    usable = results[results["status"].isin(["success", "skipped"])].copy()
    return set((str(row["metric"]), str(row["side"])) for _, row in usable.iterrows())


def missing_sides(output_dir: Path) -> list[tuple[str, str]]:
    candidates = pd.read_csv(output_dir / "candidate_map.csv")
    metrics = candidates.loc[candidates["candidate_type"].ne("bucket_component"), "metric"].astype(str).tolist()
    done = done_pairs(read_results(output_dir))
    out: list[tuple[str, str]] = []
    for metric in metrics:
        for side in ("Top", "Worst"):
            if (metric, side) not in done:
                out.append((metric, side))
    return out


def append_skip(output_dir: Path, wave: str, metric: str, side: str, message: str) -> Path:
    shard_dir = output_dir / "parallel_shards" / f"{wave}_skip" / "shard_00"
    shard_dir.mkdir(parents=True, exist_ok=True)
    path = shard_dir / "official_run_results.csv"
    row = {
        "benchmark": "STOXX EUROPE 600",
        "metric": metric,
        "side": side,
        "top": side == "Top",
        "start_date": "",
        "status": "skipped",
        "message": message,
        "run_dir": "",
        "sec_list": "",
        "perf_ptf": "",
        "perf_bench": "",
        "plot": "",
    }
    pd.DataFrame([row]).to_csv(path, index=False)
    return path


def merge_main(output_dir: Path) -> pd.DataFrame:
    results = read_results(output_dir)
    results.to_csv(output_dir / "official_run_results.csv", index=False)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Isolated STOXX600 synergy resume driver.")
    parser.add_argument("--output-dir", default=str(OUT_DIR))
    parser.add_argument("--limit-sides", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--retries", type=int, default=1)
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    processed = 0
    while True:
        missing = missing_sides(output_dir)
        if not missing:
            break
        metric, side = missing[0]
        wave = f"wave_20260710_isolated_{datetime.now().strftime('%H%M%S')}_{processed:04d}"
        print({"event": "isolated_start", "metric": metric, "side": side, "remaining_sides": len(missing), "wave": wave}, flush=True)
        before = done_pairs(read_results(output_dir))
        attempts = max(args.retries, 1)
        for attempt in range(1, attempts + 1):
            cmd = [
                sys.executable,
                str(RUNNER),
                "--output-dir",
                str(output_dir),
                "--metrics",
                metric,
                "--workers",
                "1",
                "--wave",
                f"{wave}_try{attempt}",
                "--no-pool",
                "--max-runs",
                "1",
                "--skip-summary",
            ]
            try:
                completed = subprocess.run(cmd, cwd=str(BACKTEST_ROOT), timeout=args.timeout, check=False)
                code = completed.returncode
            except subprocess.TimeoutExpired:
                code = 124
            merge_main(output_dir)
            after = done_pairs(read_results(output_dir))
            if len(after) > len(before) or (metric, side) in after:
                break
            if attempt == attempts:
                message = f"official child process exited {code}; no {side} artifact written; excluded from synergy claims"
                path = append_skip(output_dir, wave, metric, side, message)
                print({"event": "isolated_skip", "metric": metric, "side": side, "code": code, "path": str(path)}, flush=True)
                merge_main(output_dir)
        processed += 1
        if args.limit_sides and processed >= args.limit_sides:
            break
    results = merge_main(output_dir)
    missing = missing_sides(output_dir)
    print({"event": "isolated_complete", "rows": len(results), "remaining_sides": len(missing)}, flush=True)
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""刷新 ML_Enhanced 生产 Score ML 并写 pipeline manifest。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from tp_core.data_sources import LAST_SCREEN_PATH, SCREEN_AGGREGATE_PATH, TP_ROOT
from tp_models.ml import cli as ml_cli

from .common import StepManifest, path_profile


ML_DIR = TP_ROOT / "03_ml_enhanced"
ML_CLI = Path(ml_cli.__file__)
ML_SIGNALS_PATH = TP_ROOT / "04_signals" / "ml_signals.parquet"


def _json_from_stdout(stdout: str) -> dict[str, object]:
    start = stdout.find("{")
    if start < 0:
        return {}
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError:
        return {}


def run_refresh_ml(args: argparse.Namespace) -> Path:
    manifest = StepManifest("refresh_ml", vars(args).copy())
    manifest.inputs = {
        "screen_aggregate": path_profile(SCREEN_AGGREGATE_PATH, parquet=True),
        "last_screen": path_profile(LAST_SCREEN_PATH, parquet=True),
        "ml_cli": path_profile(ML_CLI),
    }
    try:
        command = [sys.executable, "-m", "tp_models.ml.cli"]
        if getattr(args, "inspect_only", False):
            command.extend(["inspect", "--json"])
        else:
            command.append("produce-score-ml")
            for value in args.date or []:
                command.extend(["--date", value])
            if args.from_date:
                command.extend(["--from-date", args.from_date])
            if args.to_date:
                command.extend(["--to-date", args.to_date])
            for value in args.universe or []:
                command.extend(["--universe", value])

        completed = subprocess.run(
            command,
            cwd=TP_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=int(args.timeout_seconds),
        )
        payload = _json_from_stdout(completed.stdout)
        manifest.details["command"] = {
            "argv": command,
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
            "payload": payload,
        }
        if completed.returncode != 0:
            raise RuntimeError(f"ML refresh failed with exit code {completed.returncode}")

        if getattr(args, "inspect_only", False):
            manifest.add_validation("ml_refresh_skipped", True, "inspect-only 未重算 Score ML")
            manifest.add_validation(
                "score_ml_has_scored_dates",
                bool(payload.get("latest_scored_date")),
                "Score ML 已有覆盖日期" if payload.get("latest_scored_date") else "Score ML 没有覆盖日期",
                payload,
            )
        else:
            action = payload.get("action")
            manifest.add_validation(
                "score_ml_action_valid",
                action in {"updated", "skipped"},
                f"Score ML action={action}",
                payload,
            )
            manifest.add_validation(
                "ml_signals_exist",
                ML_SIGNALS_PATH.exists(),
                "ML signals 已存在" if ML_SIGNALS_PATH.exists() else "ML signals 缺失",
            )

        manifest.outputs = {
            "screen_aggregate": path_profile(SCREEN_AGGREGATE_PATH, parquet=True),
            "last_screen": path_profile(LAST_SCREEN_PATH, parquet=True),
            "ml_signals": path_profile(ML_SIGNALS_PATH, parquet=True),
        }
        return manifest.write("success")
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新 ML_Enhanced Score ML 并写 pipeline manifest")
    parser.add_argument("--date", action="append", help="目标月末日期，可重复")
    parser.add_argument("--from-date", help="只处理该日期之后的缺失月份")
    parser.add_argument("--to-date", help="只处理该日期之前的缺失月份")
    parser.add_argument("--universe", action="append", choices=["EU", "US", "OTHER", "EM"], help="Universe，可重复")
    parser.add_argument("--inspect-only", action="store_true", help="只检查 Score ML 覆盖，不重算")
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest_path = run_refresh_ml(args)
    print(f"refresh_ml manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

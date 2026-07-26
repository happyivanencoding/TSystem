"""传统代码版回测 pipeline 入口。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH, TP_ROOT

from .common import StepManifest, path_profile, run_python_script


BACKTEST_SCRIPT = TP_ROOT / "07_backtest_code" / "run_backtest.py"
BACKTEST_RUNS_DIR = TP_ROOT / "07_backtest_code" / "runs"


def _common_args(args: argparse.Namespace) -> list[str]:
    result = ["--profile", args.profile]
    if args.screen:
        result.extend(["--screen", args.screen])
    if args.returns:
        result.extend(["--returns", args.returns])
    if args.user:
        result.extend(["--user", args.user])
    return result


def _run_args(args: argparse.Namespace) -> list[str]:
    result = _common_args(args)
    if args.bench:
        result.extend(["--bench", args.bench])
    for metric in args.metric or []:
        result.extend(["--metric", metric])
    if args.start_date:
        result.extend(["--start-date", args.start_date])
    if args.percentile is not None:
        result.extend(["--percentile", str(args.percentile)])
    if args.ptf_name:
        result.extend(["--ptf-name", args.ptf_name])
    if args.output_dir:
        result.extend(["--output-dir", args.output_dir])
    if args.max_weight is not None:
        result.extend(["--max-weight", str(args.max_weight)])
    if args.sector_neutral:
        result.append("--sector-neutral")
    if args.top:
        result.append("--top")
    if args.bottom:
        result.append("--bottom")
    if args.batch:
        result.append("--batch")
    if getattr(args, "record_experiment", False):
        result.append("--record-experiment")
    if getattr(args, "hypothesis_id", None):
        result.extend(["--hypothesis-id", args.hypothesis_id])
    if getattr(args, "experiment_name", None):
        result.extend(["--experiment-name", args.experiment_name])
    if getattr(args, "parent_run_id", None):
        result.extend(["--parent-run-id", args.parent_run_id])
    if getattr(args, "effective_trial_count", None) is not None:
        result.extend(["--effective-trial-count", str(args.effective_trial_count)])
    if getattr(args, "experiment_root", None):
        result.extend(["--experiment-root", args.experiment_root])
    return result


def run_backtest_step(args: argparse.Namespace) -> Path:
    manifest = StepManifest("run_backtest", vars(args).copy())
    manifest.inputs = {
        "screen": path_profile(args.screen or SCREEN_AGGREGATE_PATH, parquet=True),
        "returns": path_profile(args.returns or RETURNS_PATH, parquet=True),
        "backtest_script": path_profile(BACKTEST_SCRIPT),
    }
    try:
        inspect_result = run_python_script(BACKTEST_SCRIPT, ["inspect", *_common_args(args)])
        manifest.details["inspect"] = inspect_result
        manifest.add_validation(
            "inspect_passed",
            inspect_result["returncode"] == 0,
            "回测输入 inspect 通过" if inspect_result["returncode"] == 0 else "回测输入 inspect 失败",
        )
        if inspect_result["returncode"] != 0:
            manifest.outputs = {"backtest_runs": path_profile(BACKTEST_RUNS_DIR)}
            manifest_path = manifest.write("failed")
            raise RuntimeError(f"回测 inspect 失败，manifest: {manifest_path}")

        if args.inspect_only:
            manifest.outputs = {"backtest_runs": path_profile(BACKTEST_RUNS_DIR)}
            manifest.add_validation("run_skipped", True, "inspect-only 模式未执行回测")
            return manifest.write("success")

        run_result = run_python_script(BACKTEST_SCRIPT, ["run", *_run_args(args)])
        manifest.details["run"] = run_result
        manifest.outputs = {"backtest_runs": path_profile(BACKTEST_RUNS_DIR)}
        manifest.add_validation(
            "backtest_run_passed",
            run_result["returncode"] == 0,
            "回测运行成功" if run_result["returncode"] == 0 else "回测运行失败",
        )
        manifest_path = manifest.write("success" if run_result["returncode"] == 0 else "failed")
        if run_result["returncode"] != 0:
            raise RuntimeError(f"回测运行失败，manifest: {manifest_path}")
        return manifest_path
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行传统代码版回测并写 pipeline manifest")
    parser.add_argument("--profile", default="default", help="07_backtest_code/configs 下的 YAML profile")
    parser.add_argument("--screen", help="覆盖 screen parquet")
    parser.add_argument("--returns", help="覆盖 returns parquet")
    parser.add_argument("--user", help="运行用户/产物分组名")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    parser.add_argument("--inspect-only", action="store_true", help="只检查输入，不执行回测")
    parser.add_argument("--bench", help="benchmark 名称")
    parser.add_argument("--metric", action="append", help="排名字段；可重复传入")
    parser.add_argument("--start-date", help="回测开始日期")
    parser.add_argument("--percentile", type=float, help="选股分位阈值")
    parser.add_argument("--ptf-name", help="组合名称")
    parser.add_argument("--output-dir", help="输出目录")
    parser.add_argument("--max-weight", type=float, help="单股最大权重")
    parser.add_argument("--sector-neutral", action="store_true", help="行业中性")
    parser.add_argument("--top", action="store_true", help="选择高分端")
    parser.add_argument("--bottom", action="store_true", help="选择低分端")
    parser.add_argument("--batch", action="store_true", help="按 profile batch 配置运行")
    parser.add_argument("--record-experiment", action="store_true", help="写入可查询的实验 Run Card")
    parser.add_argument("--hypothesis-id", help="稳定的研究命题 ID")
    parser.add_argument("--experiment-name", help="实验名称")
    parser.add_argument("--parent-run-id", help="父运行 ID，用于 lineage")
    parser.add_argument("--effective-trial-count", type=int, help="该命题的有效试验次数")
    parser.add_argument("--experiment-root", help="实验记录根目录")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest_path = run_backtest_step(args)
    print(f"run_backtest manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

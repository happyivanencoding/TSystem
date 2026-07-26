"""命令行入口：运行传统代码版回测。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Iterable

from backtest_code.config.loader import load_settings
from backtest_code.config.settings import AppSettings
from backtest_code.runner.service import BacktestService
from backtest_code.runner.validators import inspect_file_pair
from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH


def _apply_canonical_defaults(settings: AppSettings) -> AppSettings:
    if not settings.paths.screen:
        settings.paths.screen = str(SCREEN_AGGREGATE_PATH)
    if not settings.paths.returns:
        settings.paths.returns = str(RETURNS_PATH)
    return settings


def _load_profile(profile: str) -> AppSettings:
    return _apply_canonical_defaults(load_settings(profile))


def _apply_common_overrides(settings: AppSettings, args: argparse.Namespace) -> AppSettings:
    if getattr(args, "screen", None):
        settings.paths.screen = args.screen
    if getattr(args, "returns", None):
        settings.paths.returns = args.returns
    if getattr(args, "output_dir", None):
        settings.paths.output_dir = args.output_dir
    if getattr(args, "user", None):
        settings.user.name = args.user
    if getattr(args, "bench", None):
        settings.run.bench = args.bench
    if getattr(args, "metric", None):
        settings.run.metrics = list(args.metric)
    if getattr(args, "start_date", None):
        settings.run.start_date = args.start_date
    if getattr(args, "percentile", None) is not None:
        settings.run.percentile = args.percentile
    if getattr(args, "ptf_name", None):
        settings.run.ptf_name = args.ptf_name
    if getattr(args, "max_weight", None) is not None:
        settings.run.max_weight = args.max_weight
    if getattr(args, "sector_neutral", False):
        settings.run.sector_neutral = True
    if getattr(args, "bottom", False):
        settings.run.top = False
    if getattr(args, "top", False):
        settings.run.top = True
    if getattr(args, "record_experiment", False):
        settings.experiment.enabled = True
    if getattr(args, "hypothesis_id", None):
        settings.experiment.hypothesis_id = args.hypothesis_id
    if getattr(args, "experiment_name", None):
        settings.experiment.name = args.experiment_name
    if getattr(args, "parent_run_id", None):
        settings.experiment.parent_run_id = args.parent_run_id
    if getattr(args, "effective_trial_count", None) is not None:
        settings.experiment.effective_trial_count = args.effective_trial_count
    if getattr(args, "experiment_root", None):
        settings.experiment.root = args.experiment_root
    return settings



def _compact_inspection(info):
    if info is None:
        return None
    dates = list(info.available_dates or [])
    metrics = list(info.metric_candidates or [])
    return {
        "file_path": info.file_path,
        "rows": info.rows,
        "column_count": len(info.columns),
        "detected_benchmarks": info.detected_benchmarks,
        "metric_candidates_count": len(metrics),
        "metric_candidates_sample": metrics[:40],
        "date_start": dates[0] if dates else None,
        "date_end": dates[-1] if dates else None,
        "date_count": len(dates),
        "has_esg": info.has_esg,
        "has_sector_icb19": info.has_sector_icb19,
        "has_sector_icb11": info.has_sector_icb11,
        "has_market_cap": info.has_market_cap,
    }

def _print_run_summary(result) -> None:
    print(f"batch={result.is_batch}")
    for run in result.runs:
        print(f"[{run.status}] {run.name}: {run.message}")
        print(f"  run_dir: {run.artifacts.run_dir}")
        if run.validation.as_text():
            print(run.validation.as_text())


def cmd_inspect(args: argparse.Namespace) -> int:
    settings = _apply_common_overrides(_load_profile(args.profile), args)
    screen_info, returns_info, report = inspect_file_pair(settings.paths.screen, settings.paths.returns)
    if args.full:
        payload = {
            "screen": asdict(screen_info) if screen_info else None,
            "returns": asdict(returns_info) if returns_info else None,
            "validation": {
                "is_valid": report.is_valid,
                "messages": report.as_text(),
            },
        }
    else:
        payload = {
            "screen": _compact_inspection(screen_info),
            "returns": _compact_inspection(returns_info),
            "validation": {
                "is_valid": report.is_valid,
                "messages": report.as_text(),
            },
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if report.is_valid else 1


def cmd_run(args: argparse.Namespace) -> int:
    settings = _apply_common_overrides(_load_profile(args.profile), args)
    result = BacktestService().run(settings, force_batch=args.batch)
    _print_run_summary(result)
    return 0 if all(run.status == "success" for run in result.runs) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="传统代码版回测入口")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--profile", default="default", help="configs/ 下的 YAML profile 名称")
        subparser.add_argument("--screen", help="覆盖 screen parquet 路径")
        subparser.add_argument("--returns", help="覆盖 returns parquet 路径")
        subparser.add_argument("--user", help="运行用户/产物分组名")

    inspect_parser = subparsers.add_parser("inspect", help="检查输入文件和可用字段")
    add_common(inspect_parser)
    inspect_parser.add_argument("--full", action="store_true", help="输出完整字段列表和 returns 列名")
    inspect_parser.set_defaults(func=cmd_inspect)

    run_parser = subparsers.add_parser("run", help="执行单次或批量回测")
    add_common(run_parser)
    run_parser.add_argument("--bench", help="benchmark 名称，例如 STOXX EUROPE 600")
    run_parser.add_argument("--metric", action="append", help="排名字段；可重复传入")
    run_parser.add_argument("--start-date", help="回测开始日期，YYYY-MM-DD")
    run_parser.add_argument("--percentile", type=float, help="选股分位阈值")
    run_parser.add_argument("--ptf-name", help="组合名称")
    run_parser.add_argument("--output-dir", help="生产模式输出目录")
    run_parser.add_argument("--max-weight", type=float, help="单股最大权重")
    run_parser.add_argument("--sector-neutral", action="store_true", help="启用行业中性回测")
    run_parser.add_argument("--top", action="store_true", help="选择高分端")
    run_parser.add_argument("--bottom", action="store_true", help="选择低分端")
    run_parser.add_argument("--batch", action="store_true", help="按 profile 中 batch 配置运行批量回测")
    run_parser.add_argument("--record-experiment", action="store_true", help="写入可查询的实验 Run Card")
    run_parser.add_argument("--hypothesis-id", help="稳定的研究命题 ID")
    run_parser.add_argument("--experiment-name", help="实验名称")
    run_parser.add_argument("--parent-run-id", help="父运行 ID，用于 lineage")
    run_parser.add_argument("--effective-trial-count", type=int, help="该命题的有效试验次数")
    run_parser.add_argument("--experiment-root", help="实验记录根目录")
    run_parser.set_defaults(func=cmd_run)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

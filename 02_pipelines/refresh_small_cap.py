"""刷新 Europe small-cap defensive factor model 并写 pipeline manifest。"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Any, Iterable

from tp_core.data_sources import SCREEN_AGGREGATE_PATH, TP_ROOT
from tp_core.signals import validate_signal_frame

from .common import StepManifest, path_profile


MODEL_SCRIPT = TP_ROOT / "15_small_cap_model" / "src" / "small_cap_model.py"
DEFAULT_CONFIG = TP_ROOT / "15_small_cap_model" / "config" / "eu_small_defensive_tilt.json"
DEFAULT_OUTPUT_DIR = TP_ROOT / "15_small_cap_model" / "outputs"
DEFAULT_SIGNAL_OUTPUT = TP_ROOT / "04_signals" / "small_cap_model_signals.parquet"


def _load_model_module() -> Any:
    spec = importlib.util.spec_from_file_location("tp_small_cap_model", MODEL_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 small-cap model: {MODEL_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_refresh_small_cap(args: argparse.Namespace) -> Path:
    manifest = StepManifest("refresh_small_cap", vars(args).copy())
    screen_path = Path(getattr(args, "screen", SCREEN_AGGREGATE_PATH))
    config_path = Path(getattr(args, "config", DEFAULT_CONFIG))
    output_dir = Path(getattr(args, "output_dir", DEFAULT_OUTPUT_DIR))
    signal_output = Path(getattr(args, "signal_output", DEFAULT_SIGNAL_OUTPUT))
    manifest.inputs = {
        "screen_aggregate": path_profile(screen_path, parquet=True),
        "model_script": path_profile(MODEL_SCRIPT),
        "config": path_profile(config_path),
    }
    try:
        module = _load_model_module()
        if getattr(args, "inspect_only", False):
            result = module.inspect_outputs(output_dir=output_dir, signal_output=signal_output)
            manifest.add_validation(
                "small_cap_outputs_exist",
                bool(result.get("summary_exists") and result.get("signal_exists")),
                "小盘模型产物存在" if result.get("summary_exists") and result.get("signal_exists") else "小盘模型产物缺失",
                result,
            )
        else:
            result = module.export_small_cap_model(
                screen_path=screen_path,
                config_path=config_path,
                output_dir=output_dir,
                signal_output=signal_output,
                as_of=getattr(args, "as_of", None),
                latest_only=not getattr(args, "all_history", False),
            )
            manifest.add_validation(
                "small_cap_latest_coverage",
                float(result.get("latest_coverage") or 0.0) >= float(getattr(args, "min_coverage", 0.5)),
                "最新小盘模型覆盖率通过",
                {"latest_coverage": result.get("latest_coverage"), "latest_date": result.get("latest_date")},
            )

        manifest.details["result"] = result
        manifest.outputs = {
            "output_dir": path_profile(output_dir),
            "summary": path_profile(output_dir / "eu_small_model_summary.json"),
            "panel": path_profile(output_dir / "eu_small_model_scores_latest.parquet", parquet=True),
            "variable_coverage": path_profile(output_dir / "eu_small_variable_coverage.csv"),
            "small_cap_model_signals": path_profile(signal_output, parquet=True),
        }
        if signal_output.exists():
            import pandas as pd

            signal = pd.read_parquet(signal_output)
            validation = validate_signal_frame(signal)
            manifest.add_validation(
                "small_cap_signal_schema",
                validation.is_valid,
                "小盘模型信号表 schema 通过" if validation.is_valid else "小盘模型信号表 schema 失败",
                {"errors": validation.errors, "warnings": validation.warnings, "rows": int(len(signal))},
            )
        return manifest.write("success")
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新 Europe small-cap defensive factor model")
    parser.add_argument("--as-of", help="只使用该日期之前的 screen 日期")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    parser.add_argument("--screen", default=str(SCREEN_AGGREGATE_PATH))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--signal-output", default=str(DEFAULT_SIGNAL_OUTPUT))
    parser.add_argument("--all-history", action="store_true", help="导出全历史信号；默认只导出最新一期")
    parser.add_argument("--inspect-only", action="store_true", help="只检查已有产物，不重算")
    parser.add_argument("--min-coverage", type=float, default=0.5, help="最新一期有效模型分数最低覆盖率")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest_path = run_refresh_small_cap(args)
    print(f"refresh_small_cap manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

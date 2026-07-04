"""刷新 Regime detector 并导出标准风险预算信号。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterable

import pandas as pd

from tp_core.data_sources import TP_ROOT

from .common import StepManifest, path_profile, run_python_module, run_python_script


REGIME_DIR = TP_ROOT / "03_regime_model"
DEFAULT_REGIME_OUTPUT = TP_ROOT / "04_signals" / "regime_risk_budget.parquet"
MODEL_DIAGNOSTICS_OUTPUT = REGIME_DIR / "output" / "model_diagnostics.json"


def _ensure_success(result: dict[str, object], label: str) -> None:
    if result.get("returncode") == 0:
        return
    detail = str(result.get("stderr") or result.get("stdout") or "")
    raise RuntimeError(f"{label} failed with returncode {result.get('returncode')}: {detail[-1200:]}")


def _json_value(value: object) -> object:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _load_regime_module(module_name: str) -> ModuleType:
    if str(REGIME_DIR) not in sys.path:
        sys.path.insert(0, str(REGIME_DIR))
    path = REGIME_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"tp_refresh_regime_{module_name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 Regime 模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _comparison_rows(frame, *, metric: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if frame is None or frame.empty:
        return rows
    metric_frame = frame.sort_values(metric, ascending=False) if metric in frame.columns else frame
    for model_name, row in metric_frame.iterrows():
        payload: dict[str, object] = {"model": str(model_name)}
        for column, value in row.items():
            payload[str(column)] = None if pd.isna(value) else value
        rows.append(payload)
    return rows


def write_model_diagnostics(output: Path = MODEL_DIAGNOSTICS_OUTPUT) -> Path:
    ml_compare = _load_regime_module("ml_compare")
    vol_compare = _load_regime_module("vol_compare")
    payload: dict[str, object] = {"regions": {}, "updated_at": None}
    for region in ("US", "EU"):
        direction = ml_compare.evaluate(region)
        vol = vol_compare.evaluate(region, "fwd_vol")
        mdd = vol_compare.evaluate(region, "fwd_mdd")
        payload["regions"][region] = {
            "direction_models": _comparison_rows(direction, metric="准确率"),
            "volatility_models": _comparison_rows(vol, metric="高波动AUC"),
            "drawdown_models": _comparison_rows(mdd, metric="高波动AUC"),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime

    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_value), encoding="utf-8")
    return output


def run_refresh_regime(args: argparse.Namespace) -> Path:
    manifest = StepManifest("refresh_regime", vars(args).copy())
    build_features_script = REGIME_DIR / "build_features.py"
    walkforward_script = REGIME_DIR / "walkforward.py"
    output = Path(args.regime_output)
    run_type = getattr(args, "run_type", "production")
    manifest.inputs = {
        "build_features": path_profile(build_features_script),
        "walkforward": path_profile(walkforward_script),
    }

    try:
        steps: list[dict[str, object]] = []
        build_result = run_python_script(build_features_script)
        _ensure_success(build_result, "build_features")
        steps.append({"name": "build_features", **build_result})

        walkforward_result = run_python_script(walkforward_script)
        _ensure_success(walkforward_result, "walkforward")
        steps.append({"name": "walkforward", **walkforward_result})

        export_args = [
            "--skip-ml",
            "--skip-technical",
            "--regime-oos",
            "--regime-output",
            str(output),
            "--run-type",
            run_type,
        ]
        export_result = run_python_module("02_pipelines.export_signals", export_args)
        _ensure_success(export_result, "export_signals")
        steps.append({"name": "export_signals", **export_result})
        if not output.exists():
            raise FileNotFoundError(f"Regime output was not written: {output}")

        dashboard_result = run_python_script(REGIME_DIR / "export_dashboard.py")
        _ensure_success(dashboard_result, "export_dashboard")
        steps.append({"name": "export_dashboard", **dashboard_result})

        diagnostics_output = write_model_diagnostics()

        manifest.details["steps"] = steps
        manifest.outputs = {
            "features_US": path_profile(REGIME_DIR / "output" / "features_US.parquet", parquet=True),
            "features_EU": path_profile(REGIME_DIR / "output" / "features_EU.parquet", parquet=True),
            "regime_oos_US": path_profile(REGIME_DIR / "output" / "regime_oos_US.parquet", parquet=True),
            "regime_oos_EU": path_profile(REGIME_DIR / "output" / "regime_oos_EU.parquet", parquet=True),
            "regime_risk_budget": path_profile(output, parquet=True),
            "model_diagnostics": path_profile(diagnostics_output),
            "risk_dashboard_data": path_profile(REGIME_DIR / "webapp" / "data.js"),
        }
        manifest.add_validation("regime_signal_exists", output.exists(), "Regime 风险预算信号已导出")
        manifest.add_validation("model_diagnostics_exists", diagnostics_output.exists(), "Regime 模型诊断已导出")
        return manifest.write("success")
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新 Regime detector 并导出统一风险预算信号")
    parser.add_argument("--regime-output", default=str(DEFAULT_REGIME_OUTPUT), help="Regime 风险预算信号输出路径")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest_path = run_refresh_regime(args)
    print(f"refresh_regime manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

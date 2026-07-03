"""导出 Regime 区域风险预算信号。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Iterable

import pandas as pd

TP_ROOT = Path(__file__).resolve().parents[1]
if str(TP_ROOT) not in sys.path:
    sys.path.insert(0, str(TP_ROOT))

import sitecustomize  # noqa: F401

from tp_core.signals import standardize_signal_frame, write_signal_frame  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = TP_ROOT / "04_signals" / "regime_risk_budget.parquet"
MIN_CALIBRATION_STATE_MONTHS = 6


def risk_budget_from_label(label: object) -> float:
    text = str(label)
    if "Risk-On" in text or "扩张" in text:
        return 1.10
    if "Risk-Off" in text or "衰退" in text or "压力" in text or "收缩" in text:
        return 0.70
    if "震荡" in text:
        return 0.90
    return 1.00


def calibrated_risk_budget(regime: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=regime.index)
    result["risk_budget_multiplier"] = regime["label"].map(risk_budget_from_label)
    result["calibration_method"] = "static_fallback"
    result["state_hist_months"] = 0
    result["state_fwd_ret_mean"] = pd.NA
    result["state_fwd_ret_vol"] = pd.NA

    for _, group in regime.sort_values("Date").groupby("region", sort=False):
        past_rows: list[pd.Series] = []
        for idx, row in group.iterrows():
            past = pd.DataFrame(past_rows)
            if not past.empty and "fwd_ret" in past.columns and pd.notna(row.get("state")):
                valid = past.dropna(subset=["fwd_ret"])
                same = valid[valid["state"] == row["state"]]
                if len(same) >= MIN_CALIBRATION_STATE_MONTHS and len(valid) >= MIN_CALIBRATION_STATE_MONTHS:
                    all_mean = valid["fwd_ret"].mean()
                    all_vol = valid["fwd_ret"].std()
                    state_mean = same["fwd_ret"].mean()
                    state_vol = same["fwd_ret"].std()
                    if pd.isna(state_vol):
                        state_vol = all_vol
                    vol_ratio = state_vol / all_vol if pd.notna(all_vol) and all_vol > 0 else 1.0
                    mean_edge = state_mean - all_mean

                    if state_mean < -0.002:
                        multiplier = 0.70
                    elif vol_ratio >= 1.35:
                        multiplier = 0.70
                    elif vol_ratio >= 1.15 or mean_edge <= -0.005:
                        multiplier = 0.90
                    elif state_mean >= 0 and vol_ratio <= 0.95:
                        multiplier = 1.10
                    else:
                        multiplier = 1.00

                    result.at[idx, "risk_budget_multiplier"] = multiplier
                    result.at[idx, "calibration_method"] = "historical_state_fwd_return"
                    result.at[idx, "state_hist_months"] = len(same)
                    result.at[idx, "state_fwd_ret_mean"] = state_mean
                    result.at[idx, "state_fwd_ret_vol"] = state_vol
            past_rows.append(row)
    return result


def _read_regime(region: str, *, oos: bool = False) -> pd.DataFrame:
    name = f"regime_oos_{region}.parquet" if oos else f"regime_{region}.parquet"
    path = PROJECT_DIR / "output" / name
    frame = pd.read_parquet(path)
    if "Date" not in frame.columns:
        frame = frame.reset_index()
    frame["region"] = region
    frame["source_file"] = str(path)
    return frame


def export_risk_budget(
    *,
    output: Path = DEFAULT_OUTPUT,
    oos: bool = False,
    regions: list[str] | None = None,
    calibrated: bool = False,
) -> Path:
    regions = regions or ["US", "EU"]
    frames = [_read_regime(region, oos=oos) for region in regions]
    regime = pd.concat(frames, ignore_index=True)
    if calibrated:
        regime = regime.join(calibrated_risk_budget(regime))
    else:
        regime["risk_budget_multiplier"] = regime["label"].map(risk_budget_from_label)
        regime["calibration_method"] = "static_label"
        regime["state_hist_months"] = pd.NA
        regime["state_fwd_ret_mean"] = pd.NA
        regime["state_fwd_ret_vol"] = pd.NA
    model_version = "regime_model_current"
    if oos:
        model_version += "_oos"
    if calibrated:
        model_version += "_calibrated"
    signals = pd.DataFrame(
        {
            "Date": regime["Date"],
            "signal_family": "Regime",
            "signal_name": "risk_budget_multiplier",
            "scope": "region",
            "score": regime["risk_budget_multiplier"],
            "direction": "higher_risk_budget",
            "coverage_flag": regime["risk_budget_multiplier"].notna(),
            "model_version": model_version,
            "source_project": "regime_model",
            "region": regime["region"],
            "raw_value": regime["label"],
            "signal_description": "根据历史同状态前瞻收益校准的组合风险预算乘数" if calibrated else "根据 Regime 标签映射的组合风险预算乘数",
            "regime_state": regime["state"],
            "fwd_ret": regime.get("fwd_ret"),
            "calibration_method": regime["calibration_method"],
            "state_hist_months": regime["state_hist_months"],
            "state_fwd_ret_mean": regime["state_fwd_ret_mean"],
            "state_fwd_ret_vol": regime["state_fwd_ret_vol"],
            "source_file": regime["source_file"],
        }
    )
    signals = standardize_signal_frame(signals)
    return write_signal_frame(signals, output)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出 Regime 风险预算统一信号表")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出 parquet 路径")
    parser.add_argument("--oos", action="store_true", help="使用样本外 regime_oos 文件")
    parser.add_argument("--calibrated", action="store_true", help="使用历史同状态前瞻收益校准风险预算")
    parser.add_argument("--region", action="append", choices=["US", "EU"], help="区域；可重复传入，默认 US+EU")
    args = parser.parse_args(list(argv) if argv is not None else None)
    output = export_risk_budget(output=Path(args.output), oos=args.oos, regions=args.region, calibrated=args.calibrated)
    print(f"Regime risk budget signals written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

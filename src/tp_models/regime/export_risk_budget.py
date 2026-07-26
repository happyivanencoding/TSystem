"""导出 Regime 区域风险预算信号。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd

from tp_core.data_sources import TP_ROOT
from tp_core.signals import standardize_signal_frame, write_signal_frame
from tp_core.workspace import SIGNALS_DIR

from . import risk_budget_model

PROJECT_DIR = TP_ROOT / "03_regime_model"
DEFAULT_OUTPUT = SIGNALS_DIR / "regime_risk_budget.parquet"
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
    risk_model: str = "hybrid",
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
    regime["current_rvol"] = pd.NA
    regime["target_vol"] = pd.NA
    regime["raw_multiplier"] = pd.NA
    regime["risk_model"] = "hmm_k4"

    if risk_model == "hybrid" and "EU" in regions:
        eu = risk_budget_model.eu_persistence_risk_budget().reset_index()
        eu_by_date = eu.set_index("Date")
        eu_rows = regime["region"].eq("EU") & regime["Date"].isin(eu_by_date.index)
        for idx in regime.index[eu_rows]:
            date = regime.at[idx, "Date"]
            row = eu_by_date.loc[date]
            for column in [
                "state",
                "label",
                "risk_budget_multiplier",
                "current_rvol",
                "target_vol",
                "raw_multiplier",
                "state_hist_months",
            ]:
                regime.at[idx, column] = row[column]
            regime.at[idx, "calibration_method"] = "eu_realized_vol_persistence"
            regime.at[idx, "risk_model"] = "eu_volatility_persistence"

    model_suffix = "_oos" if oos else ""
    calibration_suffix = "_calibrated" if calibrated else ""
    if risk_model == "hybrid":
        regime["model_version"] = regime["risk_model"].map(
            {
                "hmm_k4": f"regime_hybrid_v2_us_hmm{model_suffix}{calibration_suffix}",
                "eu_volatility_persistence": "regime_hybrid_v2_eu_vol_persistence",
            }
        )
    else:
        regime["model_version"] = f"regime_model_current{model_suffix}{calibration_suffix}"
    regime["signal_description"] = regime["risk_model"].map(
        {
            "hmm_k4": "根据 HMM Regime 标签映射的组合风险预算乘数",
            "eu_volatility_persistence": "EU 当前已实现波动相对历史目标波动的因果风险预算乘数",
        }
    )
    signals = pd.DataFrame(
        {
            "Date": regime["Date"],
            "signal_family": "Regime",
            "signal_name": "risk_budget_multiplier",
            "scope": "region",
            "score": regime["risk_budget_multiplier"],
            "direction": "higher_risk_budget",
            "coverage_flag": regime["risk_budget_multiplier"].notna(),
            "model_version": regime["model_version"],
            "source_project": "regime_model",
            "region": regime["region"],
            "raw_value": regime["label"],
            "signal_description": regime["signal_description"],
            "regime_state": regime["state"],
            "fwd_ret": regime.get("fwd_ret"),
            "calibration_method": regime["calibration_method"],
            "state_hist_months": regime["state_hist_months"],
            "state_fwd_ret_mean": regime["state_fwd_ret_mean"],
            "state_fwd_ret_vol": regime["state_fwd_ret_vol"],
            "current_rvol": regime["current_rvol"],
            "target_vol": regime["target_vol"],
            "raw_multiplier": regime["raw_multiplier"],
            "risk_model": regime["risk_model"],
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
    parser.add_argument("--risk-model", choices=["hybrid", "hmm"], default="hybrid", help="hybrid=US HMM + EU 波动持续性；hmm=旧版统一 HMM")
    parser.add_argument("--region", action="append", choices=["US", "EU"], help="区域；可重复传入，默认 US+EU")
    args = parser.parse_args(list(argv) if argv is not None else None)
    output = export_risk_budget(
        output=Path(args.output),
        oos=args.oos,
        regions=args.region,
        calibrated=args.calibrated,
        risk_model=args.risk_model,
    )
    print(f"Regime risk budget signals written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

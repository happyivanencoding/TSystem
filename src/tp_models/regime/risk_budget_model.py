"""区域化 Regime 风险预算：US 保留 HMM，EU 使用因果波动持续性缩放。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, vol_compare


EU_MIN_HISTORY = 60
EU_MIN_MULTIPLIER = 0.70
EU_MAX_MULTIPLIER = 1.30


def _state_from_multiplier(multiplier: float) -> int:
    if multiplier > 1.15:
        return 0
    if multiplier > 0.95:
        return 1
    if multiplier > 0.80:
        return 2
    return 3


def eu_persistence_risk_budget(
    features: pd.DataFrame | None = None,
    forward_vol: pd.Series | None = None,
    *,
    min_history: int = EU_MIN_HISTORY,
) -> pd.DataFrame:
    """用截至当月已实现的信息生成 EU 连续风险预算，不使用当月之后的数据。"""

    if features is None:
        features = pd.read_parquet(config.OUTPUT_DIR / "features_EU.parquet").sort_index()
    if forward_vol is None:
        forward_vol = vol_compare.fwd_risk("EU")["fwd_vol"]

    current_vol = pd.to_numeric(features["rvol_ann"], errors="coerce").sort_index()
    forward_vol = pd.to_numeric(forward_vol, errors="coerce").dropna().sort_index()
    rows = []
    for date, realized_vol in current_vol.items():
        history = forward_vol[forward_vol.index < date]
        if len(history) < min_history or pd.isna(realized_vol) or realized_vol <= 0:
            continue
        target_vol = float(history.median())
        raw_multiplier = target_vol / float(realized_vol)
        multiplier = float(np.clip(raw_multiplier, EU_MIN_MULTIPLIER, EU_MAX_MULTIPLIER))
        state = _state_from_multiplier(multiplier)
        rows.append(
            {
                "Date": date,
                "state": state,
                "label": ["扩张(Risk-On)", "平稳", "震荡", "危机(Risk-Off)"][state],
                "risk_budget_multiplier": multiplier,
                "current_rvol": float(realized_vol),
                "target_vol": target_vol,
                "raw_multiplier": raw_multiplier,
                "state_hist_months": int(len(history)),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "state",
                "label",
                "risk_budget_multiplier",
                "current_rvol",
                "target_vol",
                "raw_multiplier",
                "state_hist_months",
            ]
        ).rename_axis("Date")
    return pd.DataFrame(rows).set_index("Date").sort_index()

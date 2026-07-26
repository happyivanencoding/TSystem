"""Bottom-up aggregation for Score ML_IF, used only by selected model comparisons."""
import numpy as np
import pandas as pd

from . import config, data_loader


SCORE_COL = "Score ML_IF"
MLIF_COLS = [
    "mlif_mean",
    "mlif_median",
    "mlif_iqr",
    "mlif_std",
    "mlif_breadth_ge5",
    "mlif_median_ewma6",
    "mlif_breadth_ge5_ewma6",
]

DIRECTION_COLS = {
    "US": {
        "Logistic": ["mlif_median_ewma6", "mlif_breadth_ge5_ewma6"],
        "GBM": ["mlif_breadth_ge5"],
    },
    "EU": {
        "Logistic": ["mlif_breadth_ge5"],
        "GBM": MLIF_COLS,
    },
}

VOL_GBM_COLS = {
    "US": {
        "fwd_vol": ["mlif_breadth_ge5"],
        "fwd_mdd": ["mlif_breadth_ge5"],
    },
    "EU": {
        "fwd_vol": ["mlif_median"],
        "fwd_mdd": ["mlif_median_ewma6", "mlif_breadth_ge5_ewma6"],
    },
}

POST2020_HMM_COLS = {
    "US": MLIF_COLS,
    "EU": ["mlif_median_ewma6", "mlif_breadth_ge5_ewma6"],
}


def load_region_mlif(region: str, target_index: pd.Index | None = None) -> pd.DataFrame:
    cols = [
        "Date",
        config.ID_COL,
        config.RETURN_COL,
        config.REGION_NEUTRAL_COL,
        config.MKT_CAP_COL,
        SCORE_COL,
    ]
    cols += list(config.REGION_WEIGHT_COL.values())
    screen = pd.read_parquet(config.SCREEN_PATH, columns=list(dict.fromkeys(cols)))
    screen["Date"] = pd.to_datetime(screen["Date"]).dt.to_period("M").dt.to_timestamp("M")
    screen = screen[screen["Date"] >= pd.Timestamp(config.START_DATE)].copy()
    screen[SCORE_COL] = pd.to_numeric(screen[SCORE_COL], errors="coerce").astype(float)

    panel = data_loader.get_region_panel(screen, region).copy()
    panel[SCORE_COL] = pd.to_numeric(panel[SCORE_COL], errors="coerce").astype(float)
    grouped = panel.groupby("Date", sort=True)[SCORE_COL]

    out = pd.DataFrame(index=pd.Index(sorted(panel["Date"].unique()), name="Date"))
    out["mlif_mean"] = grouped.mean()
    out["mlif_median"] = grouped.median()
    p25 = grouped.apply(lambda s: s.dropna().quantile(0.25) if s.notna().any() else np.nan)
    p75 = grouped.apply(lambda s: s.dropna().quantile(0.75) if s.notna().any() else np.nan)
    out["mlif_iqr"] = p75 - p25
    out["mlif_std"] = grouped.std()
    out["mlif_breadth_ge5"] = grouped.apply(
        lambda s: float((s.dropna() >= 5.0).mean()) if s.notna().any() else np.nan
    )
    out["mlif_median_ewma6"] = out["mlif_median"].ewm(span=6, adjust=False).mean()
    out["mlif_breadth_ge5_ewma6"] = out["mlif_breadth_ge5"].ewm(span=6, adjust=False).mean()
    out = out[MLIF_COLS]
    if target_index is not None:
        out = out.reindex(pd.to_datetime(target_index).to_period("M").to_timestamp("M"))
        out.index.name = "Date"
    return out


def direction_cols(region: str, model_name: str) -> list[str]:
    return DIRECTION_COLS.get(region, {}).get(model_name, [])


def vol_gbm_cols(region: str, target: str) -> list[str]:
    return VOL_GBM_COLS.get(region, {}).get(target, [])


def post2020_hmm_cols(region: str) -> list[str]:
    return POST2020_HMM_COLS.get(region, [])

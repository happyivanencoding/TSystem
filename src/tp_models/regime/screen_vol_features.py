"""Bottom-up single-stock volatility features selected from screen data."""
import numpy as np
import pandas as pd

from tp_core.io import read_screen_aggregate

from . import config, data_loader

SOURCE_COLS = {
    "v60": "Daily Vol 60J",
    "v90": "Daily Vol 90J",
    "v1y": "Daily Vol 260J",
}

CORE_COLS = [
    "sv_v60_med",
    "sv_v60_v1y_ratio",
    "sv_v90_v1y_ratio",
    "sv_v60_above_v1y_breadth",
    "sv_v90_above_v1y_breadth",
]

DISP_COLS = [
    "sv_v60_iqr",
    "sv_v90_iqr",
    "sv_v1y_iqr",
    "sv_v60_v90_ratio",
]

SECTOR_COLS = [
    "sv_sector_v60_disp",
    "sv_sector_v90_disp",
    "sv_sector_v1y_disp",
    "sv_def_cyc_v60_spread",
    "sv_def_cyc_v90_spread",
    "sv_def_cyc_v1y_spread",
]

ALL_COLS = [
    "sv_v60_med",
    "sv_v90_med",
    "sv_v1y_med",
    "sv_v60_iqr",
    "sv_v90_iqr",
    "sv_v1y_iqr",
    "sv_v60_v1y_ratio",
    "sv_v90_v1y_ratio",
    "sv_v60_v90_ratio",
    "sv_v60_above_v1y_breadth",
    "sv_v90_above_v1y_breadth",
    "sv_sector_v60_disp",
    "sv_sector_v90_disp",
    "sv_sector_v1y_disp",
    "sv_sector_v60_iqr",
    "sv_sector_v90_iqr",
    "sv_sector_v1y_iqr",
    "sv_def_cyc_v60_spread",
    "sv_def_cyc_v90_spread",
    "sv_def_cyc_v1y_spread",
]


def _iqr(series: pd.Series) -> float:
    s = series.dropna()
    if len(s) < 5:
        return np.nan
    return float(s.quantile(0.75) - s.quantile(0.25))


def _ratio(a: float, b: float) -> float:
    if pd.isna(a) or pd.isna(b) or b == 0:
        return np.nan
    return float(a / b - 1.0)


def _aggregate_month(g: pd.DataFrame) -> pd.Series:
    row = {}
    med = {}
    for key, col in SOURCE_COLS.items():
        med[key] = g[col].median()
        row[f"sv_{key}_med"] = med[key]
        row[f"sv_{key}_iqr"] = _iqr(g[col])
    row["sv_v60_v1y_ratio"] = _ratio(med["v60"], med["v1y"])
    row["sv_v90_v1y_ratio"] = _ratio(med["v90"], med["v1y"])
    row["sv_v60_v90_ratio"] = _ratio(med["v60"], med["v90"])

    pair = g[[SOURCE_COLS["v60"], SOURCE_COLS["v1y"]]].dropna()
    row["sv_v60_above_v1y_breadth"] = (
        float((pair[SOURCE_COLS["v60"]] > pair[SOURCE_COLS["v1y"]]).mean()) if len(pair) else np.nan
    )
    pair = g[[SOURCE_COLS["v90"], SOURCE_COLS["v1y"]]].dropna()
    row["sv_v90_above_v1y_breadth"] = (
        float((pair[SOURCE_COLS["v90"]] > pair[SOURCE_COLS["v1y"]]).mean()) if len(pair) else np.nan
    )

    sector = g.dropna(subset=[config.SECTOR_COL]).copy()
    counts = sector.groupby(config.SECTOR_COL).size()
    valid_sectors = counts[counts >= config.MIN_SECTOR_SIZE].index
    sector = sector[sector[config.SECTOR_COL].isin(valid_sectors)]
    sector_median = sector.groupby(config.SECTOR_COL)[list(SOURCE_COLS.values())].median()
    for key, col in SOURCE_COLS.items():
        row[f"sv_sector_{key}_disp"] = sector_median[col].std(ddof=1) if len(sector_median) > 1 else np.nan
        row[f"sv_sector_{key}_iqr"] = _iqr(sector_median[col])
        defensive = g.loc[g[config.SECTOR_COL].isin(config.DEFENSIVE_SECTORS), col].median()
        cyclical = g.loc[(~g[config.SECTOR_COL].isin(config.DEFENSIVE_SECTORS)) & (g[config.SECTOR_COL] != 0), col].median()
        row[f"sv_def_cyc_{key}_spread"] = defensive - cyclical if pd.notna(defensive) and pd.notna(cyclical) else np.nan
    return pd.Series(row)


def build_region_screen_vol(screen: pd.DataFrame, region: str) -> pd.DataFrame:
    panel = data_loader.get_region_panel(screen, region).copy()
    for col in SOURCE_COLS.values():
        panel[col] = pd.to_numeric(panel[col], errors="coerce").astype(float)
    out = panel.groupby("Date", group_keys=True).apply(_aggregate_month, include_groups=False)
    out = out[ALL_COLS].sort_index()
    out.index.name = "Date"
    return out


def load_region_screen_vol(region: str, target_index: pd.Index | None = None) -> pd.DataFrame:
    cols = [
        "Date",
        config.ID_COL,
        config.RETURN_COL,
        config.REGION_NEUTRAL_COL,
        config.SECTOR_COL,
        config.MKT_CAP_COL,
    ]
    cols += list(SOURCE_COLS.values())
    cols += list(config.REGION_WEIGHT_COL.values())
    screen = read_screen_aggregate(
        config.SCREEN_PATH,
        columns=list(dict.fromkeys(cols)),
        date_from=pd.Timestamp(config.START_DATE),
    )
    screen["Date"] = pd.to_datetime(screen["Date"]).dt.to_period("M").dt.to_timestamp("M")
    screen = screen[screen["Date"] >= pd.Timestamp(config.START_DATE)].copy()
    out = build_region_screen_vol(screen, region)
    if target_index is not None:
        out = out.reindex(pd.to_datetime(target_index).to_period("M").to_timestamp("M"))
        out.index.name = "Date"
    return out


def production_k4_cols(region: str) -> list[str]:
    return CORE_COLS if region == "US" else []


def direction_cols(region: str, model_name: str) -> list[str]:
    return []


def vol_ridge_cols(region: str, target: str) -> list[str]:
    if region == "US" and target in {"fwd_vol", "fwd_mdd"}:
        return ALL_COLS
    if region == "EU" and target in {"fwd_vol", "fwd_mdd"}:
        return DISP_COLS
    return []


def vol_gbm_cols(region: str, target: str) -> list[str]:
    if region == "US" and target == "fwd_vol":
        return SECTOR_COLS
    if region == "EU" and target == "fwd_vol":
        return DISP_COLS
    if region == "EU" and target == "fwd_mdd":
        return ALL_COLS
    return []


def post2020_hmm_cols(region: str) -> list[str]:
    if region == "US":
        return CORE_COLS
    if region == "EU":
        return SECTOR_COLS
    return []

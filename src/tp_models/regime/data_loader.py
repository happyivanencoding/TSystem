"""数据加载：读取 screen_aggregate，并按指数成分(point-in-time)筛选地区个股。"""
import numpy as np
import pandas as pd

from . import config


def load_screen() -> pd.DataFrame:
    """加载 screen 所需列，按起始日期截断。"""
    df = pd.read_parquet(config.SCREEN_PATH, columns=config.screen_columns())
    df["Date"] = pd.to_datetime(df["Date"])
    df = df[df["Date"] >= pd.Timestamp(config.START_DATE)].copy()
    return df


def get_region_panel(df: pd.DataFrame, region: str) -> pd.DataFrame:
    """取某地区的成分面板，附带权重列 'w'。

    - 有真实指数权重的月份(2009起)：取权重>0 的成分(天然 point-in-time)。
    - 更早月份(无权重)：用"地区内市值前 N"代理池补齐(已标记, 仅作样本扩展)。
    聚合全程等权，故代理池只需成分名单(w 置 NaN)。
    """
    wcol = config.REGION_WEIGHT_COL[region]
    real = df[df[wcol] > 0].copy()
    real["w"] = real[wcol]

    # 代理池：真实成分缺失的更早月份，取地区内市值前 N
    real_dates = set(real["Date"].unique())
    src = df[(~df["Date"].isin(real_dates))
             & (df[config.REGION_NEUTRAL_COL] == config.PROXY_REGION[region])]
    proxy = (src.dropna(subset=[config.MKT_CAP_COL, config.RETURN_COL])
                .sort_values(["Date", config.MKT_CAP_COL], ascending=[True, False])
                .groupby("Date").head(config.PROXY_N[region]).copy())
    proxy["w"] = np.nan
    return pd.concat([real, proxy]).sort_values("Date")


def constituents(region: str) -> dict:
    """{月末日期: [成分6位SEDOL]}，复用 get_region_panel(真实指数/代理池)。

    供 returns 侧目标(前瞻收益/波动)与特征侧共用同一成分口径。
    """
    cols = ["Date", config.ID_COL, config.RETURN_COL,
            config.REGION_NEUTRAL_COL, config.MKT_CAP_COL]
    cols += list(config.REGION_WEIGHT_COL.values())
    df = pd.read_parquet(config.SCREEN_PATH, columns=list(dict.fromkeys(cols)))
    df["Date"] = pd.to_datetime(df["Date"])
    df = df[df["Date"] >= pd.Timestamp(config.START_DATE)].copy()
    panel = get_region_panel(df, region)
    panel["id"] = panel[config.ID_COL].astype(str).str[:6]
    return {pd.Timestamp(t): g["id"].unique().tolist()
            for t, g in panel.groupby("Date")}

"""日度收益数据：从 returns.parquet 计算 screen 无法提供的 regime 信号。

新增特征（每地区每月末，基于当期成分的 trailing 日度窗口）：
- rvol_ann      : 等权组合年化已实现波动
- avg_corr      : 成分平均两两相关性（risk-on/off 核心信号）
- down_day_freq : 近一个月组合下跌交易日占比
"""
import numpy as np
import pandas as pd

from tp_core.data_sources import RETURNS_PATH
from tp_core.io import read_returns, resolve_return_columns

from . import config

CORR_WINDOW = 63   # 约3个月交易日，用于波动与相关性
DOWN_WINDOW = 21   # 约1个月交易日，用于下跌频率


def load_returns(
    *,
    columns: list[str] | tuple[str, ...] | None = None,
    date_from: str | pd.Timestamp | None = None,
    date_to: str | pd.Timestamp | None = None,
    engine: str | None = None,
) -> pd.DataFrame:
    """加载日度收益，列名去掉 '-R' 后缀以对齐 SEDOL 前6位。"""
    requested = resolve_return_columns(
        config.RETURNS_PATH,
        columns,
        engine=engine,
    )
    if columns is not None and not requested:
        return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))
    r = read_returns(
        RETURNS_PATH if RETURNS_PATH else config.RETURNS_PATH,
        columns=requested,
        date_from=pd.Timestamp(date_from) if date_from is not None else None,
        date_to=pd.Timestamp(date_to) if date_to is not None else None,
        engine=engine,
    )
    r.columns = [c[:-2] if str(c).endswith("-R") else c for c in r.columns]
    return r


def _month_features(r: pd.DataFrame, t: pd.Timestamp, ids: list[str]) -> dict:
    ids = [i for i in ids if i in r.columns]
    if not ids:
        return {"rvol_ann": np.nan, "avg_corr": np.nan, "down_day_freq": np.nan}
    win = r.loc[:t, ids].tail(CORR_WINDOW)
    win = win.dropna(axis=1, thresh=int(0.8 * len(win)))
    if win.shape[1] < 5:
        return {"rvol_ann": np.nan, "avg_corr": np.nan, "down_day_freq": np.nan}

    port = win.mean(axis=1)
    rvol = port.std() * np.sqrt(252)

    c = win.corr().values
    upper = c[np.triu_indices_from(c, 1)]
    avg_corr = np.nanmean(upper)

    port_recent = port.tail(DOWN_WINDOW)
    down_freq = (port_recent < 0).mean()
    return {"rvol_ann": rvol, "avg_corr": avg_corr, "down_day_freq": down_freq}


def build_return_features(screen_df: pd.DataFrame, region: str, r: pd.DataFrame) -> pd.DataFrame:
    """按地区生成日度衍生的月度特征表，索引为月末日期。"""
    from .data_loader import get_region_panel  # 复用同一套成分判定(真实指数/代理池)
    panel = get_region_panel(screen_df, region)[["Date", config.ID_COL]].copy()
    panel["id"] = panel[config.ID_COL].astype(str).str[:6]

    rows = {}
    for t, g in panel.groupby("Date"):
        rows[pd.Timestamp(t)] = _month_features(r, pd.Timestamp(t), g["id"].tolist())
    out = pd.DataFrame(rows).T.sort_index()
    out.index.name = "Date"
    return out

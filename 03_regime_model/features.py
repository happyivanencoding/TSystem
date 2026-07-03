"""特征工程：把个股横截面聚合成"市场状态"月度特征（bottom-up）。

每个地区、每个月末，仅用当期指数成分计算：
- 估值水平与分散度
- 盈利修正广度与成长
- 质量 / 杠杆
- 波动 / 回撤
- 动量、横截面收益分散与市场宽度
- 因子多空价差收益（同期已实现）
"""
import numpy as np
import pandas as pd

import config


def _iqr(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) < 5:
        return np.nan
    return s.quantile(0.75) - s.quantile(0.25)


def _aggregate_month(g: pd.DataFrame) -> pd.Series:
    """单月单地区的横截面聚合 -> 一行特征。"""
    f = {}

    # 估值水平（中位数）与分散度（IQR）
    f["val_earnyield_med"] = g["Earns Yield NTM"].median()
    f["val_earnyield_disp"] = _iqr(g["Earns Yield NTM"])
    f["val_dvdyield_med"] = g["DVD Yield NTM"].median()
    f["val_pe_pct_disp"] = g["PCT PE NTM"].std()

    # 盈利修正广度 / 成长
    rev = g["EPS Revision Ratio"].dropna()
    f["eps_rev_breadth"] = (rev > 0).mean() if len(rev) else np.nan
    f["eps_rev_med"] = g["EPS Revision Ratio"].median()
    f["eps_ntm3m_growth_med"] = g["EPS NTM 3M Growth"].median()
    f["eps_growth_ntm_med"] = g["EPS Growth NTM"].median()
    f["sales_growth_ntm_med"] = g["Sales Growth NTM"].median()

    # 质量 / 杠杆
    f["roe_med"] = g["ROE avg FY0"].median()
    f["netdebt_ebitda_med"] = g["NetDebt to EBITDA exFIN"].median()

    # 波动：长短窗中位数与横截面分散；短/长比值反映波动加速
    f["vol_med"] = g["Daily Vol 260J"].median()
    f["vol_disp"] = _iqr(g["Daily Vol 260J"])
    f["vol_short_med"] = g["Daily Vol 90J"].median()

    # 动量水平；已实现月度收益的横截面分散、偏度与市场宽度
    f["mom_med"] = g["MOM Score"].median()
    ret = g[config.RETURN_COL].dropna()
    f["ret_disp"] = ret.std() if len(ret) else np.nan
    f["ret_skew"] = ret.skew() if len(ret) >= 5 else np.nan
    f["breadth_pos"] = (ret > 0).mean() if len(ret) else np.nan

    # 周期-防御板块月度收益差（risk-on/off 信号，trailing 已实现）
    sec = g[config.SECTOR_COL]
    defn = ret[sec.isin(config.DEFENSIVE_SECTORS)]
    cyc = ret[(~sec.isin(config.DEFENSIVE_SECTORS)) & (sec != 0)]
    f["cyc_def_spread"] = (cyc.mean() - defn.mean()) if len(defn) and len(cyc) else np.nan

    return pd.Series(f)


def _factor_spreads(panel: pd.DataFrame) -> pd.DataFrame:
    """因子多空价差：用 t-1 的因子分位排序、t 的已实现收益，顶组-底组（避免同期循环）。

    安全起见再做一次中性化：每月横截面内按 区域×行业 对因子分位做"组内 rank"
    （严格行业中性，尾部各行业均衡），并对成分过少的组做阈值保护后剔除。
    """
    p = panel.sort_values([config.ID_COL, "Date"]).copy()
    grp = ["Date", config.REGION_NEUTRAL_COL, config.SECTOR_COL]
    out = {}
    for name, col in config.FACTOR_PCTILE_COLS.items():
        # 组内百分位排名 [0,1]；组内有效成分过少则置 NaN 剔除
        gb = p.groupby(grp)[col]
        rnk = gb.rank(pct=True)
        rnk = rnk.where(gb.transform("count") >= config.MIN_SECTOR_SIZE)
        # 个股内滞后一期
        p["_rank_lag"] = rnk.groupby(p[config.ID_COL]).shift(1)

        def _spread(g: pd.DataFrame) -> float:
            sub = g[["_rank_lag", config.RETURN_COL]].dropna()
            if len(sub) < 25:
                return np.nan
            hi = sub["_rank_lag"] >= sub["_rank_lag"].quantile(0.8)
            lo = sub["_rank_lag"] <= sub["_rank_lag"].quantile(0.2)
            return sub.loc[hi, config.RETURN_COL].mean() - sub.loc[lo, config.RETURN_COL].mean()

        out[f"spread_{name.lower()}"] = p.groupby("Date").apply(_spread, include_groups=False)
    return pd.DataFrame(out)


def build_region_features(df: pd.DataFrame, region: str) -> pd.DataFrame:
    """生成某地区的月度特征表，索引为月末日期。"""
    from data_loader import get_region_panel

    panel = get_region_panel(df, region)
    feats = panel.groupby("Date", group_keys=True).apply(
        _aggregate_month, include_groups=False
    )
    spreads = _factor_spreads(panel)
    feats = feats.join(spreads)
    feats.index.name = "Date"
    return feats.sort_index()

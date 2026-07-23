"""导出风险仪表盘数据：HMM 状态 + Ridge 波动预测 + 线性可解释归因 + 配置信号。

产物：webapp/data.js (window.DASHBOARD_DATA)，供静态前端读取(无需服务器)。
"""
import json

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

import config
import model
import vol_compare
from tp_core.general_backtest import backtest_return_series

# 状态颜色(压力升序：绿->红)
STATE_COLORS = ["#43a047", "#c0ca33", "#fb8c00", "#e53935"]
# 配置信号参数
TARGET_VOL = 0.12
STATE_MULT = {0: 1.0, 1: 0.9, 2: 0.7, 3: 0.4}
# 特征友好名(可解释展示)
FEATURE_LABELS = {
    "val_earnyield_med": "盈利收益率(中位)", "val_earnyield_disp": "估值分散度",
    "val_dvdyield_med": "股息率(中位)", "val_pe_pct_disp": "PE分位分散",
    "eps_rev_breadth": "盈利上修广度", "eps_rev_med": "盈利修正(中位)",
    "eps_ntm3m_growth_med": "NTM EPS 3M增速", "eps_growth_ntm_med": "NTM EPS增速",
    "sales_growth_ntm_med": "NTM营收增速", "roe_med": "ROE(中位)",
    "netdebt_ebitda_med": "净负债/EBITDA", "vol_med": "个股波动(中位)",
    "vol_disp": "波动分散度", "vol_short_med": "短期波动(中位)", "mom_med": "动量得分(中位)",
    "ret_disp": "收益横截面分散", "ret_skew": "收益偏度", "breadth_pos": "上涨广度",
    "spread_value": "价值因子价差", "spread_quality": "质量因子价差",
    "spread_mom": "动量因子价差", "spread_lowvol": "低波因子价差",
    "cyc_def_spread": "周期-防御价差", "rvol_ann": "已实现波动(年化)",
    "avg_corr": "成分平均相关性", "down_day_freq": "近月下跌日占比",
    "sv_v60_med": "60日个股波动(中位)", "sv_v60_v1y_ratio": "60日/1年波动比",
    "sv_v90_v1y_ratio": "90日/1年波动比",
    "sv_v60_above_v1y_breadth": "60日波动高于1年占比",
    "sv_v90_above_v1y_breadth": "90日波动高于1年占比",
}


def _label(f: str) -> str:
    return FEATURE_LABELS.get(f, f)


def build_region(region: str) -> dict:
    feats = model.load_features(region).ffill().dropna()
    fwd_vol = vol_compare.fwd_risk(region)["fwd_vol"]
    fwd_ret = model.market_fwd_return(region)
    regime = pd.read_parquet(config.OUTPUT_DIR / f"regime_{region}.parquet")

    cols = list(feats.columns)
    # Ridge 波动模型(全样本拟合，用于当前预测与可解释归因)
    train = feats.join(fwd_vol.rename("y"), how="inner").dropna()
    scaler = StandardScaler().fit(train[cols])
    ridge = Ridge(alpha=10.0).fit(scaler.transform(train[cols]), train["y"])

    # 当前(最新)月份的预测与线性归因：contrib_j = coef_j * z_j
    z_all = pd.DataFrame(scaler.transform(feats[cols]), index=feats.index, columns=cols)
    z_cur = z_all.iloc[-1]
    contrib = ridge.coef_ * z_cur.values
    pred_vol_cur = float(ridge.intercept_ + contrib.sum())
    fitted_vol = ridge.intercept_ + z_all.values @ ridge.coef_   # 全历史拟合(展示用)

    # HMM 当前状态与状态画像(各状态标准化特征均值)
    cur_state = int(regime["state"].iloc[-1])
    cur_label = regime["label"].iloc[-1]
    zr = z_all.join(regime["state"], how="inner")
    state_prof = zr.groupby("state")[cols].mean()

    # 配置信号
    w_vol = float(np.clip(TARGET_VOL / pred_vol_cur, 0.0, 1.5))
    smult = STATE_MULT.get(cur_state, 1.0)
    equity_w = float(np.clip(w_vol * smult, 0.0, 1.0))

    # 时间序列(对齐到特征索引)
    cum = backtest_return_series(
        fwd_ret.reindex(feats.index).shift(1).fillna(0),
        initial_nav=1.0,
        periods_per_year=12,
        name=f"{region}_dashboard_market",
    ).nav
    series = {
        "dates": [d.strftime("%Y-%m") for d in feats.index],
        "state": [int(s) for s in regime["state"].reindex(feats.index).fillna(0)],
        "cum_return": [round(float(x), 4) for x in cum.values],
        "realized_vol": [None if pd.isna(v) else round(float(v), 4)
                         for v in fwd_vol.reindex(feats.index).values],
        "fitted_vol": [round(float(x), 4) for x in fitted_vol],
    }

    contrib_list = sorted(
        [{"feat": _label(c), "z": round(float(z_cur[c]), 3),
          "contrib": round(float(contrib[i]), 4)} for i, c in enumerate(cols)],
        key=lambda d: -abs(d["contrib"]))
    coef_list = sorted(
        [{"feat": _label(c), "coef": round(float(ridge.coef_[i]), 4)} for i, c in enumerate(cols)],
        key=lambda d: -abs(d["coef"]))
    prof_list = sorted(
        [{"feat": _label(c), "z": round(float(state_prof.loc[cur_state, c]), 3)} for c in cols],
        key=lambda d: -abs(d["z"]))

    return {
        "as_of": feats.index[-1].strftime("%Y-%m"),
        "labels": list(regime["label"].drop_duplicates().sort_index().values) if False else None,
        "state_labels": [s for _, s in sorted(
            {int(r.state): r.label for r in regime.itertuples()}.items())],
        "colors": STATE_COLORS,
        "current": {
            "state": cur_state, "label": cur_label,
            "pred_vol": round(pred_vol_cur, 4),
            "w_vol": round(w_vol, 3), "state_mult": smult,
            "target_vol": TARGET_VOL, "equity_weight": round(equity_w, 3),
        },
        "series": series,
        "contrib": contrib_list,
        "ridge_coef": coef_list,
        "state_profile": prof_list,
        "ridge_intercept": round(float(ridge.intercept_), 4),
    }


def main():
    data = {region: build_region(region) for region in config.REGION_WEIGHT_COL}
    out = config.OUTPUT_DIR.parent / "webapp" / "data.js"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("window.DASHBOARD_DATA = " + json.dumps(data, ensure_ascii=False) + ";",
                   encoding="utf-8")
    for r, d in data.items():
        print(f"[{r}] as_of={d['as_of']} 状态={d['current']['label']} "
              f"预测波动={d['current']['pred_vol']:.1%} 建议权益={d['current']['equity_weight']:.0%}")
    print(f"已导出 -> {out}")


if __name__ == "__main__":
    main()

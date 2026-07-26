"""范式对比(风险预测任务)：预测【真实】下月已实现波动率与最大回撤。

波动具强聚集性、可预测，是 regime 模型的强项。OOS walk-forward 对比：
- 持续性基准：用当前 rvol_ann 预测下月波动(很强的基准)。
- HMM 状态：因果"状态->历史下月波动均值"映射。
- Ridge / GBM：监督式回归(全部特征)。
目标由 returns.parquet 日度收益计算(成分等权、PIT)。
指标：Pearson、Spearman IC、R²(对均值)、高波动(顶档)识别 AUC。
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr

from . import (
    config,
    data_loader,
    ml_if_features,
    model,
    returns_loader,
    screen_vol_features,
)
from tp_core.backtesting import calculate_return_series_nav

MIN_TRAIN = 60


def _join_new_columns(base: pd.DataFrame, extra: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    cols = [c for c in cols if c not in base.columns]
    return base.join(extra[cols]) if cols else base


def fwd_risk(region: str) -> pd.DataFrame:
    """各月真实下月已实现波动(年化)与最大回撤(等权市场，来自日度收益)。"""
    members = data_loader.constituents(region)
    r = returns_loader.load_returns()
    r = r.loc[:, ~r.columns.duplicated()]
    dates = sorted(members)

    vol, mdd = {}, {}
    for i in range(len(dates) - 1):
        t, t1 = pd.Timestamp(dates[i]), pd.Timestamp(dates[i + 1])
        ids = [x for x in members[t] if x in r.columns]
        win = r.loc[(r.index > t) & (r.index <= t1), ids]
        if not ids or len(win) < 5:
            continue
        port = win.mean(axis=1).fillna(0)            # 等权市场日收益
        vol[t] = port.std() * np.sqrt(252)
        c = calculate_return_series_nav(
            port,
            initial_nav=1.0,
            periods_per_year=252,
            name=f"{region}_market_risk",
        ).nav
        mdd[t] = float((1 - c / c.cummax()).max())
    return pd.DataFrame({"fwd_vol": pd.Series(vol), "fwd_mdd": pd.Series(mdd)}).sort_index()


def _metrics(y: np.ndarray, p: np.ndarray) -> dict:
    ss_res = np.sum((y - p) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    hi = (y >= np.quantile(y, 2 / 3)).astype(int)
    return {
        "Pearson": round(np.corrcoef(y, p)[0, 1], 3),
        "IC(Spearman)": round(spearmanr(y, p).statistic, 3),
        "R2": round(1 - ss_res / ss_tot, 3),
        "高波动AUC": round(roc_auc_score(hi, p), 3),
    }


def _hmm_pred(region: str, index, target: pd.Series) -> np.ndarray:
    """因果：当前 OOS 状态的历史下月目标均值作为预测。"""
    oos = pd.read_parquet(config.OUTPUT_DIR / f"regime_oos_{region}.parquet")["state"]
    preds = []
    for t in index:
        st = oos.get(t, np.nan)
        past = oos[oos.index < t]
        same = target[past.index[past.values == st]] if not np.isnan(st) else target.iloc[:0]
        preds.append(same.mean() if len(same) else target[past.index].mean())
    return np.array(preds)


def evaluate(region: str, tgt: str) -> pd.DataFrame:
    feats = model.load_features(region).ffill().dropna()
    risk = fwd_risk(region)[tgt]
    ridge_feats = model.load_features(region)
    ridge_cols = screen_vol_features.vol_ridge_cols(region, tgt)
    if ridge_cols:
        ridge_feats = _join_new_columns(
            ridge_feats,
            screen_vol_features.load_region_screen_vol(region, ridge_feats.index),
            ridge_cols,
        )
    df = ridge_feats.ffill().dropna().join(risk, how="inner").dropna(subset=[tgt])
    X = df.drop(columns=[tgt])
    y = df[tgt]

    test_idx = X.index[MIN_TRAIN:]
    yt = y.loc[test_idx].values

    ridge_p = []
    for i in range(MIN_TRAIN, len(X)):
        Xtr, ytr = X.iloc[:i], y.iloc[:i]
        sc = StandardScaler().fit(Xtr)
        ridge_p.append(Ridge(alpha=10.0).fit(sc.transform(Xtr), ytr).predict(sc.transform(X.iloc[[i]]))[0])

    gbm_cols = ml_if_features.vol_gbm_cols(region, tgt)
    screen_vol_cols = screen_vol_features.vol_gbm_cols(region, tgt)
    gbm_feats = model.load_features(region)
    if gbm_cols:
        gbm_feats = _join_new_columns(
            gbm_feats,
            ml_if_features.load_region_mlif(region, gbm_feats.index),
            gbm_cols,
        )
    if screen_vol_cols:
        gbm_feats = _join_new_columns(
            gbm_feats,
            screen_vol_features.load_region_screen_vol(region, gbm_feats.index),
            screen_vol_cols,
        )
    gbm_df = gbm_feats.ffill().dropna().join(risk, how="inner").dropna(subset=[tgt])
    Xg = gbm_df.drop(columns=[tgt])
    yg = gbm_df[tgt]
    gbm_idx = Xg.index[MIN_TRAIN:]
    ytg = yg.loc[gbm_idx].values
    gbm_p = []
    for i in range(MIN_TRAIN, len(Xg)):
        Xtr, ytr = Xg.iloc[:i], yg.iloc[:i]
        gbm = HistGradientBoostingRegressor(max_depth=3, max_iter=200, learning_rate=0.05,
                                            l2_regularization=1.0, random_state=0).fit(Xtr, ytr)
        gbm_p.append(gbm.predict(Xg.iloc[[i]])[0])

    persist = X.loc[test_idx, "rvol_ann"].values          # 持续性基准
    hmm_p = _hmm_pred(region, test_idx, y)

    rows = {
        "持续性(rvol_ann)": _metrics(yt, persist),
        "HMM状态": _metrics(yt, hmm_p),
        "Ridge+ScreenVol": _metrics(yt, np.array(ridge_p)),
        "GBM+ML_IF+ScreenVol": _metrics(ytg, np.array(gbm_p)),
    }
    return pd.DataFrame(rows).T


def main():
    for tgt, name in [("fwd_vol", "下月已实现波动率"), ("fwd_mdd", "下月最大回撤")]:
        print(f"\n############ 目标：{name} ############")
        for region in config.REGION_WEIGHT_COL:
            print(f"\n===== {region} =====")
            print(evaluate(region, tgt).to_string())


if __name__ == "__main__":
    main()

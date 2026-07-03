"""范式对比：在"预测下月市场涨跌"同一任务上，OOS 比较
基准(恒涨/买入持有) / HMM状态 / Logistic / GBM。

- 严格 walk-forward：决策点 t 只用已实现目标的历史样本(s<=t-1)训练，预测 t 的下月收益。
- 目标：sign(TTR_Fwd1M) 成分等权下月收益。
- HMM 用已生成的 OOS 状态序列 + 因果"状态->历史前瞻收益均值"映射转成涨跌预测。
- 指标：方向准确率、AUC(概率模型)、看涨做多否则空仓的策略年化/夏普。
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

import config
import model

MIN_TRAIN = 60


def _data(region: str):
    feats = model.load_features(region).ffill().dropna()
    fwd = model.market_fwd_return(region).reindex(feats.index)
    df = feats.copy()
    df["_fwd"] = fwd
    df = df.dropna(subset=["_fwd"])          # 末月无前瞻收益, 剔除
    X = df.drop(columns=["_fwd"])
    y = (df["_fwd"] > 0).astype(int)
    return X, y, df["_fwd"]


def _strategy(pred_up: np.ndarray, fwd: np.ndarray) -> dict:
    strat = np.where(pred_up == 1, fwd, 0.0)
    ann = strat.mean() * 12
    vol = strat.std(ddof=1) * np.sqrt(12)
    return {"年化收益%": round(ann * 100, 2),
            "夏普": round(ann / vol, 2) if vol > 0 else np.nan}


def _hmm_pred(region: str, index: pd.Index, fwd: pd.Series) -> np.ndarray:
    """用 OOS 状态 + 因果状态收益映射做涨跌预测：当前状态历史前瞻均值>0 则看涨。"""
    oos = pd.read_parquet(config.OUTPUT_DIR / f"regime_oos_{region}.parquet")["state"]
    preds = []
    for t in index:
        st = oos.get(t, np.nan)
        past = oos[oos.index < t]
        if np.isnan(st) or len(past) < 12:
            preds.append(1)                  # 历史不足时默认看涨(base rate)
            continue
        same = fwd[past.index[past.values == st]]
        preds.append(1 if (same.mean() > 0 if len(same) else True) else 0)
    return np.array(preds)


def evaluate(region: str) -> pd.DataFrame:
    X, y, fwd = _data(region)
    n = len(X)
    test_idx = X.index[MIN_TRAIN:]
    yt = y.loc[test_idx].values
    fwt = fwd.loc[test_idx].values

    # 监督模型 walk-forward
    log_p, gbm_p = [], []
    for i in range(MIN_TRAIN, n):
        Xtr, ytr = X.iloc[:i], y.iloc[:i]
        sc = StandardScaler().fit(Xtr)
        lr = LogisticRegression(C=0.3, max_iter=1000).fit(sc.transform(Xtr), ytr)
        log_p.append(lr.predict_proba(sc.transform(X.iloc[[i]]))[0, 1])
        gbm = HistGradientBoostingClassifier(max_depth=3, max_iter=200,
                                             learning_rate=0.05, l2_regularization=1.0,
                                             random_state=0).fit(Xtr, ytr)
        gbm_p.append(gbm.predict_proba(X.iloc[[i]])[0, 1])
    log_p, gbm_p = np.array(log_p), np.array(gbm_p)

    hmm_pred = _hmm_pred(region, test_idx, fwd)
    base_pred = np.ones_like(yt)             # 恒看涨

    def acc(p): return round((p == yt).mean(), 3)
    def auc(prob):
        from sklearn.metrics import roc_auc_score
        return round(roc_auc_score(yt, prob), 3)

    rows = {
        "基准(恒涨)": {"准确率": acc(base_pred), "AUC": np.nan, **_strategy(base_pred, fwt)},
        "HMM状态": {"准确率": acc(hmm_pred), "AUC": np.nan, **_strategy(hmm_pred, fwt)},
        "Logistic": {"准确率": acc((log_p > 0.5).astype(int)), "AUC": auc(log_p),
                     **_strategy((log_p > 0.5).astype(int), fwt)},
        "GBM": {"准确率": acc((gbm_p > 0.5).astype(int)), "AUC": auc(gbm_p),
                **_strategy((gbm_p > 0.5).astype(int), fwt)},
    }
    return pd.DataFrame(rows).T


def main():
    for region in config.REGION_WEIGHT_COL:
        tab = evaluate(region)
        print(f"\n===== {region} OOS 范式对比 (n={len(model.load_features(region).ffill().dropna())-MIN_TRAIN-1}月) =====")
        print(tab.to_string())


if __name__ == "__main__":
    main()

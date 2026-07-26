"""Regime 识别：预处理 + GaussianHMM(K=4) + 状态标注与前瞻验证。"""
from functools import lru_cache

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler, RobustScaler
from hmmlearn.hmm import GaussianHMM

from . import config, data_loader, returns_loader

SEED = 42
N_INIT = 10
K_RANGE = range(2, 7)        # BIC 选 K 的候选范围
STICKINESS_KAPPA = 20.0      # 转移矩阵对角先验强度：越大状态越粘滞(少跳变)
# diag 协方差：样本仅~200、特征26个，full 协方差会严重过参数化，diag 更稳健、利于样本外
COV_TYPE = "diag"
# 高偏特征用稳健缩放(中位数/IQR)，其余用标准化
ROBUST_FEATURES = ["ret_skew", "spread_value", "spread_quality", "spread_mom", "spread_lowvol"]
# K=4 时的语义命名（按市场压力升序）
STATE_LABELS_K4 = ["扩张(Risk-On)", "平稳", "震荡", "危机(Risk-Off)"]
STATE_LABELS_EN_K4 = ["Calm", "Normal", "Elevated", "Crisis"]


def state_names(k: int) -> tuple[list[str], list[str]]:
    """按压力升序返回(中文,英文)状态名；K=4 用语义名，否则用通用分级名。"""
    if k == 4:
        return STATE_LABELS_K4, STATE_LABELS_EN_K4
    zh = [f"压力{i}" for i in range(k)]
    en = [f"L{i}" for i in range(k)]
    zh[0], zh[-1] = "Risk-On", "危机(Risk-Off)"
    en[0], en[-1] = "Calm", "Crisis"
    return zh, en


def make_prior(k: int) -> np.ndarray:
    """对角加权的转移矩阵 Dirichlet 先验，鼓励自转移(粘滞)。"""
    prior = np.ones((k, k))
    np.fill_diagonal(prior, 1.0 + STICKINESS_KAPPA)
    return prior


def load_features(region: str) -> pd.DataFrame:
    return pd.read_parquet(config.OUTPUT_DIR / f"features_{region}.parquet").sort_index()


def preprocess(feats: pd.DataFrame) -> tuple[np.ndarray, pd.DataFrame]:
    """少量缺失前向填充 -> 删除开头残留 NaN -> 标准化 + 高偏稳健缩放。"""
    f = feats.ffill().dropna()
    robust = [c for c in ROBUST_FEATURES if c in f.columns]
    other = [c for c in f.columns if c not in robust]
    z_other = StandardScaler().fit_transform(f[other])
    z_robust = RobustScaler().fit_transform(f[robust])
    Z = np.hstack([z_other, z_robust])
    return Z, f


def fit_hmm(Z: np.ndarray, k: int, n_init: int = N_INIT) -> tuple[GaussianHMM, np.ndarray]:
    """多次随机初始化，取对数似然最高的模型；带粘滞先验。"""
    best = None
    prior = make_prior(k)
    for s in range(n_init):
        m = GaussianHMM(n_components=k, covariance_type=COV_TYPE, n_iter=500,
                        random_state=SEED + s, transmat_prior=prior)
        m.fit(Z)
        try:
            ll = m.score(Z)
        except Exception:
            continue
        if best is None or ll > best[0]:
            best = (ll, m)
    model = best[1]
    return model, model.predict(Z)


def _knee(s: pd.Series) -> int:
    """在(单调递减的)BIC曲线上取拐点：离首尾连线最远的点，避免选到边界。"""
    x = np.asarray(s.index, float)
    y = s.values.astype(float)
    xn = (x - x.min()) / (x.max() - x.min())
    yn = (y - y.min()) / (y.max() - y.min())
    line = yn[0] + (yn[-1] - yn[0]) * (xn - xn[0]) / (xn[-1] - xn[0])
    return int(x[np.argmax(line - yn)])


def select_k(Z: np.ndarray) -> tuple[int, pd.Series]:
    """计算 K_RANGE 的 BIC（带粘滞先验），按拐点选 K（BIC 常单调，全局最小会触边界）。"""
    bic = {k: fit_hmm(Z, k)[0].bic(Z) for k in K_RANGE}
    s = pd.Series(bic, name="BIC")
    return _knee(s), s


def label_states(feats: pd.DataFrame, states: np.ndarray) -> dict[int, int]:
    """按市场压力(波动+相关性)给状态排序，返回 {原始状态: 压力名次0..3}。"""
    tmp = feats[["rvol_ann", "avg_corr"]].copy()
    tmp["state"] = states
    stress = tmp.groupby("state").mean()
    stress["score"] = (StandardScaler().fit_transform(stress)).sum(axis=1)
    order = stress["score"].sort_values().index.tolist()
    return {orig: rank for rank, orig in enumerate(order)}


@lru_cache(maxsize=None)
def market_fwd_return(region: str) -> pd.Series:
    """各月成分等权的【真实】未来1月已实现收益，由 returns.parquet 日度收益计算。

    成分按当月口径 point-in-time 锁定后持有至下一月末；TTR_Fwd1M 仅是预测、不用。
    """
    members = data_loader.constituents(region)

    r = returns_loader.load_returns()
    r = r.loc[:, ~r.columns.duplicated()]
    dates = sorted(members)

    out = {}
    for i in range(len(dates) - 1):
        t, t1 = pd.Timestamp(dates[i]), pd.Timestamp(dates[i + 1])
        ids = [x for x in members[t] if x in r.columns]
        win = r.loc[(r.index > t) & (r.index <= t1), ids]
        if not ids or win.empty:
            continue
        cum = (1 + win.fillna(0)).prod() - 1     # 各股前瞻已实现收益
        out[t] = cum.mean()                       # 等权市场前瞻收益
    s = pd.Series(out, name="fwd_ret").sort_index()
    s.index.name = "Date"
    return s


def run(region: str, k: int | None = None) -> tuple[pd.DataFrame, int, pd.Series]:
    """全样本拟合：BIC 选 K(或指定 k)，返回(状态表, K, BIC序列)。"""
    feats = load_features(region)
    Z, f = preprocess(feats)
    if k is None:
        k, bic = select_k(Z)
    else:
        bic = pd.Series(dtype=float)
    model, states = fit_hmm(Z, k)
    rank = label_states(f, states)
    zh, _ = state_names(k)

    res = pd.DataFrame(index=f.index)
    res["state"] = [rank[s] for s in states]
    res["label"] = res["state"].map(dict(enumerate(zh)))
    res["fwd_ret"] = market_fwd_return(region).reindex(res.index)
    return res, k, bic

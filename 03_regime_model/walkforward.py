"""样本外滚动(walk-forward)：每月仅用截至当月的数据拟合，得到真正 OOS 的状态序列。

- 扩展窗口：起始训练 MIN_TRAIN 个月，逐月扩展。
- 严格无前视：标准化器与 HMM 均只在当前窗口内拟合。
- 标签对齐：每次重拟合后按"市场压力"排序，保证语义一致(0=低压力..K-1=危机)。
- K 固定为全样本 BIC 拐点选出的值（结构性选择，不逐月重选以避免不稳定）。
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config
import model
from tp_core.backtesting import calculate_return_series_nav

MIN_TRAIN = 60     # 起始训练窗口(月)
N_INIT_WF = 3      # 每步随机初始化次数(滚动较多，适当减小)


def walk_forward(region: str, k: int) -> pd.DataFrame:
    feats = model.load_features(region)
    nowcast = {}
    for t in range(MIN_TRAIN, len(feats) + 1):
        window = feats.iloc[:t]
        if len(window.ffill().dropna()) < MIN_TRAIN:
            continue
        Z, f = model.preprocess(window)           # 仅窗口内 fit 标准化器，无前视
        m, st = model.fit_hmm(Z, k, n_init=N_INIT_WF)
        rank = model.label_states(f, st)
        nowcast[f.index[-1]] = rank[st[-1]]        # 末月的 OOS nowcast
    res = pd.DataFrame({"state": pd.Series(nowcast)}).sort_index()
    zh, _ = model.state_names(k)
    res["label"] = res["state"].map(dict(enumerate(zh)))
    res["fwd_ret"] = model.market_fwd_return(region).reindex(res.index)
    res.index.name = "Date"
    return res


def evaluate(res: pd.DataFrame, k: int) -> pd.DataFrame:
    g = res.dropna(subset=["fwd_ret"]).groupby("state")["fwd_ret"]
    zh, _ = model.state_names(k)
    tab = pd.DataFrame({
        "label": [zh[s] for s in g.size().index],
        "月数": g.size(),
        "前瞻月收益均值%": (g.mean() * 100).round(2),
        "前瞻月收益波动%": (g.std() * 100).round(2),
        "胜率": g.apply(lambda x: (x > 0).mean()).round(3),
    })
    return tab


def plot_regime(res: pd.DataFrame, region: str, k: int) -> None:
    realized = res["fwd_ret"].shift(1).fillna(0)
    cum = calculate_return_series_nav(
        realized,
        initial_nav=1.0,
        periods_per_year=12,
        name=f"{region}_walkforward_market",
    ).nav
    cmap = plt.get_cmap("RdYlGn_r")
    colors = [cmap(i / max(k - 1, 1)) for i in range(k)]
    _, labels_en = model.state_names(k)

    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(cum.index, cum.values, color="black", lw=1.2, zorder=3)
    for st in range(k):
        for d in res.index[res["state"] == st]:
            ax.axvspan(d, d + pd.offsets.MonthEnd(1), color=colors[st], alpha=0.3, lw=0)
    handles = [plt.Rectangle((0, 0), 1, 1, color=colors[i], alpha=0.5) for i in range(k)]
    ax.legend(handles, labels_en, loc="upper left", ncol=k)
    ax.set_title(f"{region} Out-of-Sample Regime (HMM K={k}, walk-forward)")
    ax.set_ylabel("Cumulative Return (EW)")
    fig.tight_layout()
    out = config.OUTPUT_DIR / f"regime_oos_{region}.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"        图已保存 -> {out}")


def main() -> None:
    for region in config.REGION_WEIGHT_COL:
        k = config.FIXED_K                        # EU/US 统一 K=4
        res = walk_forward(region, k)
        res.to_parquet(config.OUTPUT_DIR / f"regime_oos_{region}.parquet")
        print(f"\n===== {region} OOS  (K={k}, {res.index.min():%Y-%m} ~ {res.index.max():%Y-%m}, {len(res)}月) =====")
        print(evaluate(res, k).to_string(index=False))
        print(f"最新状态({res.index.max():%Y-%m}): {res['label'].iloc[-1]}")
        plot_regime(res, region, k)


if __name__ == "__main__":
    main()

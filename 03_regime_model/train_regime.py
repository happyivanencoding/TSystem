"""入口：对 US/EU 训练 regime 模型，输出状态序列、验证表与可视化。"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config
import model
from tp_core.general_backtest import backtest_return_series


def evaluate(res: pd.DataFrame) -> pd.DataFrame:
    """各状态的前瞻月收益统计：均值/波动/胜率/占比。"""
    g = res.dropna(subset=["fwd_ret"]).groupby(["state", "label"])["fwd_ret"]
    tab = pd.DataFrame({
        "月数": g.size(),
        "占比": (g.size() / len(res)).round(3),
        "前瞻月收益均值": (g.mean() * 100).round(2),
        "前瞻月收益波动": (g.std() * 100).round(2),
        "胜率": (g.apply(lambda x: (x > 0).mean())).round(3),
    })
    return tab


def plot_regime(res: pd.DataFrame, region: str, k: int) -> None:
    """市场累计收益曲线 + 状态背景着色（K 自适应）。"""
    realized = res["fwd_ret"].shift(1).fillna(0)  # 当月已实现≈上月前瞻
    cum = backtest_return_series(
        realized,
        initial_nav=1.0,
        periods_per_year=12,
        name=f"{region}_regime_market",
    ).nav
    cmap = plt.get_cmap("RdYlGn_r")
    colors = [cmap(i / max(k - 1, 1)) for i in range(k)]  # 绿(低压力)->红(高压力)
    _, labels_en = model.state_names(k)

    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(cum.index, cum.values, color="black", lw=1.2, zorder=3)
    for st in range(k):
        for d in res.index[res["state"] == st]:
            ax.axvspan(d, d + pd.offsets.MonthEnd(1), color=colors[st], alpha=0.3, lw=0)
    handles = [plt.Rectangle((0, 0), 1, 1, color=colors[i], alpha=0.5) for i in range(k)]
    ax.legend(handles, labels_en, loc="upper left", ncol=k)
    ax.set_title(f"{region} Regime (HMM K={k}) - Cumulative Return & States")
    ax.set_ylabel("Cumulative Return (EW)")
    fig.tight_layout()
    out = config.OUTPUT_DIR / f"regime_{region}.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"        图已保存 -> {out}")


def main() -> None:
    for region in config.REGION_WEIGHT_COL:
        res, k, bic = model.run(region, k=config.FIXED_K)
        res.to_parquet(config.OUTPUT_DIR / f"regime_{region}.parquet")
        print(f"\n===== {region}  ({res.index.min():%Y-%m} ~ {res.index.max():%Y-%m}, {len(res)}月) =====")
        print(f"使用固定 K={k}")
        print(evaluate(res).to_string())
        print(f"最新状态({res.index.max():%Y-%m}): {res['label'].iloc[-1]}")
        plot_regime(res, region, k)


if __name__ == "__main__":
    main()

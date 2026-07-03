"""入口脚本：生成 EU / US 月度特征表并落地到 output/。"""
import pandas as pd

import config
import data_loader
import features
import returns_loader


def _selected_macro_features(region: str) -> pd.DataFrame:
    macro = pd.read_parquet(config.MACRO_PATH).sort_index()
    macro.index = pd.to_datetime(macro.index).to_period("M").to_timestamp("M")
    macro = macro.groupby(level=0).last()
    cols = config.MACRO_FEATURE_COLS[region]
    missing = [c for c in cols if c not in macro.columns]
    if missing:
        raise KeyError(f"macro_data.parquet 缺少 {region} 宏观列: {missing}")
    out = macro[list(cols)].rename(columns=cols)
    out.index.name = "Date"
    return out


def main() -> None:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = data_loader.load_screen()
    daily = returns_loader.load_returns()

    for region in config.REGION_WEIGHT_COL:
        feats = features.build_region_features(df, region)
        ret_feats = returns_loader.build_return_features(df, region, daily)
        feats = feats.join(ret_feats)
        feats = feats.join(_selected_macro_features(region))
        out = config.OUTPUT_DIR / f"features_{region}.parquet"
        feats.to_parquet(out)
        n_proxy = (feats.index < pd.Timestamp(config.PROXY_END)).sum()
        print(f"[{region}] 月度样本: {len(feats)}  "
              f"区间: {feats.index.min():%Y-%m} ~ {feats.index.max():%Y-%m}  "
              f"特征数: {feats.shape[1]}  (其中代理池月份: {n_proxy})")
        print(f"        缺失率最高的5列:\n"
              f"{(feats.isna().mean().sort_values(ascending=False).head().round(3)).to_string()}")
        print(f"        已保存 -> {out}\n")


if __name__ == "__main__":
    main()

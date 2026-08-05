"""入口脚本：生成 EU / US 月度特征表并落地到 output/。"""
import pandas as pd

from . import config, data_loader, features, returns_loader, screen_vol_features


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


def _selected_macro2_features(region: str, target_index: pd.Index) -> pd.DataFrame:
    raw = pd.read_excel(
        config.MACRO2_PATH,
        sheet_name=config.MACRO2_SHEETS[region],
        header=None,
        usecols="A:P",
        engine="openpyxl",
    )
    raw = raw.iloc[3:, [0, 14, 15]].copy()
    raw.columns = ["Date", "macro2_citi_raw", "macro2_bnp_raw"]
    raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce").dt.to_period("M").dt.to_timestamp("M")
    raw = raw.dropna(subset=["Date"]).set_index("Date").sort_index()
    raw = raw[~raw.index.duplicated(keep="last")]
    raw = raw.apply(pd.to_numeric, errors="coerce")

    full_index = target_index.union(raw.index).sort_values()
    out = pd.DataFrame(index=target_index)
    for col in ["macro2_citi_raw", "macro2_bnp_raw"]:
        series = raw[col].dropna()
        aligned = series.reindex(full_index).interpolate(method="time", limit_area="inside")
        out[col] = aligned.reindex(target_index)
        out[col.replace("_raw", "_ewma")] = out[col].ewm(span=6, adjust=False).mean()

    out = out[list(config.MACRO2_FEATURE_COLS)]
    out.index.name = "Date"
    return out


def main() -> None:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = data_loader.load_screen()
    requested = sorted(
        set(df[config.ID_COL].dropna().astype(str).str[:6])
    )
    daily = returns_loader.load_returns(columns=requested)

    for region in config.REGION_WEIGHT_COL:
        feats = features.build_region_features(df, region)
        ret_feats = returns_loader.build_return_features(df, region, daily)
        feats = feats.join(ret_feats)
        feats = feats.join(_selected_macro_features(region))
        feats = feats.join(_selected_macro2_features(region, feats.index))
        screen_vol_cols = screen_vol_features.production_k4_cols(region)
        if screen_vol_cols:
            screen_vol = screen_vol_features.build_region_screen_vol(df, region)
            feats = feats.join(screen_vol[screen_vol_cols])
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

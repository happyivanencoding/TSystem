"""Point-in-time price labels and simple expanding-window news research."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from . import config
from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH
from tp_core.backtesting import calculate_return_series_nav


ID_COL = "Company SEDOL"
DATE_COL = "Date"
COUNTRY_COL = "Exchange Country Name"
REGION_COL = "Exchange Country Region"
SECTOR_COL = " Benchmark ICB Supersector "
MKT_CAP_COL = "Benchmark Market Value Millions in EUR"

SCREEN_COLUMNS = [
    DATE_COL,
    ID_COL,
    COUNTRY_COL,
    REGION_COL,
    SECTOR_COL,
    MKT_CAP_COL,
    "Weight in SP500",
    "Weight in STOXX EUROPE 600",
    "Weight in NIKKEI",
    "Weight in MSCI EM",
    "Weight in MSCI WORLD",
]

EU_COUNTRY_NAMES = {
    "AUSTRIA",
    "BELGIUM",
    "DENMARK",
    "FINLAND",
    "FRANCE",
    "GERMANY",
    "IRELAND",
    "ITALY",
    "LUXEMBOURG",
    "NETHERLANDS",
    "NORWAY",
    "PORTUGAL",
    "SPAIN",
    "SWEDEN",
    "SWITZERLAND",
    "UNITED KINGDOM",
}


def _real_weight(group: pd.DataFrame, market: str) -> pd.Series:
    spec = config.MARKET_SPECS[market]
    weights = group[list(spec.weight_columns)].apply(pd.to_numeric, errors="coerce").fillna(0)
    value = weights.max(axis=1)
    if market == "CN_HK":
        value = value.where(group[COUNTRY_COL].isin(["CHINA", "HONG KONG"]), 0.0)
    return value


def _proxy_candidates(group: pd.DataFrame, market: str) -> pd.DataFrame:
    spec = config.MARKET_SPECS[market]
    if spec.proxy_region:
        return group[group[REGION_COL].eq(spec.proxy_region)]
    if spec.proxy_country:
        return group[group[COUNTRY_COL].eq(spec.proxy_country)]
    return group.iloc[0:0]


def build_universe_panel(
    screen_path: Path = SCREEN_AGGREGATE_PATH,
    start: str = config.START_DATE,
    markets: Iterable[str] = config.MARKETS,
) -> pd.DataFrame:
    """Build monthly point-in-time constituents; proxies are explicit, never silent."""

    screen = pd.read_parquet(screen_path, columns=SCREEN_COLUMNS)
    screen[DATE_COL] = pd.to_datetime(screen[DATE_COL], errors="coerce")
    screen = screen[screen[DATE_COL].ge(pd.Timestamp(start))].copy()
    screen[ID_COL] = screen[ID_COL].astype("string").str[:6]
    screen = screen.dropna(subset=[DATE_COL, ID_COL])

    records: list[pd.DataFrame] = []
    for market in markets:
        spec = config.MARKET_SPECS[market]
        last_real: pd.DataFrame | None = None
        last_real_date: pd.Timestamp | None = None
        for date, group in screen.groupby(DATE_COL, sort=True):
            group = group.copy()
            group["_real_weight"] = _real_weight(group, market)
            chosen = group[group["_real_weight"].gt(0)].copy()
            is_proxy = False
            is_stale = False
            weight_snapshot_date = pd.Timestamp(date)
            if not chosen.empty:
                last_real = chosen.copy()
                last_real_date = pd.Timestamp(date)
            elif last_real is not None:
                chosen = last_real.copy()
                chosen[DATE_COL] = pd.Timestamp(date)
                is_stale = True
                weight_snapshot_date = pd.Timestamp(last_real_date)
            elif spec.proxy_n:
                chosen = _proxy_candidates(group, market).dropna(subset=[MKT_CAP_COL]).copy()
                chosen = chosen.sort_values(MKT_CAP_COL, ascending=False).head(spec.proxy_n)
                chosen["_real_weight"] = 1.0
                is_proxy = True
            if chosen.empty:
                continue
            chosen["weight"] = pd.to_numeric(chosen["_real_weight"], errors="coerce").fillna(0)
            weight_sum = chosen["weight"].sum()
            if weight_sum <= 0:
                continue
            chosen["weight"] /= weight_sum
            chosen["market"] = market
            chosen["benchmark"] = spec.benchmark
            chosen["universe_is_proxy"] = is_proxy
            chosen["universe_is_stale"] = is_stale
            chosen["weight_snapshot_date"] = weight_snapshot_date
            chosen["sector_code"] = pd.to_numeric(chosen[SECTOR_COL], errors="coerce").astype("Int64")
            records.append(
                chosen[
                    [
                        DATE_COL,
                        "market",
                        "benchmark",
                        ID_COL,
                        "sector_code",
                        "weight",
                        "universe_is_proxy",
                        "universe_is_stale",
                        "weight_snapshot_date",
                    ]
                ]
            )
    if not records:
        return pd.DataFrame(
            columns=[
                DATE_COL,
                "market",
                "benchmark",
                ID_COL,
                "sector_code",
                "weight",
                "universe_is_proxy",
                "universe_is_stale",
                "weight_snapshot_date",
            ]
        )
    return pd.concat(records, ignore_index=True).sort_values(["market", DATE_COL, ID_COL]).reset_index(drop=True)


def _available_return_mapping(path: Path, ids: Iterable[str]) -> dict[str, str]:
    available = set(pq.ParquetFile(path).schema_arrow.names)
    result = {}
    for sedol in set(map(str, ids)):
        if f"{sedol}-R" in available:
            result[sedol] = f"{sedol}-R"
        elif sedol in available:
            result[sedol] = sedol
    return result


def _forward_stats(values: pd.Series, horizon: int) -> pd.DataFrame:
    array = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    compounded = np.full(len(array), np.nan)
    volatility = np.full(len(array), np.nan)
    drawdown = np.full(len(array), np.nan)
    for idx in range(len(array)):
        window = array[idx + 1 : idx + 1 + horizon]
        valid = window[np.isfinite(window)]
        if len(valid) < max(1, int(np.ceil(horizon * 0.8))):
            continue
        path = np.cumprod(1 + valid)
        compounded[idx] = path[-1] - 1
        volatility[idx] = np.std(valid, ddof=1) * np.sqrt(252) if len(valid) > 1 else 0.0
        drawdown[idx] = np.min(
            np.r_[0.0, path / np.maximum.accumulate(np.r_[1.0, path])[:-1] - 1]
        )
    return pd.DataFrame(
        {
            f"target_return_{horizon}d": compounded,
            f"target_realized_vol_{horizon}d": volatility,
            f"target_drawdown_{horizon}d": drawdown,
        },
        index=values.index,
    )


def build_price_labels(
    universe: pd.DataFrame,
    returns_path: Path = RETURNS_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DatetimeIndex]]:
    """Create daily market and sector labels from prior month-end constituents."""

    if universe.empty:
        raise ValueError("universe 为空")
    mapping = _available_return_mapping(returns_path, universe[ID_COL].dropna())
    if not mapping:
        raise ValueError("universe 与 returns 没有可用 SEDOL 交集")
    raw = pd.read_parquet(returns_path, columns=sorted(set(mapping.values())))
    raw.index = pd.to_datetime(raw.index, errors="coerce")
    raw = raw.rename(columns={raw_name: sedol for sedol, raw_name in mapping.items()}).sort_index()

    market_rows: list[pd.DataFrame] = []
    sector_rows: list[pd.DataFrame] = []
    for market, market_panel in universe.groupby("market", sort=False):
        dates = sorted(pd.to_datetime(market_panel[DATE_COL].unique()))
        for idx, snapshot in enumerate(dates):
            next_snapshot = dates[idx + 1] if idx + 1 < len(dates) else raw.index.max()
            if next_snapshot <= snapshot:
                continue
            holdings = market_panel[market_panel[DATE_COL].eq(snapshot)].copy()
            ids = [sedol for sedol in holdings[ID_COL].astype(str) if sedol in raw.columns]
            if not ids:
                continue
            daily = raw.loc[(raw.index > snapshot) & (raw.index <= next_snapshot), ids]
            if daily.empty:
                continue
            weights = holdings.drop_duplicates(ID_COL).set_index(ID_COL)["weight"].reindex(ids).astype(float)
            available_weight = daily.notna().mul(weights, axis=1).sum(axis=1)
            portfolio = daily.fillna(0).mul(weights, axis=1).sum(axis=1).div(available_weight.replace(0, np.nan))
            portfolio = portfolio.where(available_weight.ge(0.70))
            market_rows.append(
                pd.DataFrame(
                    {
                        "trading_date": daily.index,
                        "market": market,
                        "market_return": portfolio.values,
                        "coverage_weight": available_weight.values,
                        "universe_snapshot": snapshot,
                        "universe_is_proxy": bool(holdings["universe_is_proxy"].iloc[0]),
                        "universe_is_stale": bool(holdings["universe_is_stale"].iloc[0]),
                        "weight_snapshot_date": holdings["weight_snapshot_date"].iloc[0],
                        "constituents": len(ids),
                    }
                )
            )

            for sector_code, sector_holdings in holdings.dropna(subset=["sector_code"]).groupby("sector_code"):
                sector_ids = [sedol for sedol in sector_holdings[ID_COL].astype(str) if sedol in daily.columns]
                if not sector_ids:
                    continue
                sector_weights = sector_holdings.drop_duplicates(ID_COL).set_index(ID_COL)["weight"].reindex(sector_ids).astype(float)
                total_sector_weight = float(sector_weights.sum())
                if total_sector_weight <= 0:
                    continue
                normalized = sector_weights / total_sector_weight
                sector_daily = daily[sector_ids]
                coverage = sector_daily.notna().mul(normalized, axis=1).sum(axis=1)
                sector_return = sector_daily.fillna(0).mul(normalized, axis=1).sum(axis=1).div(coverage.replace(0, np.nan))
                sector_return = sector_return.where(coverage.ge(0.60))
                sector_rows.append(
                    pd.DataFrame(
                        {
                            "trading_date": sector_daily.index,
                            "market": market,
                            "sector_code": int(sector_code),
                            "sector_return": sector_return.values,
                            "coverage_weight": coverage.values,
                            "universe_snapshot": snapshot,
                            "universe_is_proxy": bool(holdings["universe_is_proxy"].iloc[0]),
                            "universe_is_stale": bool(holdings["universe_is_stale"].iloc[0]),
                            "weight_snapshot_date": holdings["weight_snapshot_date"].iloc[0],
                            "constituents": len(sector_ids),
                        }
                    )
                )

    market_labels = pd.concat(market_rows, ignore_index=True).drop_duplicates(["trading_date", "market"], keep="last")
    market_labels = market_labels.sort_values(["market", "trading_date"]).reset_index(drop=True)
    enhanced = []
    for market, group in market_labels.groupby("market", sort=False):
        group = group.copy()
        group["target_return_1d"] = group["market_return"].shift(-1)
        group = pd.concat([group, _forward_stats(group["market_return"], 5)], axis=1)
        enhanced.append(group)
    market_labels = pd.concat(enhanced, ignore_index=True)
    global_1d = market_labels.groupby("trading_date")["target_return_1d"].mean().rename("global_target_return_1d")
    global_5d = market_labels.groupby("trading_date")["target_return_5d"].mean().rename("global_target_return_5d")
    market_labels = market_labels.merge(global_1d, on="trading_date", how="left").merge(global_5d, on="trading_date", how="left")
    market_labels["target_excess_return_1d"] = market_labels["target_return_1d"] - market_labels["global_target_return_1d"]
    market_labels["target_excess_return_5d"] = market_labels["target_return_5d"] - market_labels["global_target_return_5d"]

    sector_labels = pd.concat(sector_rows, ignore_index=True) if sector_rows else pd.DataFrame()
    if not sector_labels.empty:
        enriched_sector = []
        for (_, _), group in sector_labels.groupby(["market", "sector_code"], sort=False):
            group = group.sort_values("trading_date").copy()
            group = pd.concat([group, _forward_stats(group["sector_return"], 5)], axis=1)
            group = pd.concat([group, _forward_stats(group["sector_return"], 20)], axis=1)
            enriched_sector.append(group)
        sector_labels = pd.concat(enriched_sector, ignore_index=True)
        market_targets = market_labels[
            ["trading_date", "market", "target_return_5d"]
        ].rename(columns={"target_return_5d": "market_target_return_5d"})
        sector_labels = sector_labels.merge(market_targets, on=["trading_date", "market"], how="left")
        sector_labels["target_sector_excess_5d"] = (
            sector_labels["target_return_5d"] - sector_labels["market_target_return_5d"]
        )

    calendars = {
        market: pd.DatetimeIndex(group.loc[group["market_return"].notna(), "trading_date"]).sort_values().unique()
        for market, group in market_labels.groupby("market")
    }
    return market_labels, sector_labels, calendars


def coverage_audit(universe: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for market in config.MARKETS:
        u = universe[universe["market"].eq(market)]
        l = labels[labels["market"].eq(market)]
        rows.append(
            {
                "market": market,
                "universe_first_date": u[DATE_COL].min(),
                "universe_last_date": u[DATE_COL].max(),
                "universe_months": int(u[DATE_COL].nunique()),
                "median_constituents": float(u.groupby(DATE_COL)[ID_COL].nunique().median()) if not u.empty else np.nan,
                "proxy_months": int(u.loc[u["universe_is_proxy"], DATE_COL].nunique()),
                "stale_weight_months": int(u.loc[u["universe_is_stale"], DATE_COL].nunique()),
                "label_first_date": l["trading_date"].min(),
                "label_last_date": l["trading_date"].max(),
                "label_days": int(l["trading_date"].nunique()),
                "label_coverage_ge_70pct": float(l["coverage_weight"].ge(0.70).mean()) if not l.empty else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _normalized_label(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    return "".join(character for character in text.casefold() if character.isalnum())


def _company_aliases(value: object) -> list[str]:
    if pd.isna(value):
        return []
    import re

    tokens = re.findall(r"[a-z0-9]+", str(value).casefold())
    full = "".join(tokens)
    suffixes = {
        "ag", "co", "company", "corp", "corporation", "group", "holding", "holdings",
        "inc", "incorporated", "limited", "ltd", "nv", "plc", "sa", "sas", "se", "spa",
    }
    while len(tokens) > 1 and tokens[-1] in suffixes:
        tokens.pop()
    canonical = "".join(tokens)
    return list(dict.fromkeys(alias for alias in (full, canonical) if len(alias) >= 4))


def _country_market(country: object) -> str | None:
    name = "" if pd.isna(country) else str(country).strip().upper()
    if name == "UNITED STATES":
        return "US"
    if name == "JAPAN":
        return "JP"
    if name in {"CHINA", "HONG KONG"}:
        return "CN_HK"
    if name in EU_COUNTRY_NAMES:
        return "EU"
    return None


def audit_existing_news_mapping(
    news_path: Path,
    mapping_path: Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Audit the 13-day local file only as an entity/market/sector mapping source."""

    mapping_path = mapping_path or (config.TP_ROOT / "00_screen" / "factset_icb_mapping.xlsx")
    news = pd.read_parquet(
        news_path,
        columns=["Date", "Title", "Company", "ISIN", "NAME", "SECTOR", "COUNTRY", "COMPANY"],
    )
    mapping = pd.read_excel(mapping_path, sheet_name="Mapping")
    sector_map: dict[str, int] = {}
    for name, code in mapping[["Benchmark ICB Supersector 19", "ICB19_ID"]].dropna().itertuples(index=False):
        sector_map[_normalized_label(name)] = int(code)
    for name, code in mapping[["FactSet Ind", "Transco_ICB_19"]].dropna().itertuples(index=False):
        sector_map[_normalized_label(name)] = int(code)

    result = news.copy()
    result["market"] = result["COUNTRY"].map(_country_market).astype("string")
    result["sector_code"] = result["SECTOR"].map(lambda value: sector_map.get(_normalized_label(value))).astype("Int64")
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result["company_key"] = result["ISIN"].fillna(result["Company"]).astype("string")
    audit = (
        result.groupby(["COUNTRY", "market"], dropna=False)
        .agg(
            rows=("Title", "size"),
            unique_days=("Date", lambda values: values.dt.normalize().nunique()),
            companies=("company_key", "nunique"),
            market_mapped=("market", lambda values: values.notna().mean()),
            sector_mapped=("sector_code", lambda values: values.notna().mean()),
        )
        .reset_index()
    )
    summary = {
        "path": str(news_path),
        "rows": len(result),
        "first_date": str(result["Date"].min()),
        "last_date": str(result["Date"].max()),
        "unique_days": int(result["Date"].dt.normalize().nunique()),
        "duplicate_date_titles": int(result.duplicated(["Date", "Title"]).sum()),
        "market_mapping_coverage": float(result["market"].notna().mean()),
        "sector_mapping_coverage": float(result["sector_code"].notna().mean()),
        "use_as_historical_source": False,
    }
    return audit, summary


def build_entity_sector_history(
    universe: pd.DataFrame,
    screen_path: Path = SCREEN_AGGREGATE_PATH,
) -> pd.DataFrame:
    """Build exact historical aliases from the same point-in-time universe used by labels."""

    names = pd.read_parquet(screen_path, columns=[DATE_COL, ID_COL, "Name"])
    names[DATE_COL] = pd.to_datetime(names[DATE_COL], errors="coerce")
    names[ID_COL] = names[ID_COL].astype("string").str[:6]
    names = names.dropna(subset=[DATE_COL, ID_COL, "Name"]).drop_duplicates([DATE_COL, ID_COL])
    history = universe[[DATE_COL, "market", ID_COL, "sector_code"]].merge(
        names, on=[DATE_COL, ID_COL], how="left"
    )
    history["alias"] = history["Name"].map(_company_aliases)
    history = history.explode("alias")
    history = history[history["alias"].fillna("").str.len().ge(4) & history["sector_code"].notna()].copy()
    ambiguity = history.groupby([DATE_COL, "market", "alias"])["sector_code"].nunique()
    ambiguous_keys = set(ambiguity[ambiguity.gt(1)].index)
    if ambiguous_keys:
        keys = pd.MultiIndex.from_frame(history[[DATE_COL, "market", "alias"]])
        history = history[~keys.isin(ambiguous_keys)].copy()
    return history[
        [DATE_COL, "market", "alias", "Name", ID_COL, "sector_code"]
    ].drop_duplicates([DATE_COL, "market", "alias", ID_COL]).sort_values(
        ["market", "alias", DATE_COL]
    ).reset_index(drop=True)


def news_feature_columns(frame: pd.DataFrame) -> list[str]:
    prefixes = ("topic_", "sentiment_ewm_", "uncertainty_ewm_")
    base = {
        "event_count",
        "source_breadth",
        "importance_sum",
        "novelty_mean",
        "sentiment",
        "local_sentiment",
        "global_sentiment",
        "uncertainty",
        "disagreement",
        "coverage_score",
        "quality_score",
        "news_volume_z",
    }
    return [column for column in frame.columns if column in base or column.startswith(prefixes)]


def walk_forward_ridge(
    daily_state: pd.DataFrame,
    labels: pd.DataFrame,
    targets: Iterable[str] = (
        "target_excess_return_1d",
        "target_excess_return_5d",
        "target_realized_vol_5d",
        "target_drawdown_5d",
    ),
    min_train: int = 252,
    alpha: float = 10.0,
) -> pd.DataFrame:
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    merged = daily_state.merge(labels, on=["trading_date", "market"], how="inner")
    if "ingestion_covered" in merged:
        merged = merged[merged["ingestion_covered"].fillna(False)].copy()
    features = news_feature_columns(merged)
    if not features:
        raise ValueError("daily_state 没有可用新闻特征")
    predictions: list[pd.DataFrame] = []
    for market, market_frame in merged.groupby("market", sort=False):
        market_frame = market_frame.sort_values("trading_date").copy()
        years = sorted(market_frame["trading_date"].dt.year.unique())
        for year in years:
            train = market_frame[market_frame["trading_date"].dt.year.lt(year)]
            test = market_frame[market_frame["trading_date"].dt.year.eq(year)]
            if len(train) < min_train or test.empty:
                continue
            context = ["trading_date", "market", "universe_is_proxy"] + [
                column
                for column in ["event_count", "coverage_score", "source_breadth", "source_era"]
                if column in test
            ]
            base = test[context].copy()
            for target in targets:
                usable = train.dropna(subset=[target])
                if len(usable) < min_train:
                    continue
                model = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=alpha))
                model.fit(usable[features], usable[target])
                base[f"pred_{target}"] = model.predict(test[features])
                base[f"actual_{target}"] = test[target].to_numpy()
                base[f"train_end_{target}"] = usable["trading_date"].max()
                base[f"train_n_{target}"] = len(usable)
            predictions.append(base)
    return pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()


def _safe_corr(left: pd.Series, right: pd.Series, *, rank: bool = False) -> float:
    valid = left.notna() & right.notna()
    if valid.sum() < 2 or left[valid].nunique() < 2 or right[valid].nunique() < 2:
        return np.nan
    x = left[valid].rank() if rank else left[valid]
    y = right[valid].rank() if rank else right[valid]
    return float(x.corr(y))


def evaluate_predictions(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for pred_column in [column for column in predictions.columns if column.startswith("pred_")]:
        target = pred_column.removeprefix("pred_")
        actual_column = f"actual_{target}"
        for market, group in predictions.dropna(subset=[pred_column, actual_column]).groupby("market"):
            pred = group[pred_column]
            actual = group[actual_column]
            is_daily_return = target.endswith("return_1d")
            position = np.sign(pred) if is_daily_return else pd.Series(np.nan, index=group.index)
            turnover = position.diff().abs().fillna(position.abs())
            strategy = position * actual
            if is_daily_return:
                strategy_returns = pd.Series(
                    strategy.to_numpy(),
                    index=pd.to_datetime(group["trading_date"]),
                    name=f"{market}_{target}",
                )
                wealth = calculate_return_series_nav(
                    strategy_returns,
                    initial_nav=1.0,
                    periods_per_year=252,
                    name=f"{market}_{target}",
                ).nav
                drawdown = wealth / wealth.cummax() - 1
                strategy_std = strategy.std(ddof=1)
            else:
                drawdown = pd.Series(np.nan, index=group.index)
                strategy_std = np.nan
            rows.append(
                {
                    "market": market,
                    "target": target,
                    "observations": len(group),
                    "pearson_ic": _safe_corr(pred, actual),
                    "spearman_ic": _safe_corr(pred, actual, rank=True),
                    "direction_hit_rate": float((np.sign(pred) == np.sign(actual)).mean()),
                    "mae": float((pred - actual).abs().mean()),
                    "proxy_observations": int(group["universe_is_proxy"].sum()),
                    "strategy_sharpe": float(strategy.mean() / strategy_std * np.sqrt(252))
                    if is_daily_return and strategy_std > 0
                    else np.nan,
                    "strategy_max_drawdown": float(drawdown.min()) if is_daily_return else np.nan,
                    "average_turnover": float(turnover.mean()) if is_daily_return else np.nan,
                    "net_sharpe_5bps": float(
                        (strategy - turnover * 0.0005).mean()
                        / (strategy - turnover * 0.0005).std(ddof=1)
                        * np.sqrt(252)
                    )
                    if is_daily_return and (strategy - turnover * 0.0005).std(ddof=1) > 0
                    else np.nan,
                    "net_sharpe_10bps": float(
                        (strategy - turnover * 0.001).mean()
                        / (strategy - turnover * 0.001).std(ddof=1)
                        * np.sqrt(252)
                    )
                    if is_daily_return and (strategy - turnover * 0.001).std(ddof=1) > 0
                    else np.nan,
                }
            )
    return pd.DataFrame(rows)


def annual_prediction_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for pred_column in [column for column in predictions if column.startswith("pred_target_excess_return_")]:
        target = pred_column.removeprefix("pred_")
        actual_column = f"actual_{target}"
        usable = predictions.dropna(subset=[pred_column, actual_column]).copy()
        usable["year"] = usable["trading_date"].dt.year
        for (market, year), group in usable.groupby(["market", "year"]):
            rows.append(
                {
                    "market": market,
                    "year": int(year),
                    "target": target,
                    "observations": len(group),
                    "pearson_ic": _safe_corr(group[pred_column], group[actual_column]),
                    "direction_hit_rate": float(
                        (np.sign(group[pred_column]) == np.sign(group[actual_column])).mean()
                    ),
                }
            )
    return pd.DataFrame(rows)


def placebo_metrics(predictions: pd.DataFrame, labels: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    price = labels[["trading_date", "market", "market_return"]].sort_values(["market", "trading_date"]).copy()
    price["price_only_score"] = price.groupby("market")["market_return"].transform(
        lambda values: values.rolling(20, min_periods=10).sum()
    )
    merged = predictions.merge(price, on=["trading_date", "market"], how="left")
    rows = []
    rng = np.random.default_rng(seed)
    for pred_column in [column for column in merged if column.startswith("pred_target_excess_return_")]:
        target = pred_column.removeprefix("pred_")
        actual_column = f"actual_{target}"
        for market, group in merged.sort_values("trading_date").groupby("market"):
            group = group.dropna(subset=[pred_column, actual_column]).copy()
            variants = {
                "news": group[pred_column],
                "news_lag_1d": group[pred_column].shift(1),
                "news_shuffled": pd.Series(rng.permutation(group[pred_column].to_numpy()), index=group.index),
                "price_only": group["price_only_score"],
            }
            for name, score in variants.items():
                valid = score.notna() & group[actual_column].notna()
                rows.append(
                    {
                        "market": market,
                        "target": target,
                        "variant": name,
                        "observations": int(valid.sum()),
                        "pearson_ic": _safe_corr(score[valid], group.loc[valid, actual_column]),
                        "spearman_ic": _safe_corr(
                            score[valid], group.loc[valid, actual_column], rank=True
                        ),
                        "direction_hit_rate": float(
                            (np.sign(score[valid]) == np.sign(group.loc[valid, actual_column])).mean()
                        )
                        if valid.any()
                        else np.nan,
                    }
                )
    return pd.DataFrame(rows)


def _causal_z(values: pd.Series, min_periods: int = 60) -> pd.Series:
    history = values.shift(1)
    mean = history.expanding(min_periods=min_periods).mean()
    std = history.expanding(min_periods=min_periods).std().replace(0, np.nan)
    return ((values - mean) / std).clip(-5, 5)


def build_market_signal_panel(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    frame = predictions.sort_values(["market", "trading_date"]).copy()
    risk_parts = []
    for market, group in frame.groupby("market", sort=False):
        group = group.copy()
        vol = group.get("pred_target_realized_vol_5d", pd.Series(np.nan, index=group.index))
        drawdown = group.get("pred_target_drawdown_5d", pd.Series(np.nan, index=group.index))
        group["risk_score"] = (_causal_z(vol) + _causal_z(-drawdown)) / 2
        history = group["risk_score"].shift(1).expanding(min_periods=252)
        q30 = history.quantile(0.30)
        q70 = history.quantile(0.70)
        q90 = history.quantile(0.90)
        group["risk_state"] = np.select(
            [group["risk_score"].ge(q90), group["risk_score"].ge(q70), group["risk_score"].le(q30)],
            ["crisis", "high_risk", "low_risk"],
            default="normal",
        )
        group.loc[q30.isna(), "risk_state"] = "unknown"
        risk_parts.append(group)
    frame = pd.concat(risk_parts, ignore_index=True)

    panels = []
    for horizon in (1, 5):
        target = f"target_excess_return_{horizon}d"
        pred_column = f"pred_{target}"
        if pred_column not in frame:
            continue
        part = frame.copy()
        part["forecast_bp"] = part[pred_column] * 10_000
        part["position"] = np.sign(part[pred_column]).astype("Int8")
        standardized = part.groupby("market")[pred_column].transform(_causal_z)
        part["signal_strength"] = np.sign(part[pred_column]) * standardized.abs()
        coverage = pd.to_numeric(part.get("coverage_score", 0), errors="coerce").fillna(0).clip(0, 1)
        train_n = pd.to_numeric(part.get(f"train_n_{target}", 0), errors="coerce").fillna(0)
        part["confidence"] = ((0.25 + 0.75 * coverage) * (train_n / 756).clip(0, 1)).clip(0, 1)
        part["signal_scope"] = "market"
        part["sector_code"] = pd.NA
        part["horizon"] = f"{horizon}d"
        part["sector_score"] = np.nan
        part["training_cutoff"] = part.get(f"train_end_{target}")
        part["model_version"] = "news_ridge_expanding_yearly_v1"
        part["actual_return"] = part.get(f"actual_{target}")
        panels.append(
            part[
                [
                    "trading_date",
                    "market",
                    "sector_code",
                    "signal_scope",
                    "horizon",
                    "forecast_bp",
                    "position",
                    "signal_strength",
                    "risk_score",
                    "risk_state",
                    "sector_score",
                    "confidence",
                    "training_cutoff",
                    "model_version",
                    "universe_is_proxy",
                    "actual_return",
                ]
            ]
        )
    return pd.concat(panels, ignore_index=True) if panels else pd.DataFrame()


def build_sector_signal_panel(
    sector_state: pd.DataFrame,
    sector_labels: pd.DataFrame,
    market_state: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if sector_labels.empty:
        return pd.DataFrame()
    keys = ["trading_date", "market", "sector_code"]
    features = ["event_count", "sentiment", "uncertainty", "news_volume_z", "coverage_score"]
    available = keys + [column for column in features if column in sector_state]
    labels = sector_labels
    if market_state is not None and "ingestion_covered" in market_state:
        covered = market_state.loc[
            market_state["ingestion_covered"].fillna(False), ["trading_date", "market"]
        ].drop_duplicates()
        labels = labels.merge(covered, on=["trading_date", "market"], how="inner")
    merged = labels.merge(sector_state[available], on=keys, how="left")
    for column in features:
        if column not in merged:
            merged[column] = 0.0
        merged[column] = pd.to_numeric(merged[column], errors="coerce").fillna(0.0)
    merged = merged.sort_values(["market", "sector_code", "trading_date"]).reset_index(drop=True)
    merged["raw_sector_news"] = (
        merged["sentiment"] + 0.10 * merged["news_volume_z"] - 0.25 * merged["uncertainty"]
    )
    merged["historical_sector_news"] = merged.groupby(["market", "sector_code"])["raw_sector_news"].transform(
        _causal_z
    )
    score_input = merged["historical_sector_news"].fillna(merged["raw_sector_news"])
    score_input = score_input.where(merged["event_count"].gt(0))
    merged["sector_score"] = score_input.groupby([merged["trading_date"], merged["market"]]).rank(
        pct=True, method="average"
    ) * 2 - 1
    merged["confidence"] = (
        merged["coverage_score"].clip(0, 1) * (merged["event_count"] / 3).clip(0, 1)
    )
    merged["training_cutoff"] = merged.groupby(["market", "sector_code"])["trading_date"].shift(1)
    panels = []
    for horizon in (5, 20):
        actual_column = f"target_return_{horizon}d"
        if actual_column not in merged:
            continue
        part = merged.copy()
        part["signal_scope"] = "sector"
        part["horizon"] = f"{horizon}d"
        part["forecast_bp"] = np.nan
        part["position"] = pd.array([pd.NA] * len(part), dtype="Int8")
        part["signal_strength"] = np.nan
        part["risk_score"] = np.nan
        part["risk_state"] = pd.NA
        part["model_version"] = "sector_news_rank_causal_v1"
        part["actual_return"] = part[actual_column]
        panels.append(
            part[
                [
                    "trading_date",
                    "market",
                    "sector_code",
                    "signal_scope",
                    "horizon",
                    "forecast_bp",
                    "position",
                    "signal_strength",
                    "risk_score",
                    "risk_state",
                    "sector_score",
                    "confidence",
                    "training_cutoff",
                    "model_version",
                    "universe_is_proxy",
                    "actual_return",
                ]
            ]
        )
    return pd.concat(panels, ignore_index=True) if panels else pd.DataFrame()


def evaluate_sector_top_worst(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    sector = panel[panel["signal_scope"].eq("sector")].dropna(subset=["sector_score", "actual_return"])
    for (market, horizon, trading_date), group in sector.groupby(["market", "horizon", "trading_date"]):
        if len(group) < 6:
            continue
        ranked = group.sort_values("sector_score")
        worst = ranked.head(3)["actual_return"].mean()
        top = ranked.tail(3)["actual_return"].mean()
        rows.append(
            {
                "trading_date": trading_date,
                "market": market,
                "horizon": horizon,
                "eligible_sectors": len(group),
                "top3_return": top,
                "worst3_return": worst,
                "top_worst_spread": top - worst,
            }
        )
    daily = pd.DataFrame(rows)
    if daily.empty:
        return daily, pd.DataFrame()
    summary = daily.groupby(["market", "horizon"], as_index=False).agg(
        observations=("trading_date", "size"),
        average_top3_return=("top3_return", "mean"),
        average_worst3_return=("worst3_return", "mean"),
        average_top_worst_spread=("top_worst_spread", "mean"),
        positive_spread_rate=("top_worst_spread", lambda values: float(values.gt(0).mean())),
    )
    return daily, summary


def evaluate_risk_states(panel: pd.DataFrame, predictions: pd.DataFrame) -> pd.DataFrame:
    market = panel[(panel["signal_scope"].eq("market")) & (panel["horizon"].eq("5d"))].copy()
    actual = predictions[["trading_date", "market", "actual_target_realized_vol_5d"]]
    market = market.merge(actual, on=["trading_date", "market"], how="left")
    rows = []
    for market_code, group in market.groupby("market"):
        group = group.sort_values("trading_date").copy()
        threshold = group["actual_target_realized_vol_5d"].shift(1).expanding(min_periods=252).quantile(0.90)
        actual_crisis = group["actual_target_realized_vol_5d"].ge(threshold) & threshold.notna()
        predicted_crisis = group["risk_state"].eq("crisis")
        rows.append(
            {
                "market": market_code,
                "eligible_days": int(threshold.notna().sum()),
                "actual_crisis_days": int(actual_crisis.sum()),
                "crisis_recall": float((predicted_crisis & actual_crisis).sum() / actual_crisis.sum())
                if actual_crisis.any()
                else np.nan,
                "crisis_precision": float((predicted_crisis & actual_crisis).sum() / predicted_crisis.sum())
                if predicted_crisis.any()
                else np.nan,
            }
        )
    return pd.DataFrame(rows)


def existing_model_alignment(predictions: pd.DataFrame) -> pd.DataFrame:
    """Prepare a frequency-honest monthly join; it does not claim combined-model alpha."""

    if predictions.empty:
        return pd.DataFrame()
    monthly = predictions.sort_values("trading_date").groupby(
        ["market", predictions["trading_date"].dt.to_period("M")], as_index=False
    ).last()
    monthly["Date"] = monthly["trading_date"].dt.to_period("M").dt.to_timestamp("M")

    country_path = config.TP_ROOT / "14_country_model" / "outputs" / "country_model_panel.parquet"
    if country_path.exists():
        country = pd.read_parquet(country_path)
        country_map = {"US": ["US"], "EU": ["EMU", "UK"], "JP": ["Japan"], "CN_HK": ["EM"]}
        pieces = []
        for market, labels in country_map.items():
            part = country[country["country"].isin(labels)].groupby("Date", as_index=False)["score"].mean()
            part["market"] = market
            part = part.rename(columns={"score": "existing_country_score"})
            pieces.append(part)
        monthly = monthly.merge(pd.concat(pieces, ignore_index=True), on=["Date", "market"], how="left")

    regime_path = config.TP_ROOT / "04_signals" / "regime_risk_budget.parquet"
    if regime_path.exists():
        regime = pd.read_parquet(regime_path)[["Date", "region", "score", "model_version"]]
        regime = regime.rename(
            columns={"region": "market", "score": "existing_regime_score", "model_version": "existing_regime_version"}
        )
        monthly = monthly.merge(regime, on=["Date", "market"], how="left")
    monthly["country_baseline_is_proxy"] = monthly["market"].eq("CN_HK")
    return monthly.sort_values(["Date", "market"]).reset_index(drop=True)


def evaluate_existing_increment(alignment: pd.DataFrame) -> pd.DataFrame:
    if alignment.empty or "existing_country_score" not in alignment:
        return pd.DataFrame()
    rows = []
    for horizon in (1, 5):
        news_column = f"pred_target_excess_return_{horizon}d"
        actual_column = f"actual_target_excess_return_{horizon}d"
        if news_column not in alignment or actual_column not in alignment:
            continue
        for market, group in alignment.groupby("market"):
            common = group.dropna(subset=[news_column, "existing_country_score", actual_column]).sort_values("Date").copy()
            if len(common) < 24:
                continue
            common["news_only"] = _causal_z(common[news_column], min_periods=12)
            common["existing_only"] = _causal_z(common["existing_country_score"], min_periods=12)
            common["existing_plus_news"] = (common["news_only"] + common["existing_only"]) / 2
            for variant in ["news_only", "existing_only", "existing_plus_news"]:
                valid = common.dropna(subset=[variant, actual_column])
                rows.append(
                    {
                        "market": market,
                        "horizon": f"{horizon}d",
                        "variant": variant,
                        "observations": len(valid),
                        "pearson_ic": _safe_corr(valid[variant], valid[actual_column]),
                        "spearman_ic": _safe_corr(valid[variant], valid[actual_column], rank=True),
                        "direction_hit_rate": float(
                            (np.sign(valid[variant]) == np.sign(valid[actual_column])).mean()
                        )
                        if len(valid)
                        else np.nan,
                        "country_baseline_is_proxy": market == "CN_HK",
                        "comparison_frequency": "month_end_future_5d_screening"
                        if horizon == 5
                        else "month_end_future_1d_screening",
                    }
                )
    return pd.DataFrame(rows)


def write_label_outputs(
    universe: pd.DataFrame,
    market_labels: pd.DataFrame,
    sector_labels: pd.DataFrame,
    output_dir: Path = config.OUTPUT_DIR,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "universe_panel": output_dir / "universe_panel.parquet",
        "market_labels": output_dir / "market_labels.parquet",
        "sector_labels": output_dir / "sector_labels.parquet",
        "coverage_audit": output_dir / "coverage_audit.csv",
        "entity_sector_history": config.ENTITY_HISTORY_PATH,
    }
    universe.to_parquet(paths["universe_panel"], index=False)
    market_labels.to_parquet(paths["market_labels"], index=False)
    sector_labels.to_parquet(paths["sector_labels"], index=False)
    coverage_audit(universe, market_labels).to_csv(paths["coverage_audit"], index=False, encoding="utf-8-sig")
    build_entity_sector_history(universe).to_parquet(paths["entity_sector_history"], index=False)
    return {name: str(path) for name, path in paths.items()}


def write_backtest_outputs(
    predictions: pd.DataFrame,
    output_dir: Path,
    *,
    daily_state: pd.DataFrame,
    market_labels: pd.DataFrame,
    sector_state: pd.DataFrame,
    sector_labels: pd.DataFrame,
    compare_existing: bool = True,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=False)
    metrics = evaluate_predictions(predictions)
    annual_metrics = annual_prediction_metrics(predictions)
    placebos = placebo_metrics(predictions, market_labels)
    alignment = existing_model_alignment(predictions) if compare_existing else pd.DataFrame()
    existing_increment = evaluate_existing_increment(alignment)
    market_panel = build_market_signal_panel(predictions)
    sector_panel = build_sector_signal_panel(sector_state, sector_labels, daily_state)
    signal_panel = pd.concat([market_panel, sector_panel], ignore_index=True)
    sector_daily, sector_summary = evaluate_sector_top_worst(signal_panel)
    risk_metrics = evaluate_risk_states(market_panel, predictions)
    paths = {
        "predictions": output_dir / "predictions.parquet",
        "metrics": output_dir / "metrics.csv",
        "annual_metrics": output_dir / "annual_metrics.csv",
        "placebo_metrics": output_dir / "placebo_metrics.csv",
        "news_signal_panel": output_dir / "news_signal_panel.parquet",
        "sector_top_worst_daily": output_dir / "sector_top_worst_daily.parquet",
        "sector_top_worst_summary": output_dir / "sector_top_worst_summary.csv",
        "risk_state_metrics": output_dir / "risk_state_metrics.csv",
        "existing_model_alignment": output_dir / "existing_model_alignment.parquet",
        "existing_increment_comparison": output_dir / "existing_increment_comparison.csv",
        "run_summary": output_dir / "run_summary.json",
    }
    predictions.to_parquet(paths["predictions"], index=False)
    metrics.to_csv(paths["metrics"], index=False, encoding="utf-8-sig")
    annual_metrics.to_csv(paths["annual_metrics"], index=False, encoding="utf-8-sig")
    placebos.to_csv(paths["placebo_metrics"], index=False, encoding="utf-8-sig")
    signal_panel.to_parquet(paths["news_signal_panel"], index=False)
    sector_daily.to_parquet(paths["sector_top_worst_daily"], index=False)
    sector_summary.to_csv(paths["sector_top_worst_summary"], index=False, encoding="utf-8-sig")
    risk_metrics.to_csv(paths["risk_state_metrics"], index=False, encoding="utf-8-sig")
    alignment.to_parquet(paths["existing_model_alignment"], index=False)
    existing_increment.to_csv(paths["existing_increment_comparison"], index=False, encoding="utf-8-sig")
    signal_panel.to_parquet(config.OUTPUT_DIR / "news_signal_panel.parquet", index=False)
    summary = {
        "rows": len(predictions),
        "signal_rows": len(signal_panel),
        "sector_top_worst_days": len(sector_daily),
        "first_date": str(predictions["trading_date"].min().date()) if len(predictions) else None,
        "last_date": str(predictions["trading_date"].max().date()) if len(predictions) else None,
        "markets": sorted(predictions["market"].dropna().unique().tolist()) if len(predictions) else [],
        "evidence_level": "screening_walk_forward",
    }
    paths["run_summary"].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {name: str(path) for name, path in paths.items()}

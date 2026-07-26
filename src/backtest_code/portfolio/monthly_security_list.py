"""Monthly security-list workflow split into explicit construction stages."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import os
from typing import Any

import numpy as np
import pandas as pd

from backtest_code.core.financial_filter import FinancialFilter
from backtest_code.utils.constants import (
    COL_DATE,
    COL_ESG_SCORE,
    COL_ISIN,
    COL_MKT_CAP,
    COL_SECTOR_ICB11,
    COL_SECTOR_ICB19,
)
from backtest_code.utils.data_utils import merge_ticker_secondaire
from tp_core.portfolio_weights import apply_weighting_transform


@dataclass
class MonthlyBuildContext:
    """Inputs shared by the filtering and selection stages."""

    df: pd.DataFrame
    date: pd.Timestamp
    metrics: list[str]
    security_count: int
    sector_targets: pd.Series
    benchmark_exclusions: list[Any]
    market_cap_exclusions: list[Any]


@dataclass
class FilteredUniverse:
    """Eligible universe plus a normalized exclusion ledger."""

    df: pd.DataFrame
    exclusions: pd.DataFrame
    default_date: pd.Timestamp


def _source_screen(builder: Any, monthly_screen: pd.DataFrame | None) -> pd.DataFrame:
    if isinstance(monthly_screen, pd.DataFrame):
        return monthly_screen
    return builder.screen[builder.screen[COL_DATE] == builder.screen[COL_DATE].max()]


def _metric_columns(builder: Any) -> list[str]:
    return [builder.metrics] if isinstance(builder.metrics, str) else list(builder.metrics)


def _factor_recommendation(builder: Any, date: pd.Timestamp) -> np.ndarray:
    if isinstance(builder.reco_facto, list):
        recommendation = np.array(builder.reco_facto)
    elif isinstance(builder.reco_facto, pd.DataFrame):
        try:
            recommendation = np.array(builder.reco_facto.loc[date])
        except KeyError:
            raise KeyError(f"{date} not in reco_facto") from None
    else:
        recommendation = np.array([0.2] * 5)
    if recommendation.sum() == 0:
        return np.array([0.2] * 5)
    return recommendation / recommendation.sum()


def _sector_recommendation(builder: Any, date: pd.Timestamp) -> list[float]:
    if isinstance(builder.reco_secto, list):
        return copy.deepcopy(builder.reco_secto)
    if isinstance(builder.reco_secto, pd.DataFrame):
        try:
            return builder.reco_secto.loc[date].tolist()
        except KeyError:
            raise KeyError(f"{date} not in reco_secto") from None
    return []


def _restore_cached_base(
    builder: Any,
    cached: dict[str, Any],
    source_screen: pd.DataFrame,
    metrics: list[str],
) -> MonthlyBuildContext:
    df = cached["df"].copy(deep=True)
    score_values = builder._score_source_for_cache(source_screen, metrics, df.index)
    df.loc[:, metrics] = score_values.to_numpy()
    df.loc[~cached["eligible_market_cap"], metrics] = np.nan
    return MonthlyBuildContext(
        df=df,
        date=cached["date"],
        metrics=metrics,
        security_count=cached["nb_securities"],
        sector_targets=cached["weight_secto_bench"],
        benchmark_exclusions=list(cached["list_exclusion_bench"]),
        market_cap_exclusions=list(cached["list_exclusion_market_cut"]),
    )


def _cache_base(
    builder: Any,
    cache_key: Any,
    context: MonthlyBuildContext,
    eligible_market_cap: np.ndarray,
) -> None:
    if cache_key is None:
        return
    technical_columns = [
        COL_DATE,
        COL_MKT_CAP,
        COL_SECTOR_ICB11,
        COL_SECTOR_ICB19,
        COL_ESG_SCORE,
        f"Weight in {builder.bench}",
    ]
    compact_base = context.df.loc[
        :, [column for column in technical_columns if column in context.df.columns]
    ].copy(deep=True)
    if isinstance(compact_base.index, pd.CategoricalIndex):
        compact_base.index = pd.Index(
            compact_base.index.astype(object),
            name=compact_base.index.name,
        )
    builder.monthly_base_cache[cache_key] = {
        "df": compact_base,
        "date": context.date,
        "nb_securities": context.security_count,
        "weight_secto_bench": context.sector_targets.copy(),
        "eligible_market_cap": eligible_market_cap.copy(),
        "list_exclusion_bench": tuple(context.benchmark_exclusions),
        "list_exclusion_market_cut": tuple(context.market_cap_exclusions),
    }


def prepare_monthly_base(
    builder: Any,
    monthly_screen: pd.DataFrame | None,
) -> MonthlyBuildContext:
    """Prepare benchmark universe, scores, market-cap eligibility and targets."""

    source_screen = _source_screen(builder, monthly_screen)
    metrics = _metric_columns(builder)
    raw_date = pd.to_datetime(source_screen[COL_DATE].max())
    cache_key = builder._monthly_base_cache_key(raw_date)
    cached = builder.monthly_base_cache.get(cache_key) if cache_key is not None else None
    if cached is not None:
        return _restore_cached_base(builder, cached, source_screen, metrics)

    screen = copy.deepcopy(source_screen)
    if screen.index.duplicated().any():
        screen = screen[~screen.index.duplicated(keep="first")]
    screen = merge_ticker_secondaire(screen, builder.bench)
    df = screen[screen[f"Weight in {builder.bench}"] > 0]
    benchmark_exclusions = screen.loc[~screen.index.isin(df.index)].index.tolist()
    security_count = (
        builder.percentile
        if builder.percentile > 1
        else round(len(df) * builder.percentile)
    )
    date = raw_date + pd.offsets.MonthBegin(1)

    if builder.metrics == "Multi Avg Percentile":
        style_columns = [
            "Growth Avg Percentile",
            "LowVol Avg Percentile",
            "Mom Avg Percentile",
            "Quality Avg Percentile",
            "Value Avg Percentile",
        ]
        df.loc[:, "Multi Avg Percentile"] = df[style_columns].dot(
            _factor_recommendation(builder, date)
        )

    df = builder._prepare_market_cap_for_weighting(df)
    eligible_market_cap = (df[COL_MKT_CAP] > builder.cut_mkt_cap).to_numpy()
    df.loc[~eligible_market_cap, metrics] = np.nan
    market_cap_exclusions = df.loc[~eligible_market_cap].index.tolist()
    df = df.copy()
    df.loc[:, COL_DATE] = date
    df = apply_weighting_transform(df, builder.ponderation, COL_MKT_CAP)
    sector_targets = builder.adjust_bench_weight_with_recommandation(
        df,
        _sector_recommendation(builder, date),
        date,
    )
    context = MonthlyBuildContext(
        df=df,
        date=date,
        metrics=metrics,
        security_count=security_count,
        sector_targets=sector_targets,
        benchmark_exclusions=benchmark_exclusions,
        market_cap_exclusions=market_cap_exclusions,
    )
    _cache_base(builder, cache_key, context, eligible_market_cap)
    return context


def _append_exclusions(
    exclusions: pd.DataFrame,
    identifiers: list[Any],
    date: pd.Timestamp,
    reason: str,
) -> pd.DataFrame:
    entries = pd.DataFrame(
        {
            COL_DATE: [date] * len(identifiers),
            "Raison Exclusion": [reason] * len(identifiers),
        },
        index=identifiers,
    )
    return pd.concat([exclusions, entries], axis=0)


def filter_monthly_universe(builder: Any, context: MonthlyBuildContext) -> FilteredUniverse:
    """Apply financial, ESG and blacklist filters and record every exclusion."""

    df = context.df
    exclusions = pd.DataFrame(columns=[COL_DATE, "Raison Exclusion"])
    if builder.financial_filter_config is not None:
        financial_filter = FinancialFilter(builder.screen, builder.bench, COL_SECTOR_ICB19)
        df, financial_excluded = financial_filter.apply_filters(
            df,
            builder.financial_filter_config,
        )
        if not financial_excluded.empty:
            exclusions = pd.concat([exclusions, financial_excluded], axis=0)
    if builder.Top:
        df, exclusions = builder.filtrage_esg_liste_noire(df, context.date)

    default_date = exclusions[COL_DATE].iloc[0] if not exclusions.empty else context.date
    exclusions = _append_exclusions(
        exclusions,
        context.market_cap_exclusions,
        default_date,
        "Cut Market",
    )
    exclusions = _append_exclusions(
        exclusions,
        context.benchmark_exclusions,
        default_date,
        "Not in Bench",
    )
    df = builder.neutralise_score_by_secteur(df, context.metrics)
    df["Raison Repechage"] = ""
    return FilteredUniverse(df=df, exclusions=exclusions, default_date=default_date)


def _sector_column(builder: Any) -> str:
    return COL_SECTOR_ICB11 if builder.weight_neutral == "ICB 11" else COL_SECTOR_ICB19


def _portfolio_frame(
    builder: Any,
    selected: pd.DataFrame,
    context: MonthlyBuildContext,
    *,
    score_column: str | None,
    portfolio_name: str,
    validate_sectors: bool,
) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            COL_ISIN: selected.index,
            "Secto": selected[_sector_column(builder)].values,
            "Weight": selected[COL_MKT_CAP].values,
            "Score": (
                selected[score_column].values
                if score_column is not None
                else np.zeros(len(selected))
            ),
            COL_DATE: selected[COL_DATE].values,
            "Raison Repechage": selected["Raison Repechage"].values,
        }
    )
    if validate_sectors:
        selected_sectors = set(frame["Secto"].unique())
        benchmark_sectors = set(context.sector_targets.index)
        if not selected_sectors.issubset(benchmark_sectors):
            missing = selected_sectors.difference(benchmark_sectors)
            raise ValueError(f"Error: Sectors {missing} not defined in weight_secto_bench")
    frame = builder._apply_security_weight_constraints(frame, context.sector_targets)
    frame["PTF"] = portfolio_name
    return frame[["PTF", COL_ISIN, "Weight", COL_DATE, "Raison Repechage", "Secto", "Score"]]


def build_financial_only_portfolio(
    builder: Any,
    universe: FilteredUniverse,
    context: MonthlyBuildContext,
) -> pd.DataFrame:
    selected = universe.df.copy()
    selected["Raison Repechage"] = "Financial Filter"
    return _portfolio_frame(
        builder,
        selected,
        context,
        score_column=None,
        portfolio_name=builder.ptf_name,
        validate_sectors=False,
    )


def _add_sector_threshold_holdings(
    builder: Any,
    universe: pd.DataFrame,
    selected: pd.DataFrame,
    metric: str,
) -> pd.DataFrame:
    if builder.cap_weight_threshold is None:
        return selected
    sector_selected = universe.groupby(COL_SECTOR_ICB19).apply(
        builder.select_titles,
        max_weight_threshold=builder.cap_weight_threshold,
        column=metric,
    )
    sector_selected = sector_selected.drop(columns=[COL_SECTOR_ICB19]).reset_index(drop=False)
    sector_selected.index = sector_selected[COL_ISIN]
    sector_selected = sector_selected.drop(columns=[COL_ISIN])
    sector_selected["Raison Repechage"] = "Sector"
    return pd.concat([selected, sector_selected])[lambda frame: ~frame.index.duplicated(keep="first")]


def _add_top_mandatory_holdings(
    builder: Any,
    universe: pd.DataFrame,
    selected: pd.DataFrame,
) -> pd.DataFrame:
    if not isinstance(builder.top_mandatory, (int, float)):
        return selected
    mandatory = universe.nlargest(int(builder.top_mandatory), f"Weight in {builder.bench}")
    mandatory["Raison Repechage"] = "Top Obligatoire par Région"
    combined = pd.concat([mandatory, selected], axis=0)
    return combined[~combined.index.duplicated(keep="first")]


def _add_missing_sector_holdings(
    builder: Any,
    universe: pd.DataFrame,
    selected: pd.DataFrame,
    context: MonthlyBuildContext,
    metric: str,
) -> pd.DataFrame:
    if builder.weight_neutral not in {"ICB 19", "ICB 11"}:
        return selected
    sector_column = _sector_column(builder)
    required = {sector for sector, target in context.sector_targets.items() if target > 0}
    present = set(selected[sector_column].dropna().tolist())
    additions: list[pd.DataFrame] = []
    for missing_sector in required - present:
        candidates = universe[universe[sector_column] == missing_sector]
        if candidates.empty:
            continue
        addition = (
            candidates.nlargest(1, metric)
            if builder.Top
            else candidates.nsmallest(1, metric)
        ).copy()
        addition["Raison Repechage"] = "Sector neutrality"
        additions.append(addition)
    if not additions:
        return selected
    combined = pd.concat([selected, *additions])
    return combined[~combined.index.duplicated(keep="first")]


def _select_for_metric(
    builder: Any,
    universe: pd.DataFrame,
    context: MonthlyBuildContext,
    metric: str,
) -> pd.DataFrame:
    if builder.Top:
        selected = universe.nlargest(context.security_count, metric)
        selected["Raison Repechage"] = metric
        selected = _add_sector_threshold_holdings(builder, universe, selected, metric)
    else:
        selected = universe.nsmallest(context.security_count, metric)
        selected["Raison Repechage"] = "Worst Metric"
    selected = _add_top_mandatory_holdings(builder, universe, selected)
    return _add_missing_sector_holdings(builder, universe, selected, context, metric)


def _record_metric_exclusions(
    exclusions: pd.DataFrame,
    universe: pd.DataFrame,
    selected: pd.DataFrame,
    default_date: pd.Timestamp,
    metric: str,
) -> pd.DataFrame:
    identifiers = universe.loc[~universe.index.isin(selected.index)].index.tolist()
    entries = pd.DataFrame(
        {
            COL_DATE: [default_date] * len(identifiers),
            "Raison Exclusion": [f"Bad {metric}"] * len(identifiers),
        },
        index=identifiers,
    )
    if COL_ISIN in exclusions.columns:
        exclusions = exclusions.set_index(COL_ISIN)
    combined = entries.copy() if exclusions.empty else pd.concat([exclusions, entries], axis=0)
    combined.index.name = COL_ISIN
    return combined.reset_index()


def build_ranked_portfolios(
    builder: Any,
    universe: FilteredUniverse,
    context: MonthlyBuildContext,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    portfolios: list[pd.DataFrame] = []
    exclusions = universe.exclusions
    for metric in context.metrics:
        selected = _select_for_metric(builder, universe.df, context, metric)
        if builder.Top:
            exclusions = _record_metric_exclusions(
                exclusions,
                universe.df,
                selected,
                universe.default_date,
                metric,
            )
        portfolios.append(
            _portfolio_frame(
                builder,
                selected,
                context,
                score_column=metric,
                portfolio_name=builder.get_portfolio_name(metric),
                validate_sectors=True,
            )
        )
    result = pd.concat(portfolios, ignore_index=True) if portfolios else pd.DataFrame()
    return result, exclusions


def _save_result(builder: Any, result: pd.DataFrame) -> None:
    if builder.output_dir is None:
        return
    if builder.mode_monthly_prod:
        builder.save_portfolio_data_incremental(result, builder.output_dir)
        return
    result.to_excel(os.path.join(builder.output_dir, "sec_list_result.xlsx"))


def build_monthly_security_list(
    builder: Any,
    monthly_screen: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Execute the monthly workflow while keeping the façade's public contract."""

    context = prepare_monthly_base(builder, monthly_screen)
    universe = filter_monthly_universe(builder, context)
    if builder.use_factor_ranking:
        result, exclusions = build_ranked_portfolios(builder, universe, context)
    else:
        result = build_financial_only_portfolio(builder, universe, context)
        exclusions = universe.exclusions
    _save_result(builder, result)
    builder.sec_list_monthly = result.copy(deep=True)
    builder.list_exclusion_monthly = exclusions.copy(deep=True)
    return result, exclusions

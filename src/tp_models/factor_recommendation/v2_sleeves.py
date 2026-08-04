"""v2 official factor-sleeve database.

The v2 research unit is a monthly factor sleeve, not a security forecast.  This
module is intentionally small at the public boundary: it loads canonical data,
constructs Top/Worst portfolios through the official TP backtest facade, and
returns auditable monthly rows plus minimal holdings.  It does not write to a
production signal path.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from tp_backtest.runner.input_loader import load_pruned_backtest_inputs
from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH


V2_FACTOR_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "value",
        "label": "Value",
        "source_columns": ("Value Avg Percentile",),
        "direction": 1,
        "family": "value",
        "definition": "Higher percentile indicates cheaper valuation relative to the canonical cross-section.",
    },
    {
        "name": "quality",
        "label": "Quality",
        "source_columns": ("Quality Avg Percentile",),
        "direction": 1,
        "family": "quality",
        "definition": "Higher percentile indicates stronger canonical profitability, balance-sheet and earnings-quality characteristics.",
    },
    {
        "name": "growth",
        "label": "Growth",
        "source_columns": ("Growth Avg Percentile",),
        "direction": 1,
        "family": "growth",
        "definition": "Higher percentile indicates stronger canonical fundamental growth characteristics.",
    },
    {
        "name": "momentum",
        "label": "Momentum",
        "source_columns": ("Mom Avg Percentile",),
        "direction": 1,
        "family": "momentum",
        "definition": "Higher percentile indicates stronger canonical price-momentum characteristics.",
    },
    {
        "name": "lowvol",
        "label": "Low Volatility",
        "source_columns": ("LowVol Avg Percentile",),
        "direction": 1,
        "family": "lowvol",
        "definition": "Higher percentile indicates lower realized or canonical volatility characteristics.",
    },
    {
        "name": "size",
        "label": "Large Size",
        "source_columns": ("Size Avg Percentile",),
        "direction": 1,
        "family": "size",
        "definition": "Higher percentile indicates larger market-cap exposure; it is not a small-cap signal.",
    },
    {
        "name": "small_size",
        "label": "Small Size",
        "source_columns": ("Size Avg Percentile",),
        "direction": -1,
        "family": "size",
        "definition": "The explicit inverse of Size: small_size = 100 - Size percentile.",
    },
    {
        "name": "dividend",
        "label": "Dividend",
        "source_columns": ("Dividend Avg Percentile",),
        "direction": 1,
        "family": "dividend",
        "definition": "Higher percentile indicates stronger canonical dividend characteristics.",
    },
)


V2_COMPONENTS: tuple[dict[str, Any], ...] = (
    {
        "region": "US",
        "region_component": "US",
        "benchmark": "SP500",
        "weight_column": "Weight in SP500",
        "currency": "USD",
        "minimum_monthly_constituents": 50,
    },
    {
        "region": "EUROPE",
        "region_component": "EUROPE",
        "benchmark": "STOXX EUROPE 600",
        "weight_column": "Weight in STOXX EUROPE 600",
        "currency": "EUR",
        "minimum_monthly_constituents": 100,
    },
    {
        "region": "JAPAN",
        "region_component": "JAPAN",
        "benchmark": "NIKKEI",
        "weight_column": "Weight in NIKKEI",
        "currency": "JPY",
        "country_allowlist": ("JP",),
        "country_column": "Exchange Country Iso2",
        "minimum_monthly_constituents": 20,
    },
    {
        "region": "GLOBAL",
        "region_component": "GLOBAL",
        "benchmark": "MSCI WORLD",
        "weight_column": "Weight in MSCI WORLD",
        "currency": "USD",
        "minimum_monthly_constituents": 250,
    },
    {
        "region": "ASIA_EX_JAPAN",
        "region_component": "ASIA_EX_JAPAN",
        "benchmark": "MSCI EM",
        "weight_column": "Weight in MSCI EM",
        "currency": "component_local_currency",
        "country_column": "Exchange Country Iso2",
        "country_allowlist": ("CN", "HK", "IN", "KR", "TW", "SG", "MY", "TH", "ID", "PH"),
        "exclude_countries": ("JP",),
        "minimum_monthly_constituents": 50,
    },
)


@dataclass(frozen=True)
class SleeveRunSpec:
    region: str
    region_component: str
    benchmark: str
    factor: str
    sleeve_side: str
    sleeve_percentile: float = 0.2
    internal_cost_bps: float = 15.0
    max_weight: float = 1.0
    engine_id: str = "tp.security_nav"
    engine_version: str = "3.0.0"

    @property
    def sleeve_version(self) -> str:
        return f"v2-p{int(round(self.sleeve_percentile * 100)):02d}"


def factor_definition_frame() -> pd.DataFrame:
    """Return the frozen factor definitions for reports and UI help text."""

    return pd.DataFrame(
        [
            {
                "factor": item["name"],
                "label": item["label"],
                "source_columns": ", ".join(item["source_columns"]),
                "direction": item["direction"],
                "family": item["family"],
                "definition": item["definition"],
            }
            for item in V2_FACTOR_DEFINITIONS
        ]
    )


def factor_definition_map() -> dict[str, dict[str, Any]]:
    return {str(item["name"]): dict(item) for item in V2_FACTOR_DEFINITIONS}


def component_map() -> dict[str, dict[str, Any]]:
    return {str(item["region_component"]): dict(item) for item in V2_COMPONENTS}


def _as_datetime(value: Any) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is not None:
        parsed = parsed.tz_localize(None)
    return parsed.normalize()


def _month_end(value: Any) -> pd.Timestamp:
    return _as_datetime(value) + pd.offsets.MonthEnd(0)


def _component_screen(screen: pd.DataFrame, component: Mapping[str, Any]) -> pd.DataFrame:
    out = screen.copy()
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce").dt.normalize()
    out = out.dropna(subset=["Date"])
    weight_column = str(component["weight_column"])
    if weight_column not in out.columns:
        raise KeyError(f"official sleeve input is missing {weight_column!r}")
    mask = pd.to_numeric(out[weight_column], errors="coerce").gt(0)
    country_column = component.get("country_column")
    countries = out[country_column].astype("string") if country_column and country_column in out.columns else None
    allowlist = tuple(component.get("country_allowlist") or ())
    if allowlist:
        if countries is None:
            raise KeyError(f"{component['region_component']} requires {country_column!r}")
        mask &= countries.isin(allowlist)
    excludes = tuple(component.get("exclude_countries") or ())
    if excludes and countries is not None:
        mask &= ~countries.isin(excludes)
    out = out.loc[mask].copy()
    if out.empty:
        raise ValueError(f"no PIT members for {component['region_component']}")
    return out


def _factor_column(factor: str) -> str:
    definition = factor_definition_map().get(str(factor))
    if not definition:
        raise KeyError(f"unknown v2 factor: {factor}")
    return str(definition["source_columns"][0])


def _factor_engine_top(factor: str, sleeve_side: str) -> bool:
    top_factor = factor != "small_size"
    return top_factor if sleeve_side == "Top" else not top_factor


def _compound(values: pd.Series) -> float:
    if values is None or values.empty:
        return float("nan")
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return float("nan")
    return float((1.0 + numeric).prod() - 1.0)


def _result_daily_series(result: Any, name: str) -> pd.Series:
    value = getattr(result, name, None)
    if value is None:
        value = getattr(result, "daily_returns", None)
    if value is None:
        raise RuntimeError(f"official engine result has no {name} or daily_returns")
    series = pd.Series(value).copy()
    series.index = pd.to_datetime(series.index).normalize()
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def _result_nav(result: Any, name: str) -> pd.Series:
    value = getattr(result, name, None)
    if value is None:
        value = getattr(result, "nav", None)
    series = pd.Series(value).copy()
    series.index = pd.to_datetime(series.index).normalize()
    return pd.to_numeric(series, errors="coerce")


def _stable_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _period_rows(
    *,
    spec: SleeveRunSpec,
    screen: pd.DataFrame,
    portfolio_result: Any,
    benchmark_result: Any,
    max_months: int | None = None,
) -> pd.DataFrame:
    """Translate daily official results into formation-date labelled monthly rows."""

    dates = sorted(pd.Timestamp(value) for value in screen["Date"].dropna().unique())
    if len(dates) < 2:
        return pd.DataFrame()
    if max_months is not None:
        dates = dates[: max(2, int(max_months) + 1)]
    portfolio_gross = _result_daily_series(portfolio_result, "gross_daily_returns")
    benchmark_daily = _result_daily_series(benchmark_result, "gross_daily_returns")
    net_nav = _result_nav(portfolio_result, "net_nav")
    gross_nav = _result_nav(portfolio_result, "gross_nav")
    benchmark_nav = _result_nav(benchmark_result, "gross_nav")
    turnover = getattr(portfolio_result, "turnover", pd.Series(dtype=float))
    turnover = pd.Series(turnover)
    turnover.index = pd.to_datetime(turnover.index).normalize() if len(turnover) else turnover.index
    turnover_daily = turnover.reindex(portfolio_gross.index, fill_value=0.0)
    explicit_net = getattr(portfolio_result, "net_daily_returns", None)
    if explicit_net is not None:
        portfolio_net = _result_daily_series(portfolio_result, "net_daily_returns")
    else:
        cost_rate = float(spec.internal_cost_bps) / 10_000.0
        portfolio_net = (portfolio_gross - turnover.reindex(portfolio_gross.index, fill_value=0.0) * cost_rate).rename("net_daily_return")
    rows: list[dict[str, Any]] = []
    component_weight = str(component_map()[spec.region_component]["weight_column"])
    factor_column = _factor_column(spec.factor)
    for index, formation_date in enumerate(dates[:-1]):
        next_date = dates[index + 1]
        days = (portfolio_net.index > formation_date) & (portfolio_net.index <= next_date)
        if not bool(days.any()):
            continue
        gross_return = _compound(portfolio_gross.loc[days])
        net_return = _compound(portfolio_net.loc[days])
        benchmark_return = _compound(benchmark_daily.reindex(portfolio_net.index).fillna(0.0).loc[days])
        component_at_date = screen.loc[screen["Date"].eq(formation_date)]
        score_values = pd.to_numeric(component_at_date.get(factor_column), errors="coerce")
        score_values = score_values.dropna()
        benchmark_values = pd.to_numeric(component_at_date.get(component_weight), errors="coerce")
        benchmark_coverage = float(benchmark_values.notna().mean()) if len(component_at_date) else 0.0
        target_date = formation_date + pd.offsets.MonthBegin(1)
        target_holdings = getattr(portfolio_result, "execution_weights", pd.DataFrame())
        holdings_count = 0
        if isinstance(target_holdings, pd.DataFrame) and not target_holdings.empty:
            try:
                target_frame = target_holdings.reset_index()
                target_frame["Date"] = pd.to_datetime(target_frame["Date"], errors="coerce").dt.normalize()
                holdings_count = int(target_frame.loc[target_frame["Date"].eq(target_date)].shape[0])
            except (KeyError, TypeError, ValueError):
                holdings_count = 0
        if holdings_count == 0:
            holdings_count = max(1, int(round(len(component_at_date) * spec.sleeve_percentile)))
        factor_coverage = float(score_values.notna().mean()) if len(component_at_date) else 0.0
        minimum_constituents = int(component_map()[spec.region_component].get("minimum_monthly_constituents", 1))
        turnover_value = float(turnover_daily.loc[days].sum()) if len(turnover_daily) else float("nan")
        fingerprint = _stable_fingerprint(
            {
                "formation_date": str(formation_date.date()),
                "target_date": str(next_date.date()),
                "spec": spec.__dict__,
                "factor_column": factor_column,
                "component_weight": component_weight,
            }
        )
        rows.append(
            {
                "Date": formation_date,
                "feature_as_of_date": formation_date,
                "effective_start_date": portfolio_net.index[days].min(),
                "effective_end_date": portfolio_net.index[days].max(),
                "target_date": next_date,
                "region": spec.region,
                "region_component": spec.region_component,
                "benchmark": spec.benchmark,
                "factor": spec.factor,
                "factor_source_column": factor_column,
                "sleeve_side": spec.sleeve_side,
                "sleeve_version": spec.sleeve_version,
                "gross_return": gross_return,
                "internal_cost": gross_return - net_return if np.isfinite(gross_return) and np.isfinite(net_return) else np.nan,
                "net_return": net_return,
                "benchmark_return": benchmark_return,
                "active_return": net_return - benchmark_return if np.isfinite(net_return) and np.isfinite(benchmark_return) else np.nan,
                "spread": np.nan,
                "turnover": turnover_value,
                "holdings_count": holdings_count,
                "formation_available": bool(holdings_count >= minimum_constituents and factor_coverage > 0),
                "coverage": factor_coverage,
                "factor_coverage": factor_coverage,
                "weight_coverage": benchmark_coverage,
                "benchmark_weight_coverage": benchmark_coverage,
                "benchmark_coverage": benchmark_coverage,
                "minimum_constituents": minimum_constituents,
                "factor_score": float(score_values.mean()) if not score_values.empty else np.nan,
                "universe_count": int(len(component_at_date)),
                "engine_id": str(getattr(portfolio_result, "manifest", {}).get("engine_id", spec.engine_id)),
                "engine_version": str(getattr(portfolio_result, "manifest", {}).get("engine_version", spec.engine_version)),
                "execution_policy": "strictly_after_rebalance; apply_weights_at_close",
                "gross_nav": float(gross_nav.loc[gross_nav.index <= next_date].iloc[-1]) if not gross_nav.loc[gross_nav.index <= next_date].empty else np.nan,
                "net_nav": float(net_nav.loc[net_nav.index <= next_date].iloc[-1]) if not net_nav.loc[net_nav.index <= next_date].empty else np.nan,
                "benchmark_nav": float(benchmark_nav.loc[benchmark_nav.index <= next_date].iloc[-1]) if not benchmark_nav.loc[benchmark_nav.index <= next_date].empty else np.nan,
                "fingerprint": fingerprint,
            }
        )
    return pd.DataFrame(rows)


def _holdings_frame(
    *,
    spec: SleeveRunSpec,
    builder: Any,
    screen: pd.DataFrame,
) -> pd.DataFrame:
    source = getattr(builder, "sec_list_historical", None)
    if source is None or not isinstance(source, pd.DataFrame) or source.empty:
        return pd.DataFrame()
    frame = source.reset_index() if source.index.name or not isinstance(source.index, pd.RangeIndex) else source.copy()
    frame = frame.copy()
    date_column = "Date" if "Date" in frame.columns else None
    if date_column is None:
        return pd.DataFrame()
    frame["target_date"] = pd.to_datetime(frame[date_column], errors="coerce").dt.normalize()
    frame["formation_date"] = frame["target_date"] - pd.offsets.MonthBegin(1) + pd.offsets.MonthEnd(0)
    id_column = next((column for column in ("Company SEDOL", "ISIN", "index") if column in frame.columns), None)
    weight_column = next((column for column in ("Weight", "Portfolio weight", "weight") if column in frame.columns), None)
    if id_column is None or weight_column is None:
        return pd.DataFrame()
    return pd.DataFrame(
        {
            "formation_date": frame["formation_date"],
            "target_date": frame["target_date"],
            "region": spec.region,
            "region_component": spec.region_component,
            "benchmark": spec.benchmark,
            "factor": spec.factor,
            "sleeve_side": spec.sleeve_side,
            "sleeve_version": spec.sleeve_version,
            "security_id": frame[id_column].astype(str),
            "weight": pd.to_numeric(frame[weight_column], errors="coerce"),
            "fingerprint": _stable_fingerprint({"spec": spec.__dict__, "source": "sec_list_historical"}),
        }
    )


def run_official_factor_sleeve(
    *,
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    spec: SleeveRunSpec,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    max_months: int | None = None,
    benchmark_cache: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Run one official Top/Worst sleeve and return monthly evidence."""

    # Keep this import at the official research boundary.  Do not replace it
    # with a local ranking implementation: v2 evidence must be engine-backed.
    from tp_core.backtesting import OfficialPortfolioBacktest, nav_engine_metadata

    component = component_map()[spec.region_component]
    scoped = _component_screen(screen, component)
    scoped["Date"] = pd.to_datetime(scoped["Date"], errors="coerce").dt.normalize()
    scoped = scoped.loc[scoped["Date"].between(_as_datetime(start_date), _as_datetime(end_date))].copy()
    if scoped.empty:
        raise ValueError(f"empty scoped screen for {spec.region_component}")
    sedols = scoped["Company SEDOL"].astype(str).dropna().unique()
    scoped_returns = returns.loc[:, returns.columns.astype(str).isin(set(sedols))].copy()
    if scoped_returns.empty:
        raise ValueError(f"empty returns for {spec.region_component}")
    engine_top = _factor_engine_top(spec.factor, spec.sleeve_side)
    # The official NAV result supplies exact holdings/execution turnover.  We
    # charge the frozen sleeve cost once in the monthly translator; using the
    # fast official NAV avoids a second portfolio simulator while preserving
    # the official weight/execution boundary.
    execution_config = {
        "mode": "fast_nav",
        "commission_bps": 0.0,
        "slippage_bps": 0.0,
    }
    builder = OfficialPortfolioBacktest(
        screen=scoped,
        returns=scoped_returns,
        bench=spec.benchmark,
        percentile=spec.sleeve_percentile,
        metrics=_factor_column(spec.factor),
        ptf_name=f"v2_{spec.region_component}_{spec.factor}_{spec.sleeve_side}",
        ponderation="Market cap",
        Top=engine_top,
        copy_inputs=False,
        multiprocessing=False,
        execution_config=execution_config,
    )
    builder.build_historical_security_lists(
        start_date=_as_datetime(start_date),
        freq_rebal=None,
        screen_start_date=None,
        fill_method="drift",
    )
    builder.run_portfolio_nav(max_weight=spec.max_weight, sector_neutral=False)
    portfolio_result = builder.last_result
    if portfolio_result is None:
        raise RuntimeError("official portfolio NAV result is missing")
    cache_key = spec.region_component
    benchmark_result = benchmark_cache.get(cache_key) if benchmark_cache is not None else None
    if benchmark_result is None:
        builder.run_benchmark_nav(builder.screen, builder.start_date, spec.benchmark)
        benchmark_result = builder.last_benchmark_result
        if benchmark_cache is not None and benchmark_result is not None:
            benchmark_cache[cache_key] = benchmark_result
    if benchmark_result is None:
        raise RuntimeError("official benchmark NAV result is missing")
    monthly = _period_rows(
        spec=spec,
        screen=scoped,
        portfolio_result=portfolio_result,
        benchmark_result=benchmark_result,
        max_months=max_months,
    )
    holdings = _holdings_frame(spec=spec, builder=builder, screen=scoped)
    metadata = {
        "spec": spec.__dict__,
        "engine": nav_engine_metadata(strictly_after_rebalance=True, apply_weights_at_close=True),
        "official_import": "tp_core.backtesting.OfficialPortfolioBacktest",
        "fill_method": "drift",
        "execution_config": execution_config,
        "internal_cost_method": "official_turnover * frozen_sleeve_internal_cost_bps; charged once after official gross NAV",
        "screen_rows": int(len(scoped)),
        "return_columns": int(scoped_returns.shape[1]),
        "monthly_rows": int(len(monthly)),
        "holdings_rows": int(len(holdings)),
    }
    return monthly, holdings, metadata


def load_official_inputs(
    *,
    screen_path: str | Path = SCREEN_AGGREGATE_PATH,
    returns_path: str | Path = RETURNS_PATH,
    start_date: str | pd.Timestamp = "2013-12-31",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the minimum canonical columns needed by all v2 official sleeves."""

    metrics = [_factor_column(item["name"]) for item in V2_FACTOR_DEFINITIONS]
    benchmarks = list(dict.fromkeys(str(item["benchmark"]) for item in V2_COMPONENTS))
    screen, returns = load_pruned_backtest_inputs(
        screen_path,
        returns_path,
        metrics=metrics,
        benchmarks=benchmarks,
        start_date=start_date,
        extra_screen_columns=("Exchange Country Iso2", " Benchmark ICB Supersector ", " Benchmark ICB Industry "),
    )
    if "Date" not in screen.columns or "Company SEDOL" not in screen.columns:
        raise KeyError("official sleeve screen must contain Date and Company SEDOL")
    return screen, returns


def run_official_factor_sleeve_database(
    *,
    screen_path: str | Path = SCREEN_AGGREGATE_PATH,
    returns_path: str | Path = RETURNS_PATH,
    start_date: str | pd.Timestamp = "2013-12-31",
    end_date: str | pd.Timestamp = "2026-07-31",
    sleeve_percentiles: Iterable[float] = (0.2,),
    components: Iterable[Mapping[str, Any]] = V2_COMPONENTS,
    factors: Iterable[Mapping[str, Any]] = V2_FACTOR_DEFINITIONS,
    max_months: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Run the real official sleeve database for all component/factor/sides."""

    sleeve_percentiles = tuple(float(value) for value in sleeve_percentiles)
    screen, returns = load_official_inputs(
        screen_path=screen_path,
        returns_path=returns_path,
        start_date=start_date,
    )
    monthly_frames: list[pd.DataFrame] = []
    holdings_frames: list[pd.DataFrame] = []
    runs: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    benchmark_cache: dict[str, Any] = {}
    for component in components:
        for factor in factors:
            for percentile in sleeve_percentiles:
                for side in ("Top", "Worst"):
                    spec = SleeveRunSpec(
                        region=str(component["region"]),
                        region_component=str(component["region_component"]),
                        benchmark=str(component["benchmark"]),
                        factor=str(factor["name"]),
                        sleeve_side=side,
                        sleeve_percentile=float(percentile),
                    )
                    try:
                        monthly, holdings, metadata = run_official_factor_sleeve(
                            screen=screen,
                            returns=returns,
                            spec=spec,
                            start_date=start_date,
                            end_date=end_date,
                            max_months=max_months,
                            benchmark_cache=benchmark_cache,
                        )
                        if not monthly.empty:
                            monthly_frames.append(monthly)
                        if not holdings.empty:
                            holdings_frames.append(holdings)
                        runs.append(metadata)
                    except Exception as error:  # evidence records the missing run; no fake fallback
                        errors.append({"spec": spec.__dict__, "error": f"{type(error).__name__}: {error}"})
    monthly = pd.concat(monthly_frames, ignore_index=True) if monthly_frames else pd.DataFrame()
    holdings = pd.concat(holdings_frames, ignore_index=True) if holdings_frames else pd.DataFrame()
    if not monthly.empty:
        paired = monthly.loc[monthly["sleeve_side"].eq("Top")].merge(
            monthly.loc[monthly["sleeve_side"].eq("Worst"), ["Date", "region_component", "factor", "sleeve_version", "net_return"]].rename(columns={"net_return": "worst_net_return"}),
            on=["Date", "region_component", "factor", "sleeve_version"],
            how="left",
        )
        spread = paired["net_return"] - paired["worst_net_return"]
        keys = paired[["Date", "region_component", "factor", "sleeve_version"]].copy()
        keys["spread"] = spread
        monthly = monthly.drop(columns=["spread"], errors="ignore").merge(
            keys, on=["Date", "region_component", "factor", "sleeve_version"], how="left"
        )
        monthly["top_worst_spread"] = monthly["spread"]
    if not monthly.empty:
        monthly["factor_coverage"] = pd.to_numeric(monthly.get("factor_coverage", monthly["coverage"]), errors="coerce")
        monthly["benchmark_weight_coverage"] = pd.to_numeric(monthly.get("benchmark_weight_coverage", monthly["weight_coverage"]), errors="coerce")
    manifest = {
        "research_unit": "Date x Region x RegionComponent x Factor x SleeveSide",
        "target": "next_month_top_sleeve_net_active_return",
        "sleeve_percentiles": [float(value) for value in sleeve_percentiles],
        "official_engine": "tp_core.backtesting.OfficialPortfolioBacktest",
        "execution_policy": "strictly_after_rebalance; apply_weights_at_close",
        "fill_method": "drift",
        "runs": runs,
        "errors": errors,
        "screen_rows": int(len(screen)),
        "return_rows": int(len(returns)),
    }
    return monthly, holdings, manifest


__all__ = [
    "V2_COMPONENTS",
    "V2_FACTOR_DEFINITIONS",
    "SleeveRunSpec",
    "component_map",
    "factor_definition_frame",
    "factor_definition_map",
    "load_official_inputs",
    "run_official_factor_sleeve",
    "run_official_factor_sleeve_database",
]

"""MSCI Europe Small candidate extension with strict official evidence gates."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
from itertools import combinations
import json
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


SCRIPT_DIR = Path(__file__).resolve().parent
BACKTEST_ROOT = SCRIPT_DIR.parent
TP_ROOT = BACKTEST_ROOT.parent
import run_eu_small_relative_synergy_research as ext  # noqa: E402


base = ext.base


AD_HOC_ROOT = BACKTEST_ROOT / "runs" / "ad_hoc"
DEFAULT_SOURCE = TP_ROOT / "00_screen" / "screen_aggregate.parquet"
DEFAULT_RETURNS = TP_ROOT / "00_screen" / "returns.parquet"
DEFAULT_RAW_DIR = AD_HOC_ROOT / "eu_small_validated_gate_20260708_official"
DEFAULT_RELATIVE_DIR = AD_HOC_ROOT / "eu_small_relative_variables_20260709"
DEFAULT_OLD_SYNERGY = AD_HOC_ROOT / "eu_small_relative_synergy_20260709"
DEFAULT_OUTPUT = AD_HOC_ROOT / "eu_small_factor_extension_20260711"
OLD_CORE_THEMES = [
    "revision",
    "pmom",
    "quality_improvement",
    "deleveraging",
    "value_improvement",
]
COUNTRY_COL = "Benchmark Country English"


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = pd.to_numeric(numerator, errors="coerce")
    den = pd.to_numeric(denominator, errors="coerce").where(lambda value: value > 0)
    return (num / den).replace([np.inf, -np.inf], np.nan)


def sector_score(screen: pd.DataFrame, column: str, direction: int = 1) -> pd.Series:
    spec = base.RawMetricSpec(column, "extension", direction, "research", column)
    return base.score_raw_metric(screen, spec)


def country_aware_score(screen: pd.DataFrame, values: pd.Series) -> pd.Series:
    clipped = base.winsorize_by_date(pd.to_numeric(values, errors="coerce"), screen[base.DATE_COL])
    fallback = base.sector_rank_score(clipped, screen[base.DATE_COL], screen[base.SECTOR_COL])
    frame = pd.DataFrame(
        {
            "date": screen[base.DATE_COL],
            "sector": screen[base.SECTOR_COL],
            "country": screen[COUNTRY_COL],
            "value": clipped,
        },
        index=screen.index,
    )
    country_group = frame.groupby(["date", "country"], observed=True)["value"]
    country_count = country_group.transform("count")
    country_rank = country_group.rank(method="average", pct=True) * 10.0
    cell_group = frame.groupby(["date", "country", "sector"], observed=True)["value"]
    cell_count = cell_group.transform("count")
    cell_rank = cell_group.rank(method="average", pct=True) * 10.0
    return cell_rank.where(cell_count >= 5, country_rank.where(country_count >= 5, fallback))


def build_benchmark_returns(screen: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    parts: list[pd.Series] = []
    dates = sorted(pd.to_datetime(screen[base.DATE_COL].dropna().unique()))
    for index, date in enumerate(dates):
        future = returns.index[returns.index > date]
        if future.empty:
            continue
        start = future[0]
        if index + 1 < len(dates):
            next_future = returns.index[returns.index > dates[index + 1]]
            end = next_future[0] if len(next_future) else returns.index[-1] + pd.Timedelta(days=1)
        else:
            end = returns.index[-1] + pd.Timedelta(days=1)
        daily_index = returns.index[(returns.index >= start) & (returns.index < end)]
        month = screen[screen[base.DATE_COL].eq(date)]
        weights = pd.to_numeric(month.set_index(base.SEDOL_COL)[base.WEIGHT_COL], errors="coerce")
        weights = weights[weights.gt(0) & weights.index.isin(returns.columns)].groupby(level=0).sum()
        if len(daily_index) == 0 or weights.empty:
            continue
        weights = weights / weights.sum()
        daily = returns.loc[daily_index, weights.index].apply(pd.to_numeric, errors="coerce").fillna(0.0)
        parts.append(daily.dot(weights).rename("benchmark_return"))
    return pd.concat(parts).sort_index() if parts else pd.Series(dtype=float)


def residual_signals(screen: pd.DataFrame, returns_path: Path) -> pd.DataFrame:
    available = set(pq.ParquetFile(returns_path).schema.names)
    sedols = sorted(set(screen[base.SEDOL_COL].dropna().astype(str)).intersection(available))
    returns = pd.read_parquet(returns_path, columns=sedols)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index().apply(pd.to_numeric, errors="coerce")
    benchmark = build_benchmark_returns(screen, returns).reindex(returns.index)
    records: list[pd.DataFrame] = []
    for date, month in screen.groupby(base.DATE_COL, sort=True, observed=True):
        mapping = month.loc[
            month[base.SEDOL_COL].notna() & month[base.ISIN_COL].notna(),
            [base.SEDOL_COL, base.ISIN_COL],
        ].copy()
        mapping[base.SEDOL_COL] = mapping[base.SEDOL_COL].astype(str)
        mapping = mapping[mapping[base.SEDOL_COL].isin(returns.columns)].drop_duplicates()
        ids = mapping[base.SEDOL_COL].drop_duplicates().tolist()
        window = returns.loc[:pd.Timestamp(date), ids].tail(252)
        if len(window) < 126 or not ids:
            continue
        x = benchmark.loc[window.index].to_numpy(dtype=float)
        y = window.to_numpy(dtype=float)
        valid = np.isfinite(y) & np.isfinite(x[:, None])
        observations = valid.sum(axis=0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            x_mean = np.nanmean(np.where(valid, x[:, None], np.nan), axis=0)
            y_mean = np.nanmean(np.where(valid, y, np.nan), axis=0)
            x_center = np.where(valid, x[:, None] - x_mean, np.nan)
            y_center = np.where(valid, y - y_mean, np.nan)
            var_x = np.nanmean(x_center**2, axis=0)
            beta = np.divide(
                np.nanmean(x_center * y_center, axis=0),
                var_x,
                out=np.zeros(len(ids)),
                where=var_x > 0,
            )
            residual = y - (y_mean - beta * x_mean) - beta * x[:, None]
            residual[~valid] = np.nan
            vol = np.nanstd(residual, axis=0)
            downside = np.sqrt(np.nanmean(np.where(residual < 0, residual**2, np.nan), axis=0))
            momentum_window = residual[:-21]
            momentum_count = np.isfinite(momentum_window).sum(axis=0)
            momentum = np.expm1(np.nansum(np.log1p(np.clip(momentum_window, -0.999, None)), axis=0))
            recent = y[-63:]
            previous = y[-126:-63]
            recent_valid = np.isfinite(recent)
            previous_valid = np.isfinite(previous)
            recent_zero = np.divide(
                ((np.abs(recent) < 1e-12) & recent_valid).sum(axis=0),
                recent_valid.sum(axis=0),
                out=np.full(len(ids), np.nan),
                where=recent_valid.sum(axis=0) >= 42,
            )
            previous_zero = np.divide(
                ((np.abs(previous) < 1e-12) & previous_valid).sum(axis=0),
                previous_valid.sum(axis=0),
                out=np.full(len(ids), np.nan),
                where=previous_valid.sum(axis=0) >= 42,
            )
        momentum[momentum_count < 105] = np.nan
        vol[observations < 126] = np.nan
        downside[observations < 126] = np.nan
        risk_adjusted = np.divide(momentum, vol, out=np.full(len(ids), np.nan), where=vol > 0)
        values = pd.DataFrame(
            {
                base.SEDOL_COL: ids,
                "eu_small_residual_momentum_raw": momentum,
                "eu_small_residual_momentum_risk_adjusted_raw": risk_adjusted,
                "eu_small_residual_volatility_raw": vol,
                "eu_small_residual_downside_volatility_raw": downside,
                "zero_return_frequency_raw": recent_zero,
                "zero_return_liquidity_improvement_raw": previous_zero - recent_zero,
            }
        )
        values = mapping.merge(values, on=base.SEDOL_COL, how="left", validate="many_to_one")
        values[base.DATE_COL] = pd.Timestamp(date)
        records.append(values.drop(columns=base.SEDOL_COL))
    return pd.concat(records, ignore_index=True) if records else pd.DataFrame()


def build_extension_screen(
    source_path: Path,
    raw_dir: Path,
    returns_path: Path,
    output_dir: Path,
) -> tuple[pd.DataFrame, list[base.ModelSpec], pd.DataFrame]:
    screen = pd.read_parquet(raw_dir / "eu_small_validated_gate_screen.parquet")
    extra_columns = [
        base.DATE_COL,
        base.ISIN_COL,
        COUNTRY_COL,
        "Asset TO exFIN",
        "R&D Expense CIQ",
        "Capex CIQ",
        "FCF",
        "Ebit",
        "Sales",
        "Total Asset CIQ",
        "CFO",
        "Net Income",
        "change Net WorkCapital CIQ",
    ]
    extra = pd.read_parquet(source_path, columns=extra_columns)
    screen[base.DATE_COL] = pd.to_datetime(screen[base.DATE_COL], errors="coerce")
    extra[base.DATE_COL] = pd.to_datetime(extra[base.DATE_COL], errors="coerce")
    screen = screen.merge(extra, on=[base.DATE_COL, base.ISIN_COL], how="left", validate="one_to_one")
    screen = screen.sort_values([base.ISIN_COL, base.DATE_COL]).reset_index(drop=True)
    entity = screen[base.ISIN_COL].astype(str)

    component_scores: dict[str, str] = {
        "Sales Growth FY1": "eu_small_growth_sales_growth_fy1_score",
        "Gross Income Growth FY1": "eu_small_growth_gross_income_growth_fy1_score",
        "EPS Growth FY1": "eu_small_growth_eps_growth_fy1_score",
        "EPS Revision Ratio": "eu_small_momentum_eps_revision_ratio_score",
        "PMOM 12M1M": "eu_small_momentum_pmom_12m1m_score",
        "Oper Margin": "eu_small_quality_oper_margin_score",
        "NetDebt to EBITDA exFIN": "eu_small_quality_netdebt_to_ebitda_exfin_score",
        "Earns Yield FY1": "eu_small_value_earns_yield_fy1_score",
        "FCF Conversion": "eu_small_quality_fcf_conversion_score",
        "DPS 1Y Growth FY1": "eu_small_dividend_dps_1y_growth_fy1_score",
    }

    country_specs = [
        ("country_eps_revision_raw", "EPS Revision Ratio", 1, 0),
        ("country_pmom_raw", "PMOM 12M1M", 1, 0),
        ("country_roe_raw", "ROE avg FY0", 1, 0),
        ("country_pfcf_raw", "PFCF LTM", -1, 0),
        ("country_oper_margin_delta3_raw", "Oper Margin", 1, 3),
        ("country_deleveraging_delta3_raw", "NetDebt to EBITDA exFIN", -1, 3),
        ("country_earnings_yield_delta1_raw", "Earns Yield FY1", 1, 1),
    ]
    for output, source, direction, lag in country_specs:
        directed = pd.to_numeric(screen[source], errors="coerce").replace([np.inf, -np.inf], np.nan) * direction
        values = directed - directed.groupby(entity).shift(lag) if lag else directed
        screen[output] = country_aware_score(screen, values)
        component_scores[output] = output

    screen["asset_turnover_score"] = sector_score(screen, "Asset TO exFIN", 1)
    screen["country_asset_turnover_score"] = country_aware_score(screen, screen["Asset TO exFIN"])
    component_scores["asset_turnover_score"] = "asset_turnover_score"
    component_scores["country_asset_turnover_score"] = "country_asset_turnover_score"

    growth_base = base.average_scores(
        screen,
        [component_scores["Sales Growth FY1"], component_scores["Gross Income Growth FY1"], component_scores["EPS Revision Ratio"]],
        min_count=2,
    )
    screen["country_growth_confirmation_score"] = country_aware_score(screen, growth_base)
    component_scores["country_growth_confirmation_score"] = "country_growth_confirmation_score"

    screen["fcf_sales_raw"] = safe_ratio(screen["FCF"], screen["Sales"])
    screen["operating_accruals_raw"] = safe_ratio(screen["Net Income"] - screen["CFO"], screen["Total Asset CIQ"])
    screen["working_capital_absorption_raw"] = safe_ratio(screen["change Net WorkCapital CIQ"], screen["Total Asset CIQ"])
    screen["capex_intensity_raw"] = safe_ratio(screen["Capex CIQ"].abs(), screen["Total Asset CIQ"])
    screen["rd_intensity_raw"] = safe_ratio(screen["R&D Expense CIQ"].where(screen["R&D Expense CIQ"].ge(0)), screen["Sales"])
    screen["rd_adjusted_ebit_margin_raw"] = safe_ratio(screen["Ebit"] + screen["R&D Expense CIQ"], screen["Sales"])
    score_directions = {
        "fcf_sales_raw": 1,
        "operating_accruals_raw": -1,
        "working_capital_absorption_raw": -1,
        "capex_intensity_raw": -1,
        "rd_intensity_raw": 1,
        "rd_adjusted_ebit_margin_raw": 1,
    }
    for column, direction in score_directions.items():
        score_column = f"{column}_score"
        screen[score_column] = sector_score(screen, column, direction)
        component_scores[column] = score_column
    residual = residual_signals(screen, returns_path)
    if not residual.empty:
        screen = screen.merge(residual, on=[base.DATE_COL, base.ISIN_COL], how="left", validate="one_to_one")
    for column, direction in {
        "eu_small_residual_momentum_raw": 1,
        "eu_small_residual_momentum_risk_adjusted_raw": 1,
        "eu_small_residual_volatility_raw": -1,
        "eu_small_residual_downside_volatility_raw": -1,
        "zero_return_frequency_raw": -1,
        "zero_return_liquidity_improvement_raw": 1,
    }.items():
        score_column = f"{column}_score"
        screen[score_column] = sector_score(screen, column, direction)
        component_scores[column] = score_column

    definitions = [
        ("eu_small_ext_country_revision", "Country-aware EPS Revision", "revision", ["country_eps_revision_raw"], 1, "EPS revisions ranked within country when the cell is large enough, otherwise within industry."),
        ("eu_small_ext_country_pmom", "Country-aware PMOM", "pmom", ["country_pmom_raw"], 1, "Price momentum with country bias control and industry fallback."),
        ("eu_small_ext_country_roe", "Country-aware ROE", "quality_level", ["country_roe_raw"], 1, "Static ROE ranked against local-country peers when feasible."),
        ("eu_small_ext_country_pfcf", "Country-aware P/FCF", "value_level", ["country_pfcf_raw"], 1, "Low P/FCF ranked against local-country peers when feasible."),
        ("eu_small_ext_country_margin_improvement", "Country-aware Margin Improvement", "quality_improvement", ["country_oper_margin_delta3_raw"], 1, "Operating-margin improvement with country exposure control."),
        ("eu_small_ext_country_deleveraging", "Country-aware Deleveraging", "deleveraging", ["country_deleveraging_delta3_raw"], 1, "NetDebt/EBITDA improvement with country exposure control."),
        ("eu_small_ext_country_value_improvement", "Country-aware Earnings-yield Improvement", "value_improvement", ["country_earnings_yield_delta1_raw"], 1, "Earnings-yield improvement ranked against local-country peers."),
        ("eu_small_ext_country_quality_repair", "Country-aware Quality Repair", "quality_improvement", ["country_oper_margin_delta3_raw", "country_deleveraging_delta3_raw"], 2, "Margin improvement jointly confirmed by deleveraging."),
        ("eu_small_ext_country_growth_confirmation", "Country-aware Growth Confirmation", "growth", ["country_growth_confirmation_score"], 1, "Growth and revisions re-ranked against local-country peers."),
        ("eu_small_ext_asset_turnover", "Asset Turnover", "capital_efficiency", ["asset_turnover_score"], 1, "Sales productivity of the non-financial asset base."),
        ("eu_small_ext_country_asset_turnover", "Country-aware Asset Turnover", "capital_efficiency", ["country_asset_turnover_score"], 1, "Asset productivity with country exposure control."),
        ("eu_small_ext_low_capex_intensity", "Low Capex / Assets", "capital_efficiency", ["capex_intensity_raw"], 1, "Low physical investment intensity; missing Capex is not imputed."),
        ("eu_small_ext_capital_efficient_growth_revision", "Capital-efficient Growth + Revision", "capital_efficiency", ["Sales Growth FY1", "Gross Income Growth FY1", "country_asset_turnover_score", "EPS Revision Ratio"], 3, "Growth confirmed by asset productivity and revisions."),
        ("eu_small_ext_cash_productivity", "FCF / Sales", "capital_efficiency", ["fcf_sales_raw"], 1, "Free-cash-flow productivity relative to sales."),
        ("eu_small_ext_low_operating_accruals", "Low Operating Accruals", "accrual_quality", ["operating_accruals_raw"], 1, "Low non-cash earnings relative to total assets."),
        ("eu_small_ext_working_capital_discipline", "Working-capital Discipline", "accrual_quality", ["working_capital_absorption_raw"], 1, "Low working-capital cash absorption relative to assets."),
        ("eu_small_ext_cash_backed_margin_improvement", "Cash-backed Margin Improvement", "accrual_quality", ["country_oper_margin_delta3_raw", "operating_accruals_raw"], 2, "Margin improvement confirmed by low operating accruals."),
        ("eu_small_ext_cash_earnings_growth", "Cash-backed Earnings Growth", "accrual_quality", ["EPS Growth FY1", "operating_accruals_raw", "FCF Conversion"], 2, "Forward earnings growth confirmed by cash quality."),
        ("eu_small_ext_rd_intensity", "R&D Intensity", "intangible_investment", ["rd_intensity_raw"], 1, "R&D expense divided by sales; missing R&D is not imputed."),
        ("eu_small_ext_rd_adjusted_margin", "R&D-adjusted EBIT Margin", "intangible_investment", ["rd_adjusted_ebit_margin_raw"], 1, "EBIT plus current R&D divided by sales; diagnostic accounting adjustment."),
        ("eu_small_ext_residual_momentum", "MSCI EUR SMALL-residual Momentum 12-1", "residual_momentum", ["eu_small_residual_momentum_raw"], 1, "12-1 momentum after removing rolling MSCI EUR SMALL benchmark beta."),
        ("eu_small_ext_residual_momentum_risk_adjusted", "Risk-adjusted Residual Momentum", "residual_momentum", ["eu_small_residual_momentum_risk_adjusted_raw"], 1, "Residual momentum scaled by residual volatility."),
        ("eu_small_ext_residual_momentum_revision", "Residual Momentum + Revision", "residual_momentum", ["eu_small_residual_momentum_raw", "EPS Revision Ratio"], 2, "Residual price continuation confirmed by earnings revisions."),
        ("eu_small_ext_low_residual_volatility", "Low Residual Volatility", "residual_risk", ["eu_small_residual_volatility_raw"], 1, "Low company-specific volatility after removing MSCI EUR SMALL beta."),
        ("eu_small_ext_low_residual_downside_risk", "Low Residual Downside Risk", "residual_risk", ["eu_small_residual_downside_volatility_raw"], 1, "Low downside company-specific volatility."),
        ("eu_small_ext_downside_aware_revision", "Downside-aware Revision", "residual_risk", ["EPS Revision Ratio", "eu_small_residual_downside_volatility_raw"], 2, "Earnings revisions penalized by residual downside risk."),
        ("eu_small_ext_low_zero_return_frequency", "Low Zero-return Frequency", "liquidity_quality", ["zero_return_frequency_raw"], 1, "Low zero-return share as a price-staleness proxy; it is not a direct spread measure."),
        ("eu_small_ext_improving_zero_return_liquidity", "Improving Zero-return Liquidity", "liquidity_quality", ["zero_return_liquidity_improvement_raw"], 1, "Decline in zero-return frequency between adjacent 63-day windows."),
        ("eu_small_ext_liquid_residual_momentum", "Liquidity-confirmed Residual Momentum", "liquidity_quality", ["eu_small_residual_momentum_raw", "zero_return_frequency_raw"], 2, "Residual momentum confirmed by lower price staleness."),
    ]
    specs: list[base.ModelSpec] = []
    definition_rows: list[dict[str, object]] = []
    for metric, label, theme, inputs, min_count, note in definitions:
        columns = [component_scores.get(column, column) for column in inputs]
        screen[metric] = base.average_scores(screen, columns, min_count=min_count)
        specs.append(base.ModelSpec(metric, label, f"raw_{theme}", {column: 1 / len(columns) for column in columns}, note))
        definition_rows.append({"metric": metric, "label": label, "theme": theme, "inputs": "|".join(inputs), "min_count": min_count, "note": note})

    screen = screen.sort_values([base.DATE_COL, base.ISIN_COL]).reset_index(drop=True)
    screen.to_parquet(output_dir / "eu_small_extension_screen.parquet", index=False)
    pd.DataFrame(definition_rows).to_csv(output_dir / "candidate_definitions.csv", index=False)
    diagnostics = base.metric_diagnostics(screen, specs, [])
    diagnostics.to_csv(output_dir / "metric_diagnostics.csv", index=False)
    return screen, specs, diagnostics


def worker_run(payload: dict[str, object]) -> dict[str, object]:
    output_dir = Path(str(payload["output_dir"]))
    screen_path = Path(str(payload["screen_path"]))
    returns_path = Path(str(payload["returns_path"]))
    metrics = list(payload["metrics"])
    shard_id = int(payload["shard_id"])
    wave = str(payload["wave"])
    shard_dir = output_dir / "parallel_shards" / wave / f"shard_{shard_id:02d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_results = shard_dir / "official_run_results.csv"
    existing = ext.read_existing(
        [Path(str(payload["main_results_path"])), *sorted((output_dir / "parallel_shards").rglob("official_run_results.csv")), shard_results]
    )
    if not existing.empty:
        existing = existing[existing["metric"].isin(metrics)].copy()
    screen = pd.read_parquet(screen_path)
    available = set(pq.ParquetFile(returns_path).schema.names)
    sedols = sorted(set(screen[base.SEDOL_COL].dropna().astype(str)).intersection(available))
    returns = pd.read_parquet(returns_path, columns=sedols)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index()
    wave_slug = base.slugify(wave)[-12:] or "manual"
    results = ext.gate_runner.run_official_backtests_incremental(
        screen=screen,
        returns=returns,
        screen_path=screen_path,
        returns_path=returns_path,
        run_root_name=f"ad_hoc/euex{wave_slug}_s{shard_id:02d}",
        metrics=metrics,
        max_runs=payload.get("max_runs"),
        results_path=shard_results,
        existing_results=existing,
    )
    results = ext.dedupe_results(results)
    results.to_csv(shard_results, index=False)
    return {
        "shard_id": shard_id,
        "metrics": len(metrics),
        "rows": len(results),
        "success": int(results["status"].eq("success").sum()) if not results.empty else 0,
        "path": str(shard_results),
    }


def run_parallel(
    output_dir: Path,
    screen_path: Path,
    map_path: Path,
    returns_path: Path,
    metrics: list[str],
    workers: int,
    wave: str,
) -> pd.DataFrame:
    output_dir.mkdir(parents=True, exist_ok=True)
    main_results = output_dir / "official_run_results.csv"
    shard_paths = sorted((output_dir / "parallel_shards").rglob("official_run_results.csv"))
    completed = ext.read_existing([main_results, *shard_paths])
    remaining = ext.incomplete_metrics(metrics, completed)
    shards = ext.shard_metrics(remaining, max(1, workers))
    print(json.dumps({"event": "parallel_start", "metrics": len(metrics), "remaining": len(remaining), "shards": [len(x) for x in shards]}, ensure_ascii=False), flush=True)
    if shards:
        payloads = [
            {
                "output_dir": str(output_dir),
                "screen_path": str(screen_path),
                "map_path": str(map_path),
                "returns_path": str(returns_path),
                "main_results_path": str(main_results),
                "wave": wave,
                "shard_id": index,
                "metrics": shard,
                "max_runs": None,
            }
            for index, shard in enumerate(shards)
        ]
        with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = [executor.submit(worker_run, payload) for payload in payloads]
            for future in as_completed(futures):
                print(json.dumps({"event": "shard_done", **future.result()}, ensure_ascii=False), flush=True)
    shard_paths = sorted((output_dir / "parallel_shards").rglob("official_run_results.csv"))
    results = ext.read_existing([main_results, *shard_paths])
    results = ext.dedupe_results(results[results["metric"].isin(metrics)].copy())
    results.to_csv(main_results, index=False)
    return results


def build_gate(summary: pd.DataFrame, diagnostics: pd.DataFrame, definitions: pd.DataFrame) -> pd.DataFrame:
    top = summary[summary["side"].eq("Top") & summary["status"].eq("success")].drop_duplicates("metric")
    status = summary.pivot_table(index="metric", columns="side", values="status", aggfunc="first")
    top_map = top.set_index("metric").to_dict(orient="index")
    diag_map = diagnostics.set_index("metric").to_dict(orient="index")
    rows: list[dict[str, object]] = []
    for _, definition in definitions.iterrows():
        metric = str(definition["metric"])
        perf = top_map.get(metric, {})
        coverage = float(diag_map.get(metric, {}).get("coverage", np.nan))
        ratio = float(perf.get("ratio_cagr", np.nan))
        top_worst = float(perf.get("top_worst_ratio_return", np.nan))
        robust = float(perf.get("robust_score", np.nan))
        checks = {
            "coverage": np.isfinite(coverage) and coverage >= 0.75,
            "ratio_cagr": np.isfinite(ratio) and ratio > 0,
            "top_worst": np.isfinite(top_worst) and top_worst > 0,
            "robust_score": np.isfinite(robust) and robust > 0,
            "top_worst_success": status.get("Top", pd.Series(dtype=object)).get(metric) == "success" and status.get("Worst", pd.Series(dtype=object)).get(metric) == "success",
        }
        rows.append(
            {
                **definition.to_dict(),
                "coverage": coverage,
                "ratio_cagr": ratio,
                "top_worst_ratio_return": top_worst,
                "robust_score": robust,
                "pass_gate": all(checks.values()),
                "fail_reasons": ";".join(name for name, passed in checks.items() if not passed),
            }
        )
    return pd.DataFrame(rows).sort_values(["pass_gate", "theme", "robust_score"], ascending=[False, True, False]).reset_index(drop=True)


def build_theme_matrix(
    old_synergy_dir: Path,
    extension_screen: pd.DataFrame,
    gate: pd.DataFrame,
    output_dir: Path,
) -> tuple[pd.DataFrame, list[base.ModelSpec], pd.DataFrame]:
    passed = gate[gate["pass_gate"].astype(bool)].copy()
    new_theme_max = passed.groupby("theme")["robust_score"].max()
    eligible_new_themes = set(new_theme_max[new_theme_max.ge(2.0)].index)
    matrix_passed = passed[passed["theme"].isin(set(OLD_CORE_THEMES) | eligible_new_themes)].copy()
    old_legs = pd.read_csv(old_synergy_dir / "selected_legs.csv")
    old_legs = old_legs[old_legs["bucket"].isin(OLD_CORE_THEMES)].copy()
    new_legs = passed.rename(columns={"theme": "bucket"})[
        ["metric", "label", "bucket", "coverage", "ratio_cagr", "top_worst_ratio_return", "robust_score"]
    ].copy()
    selected_legs = pd.concat(
        [
            old_legs[[column for column in new_legs.columns if column in old_legs.columns]],
            new_legs,
        ],
        ignore_index=True,
    )
    selected_legs.to_csv(output_dir / "selected_legs.csv", index=False)
    old_columns = {theme: f"eu_small_syn_bucket_{base.slugify(theme)}" for theme in OLD_CORE_THEMES}
    id_columns = [base.DATE_COL, base.ISIN_COL, base.SEDOL_COL, "Name", base.SECTOR_COL, base.MKT_CAP_COL, base.WEIGHT_COL]
    old = pd.read_parquet(old_synergy_dir / "eu_small_relative_synergy_screen.parquet")
    old = old[[*id_columns, *old_columns.values()]].copy()
    new_metrics = matrix_passed["metric"].astype(str).tolist()
    new = extension_screen[[base.DATE_COL, base.ISIN_COL, *new_metrics]].copy()
    screen = old.merge(new, on=[base.DATE_COL, base.ISIN_COL], how="left", validate="one_to_one")
    specs: list[base.ModelSpec] = []
    map_rows: list[dict[str, object]] = []
    theme_columns: dict[str, str] = {}
    themes = list(OLD_CORE_THEMES)
    for theme in matrix_passed["theme"].drop_duplicates():
        if theme not in themes:
            themes.append(str(theme))
    for theme in themes:
        components: list[str] = []
        if theme in old_columns:
            components.append(old_columns[theme])
        selected = matrix_passed[matrix_passed["theme"].eq(theme)].sort_values("robust_score", ascending=False).head(2)
        components.extend(selected["metric"].astype(str).tolist())
        if not components:
            continue
        column = f"eu_small_ext_theme_{base.slugify(theme)}"
        screen[column] = base.average_scores(screen, components, min_count=1)
        theme_columns[theme] = column
        specs.append(base.ModelSpec(column, theme, "bucket_component", {item: 1 / len(components) for item in components}, f"old core plus passed extension legs: {theme}"))
        map_rows.append({"metric": column, "candidate_type": "bucket_component", "component_count": len(components), "buckets": theme, "components": "|".join(components), "label": theme})

    for size in (2, 3):
        for combo in combinations(theme_columns, size):
            column = f"eu_small_ext_subset_{hashlib.sha1('|'.join(combo).encode('utf-8')).hexdigest()[:12]}"
            components = {theme_columns[theme]: 1 / size for theme in combo}
            screen[column] = base.weighted_scores(screen, components, min_count=size)
            specs.append(base.ModelSpec(column, " + ".join(combo), "family_subset", components, f"{size}-theme subset"))
            map_rows.append({"metric": column, "candidate_type": "family_subset", "component_count": size, "buckets": "|".join(combo), "components": "|".join(components), "label": " + ".join(combo)})

    full = ext.full_column()
    full_components = {column: 1 / len(theme_columns) for column in theme_columns.values()}
    screen[full] = base.weighted_scores(screen, full_components, min_count=max(2, min(4, len(theme_columns))))
    specs.append(base.ModelSpec(full, "all selected themes equal-weight", "full_model", full_components, "old core plus passed extension themes"))
    map_rows.append({"metric": full, "candidate_type": "full_model", "component_count": len(theme_columns), "buckets": "|".join(theme_columns), "components": "|".join(full_components), "label": "all selected themes equal-weight"})
    for theme in theme_columns:
        kept = {name: column for name, column in theme_columns.items() if name != theme}
        column = ext.loo_column(theme)
        components = {value: 1 / len(kept) for value in kept.values()}
        screen[column] = base.weighted_scores(screen, components, min_count=max(2, min(4, len(kept))))
        specs.append(base.ModelSpec(column, f"full model without {theme}", "leave_one_out", components, f"leave out {theme}"))
        map_rows.append({"metric": column, "candidate_type": "leave_one_out", "component_count": len(kept), "buckets": "|".join(kept), "left_out_bucket": theme, "components": "|".join(components), "label": f"full model without {theme}"})

    screen.to_parquet(output_dir / "eu_small_extension_theme_screen.parquet", index=False)
    candidate_map = pd.DataFrame(map_rows)
    candidate_map.to_csv(output_dir / "theme_candidate_map.csv", index=False)
    (output_dir / "theme_metric_definitions.json").write_text(json.dumps([spec.__dict__ for spec in specs], ensure_ascii=False, indent=2), encoding="utf-8")
    return screen, specs, candidate_map


def write_report(
    output_dir: Path,
    gate: pd.DataFrame,
    subset: pd.DataFrame,
    loo: pd.DataFrame,
    manifest: dict[str, object],
) -> Path:
    passed = gate[gate["pass_gate"].astype(bool)].copy()
    failed = gate[~gate["pass_gate"].astype(bool)].copy()
    best = subset.sort_values("robust_score", ascending=False).head(20) if not subset.empty else subset
    lines = [
        "# 欧洲小盘股因子候选扩展研究",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 证据：official exact Top/Worst；Gate 与旧研究相同。",
        "- 范围：国家偏差控制、资本效率、流动性代理、应计质量、无形资产、残差动量/风险。",
        "",
        "## 结论",
        "",
        f"{len(gate)} 个预注册候选中 {len(passed)} 个通过 Gate；通过后形成 {manifest.get('validated_theme_count', 0)} 个有效主题。",
        "本报告不把文献先验、低覆盖 R&D 或经济故事当作通过证据。",
        "",
        "## 通过 Gate 的候选",
        "",
        base.frame_to_markdown(passed[["theme", "label", "coverage", "ratio_cagr", "top_worst_ratio_return", "robust_score"]], max_rows=80),
        "",
        "## 未通过候选",
        "",
        base.frame_to_markdown(failed[["theme", "label", "coverage", "ratio_cagr", "top_worst_ratio_return", "robust_score", "fail_reasons"]], max_rows=80),
        "",
        "## 最强主题组合",
        "",
        base.frame_to_markdown(best, max_rows=20),
        "",
        "## Theme leave-one-out",
        "",
        base.frame_to_markdown(loo, max_rows=30),
        "",
        "## 外部研究锚点",
        "",
        "- [ECB — Access to finance for SMEs after the financial crisis](https://www.ecb.europa.eu/press/economic-bulletin/articles/2020/html/ecb.ebart202004_02~80dcc6a564.en.html)",
        "- [ECB — SAFE, fourth quarter 2025](https://www.ecb.europa.eu/stats/ecb_surveys/safe/html/ecb.safe202602.en.html)",
        "- [New Insights on the Asset Growth Anomaly: Evidence from Europe](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4089865)",
        "- [Corporate R&D and Stock Returns: International Evidence](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/corporate-rd-and-stock-returns-international-evidence/C40B27B31D0720C6B2BA877C5159020C)",
        "- [Blitz, Huij & Martens — Residual Momentum](https://www.sciencedirect.com/science/article/pii/S0927539811000041)",
        "- [The European Liquidity Gap](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5782262)",
        "- [Accrual mispricing: Evidence from European sovereign debt crisis](https://www.sciencedirect.com/science/article/abs/pii/S0275531918310419)",
    ]
    path = output_dir / "eu_small_factor_extension_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MSCI Europe Small factor candidate extension.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--returns", default=str(DEFAULT_RETURNS))
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--relative-dir", default=str(DEFAULT_RELATIVE_DIR))
    parser.add_argument("--old-synergy-dir", default=str(DEFAULT_OLD_SYNERGY))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--gate-only", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    screen, specs, diagnostics = build_extension_screen(Path(args.source), Path(args.raw_dir), Path(args.returns), output_dir)
    manifest: dict[str, object] = {"candidate_count": len(specs), "expected_gate_run_count": 2 * len(specs)}
    if not args.build_only:
        gate_results = run_parallel(output_dir / "gate_runs", output_dir / "eu_small_extension_screen.parquet", output_dir / "candidate_definitions.csv", Path(args.returns), [spec.column for spec in specs], max(1, args.workers), datetime.now().strftime("gate_%H%M%S"))
        gate_summary = base.summarize_runs(gate_results, diagnostics)
        gate_summary.to_csv(output_dir / "gate_performance_summary.csv", index=False)
        definitions = pd.read_csv(output_dir / "candidate_definitions.csv")
        gate = build_gate(gate_summary, diagnostics, definitions)
        gate.to_csv(output_dir / "extension_validation_gate.csv", index=False)
        manifest.update({"gate_run_count": len(gate_results), "gate_success_count": int(gate_results["status"].eq("success").sum()), "gate_pass_count": int(gate["pass_gate"].sum())})
        if not args.gate_only:
            theme_screen, theme_specs, candidate_map = build_theme_matrix(Path(args.old_synergy_dir), screen, gate, output_dir)
            theme_diagnostics = base.metric_diagnostics(theme_screen, theme_specs, [])
            theme_diagnostics.to_csv(output_dir / "theme_metric_diagnostics.csv", index=False)
            theme_results = run_parallel(output_dir / "theme_runs", output_dir / "eu_small_extension_theme_screen.parquet", output_dir / "theme_candidate_map.csv", Path(args.returns), [spec.column for spec in theme_specs], max(1, args.workers), datetime.now().strftime("theme_%H%M%S"))
            theme_summary = base.summarize_runs(theme_results, theme_diagnostics)
            theme_summary.to_csv(output_dir / "theme_performance_summary.csv", index=False)
            empty_legs = pd.DataFrame(columns=["metric", "bucket"])
            _, subset, loo, claims = ext.summarize_synergy(theme_summary, empty_legs, candidate_map, output_dir, Path(args.raw_dir), Path(args.relative_dir))
            plot_paths = base.write_plotly_outputs(theme_summary, theme_results, output_dir)
            validated_themes = list(dict.fromkeys(candidate_map[candidate_map["candidate_type"].eq("bucket_component")]["buckets"]))
            manifest.update({
                "validated_theme_count": len(validated_themes),
                "validated_themes": validated_themes,
                "matrix_theme_rule": "old core themes plus new themes with max candidate robust_score >= 2.0",
                "theme_metric_count": len(theme_specs),
                "theme_expected_run_count": 2 * len(theme_specs),
                "theme_run_count": len(theme_results),
                "theme_success_count": int(theme_results["status"].eq("success").sum()),
                "family_subset_count": int(candidate_map["candidate_type"].eq("family_subset").sum()),
                "leave_one_out_count": int(candidate_map["candidate_type"].eq("leave_one_out").sum()),
                "synergy_claim_count": len(claims),
                "plot_paths": plot_paths,
            })
            report = write_report(output_dir, gate, subset, loo, manifest)
            manifest["report"] = str(report)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Nasdaq technology-factor extension with strict official evidence gates."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import warnings

import numpy as np
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
BACKTEST_ROOT = SCRIPT_DIR.parent
TP_ROOT = BACKTEST_ROOT.parent
import analyze_nasdaq_extended_factor_research as ext  # noqa: E402
import run_nasdaq_multifactor_research as base  # noqa: E402

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)


AD_HOC_ROOT = BACKTEST_ROOT / "runs" / "ad_hoc"
DEFAULT_RAW_DIR = AD_HOC_ROOT / "nasdaq_raw_gate_20260708"
DEFAULT_RELATIVE_DIR = AD_HOC_ROOT / "nasdaq_relative_variables_20260709"
DEFAULT_SCREEN = TP_ROOT / "00_screen" / "screen_aggregate.parquet"
DEFAULT_RETURNS = TP_ROOT / "00_screen" / "returns.parquet"
TECH_THEMES = [
    "profitable_growth",
    "growth_confirmation",
    "capital_efficiency",
    "intangible_investment",
    "residual_momentum",
    "residual_risk",
]


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = pd.to_numeric(numerator, errors="coerce")
    den = pd.to_numeric(denominator, errors="coerce").where(lambda value: value > 0)
    return (num / den).replace([np.inf, -np.inf], np.nan)


def score(screen: pd.DataFrame, column: str, direction: int = 1) -> pd.Series:
    spec = base.RawMetricSpec(column, "tech_component", direction, "research", column)
    return base.score_raw_metric(screen, spec)


def build_benchmark_returns(screen: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    parts = []
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
        weights = month.set_index(base.SEDOL_COL)[base.WEIGHT_COL].apply(pd.to_numeric, errors="coerce")
        weights = weights[weights.gt(0) & weights.index.isin(returns.columns)]
        if len(daily_index) == 0 or weights.empty:
            continue
        weights = weights.groupby(level=0).sum()
        weights = weights / weights.sum()
        daily = returns.loc[daily_index, weights.index].apply(pd.to_numeric, errors="coerce").fillna(0.0)
        parts.append(daily.dot(weights).rename("benchmark_return"))
    return pd.concat(parts).sort_index() if parts else pd.Series(dtype=float)


def residual_signals(screen: pd.DataFrame, returns_path: Path) -> pd.DataFrame:
    sedols = sorted(set(screen[base.SEDOL_COL].dropna().astype(str)))
    available = set(pd.read_parquet(returns_path, columns=[]).columns)
    # PyArrow returns no schema columns for columns=[] on some pandas versions.
    if not available:
        import pyarrow.parquet as pq

        available = set(pq.ParquetFile(returns_path).schema.names)
    sedols = [sedol for sedol in sedols if sedol in available]
    returns = pd.read_parquet(returns_path, columns=sedols)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index().apply(pd.to_numeric, errors="coerce")
    benchmark = build_benchmark_returns(screen, returns).reindex(returns.index)
    records = []
    for date, month in screen.groupby(base.DATE_COL, sort=True, observed=True):
        mapping = month.loc[
            month[base.SEDOL_COL].notna() & month[base.ISIN_COL].notna(),
            [base.SEDOL_COL, base.ISIN_COL],
        ].copy()
        mapping[base.SEDOL_COL] = mapping[base.SEDOL_COL].astype(str)
        mapping = mapping[mapping[base.SEDOL_COL].isin(returns.columns)].drop_duplicates()
        ids = mapping[base.SEDOL_COL].drop_duplicates().tolist()
        window = returns.loc[:pd.Timestamp(date), ids].tail(252)
        if len(window) < 126 or len(ids) == 0:
            continue
        x = benchmark.loc[window.index].to_numpy(dtype=float)
        y = window.to_numpy(dtype=float)
        valid = np.isfinite(y) & np.isfinite(x[:, None])
        observations = valid.sum(axis=0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
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
            momentum_window = residual[:-21] if len(residual) > 21 else residual[:0]
            momentum_count = np.isfinite(momentum_window).sum(axis=0)
            log_residual = np.log1p(np.clip(momentum_window, -0.999, None))
            momentum = np.expm1(np.nansum(log_residual, axis=0))
        momentum[momentum_count < 105] = np.nan
        vol[observations < 126] = np.nan
        downside[observations < 126] = np.nan
        risk_adjusted = np.divide(momentum, vol, out=np.full(len(ids), np.nan), where=vol > 0)
        values = pd.DataFrame(
            {
                base.SEDOL_COL: ids,
                "benchmark_residual_momentum_12_1_raw": momentum,
                "benchmark_residual_momentum_risk_adjusted_raw": risk_adjusted,
                "benchmark_residual_volatility_252_raw": vol,
                "benchmark_residual_downside_volatility_252_raw": downside,
            }
        )
        values = mapping.merge(values, on=base.SEDOL_COL, how="left", validate="many_to_one")
        values[base.DATE_COL] = pd.Timestamp(date)
        records.append(values.drop(columns=base.SEDOL_COL))
    return pd.concat(records, ignore_index=True) if records else pd.DataFrame()


def build_tech_screen(
    source_screen_path: Path,
    raw_dir: Path,
    returns_path: Path,
    output_dir: Path,
) -> tuple[pd.DataFrame, list[base.ModelSpec], pd.DataFrame]:
    screen = pd.read_parquet(raw_dir / "nasdaq_multifactor_screen.parquet")
    extra_columns = [
        base.DATE_COL,
        base.ISIN_COL,
        "Sales",
        "R&D Expense CIQ",
        "Capex CIQ",
        "FCF",
        "Ebit",
        "Asset TO exFIN",
    ]
    extra = pd.read_parquet(source_screen_path, columns=extra_columns)
    extra[base.DATE_COL] = pd.to_datetime(extra[base.DATE_COL], errors="coerce")
    screen[base.DATE_COL] = pd.to_datetime(screen[base.DATE_COL], errors="coerce")
    screen = screen.merge(extra, on=[base.DATE_COL, base.ISIN_COL], how="left", validate="one_to_one")

    screen["tech_rd_intensity_raw"] = safe_ratio(screen["R&D Expense CIQ"].where(screen["R&D Expense CIQ"].ge(0)), screen["Sales"])
    screen["tech_capex_intensity_raw"] = safe_ratio(-screen["Capex CIQ"], screen["Sales"])
    screen["tech_fcf_margin_raw"] = safe_ratio(screen["FCF"], screen["Sales"])
    screen["tech_rd_adjusted_ebit_margin_raw"] = safe_ratio(screen["Ebit"] + screen["R&D Expense CIQ"], screen["Sales"])

    component_directions = {
        "Sales Growth FY1": 1,
        "Gross Income Growth FY1": 1,
        "EPS Revision Ratio": 1,
        "Oper Margin": 1,
        "ROE avg FY0": 1,
        "FCF Conversion": 1,
        "tech_fcf_margin_raw": 1,
        "tech_rd_intensity_raw": 1,
        "tech_capex_intensity_raw": -1,
        "tech_rd_adjusted_ebit_margin_raw": 1,
        "Asset TO exFIN": 1,
    }
    component_scores = {}
    for column, direction in component_directions.items():
        score_column = f"{column}_tech_score"
        screen[score_column] = score(screen, column, direction)
        component_scores[column] = score_column

    screen = screen.sort_values([base.ISIN_COL, base.DATE_COL]).reset_index(drop=True)
    entity = screen[base.ISIN_COL].astype(str)
    for source, label in [("Asset TO exFIN", "asset_turnover"), ("Oper Margin", "oper_margin")]:
        directed = pd.to_numeric(screen[source], errors="coerce").replace([np.inf, -np.inf], np.nan)
        raw_score = screen[component_scores[source]]
        for lag in (1, 3):
            delta = directed - directed.groupby(entity).shift(lag)
            delta_column = f"tech_{label}_delta_{lag}_raw"
            screen[delta_column] = base.sector_rank_score(
                base.winsorize_by_date(delta, screen[base.DATE_COL]),
                screen[base.DATE_COL],
                screen[base.SECTOR_COL],
            )
            component_scores[delta_column] = delta_column
            rank_delta = raw_score - raw_score.groupby(entity).shift(lag)
            rank_column = f"tech_{label}_rank_delta_{lag}_raw"
            screen[rank_column] = base.sector_rank_score(rank_delta, screen[base.DATE_COL], screen[base.SECTOR_COL])
            component_scores[rank_column] = rank_column

    residual = residual_signals(screen, returns_path)
    if not residual.empty:
        screen = screen.merge(residual, on=[base.DATE_COL, base.ISIN_COL], how="left", validate="one_to_one")
    for column, direction in {
        "benchmark_residual_momentum_12_1_raw": 1,
        "benchmark_residual_momentum_risk_adjusted_raw": 1,
        "benchmark_residual_volatility_252_raw": -1,
        "benchmark_residual_downside_volatility_252_raw": -1,
    }.items():
        score_column = f"{column}_score"
        screen[score_column] = score(screen, column, direction)
        component_scores[column] = score_column

    definitions = [
        ("nasdaq_tech_profitable_growth", "Profitable Growth", "profitable_growth", ["Sales Growth FY1", "Gross Income Growth FY1", "Oper Margin", "FCF Conversion"], 3, "Forward growth confirmed by operating and cash conversion quality."),
        ("nasdaq_tech_growth_confirmation", "Growth + Earnings Revision", "growth_confirmation", ["Sales Growth FY1", "Gross Income Growth FY1", "EPS Revision Ratio"], 2, "Forward growth confirmed by analyst revision breadth."),
        ("nasdaq_tech_capital_efficiency", "Capital Efficiency", "capital_efficiency", ["ROE avg FY0", "Oper Margin", "FCF Conversion", "tech_fcf_margin_raw"], 3, "Profitability and free-cash-flow efficiency for asset-light firms."),
        ("nasdaq_tech_cash_funded_growth", "Cash-funded Growth", "capital_efficiency", ["Sales Growth FY1", "FCF Conversion", "tech_fcf_margin_raw"], 2, "Growth supported by internally generated cash rather than external financing."),
        ("nasdaq_tech_rd_intensity", "R&D Intensity", "intangible_investment", ["tech_rd_intensity_raw"], 1, "R&D expense divided by sales; missing R&D is not imputed as zero."),
        ("nasdaq_tech_rd_adjusted_margin", "R&D-adjusted EBIT Margin", "intangible_investment", ["tech_rd_adjusted_ebit_margin_raw"], 1, "EBIT plus current R&D expense divided by sales; diagnostic accounting adjustment."),
        ("nasdaq_tech_asset_light_growth", "Asset-light Growth", "intangible_investment", ["Sales Growth FY1", "Oper Margin", "tech_capex_intensity_raw", "tech_rd_intensity_raw"], 2, "Growth and margin quality with physical-capex discipline and disclosed R&D."),
        ("nasdaq_tech_residual_momentum", "Benchmark-residual Momentum 12-1", "residual_momentum", ["benchmark_residual_momentum_12_1_raw"], 1, "12-1 momentum after removing rolling Nasdaq benchmark beta."),
        ("nasdaq_tech_residual_momentum_risk_adjusted", "Risk-adjusted Residual Momentum", "residual_momentum", ["benchmark_residual_momentum_risk_adjusted_raw"], 1, "Benchmark-residual momentum scaled by residual volatility."),
        ("nasdaq_tech_residual_low_risk", "Low Residual Volatility", "residual_risk", ["benchmark_residual_volatility_252_raw"], 1, "Low 252-day volatility after removing rolling Nasdaq benchmark beta."),
        ("nasdaq_tech_residual_downside_risk", "Low Residual Downside Risk", "residual_risk", ["benchmark_residual_downside_volatility_252_raw"], 1, "Low downside residual volatility after removing rolling Nasdaq benchmark beta."),
        ("nasdaq_tech_asset_turnover", "Asset Turnover", "capital_efficiency", ["Asset TO exFIN"], 1, "Sales productivity of the asset base, excluding financials."),
        ("nasdaq_tech_asset_turnover_delta_1", "Asset Turnover Improvement 1M", "capital_efficiency", ["tech_asset_turnover_delta_1_raw"], 1, "One-observation improvement in asset turnover."),
        ("nasdaq_tech_asset_turnover_rank_delta_3", "Asset Turnover Rank Improvement 3M", "capital_efficiency", ["tech_asset_turnover_rank_delta_3_raw"], 1, "Three-observation improvement in sector-relative asset-turnover rank."),
        ("nasdaq_tech_capital_efficient_growth_revision", "Capital-efficient Growth + Revision", "capital_efficiency", ["Sales Growth FY1", "Gross Income Growth FY1", "Asset TO exFIN", "EPS Revision Ratio"], 3, "Growth confirmed by asset productivity and earnings revisions."),
        ("nasdaq_tech_asset_light_growth_revision", "Asset-light Growth + Revision", "intangible_investment", ["Sales Growth FY1", "Oper Margin", "tech_capex_intensity_raw", "tech_rd_intensity_raw", "EPS Revision Ratio"], 3, "Asset-light growth with disclosed-R&D information where available and mandatory earnings confirmation."),
        ("nasdaq_tech_rd_adjusted_margin_revision", "R&D-adjusted Margin + Revision", "intangible_investment", ["tech_rd_adjusted_ebit_margin_raw", "EPS Revision Ratio"], 2, "R&D-adjusted operating profitability confirmed by earnings revisions; R&D remains required."),
        ("nasdaq_tech_residual_momentum_revision", "Residual Momentum + Revision", "residual_momentum", ["benchmark_residual_momentum_12_1_raw", "EPS Revision Ratio"], 2, "Benchmark-residual price continuation confirmed by earnings revisions."),
        ("nasdaq_tech_residual_momentum_oper_improvement", "Residual Momentum + Margin Improvement", "residual_momentum", ["benchmark_residual_momentum_12_1_raw", "tech_oper_margin_delta_1_raw"], 2, "Benchmark-residual price continuation confirmed by operating-margin improvement."),
        ("nasdaq_tech_downside_aware_growth_revision", "Downside-aware Growth + Revision", "residual_risk", ["Sales Growth FY1", "EPS Revision Ratio", "benchmark_residual_downside_volatility_252_raw"], 3, "Growth and revisions penalized by benchmark-residual downside risk."),
        ("nasdaq_tech_downside_aware_residual_momentum", "Downside-aware Residual Momentum", "residual_risk", ["benchmark_residual_momentum_12_1_raw", "EPS Revision Ratio", "benchmark_residual_downside_volatility_252_raw"], 3, "Residual momentum and revisions with residual downside-risk control."),
    ]
    specs = []
    definition_rows = []
    for metric, label, theme, inputs, min_count, note in definitions:
        columns = [component_scores[column] for column in inputs]
        screen[metric] = base.average_scores(screen, columns, min_count=min_count)
        specs.append(base.ModelSpec(metric, label, f"raw_{theme}", {column: 1 / len(columns) for column in columns}, note))
        definition_rows.append({"metric": metric, "label": label, "theme": theme, "inputs": "|".join(inputs), "min_count": min_count, "note": note})

    screen_path = output_dir / "nasdaq_tech_factor_screen.parquet"
    screen.to_parquet(screen_path, index=False)
    definitions_frame = pd.DataFrame(definition_rows)
    definitions_frame.to_csv(output_dir / "tech_candidate_definitions.csv", index=False)
    diagnostics = base.metric_diagnostics(screen, specs, [])
    diagnostics.to_csv(output_dir / "metric_diagnostics.csv", index=False)
    return screen, specs, diagnostics


def gate_to_audit(gate: pd.DataFrame, definitions: pd.DataFrame) -> pd.DataFrame:
    meta = definitions.set_index("metric").to_dict(orient="index")
    rows = []
    for _, row in gate.iterrows():
        info = meta[str(row["metric"])]
        rows.append(
            {
                "metric": row["metric"],
                "label": info["label"],
                "raw_column": info["inputs"],
                "theme": info["theme"],
                "family": info["theme"],
                "source": "local_engineered",
                "evidence_scope": "tech_engineered",
                "coverage": row["coverage"],
                "ratio_cagr": row["top_ratio_cagr"],
                "top_worst_ratio_return": row["top_worst_ratio_return"],
                "robust_score": row["robust_score"],
                "pass_gate": bool(row["passed"]),
                "fail_reasons": row["fail_reasons"],
                "economic_role": info["note"],
            }
        )
    return pd.DataFrame(rows)


def shorten_synergy_metric_ids(
    screen: pd.DataFrame,
    specs: list[base.ModelSpec],
    maps: dict[str, object],
    output_dir: Path,
) -> tuple[pd.DataFrame, list[base.ModelSpec], dict[str, object], dict[str, str]]:
    renamed = {
        spec.column: f"nasdaq_ext_{base.slugify(spec.family)}_{hashlib.sha1(spec.column.encode('utf-8')).hexdigest()[:12]}"
        for spec in specs
        if len(spec.column) > 64
    }
    if not renamed:
        return screen, specs, maps, renamed
    screen = screen.rename(columns=renamed)
    new_specs = [
        base.ModelSpec(
            column=renamed.get(spec.column, spec.column),
            label=spec.label,
            family=spec.family,
            components={renamed.get(column, column): weight for column, weight in spec.components.items()},
            note=spec.note,
        )
        for spec in specs
    ]
    for map_name in ("pair", "subset", "leave_one_out"):
        source = maps.get(map_name, {})
        maps[map_name] = {renamed.get(metric, metric): info for metric, info in source.items()}
    maps["theme_scores"] = {
        theme: renamed.get(metric, metric)
        for theme, metric in maps.get("theme_scores", {}).items()
    }
    for info in maps.get("leave_one_out", {}).values():
        if "full_metric" in info:
            info["full_metric"] = renamed.get(info["full_metric"], info["full_metric"])
    (output_dir / "synergy_metric_maps.json").write_text(json.dumps(maps, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "synergy_metric_definitions.json").write_text(
        json.dumps([spec.__dict__ for spec in new_specs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return screen, new_specs, maps, renamed


def run_official_gate(
    screen_path: Path,
    returns_path: Path,
    specs: list[base.ModelSpec],
    diagnostics: pd.DataFrame,
    output_dir: Path,
    workers: int,
    wave: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    metrics = [spec.column for spec in specs]
    gate_run_dir = output_dir / "tech_gate_runs"
    gate_run_dir.mkdir(parents=True, exist_ok=True)
    gate_results_path = gate_run_dir / "official_run_results.csv"
    legacy_results_path = output_dir / "official_run_results.csv"
    if not gate_results_path.exists() and legacy_results_path.exists():
        legacy = ext.read_csv(legacy_results_path)
        legacy = legacy[legacy["metric"].isin(metrics)].copy() if not legacy.empty else legacy
        if not legacy.empty:
            legacy.to_csv(gate_results_path, index=False)
    plan = ext.RunPlan(screen_path, returns_path, metrics, gate_run_dir, gate_results_path, workers, wave)
    results = ext.run_parallel(plan)
    results.to_csv(legacy_results_path, index=False)
    summary = base.summarize_runs(results, diagnostics)
    summary.to_csv(output_dir / "performance_summary.csv", index=False)
    gate = base.build_raw_validation_gate(
        summary,
        diagnostics,
        min_coverage=0.75,
        min_ratio_cagr=0.0,
        min_top_worst_ratio_return=0.0,
        min_robust_score=0.0,
    )
    gate.to_csv(output_dir / "tech_validation_gate.csv", index=False)
    return results, summary, gate


def build_combined_synergy(
    raw_dir: Path,
    relative_dir: Path,
    tech_screen: pd.DataFrame,
    tech_audit: pd.DataFrame,
    tech_summary: pd.DataFrame,
    returns_path: Path,
    output_dir: Path,
    workers: int,
    wave: str,
) -> dict[str, object]:
    candidates = pd.concat([ext.build_candidate_audit(raw_dir, relative_dir), tech_audit], ignore_index=True)
    candidates.to_csv(output_dir / "synergy_candidate_audit.csv", index=False)
    selected_rel = candidates[candidates["pass_gate"].astype(bool) & candidates["evidence_scope"].eq("relative_raw")]
    if not selected_rel.empty:
        columns = [base.DATE_COL, base.ISIN_COL, *selected_rel["metric"].astype(str)]
        relative_screen = pd.read_parquet(relative_dir / "nasdaq_relative_variable_screen.parquet", columns=columns)
        tech_screen = tech_screen.merge(relative_screen, on=[base.DATE_COL, base.ISIN_COL], how="left", validate="one_to_one")
    ext.THEME_ORDER[:] = [*ext.THEME_ORDER, *[theme for theme in TECH_THEMES if theme not in ext.THEME_ORDER]]
    synergy_screen, all_specs, maps = ext.build_synergy_metrics(tech_screen, candidates, output_dir)
    synergy_screen, all_specs, maps, renamed_metrics = shorten_synergy_metric_ids(
        synergy_screen,
        all_specs,
        maps,
        output_dir,
    )
    theme_loo = {
        metric
        for metric, info in maps.get("leave_one_out", {}).items()
        if info.get("kind") == "theme"
    }
    specs = [
        spec
        for spec in all_specs
        if spec.family in {"family_subset", "validated_theme"}
        or spec.column == "nasdaq_ext_full_theme_composite"
        or spec.column in theme_loo
    ]
    screen_path = output_dir / "nasdaq_extended_synergy_screen.parquet"
    synergy_screen.to_parquet(screen_path, index=False)
    diagnostics = base.metric_diagnostics(synergy_screen, specs, [])
    diagnostics.to_csv(output_dir / "synergy_metric_diagnostics.csv", index=False)
    synergy_run_dir = output_dir / "synergy_theme_runs"
    synergy_run_dir.mkdir(parents=True, exist_ok=True)
    synergy_results_path = synergy_run_dir / "official_run_results.csv"
    prior_shards = sorted((synergy_run_dir / "parallel_shards").rglob("official_run_results.csv"))
    prior_results = ext.load_completed([synergy_results_path, *prior_shards])
    if not prior_results.empty:
        prior_results["metric"] = prior_results["metric"].replace(renamed_metrics)
        valid_metrics = {spec.column for spec in specs}
        prior_results = ext.dedupe_results(prior_results[prior_results["metric"].isin(valid_metrics)].copy())
        prior_results.to_csv(synergy_results_path, index=False)
    plan = ext.RunPlan(
        screen_path,
        returns_path,
        [spec.column for spec in specs],
        synergy_run_dir,
        synergy_results_path,
        workers,
        wave,
    )
    results = ext.run_parallel(plan)
    results = ext.dedupe_results(results[results["metric"].isin({spec.column for spec in specs})].copy())
    results.to_csv(output_dir / "synergy_official_run_results.csv", index=False)
    summary = base.summarize_runs(results, diagnostics)
    summary.to_csv(output_dir / "synergy_performance_summary.csv", index=False)
    single_summary = pd.concat([ext.load_single_summary(raw_dir, relative_dir), tech_summary], ignore_index=True)
    single_summary.to_csv(output_dir / "single_variable_official_summary.csv", index=False)
    pairs = ext.classify_pair_synergy(summary, single_summary, maps)
    pairs.to_csv(output_dir / "pair_synergy_results.csv", index=False)
    subsets, loo = ext.summarize_subset_and_loo(summary, maps)
    subsets.to_csv(output_dir / "family_subset_results.csv", index=False)
    loo.to_csv(output_dir / "leave_one_out_results.csv", index=False)
    claims = pairs[pairs["relationship"].eq("synergistic")].copy() if not pairs.empty else pd.DataFrame()
    claims.to_csv(output_dir / "synergy_claims.csv", index=False)
    checks = pd.concat(
        [
            ext.read_csv(raw_dir / "data_construction_checks.csv").assign(source_run="raw_level"),
            ext.read_csv(relative_dir / "data_construction_checks.csv").assign(source_run="relative_raw"),
        ],
        ignore_index=True,
    )
    checks.to_csv(output_dir / "data_construction_checks.csv", index=False)
    comparison = ext.read_csv(relative_dir / "relative_vs_level_comparison.csv")
    if not comparison.empty:
        comparison.to_csv(output_dir / "relative_vs_level_comparison.csv", index=False)
    report = ext.write_report(output_dir, checks, candidates, comparison, pairs, subsets, loo, results)
    report_text = report.read_text(encoding="utf-8")
    report_text = report_text.replace(
        "协同只基于 pair/subset/leave-one-out 证据。",
        "本次 tech extension 完整运行 validated-theme power set 与 theme leave-one-out；变量级 pair 不在本轮范围。",
    ).replace(
        "pair/subset/leave-one-out official run rows:",
        "theme subset/theme leave-one-out official run rows:",
    )
    report.write_text(report_text, encoding="utf-8")
    return {
        "report": str(report),
        "selected_variable_count": int(candidates["pass_gate"].sum()),
        "validated_theme_count": int(candidates.loc[candidates["pass_gate"].astype(bool), "theme"].nunique()),
        "synergy_metric_count": len(specs),
        "synergy_constructed_metric_count": len(all_specs),
        "synergy_scope": "complete validated-theme power set plus theme leave-one-out",
        "synergy_expected_run_count": 2 * len(specs),
        "synergy_run_count": len(results),
        "synergy_success_count": int(results["status"].eq("success").sum()),
        "synergy_claim_count": len(claims),
        "family_subset_count": len(subsets),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Nasdaq technology-specific factor extension research.")
    parser.add_argument("--screen", default=str(DEFAULT_SCREEN))
    parser.add_argument("--returns", default=str(DEFAULT_RETURNS))
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--relative-dir", default=str(DEFAULT_RELATIVE_DIR))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--gate-only", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else AD_HOC_ROOT / f"nasdaq_tech_factor_extension_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    screen, specs, diagnostics = build_tech_screen(Path(args.screen), Path(args.raw_dir), Path(args.returns), output_dir)
    screen_path = output_dir / "nasdaq_tech_factor_screen.parquet"
    manifest: dict[str, object] = {
        "output_dir": str(output_dir),
        "raw_dir": str(Path(args.raw_dir)),
        "relative_dir": str(Path(args.relative_dir)),
        "candidate_count": len(specs),
        "expected_gate_run_count": 2 * len(specs),
    }
    if not args.build_only:
        results, summary, gate = run_official_gate(
            screen_path,
            Path(args.returns),
            specs,
            diagnostics,
            output_dir,
            max(1, args.workers),
            f"tech_gate_{timestamp}",
        )
        definitions = pd.read_csv(output_dir / "tech_candidate_definitions.csv")
        tech_audit = gate_to_audit(gate, definitions)
        tech_audit.to_csv(output_dir / "tech_candidate_audit.csv", index=False)
        manifest.update(
            {
                "gate_run_count": len(results),
                "gate_success_count": int(results["status"].eq("success").sum()),
                "gate_pass_count": int(gate["passed"].sum()),
            }
        )
        if not args.gate_only:
            manifest.update(
                build_combined_synergy(
                    Path(args.raw_dir),
                    Path(args.relative_dir),
                    screen,
                    tech_audit,
                    summary,
                    Path(args.returns),
                    output_dir,
                    max(1, args.workers),
                    f"tech_synergy_{timestamp}",
                )
            )
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Factor construction helpers migrated from the download_10 reference file.

The functions here keep the research workflow small and explicit:

* impute raw factor inputs within date/sector/region groups;
* transform raw values into rank-based 0-10 scores;
* build composite factor scores from level, percentage-change and difference
  components;
* optionally run quick top-vs-bottom factor backtests with the active
  OfficialPortfolioBacktest wrapper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


DEFAULT_GROUP_COLS = [" Benchmark ICB Supersector ", "Date", "Exchange Country Region"]

DEFAULT_ABSOLUTE_NORMALIZATION = {
    "R&D Expense CIQ": "Sales",
    "Capex CIQ": "Sales",
    "Interest expense CIQ": "Ebitda",
    "Sales FY1": "Sales",
}

UNITARY_GROWTH_VARS = {
    "R&D Expense CIQ_Intensity": False,
    "Capex CIQ_Intensity": False,
    "Sales FY1_Intensity": False,
    "Interest expense CIQ_Intensity": False,
    "Net Debt to Ebit": False,
    "Net Debt to Tot Equity": False,
    "CFO 5Y CAGR": True,
    "FCF Conversion": True,
    "Gross Profit 5Y CAGR": True,
    "Const Earning 5Y CAGR": True,
    "Revenue 5Y CAGR": True,
    "Sales Growth FY1 CIQ": True,
    "Ebitda 5Y CAGR": True,
    "EBITDA Growth FY1 CIQ": True,
    "Ebit 5Y CAGR": True,
    "EPS Growth FY1 CIQ": True,
    "SP Est 5Y EPS Gr CIQ": True,
    "Gross Margin": True,
    "Ebitda Margin": True,
}


def _available_group_cols(df: pd.DataFrame, group_cols: Sequence[str]) -> list[str]:
    return [col for col in group_cols if col in df.columns]


def handle_missing_values(
    df: pd.DataFrame,
    columns: Sequence[str],
    group_cols: Sequence[str] = DEFAULT_GROUP_COLS,
) -> pd.DataFrame:
    """Fill missing values with group medians, falling back to global medians."""

    out = df.copy()
    groups = _available_group_cols(out, group_cols)
    for col in columns:
        if col not in out.columns:
            continue
        out[col] = pd.to_numeric(out[col], errors="coerce")
        if groups:
            out[col] = out[col].fillna(out.groupby(groups)[col].transform("median"))
        out[col] = out[col].fillna(out[col].median())
    return out


def neutralize_score(
    df: pd.DataFrame,
    score_col: str,
    higher_is_better: bool,
    group_cols: Sequence[str] = DEFAULT_GROUP_COLS,
    scale: float = 10.0,
) -> pd.DataFrame:
    """Convert a raw score to a grouped percentile score.

    The current portfolio builder selects with ``nlargest``. Therefore a better
    raw value must produce a higher neutralized score.
    """

    if score_col not in df.columns:
        raise KeyError(f"{score_col} not found")
    out = df.copy()
    groups = _available_group_cols(out, group_cols)
    raw = pd.to_numeric(out[score_col], errors="coerce")
    if groups:
        ranked = raw.groupby([out[col] for col in groups]).rank(pct=True, ascending=higher_is_better)
    else:
        ranked = raw.rank(pct=True, ascending=higher_is_better)
    out[score_col] = ranked * float(scale)
    return out


def build_factor_component(
    screen: pd.DataFrame,
    var_name: str,
    config: Mapping[str, object],
    group_cols: Sequence[str] = DEFAULT_GROUP_COLS,
) -> tuple[pd.DataFrame, pd.Series | float]:
    """Build a weighted component from level, pct-change and diff signals."""

    if var_name not in screen.columns:
        return screen.copy(), 0.0

    out = screen.copy().sort_values(["ISIN", "Date"])
    contribution: pd.Series | float = 0.0
    higher_is_better = bool(config.get("higher_is_better", True))

    if config.get("use_level", False):
        temp_col = f"{var_name}_score"
        out[temp_col] = out[var_name]
        out = neutralize_score(out, temp_col, higher_is_better=higher_is_better, group_cols=group_cols)
        contribution = contribution + out[temp_col] * float(config.get("weight_level", 1.0))
        out = out.drop(columns=[temp_col])

    if config.get("use_pct", False):
        pct_col = f"{var_name}_pct"
        temp_col = f"{var_name}_pct_score"
        out[pct_col] = out.groupby("ISIN")[var_name].pct_change().replace([np.inf, -np.inf], np.nan)
        out[temp_col] = out[pct_col]
        out = neutralize_score(out, temp_col, higher_is_better=higher_is_better, group_cols=group_cols)
        contribution = contribution + out[temp_col] * float(config.get("weight_pct", 1.0))
        out = out.drop(columns=[temp_col])

    if config.get("use_diff", False):
        diff_col = f"{var_name}_diff"
        temp_col = f"{var_name}_diff_score"
        out[diff_col] = out.groupby("ISIN")[var_name].diff().replace([np.inf, -np.inf], np.nan)
        out[temp_col] = out[diff_col]
        out = neutralize_score(out, temp_col, higher_is_better=higher_is_better, group_cols=group_cols)
        contribution = contribution + out[temp_col] * float(config.get("weight_diff", 1.0))
        out = out.drop(columns=[temp_col])

    return out, contribution


def calculate_quality_score(
    screen: pd.DataFrame,
    col_name: str,
    quality_config: Mapping[str, Mapping[str, object]],
    group_cols: Sequence[str] = DEFAULT_GROUP_COLS,
) -> pd.DataFrame:
    """Calculate a composite quality score from a variable configuration."""

    out = screen.copy()
    total_score: pd.Series | float = 0.0
    for var_name, config in quality_config.items():
        out, contribution = build_factor_component(out, var_name, config, group_cols=group_cols)
        total_score = total_score + contribution
    out[col_name] = total_score
    return neutralize_score(out, col_name, higher_is_better=True, group_cols=group_cols)


def transform_absolute_values(
    df: pd.DataFrame,
    abs_vars: Sequence[str],
    group_cols: Sequence[str] = DEFAULT_GROUP_COLS,
    normalization_map: Mapping[str, str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Transform absolute values into ratios or group-relative values."""

    out = df.copy()
    groups = _available_group_cols(out, group_cols)
    mapping = dict(DEFAULT_ABSOLUTE_NORMALIZATION)
    if normalization_map:
        mapping.update(normalization_map)

    new_cols: list[str] = []
    for var in abs_vars:
        if var not in out.columns:
            continue
        denominator = mapping.get(var)
        new_col = f"{var}_Intensity" if denominator else f"{var}_Relative"
        numerator = pd.to_numeric(out[var], errors="coerce")
        if denominator and denominator in out.columns:
            denom = pd.to_numeric(out[denominator], errors="coerce").replace(0, np.nan)
            out[new_col] = numerator / denom
        elif groups:
            group_median = numerator.groupby([out[col] for col in groups]).transform("median").replace(0, np.nan)
            out[new_col] = numerator / group_median
        else:
            out[new_col] = numerator / numerator.median()
        new_cols.append(new_col)
    return out, new_cols


def run_growth_factor_pipeline(
    df: pd.DataFrame,
    abs_vars: Sequence[str] | None = None,
    ratio_vars: Sequence[str] | None = None,
    group_cols: Sequence[str] = DEFAULT_GROUP_COLS,
) -> pd.DataFrame:
    """Create neutralized growth-factor features from ratio and absolute inputs."""

    abs_vars = list(abs_vars or [])
    ratio_vars = list(ratio_vars or [])
    out, transformed_abs_cols = transform_absolute_values(df.copy(), abs_vars, group_cols)
    final_feature_list = list(ratio_vars) + transformed_abs_cols
    out = out.replace([np.inf, -np.inf], np.nan)
    out = handle_missing_values(out, final_feature_list, group_cols)
    for col in final_feature_list:
        if col in out.columns:
            out = neutralize_score(out, col, higher_is_better=True, group_cols=group_cols)
    return out


def _build_factor_portfolio_backtests(
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    bench: str,
    metric: str,
    list_noire_path: str | None,
    percentile: float,
):
    from tp_core.backtesting import OfficialPortfolioBacktest

    monthly_base_cache: dict = {}
    benchmark_cache: dict = {}
    builder_top = OfficialPortfolioBacktest(
        screen,
        returns,
        bench=bench,
        percentile=percentile,
        metrics=metric,
        ptf_name=f"{metric}_top",
        esg_exclusion=0,
        liste_noire=list_noire_path,
        Top=True,
        copy_inputs=False,
        monthly_base_cache=monthly_base_cache,
        benchmark_cache=benchmark_cache,
    )
    builder_bottom = OfficialPortfolioBacktest(
        screen,
        returns,
        bench=bench,
        percentile=percentile,
        metrics=metric,
        ptf_name=f"{metric}_bottom",
        esg_exclusion=0,
        liste_noire=list_noire_path,
        Top=False,
        copy_inputs=False,
        monthly_base_cache=monthly_base_cache,
        benchmark_cache=benchmark_cache,
    )
    return builder_top, builder_bottom


def backtest_factors(
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    bench: str,
    list_noire_path: str | None,
    test_variables: Sequence[str],
    start_date: str | pd.Timestamp = "2010-01-01",
    percentile: float = 0.2,
    output_dir: str | Path | None = None,
    show_plot: bool = True,
) -> dict[str, object]:
    """Run top-vs-bottom quick backtests for one or more factor columns."""

    results: dict[str, object] = {}
    output_base = Path(output_dir) if output_dir else None
    if output_base:
        output_base.mkdir(parents=True, exist_ok=True)

    for variable in test_variables:
        builder_top, builder_bottom = _build_factor_portfolio_backtests(
            screen, returns, bench, variable, list_noire_path, percentile
        )
        for builder in [builder_top, builder_bottom]:
            builder.build_historical_security_lists(pd.Timestamp(start_date), freq_rebal=1, fill_method="copy")
            builder.run_portfolio_nav()
        save_path = None
        if output_base:
            save_path = str(output_base / f"{variable}_comparison.html")
        fig = builder_top.plot_top_vs_bottom(
            builder_bottom=builder_bottom,
            title=f"Factor Analysis: {variable}",
            save_path=save_path,
            show_plot=show_plot,
        )
        results[variable] = {"top": builder_top, "bottom": builder_bottom, "figure": fig}
    return results


def run_factor_pipeline(
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    col_name: str,
    quality_config: Mapping[str, Mapping[str, object]],
    list_noire_path: str | None,
    bench: str = "STOXX EUROPE 600",
    run_backtest: bool = True,
    **backtest_kwargs,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Calculate a composite score and optionally run a factor backtest."""

    scored = calculate_quality_score(screen, col_name, quality_config)
    results: dict[str, object] = {}
    if run_backtest:
        results = backtest_factors(scored, returns, bench, list_noire_path, [col_name], **backtest_kwargs)
    return scored, results


def test_unitary_factors(
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    unitary_quality_vars: Mapping[str, bool],
    list_noire_path: str | None,
    bench: str = "STOXX EUROPE 600",
    start_date: str | pd.Timestamp = "2010-01-01",
    percentile: float = 0.2,
    run_backtest: bool = True,
    output_dir: str | Path | None = None,
    show_plot: bool = True,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Create and optionally backtest unitary level/change/pct-change factors."""

    out = screen.copy().sort_values(["ISIN", "Date"])
    results: dict[str, object] = {}
    for var_name, is_positive in unitary_quality_vars.items():
        if var_name not in out.columns:
            continue
        out[f"{var_name}_change"] = out.groupby("ISIN")[var_name].diff()
        out[f"{var_name}_pct_change"] = out.groupby("ISIN")[var_name].pct_change().replace([np.inf, -np.inf], np.nan)

        dimensions = {
            "LEVEL": var_name,
            "CHANGE": f"{var_name}_change",
            "CHANGE_PCT": f"{var_name}_pct_change",
        }
        for dim_label, col_to_test in dimensions.items():
            out = handle_missing_values(out, [col_to_test])
            temp_col = f"UNITARY_{dim_label}_{var_name}"
            out[temp_col] = out[col_to_test]
            out = neutralize_score(out, temp_col, higher_is_better=is_positive)
            if run_backtest:
                results.update(
                    backtest_factors(
                        out,
                        returns,
                        bench,
                        list_noire_path,
                        [temp_col],
                        start_date=start_date,
                        percentile=percentile,
                        output_dir=output_dir,
                        show_plot=show_plot,
                    )
                )
    return out, results


__all__ = [
    "DEFAULT_ABSOLUTE_NORMALIZATION",
    "DEFAULT_GROUP_COLS",
    "UNITARY_GROWTH_VARS",
    "backtest_factors",
    "build_factor_component",
    "calculate_quality_score",
    "handle_missing_values",
    "neutralize_score",
    "run_factor_pipeline",
    "run_growth_factor_pipeline",
    "test_unitary_factors",
    "transform_absolute_values",
]

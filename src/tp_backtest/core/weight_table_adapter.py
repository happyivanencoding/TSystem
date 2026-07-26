"""Convert legacy security lists into the canonical target-weight contract."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from tp_core.portfolio_weights import (
    apply_weighting_transform,
    cap_weights_preserving_group_totals,
    match_group_weight_targets,
    normalize_weight_table,
)
from tp_backtest.utils.constants import (
    COL_DATE,
    COL_ISIN,
    COL_MKT_CAP,
    COL_PORTFOLIO_WEIGHT,
    COL_SECTOR_ICB19,
    COL_SEDOL,
)


def security_list_to_weight_table(
    sec_list: pd.DataFrame,
    screen: str | pd.DataFrame,
    *,
    max_weight: float = 1.0,
    col_sector: str = COL_SECTOR_ICB19,
    col_sedol: str = COL_SEDOL,
    col_isin: str = COL_ISIN,
    col_date: str = COL_DATE,
    col_mkt_cap: str = COL_MKT_CAP,
) -> pd.DataFrame:
    """Convert a OfficialPortfolioBacktest security list into canonical target weights."""

    if "Weight" not in sec_list.columns:
        raise ValueError("security list is missing the Weight column")
    screen_agg = pd.read_parquet(screen) if isinstance(screen, str) else screen
    weights = sec_list[[col_date, col_isin, "Weight"]].copy()
    weights = normalize_weight_table(
        weights,
        weight_col="Weight",
        group_cols=col_date,
        max_weight=max_weight,
    )
    weights = weights.reset_index(drop=True).rename(
        columns={"Weight": COL_PORTFOLIO_WEIGHT}
    )

    screen_lookup = screen_agg.reset_index()
    screen_lookup = screen_lookup[
        [col_date, col_isin, col_sedol, col_sector, col_mkt_cap]
    ].copy()
    screen_lookup[col_date] = pd.to_datetime(screen_lookup[col_date])
    screen_lookup[col_date] = screen_lookup[col_date] + pd.offsets.MonthBegin(1)
    weights = weights.merge(
        screen_lookup,
        on=[col_date, col_isin],
        how="left",
    )
    rows_before_returns_filter = len(weights)
    weights = weights[weights[col_sedol].notna()]
    if len(weights) != rows_before_returns_filter:
        weights = normalize_weight_table(
            weights,
            weight_col=COL_PORTFOLIO_WEIGHT,
            group_cols=col_date,
            max_weight=max_weight,
        )
    return weights[
        [col_date, col_sedol, col_isin, COL_PORTFOLIO_WEIGHT, col_sector]
    ].set_index([col_date, col_sedol])


def optimizer_result_to_weight_table(
    result: pd.DataFrame,
    *,
    date_col: str = COL_DATE,
    id_col: str = COL_SEDOL,
    weight_col: str = "target_weight",
) -> pd.DataFrame:
    """Convert optimizer output to the canonical target-weight contract."""

    required = [date_col, id_col, weight_col]
    missing = [column for column in required if column not in result.columns]
    if missing:
        raise KeyError(f"optimizer result is missing required columns: {missing}")
    weights = result.loc[
        pd.to_numeric(result[weight_col], errors="coerce").fillna(0.0) > 0,
        required,
    ].copy()
    weights = weights.rename(
        columns={
            date_col: COL_DATE,
            id_col: COL_SEDOL,
            weight_col: COL_PORTFOLIO_WEIGHT,
        }
    )
    weights[COL_DATE] = pd.to_datetime(weights[COL_DATE])
    weights[COL_SEDOL] = weights[COL_SEDOL].astype(str)
    return normalize_weight_table(
        weights,
        weight_col=COL_PORTFOLIO_WEIGHT,
        group_cols=COL_DATE,
    )


def benchmark_to_weight_table(
    sec_list: pd.DataFrame,
    indice_name: str,
    screen_agg: pd.DataFrame,
    max_weight: float,
    *,
    col_mkt_cap: str = COL_MKT_CAP,
    col_date: str = COL_DATE,
    col_sector: str = COL_SECTOR_ICB19,
    sector_neutral: bool = False,
    method: str = "Market cap",
    col_sedol: str = COL_SEDOL,
    col_isin: str = COL_ISIN,
) -> pd.DataFrame:
    """Build canonical benchmark target weights with legacy semantics."""

    required_columns = [
        col_date,
        col_sedol,
        col_isin,
        col_sector,
        col_mkt_cap,
        f"Weight in {indice_name}",
    ]
    screen = screen_agg.reset_index()
    screen = screen.loc[
        :,
        [column for column in required_columns if column in screen.columns],
    ].copy()
    indice = screen.loc[
        screen[f"Weight in {indice_name}"] > 0,
        [col_date, col_sedol, col_sector, f"Weight in {indice_name}"],
    ].reset_index(drop=True)
    indice = indice.rename(
        columns={f"Weight in {indice_name}": "Indice weight"}
    )
    indice = indice.sort_values(by=col_date)
    selections = sec_list.sort_values(by=col_date).copy()
    indice[col_date] = indice[col_date] + pd.offsets.MonthBegin(1)
    screen[col_date] = screen[col_date] + pd.offsets.MonthBegin(1)
    selections = selections.merge(
        screen[[col_date, col_isin, col_sedol, col_sector, col_mkt_cap]],
        on=[col_date, col_isin],
        how="left",
    )
    selections = selections[selections[col_sedol].notna()]

    if method not in {"EW", "Equalweight"}:
        selections = selections[selections[col_mkt_cap].notna()]
    selections = apply_weighting_transform(
        selections,
        "Equalweight" if method == "EW" else method,
        col_mkt_cap,
    )
    selections[COL_PORTFOLIO_WEIGHT] = selections[col_mkt_cap]
    selections = normalize_weight_table(
        selections,
        weight_col=COL_PORTFOLIO_WEIGHT,
        group_cols=col_date,
    )

    if sector_neutral:
        indice = normalize_weight_table(
            indice,
            weight_col="Indice weight",
            group_cols=col_date,
        )
        sector_targets = (
            indice.groupby([col_date, col_sector], dropna=False)["Indice weight"]
            .sum()
        )
        selections = match_group_weight_targets(
            selections,
            sector_targets,
            weight_col=COL_PORTFOLIO_WEIGHT,
            group_cols=[col_date, col_sector],
        )
        selections = cap_weights_preserving_group_totals(
            selections,
            weight_col=COL_PORTFOLIO_WEIGHT,
            max_weight=max_weight,
            group_cols=[col_date, col_sector],
        )
    else:
        selections = normalize_weight_table(
            selections,
            weight_col=COL_PORTFOLIO_WEIGHT,
            group_cols=col_date,
            max_weight=max_weight,
        )

    return selections[
        [col_date, col_sedol, col_isin, COL_PORTFOLIO_WEIGHT, col_sector]
    ].set_index([col_date, col_sedol])


def benchmark_reference_list(
    screen: pd.DataFrame,
    start_date: pd.Timestamp,
    bench: str,
) -> pd.DataFrame:
    """Return the legacy benchmark security list used by OfficialPortfolioBacktest."""

    reference = screen[
        (screen[COL_DATE] >= start_date)
        & (screen[f"Weight in {bench}"] > 0)
    ].reset_index()[[COL_DATE, COL_ISIN]]
    reference[COL_DATE] = pd.to_datetime(reference[COL_DATE])
    reference[COL_DATE] = reference[COL_DATE] + pd.offsets.MonthBegin(1)
    return reference


def rolling_tracking_error(
    perf_ptf: pd.Series,
    perf_bench: pd.Series,
    *,
    window: int = 21,
    periods_per_year: int = 252,
) -> pd.Series:
    """Calculate annualized rolling tracking error."""

    frame = pd.concat([perf_ptf, perf_bench], axis=1).dropna()
    if frame.shape[1] != 2:
        raise ValueError(
            "perf_ptf and perf_bench must provide exactly two aligned series"
        )
    returns = frame.pct_change().dropna()
    active_return = returns.iloc[:, 0] - returns.iloc[:, 1]
    result = active_return.rolling(window=window).std() * np.sqrt(
        periods_per_year
    )
    result.name = "TE realise"
    return result


def plot_tracking_error(
    perf_ptf: pd.Series,
    perf_bench: pd.Series,
    *,
    constraint_history: Optional[pd.DataFrame] = None,
    window: int = 21,
    save_path: Optional[str] = None,
    show_plot: bool = True,
) -> pd.DataFrame:
    """Plot realized tracking error and optional ex-ante constraints."""

    result = rolling_tracking_error(
        perf_ptf,
        perf_bench,
        window=window,
    ).to_frame()
    if (
        constraint_history is not None
        and "Tracking Error" in constraint_history.columns
    ):
        result = result.merge(
            constraint_history[["Tracking Error"]],
            left_index=True,
            right_index=True,
            how="outer",
        )
        result["Tracking Error"] = result["Tracking Error"].ffill()
        result = result.rename(columns={"Tracking Error": "TE ex-ante"})

    ax = result.plot(
        figsize=(12, 6),
        linewidth=2,
        title="Evolution du Tracking Error",
    )
    ax.set_ylabel("Tracking Error")
    ax.set_ylim(bottom=0)
    figure = ax.get_figure()
    if save_path:
        figure.savefig(save_path, dpi=150, bbox_inches="tight")
    import matplotlib.pyplot as plt

    if show_plot:
        plt.show()
    else:
        plt.close(figure)
    return result


__all__ = [
    "benchmark_reference_list",
    "benchmark_to_weight_table",
    "optimizer_result_to_weight_table",
    "plot_tracking_error",
    "rolling_tracking_error",
    "security_list_to_weight_table",
]

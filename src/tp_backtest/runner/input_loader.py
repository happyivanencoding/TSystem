"""Planification et chargement compact des entrees de backtest."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from tp_core.analytics.backend_routing import reader_engine
from tp_core.analytics.returns_io import available_return_columns, read_returns_matrix
from tp_core.io import read_returns, read_screen_aggregate

from .validators import (
    CANONICAL_COLUMN_ALIASES,
    WEIGHT_PREFIX,
    load_tabular_file,
    prepare_returns_dataframe,
)

MULTI_AVG_SOURCE_COLUMNS = (
    "Growth Avg Percentile",
    "LowVol Avg Percentile",
    "Mom Avg Percentile",
    "Quality Avg Percentile",
    "Value Avg Percentile",
)

OPTIONAL_SCREEN_COLUMNS = (
    "Name",
    " Benchmark ICB Supersector ",
    " Benchmark ICB Industry ",
)


def _unique_strings(values: Iterable[str] | str) -> list[str]:
    if isinstance(values, str):
        values = [values]
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _expanded_metric_columns(metrics: Iterable[str] | str) -> list[str]:
    expanded: list[str] = []
    for metric in _unique_strings(metrics):
        if metric == "Multi Avg Percentile":
            expanded.extend(MULTI_AVG_SOURCE_COLUMNS)
        else:
            expanded.append(metric)
    return list(dict.fromkeys(expanded))


def _first_available_alias(canonical: str, available: set[str]) -> str | None:
    aliases = CANONICAL_COLUMN_ALIASES.get(canonical, [canonical])
    return next((alias for alias in aliases if alias in available), None)


def _normalise_start_date(start_date: str | pd.Timestamp | None) -> pd.Timestamp | None:
    if start_date is None or str(start_date).strip() == "":
        return None
    parsed = pd.to_datetime(start_date, errors="coerce")
    return pd.Timestamp(parsed) if pd.notna(parsed) else None


def _read_screen_parquet(
    path: Path,
    *,
    metrics: list[str],
    benchmarks: list[str],
    start_date: pd.Timestamp | None,
    include_esg: bool,
    extra_screen_columns: Iterable[str],
) -> pd.DataFrame:
    columns = _screen_query_columns(
        path,
        metrics=metrics,
        benchmarks=benchmarks,
        include_esg=include_esg,
        extra_screen_columns=extra_screen_columns,
    )
    filters = [("Date", ">=", start_date)] if start_date is not None else None
    frame = pd.read_parquet(path, columns=columns, filters=filters)
    if start_date is not None:
        dates = pd.to_datetime(frame["Date"], errors="coerce")
        frame = frame.loc[dates >= start_date]
    return frame


def _screen_query_columns(
    path: Path,
    *,
    metrics: list[str],
    benchmarks: list[str],
    include_esg: bool,
    extra_screen_columns: Iterable[str],
) -> list[str]:
    import pyarrow.parquet as pq

    available_order = list(pq.ParquetFile(path).schema_arrow.names)
    available = set(available_order)
    required: list[str] = ["Date", "Company SEDOL"]
    if "ISIN" in available:
        required.append("ISIN")

    market_cap = _first_available_alias(
        "Benchmark Market Value Millions in EUR ",
        available,
    )
    if market_cap is None:
        raise KeyError("Missing screen column: Benchmark Market Value Millions in EUR")
    required.append(market_cap)

    missing_metrics = [metric for metric in metrics if metric not in available]
    if missing_metrics:
        raise KeyError(f"Missing screen metrics: {missing_metrics}")
    required.extend(metrics)

    for benchmark in benchmarks:
        weight_column = f"{WEIGHT_PREFIX}{benchmark}"
        if weight_column not in available:
            raise KeyError(f"Missing benchmark column: {weight_column}")
        required.append(weight_column)

    if include_esg:
        if "ESG_ANALYST_SCORE" not in available:
            raise KeyError("Missing screen column: ESG_ANALYST_SCORE")
        required.append("ESG_ANALYST_SCORE")

    optional = [*OPTIONAL_SCREEN_COLUMNS, *_unique_strings(extra_screen_columns)]
    for column in optional:
        alias = _first_available_alias(column, available)
        if alias is not None:
            required.append(alias)

    requested = set(dict.fromkeys(required))
    return [column for column in available_order if column in requested]


def _read_screen_fallback(
    path: Path,
    *,
    metrics: list[str],
    benchmarks: list[str],
    start_date: pd.Timestamp | None,
    include_esg: bool,
    extra_screen_columns: Iterable[str],
) -> pd.DataFrame:
    frame = load_tabular_file(path)
    available = set(frame.columns)
    required = ["Date", "Company SEDOL"]
    if "ISIN" in available:
        required.append("ISIN")

    market_cap = _first_available_alias(
        "Benchmark Market Value Millions in EUR ",
        available,
    )
    if market_cap is None:
        raise KeyError("Missing screen column: Benchmark Market Value Millions in EUR")
    required.append(market_cap)

    missing_metrics = [metric for metric in metrics if metric not in available]
    if missing_metrics:
        raise KeyError(f"Missing screen metrics: {missing_metrics}")
    required.extend(metrics)

    for benchmark in benchmarks:
        weight_column = f"{WEIGHT_PREFIX}{benchmark}"
        if weight_column not in available:
            raise KeyError(f"Missing benchmark column: {weight_column}")
        required.append(weight_column)

    if include_esg:
        if "ESG_ANALYST_SCORE" not in available:
            raise KeyError("Missing screen column: ESG_ANALYST_SCORE")
        required.append("ESG_ANALYST_SCORE")

    for column in [*OPTIONAL_SCREEN_COLUMNS, *_unique_strings(extra_screen_columns)]:
        alias = _first_available_alias(column, available)
        if alias is not None:
            required.append(alias)

    columns = [column for column in frame.columns if column in set(required)]
    frame = frame.loc[:, columns].copy()
    if start_date is not None:
        dates = pd.to_datetime(frame["Date"], errors="coerce")
        frame = frame.loc[dates >= start_date]
    return frame


def _screen_sedols(
    screen: pd.DataFrame,
    benchmarks: Iterable[str],
) -> set[str]:
    weight_columns = [
        f"{WEIGHT_PREFIX}{benchmark}"
        for benchmark in benchmarks
        if f"{WEIGHT_PREFIX}{benchmark}" in screen.columns
    ]
    universe = screen
    if weight_columns:
        positive_weight = (
            screen[weight_columns]
            .apply(pd.to_numeric, errors="coerce")
            .gt(0)
            .any(axis=1)
        )
        pair_mask = pd.Series(False, index=screen.index)
        try:
            from tp_backtest.utils.constants import ISIN_PAIRS

            isin_values = (
                screen["ISIN"]
                if "ISIN" in screen.columns
                else pd.Series(screen.index, index=screen.index)
            )
            pair_mask = isin_values.isin(ISIN_PAIRS)
        except ImportError:
            pass
        universe = screen.loc[positive_weight | pair_mask]
    return set(
        universe["Company SEDOL"]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda values: values.ne("")]
    )


def _read_returns_parquet(
    path: Path,
    *,
    sedols: set[str],
    start_date: pd.Timestamp | None,
) -> pd.DataFrame:
    columns = available_return_columns(path, sedols)
    frame = read_returns_matrix(
        path,
        columns=columns,
        date_from=start_date,
    )
    return prepare_returns_dataframe(frame)


def _read_returns_fallback(
    path: Path,
    *,
    sedols: set[str],
    start_date: pd.Timestamp | None,
) -> pd.DataFrame:
    frame = prepare_returns_dataframe(load_tabular_file(path))
    columns = [column for column in frame.columns if str(column) in sedols]
    frame = frame.loc[:, columns].copy()
    if start_date is not None:
        frame = frame.loc[frame.index >= start_date]
    return frame


def load_pruned_backtest_inputs(
    screen_path: str | Path,
    returns_path: str | Path,
    *,
    metrics: Iterable[str] | str,
    benchmarks: Iterable[str] | str,
    start_date: str | pd.Timestamp | None = None,
    include_esg: bool = False,
    extra_screen_columns: Iterable[str] = (),
    engine: str | None = None,
    run_type: str = "production",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Charge uniquement la periode, les facteurs et les titres necessaires."""

    screen_file = Path(screen_path)
    returns_file = Path(returns_path)
    metric_columns = _expanded_metric_columns(metrics)
    benchmark_names = _unique_strings(benchmarks)
    parsed_start_date = _normalise_start_date(start_date)
    resolved_engine = reader_engine(
        "screen_full",
        explicit_engine=engine,
        run_type=run_type,
    )

    if resolved_engine != "legacy_parquet" and screen_file.suffix.lower() == ".parquet" and returns_file.suffix.lower() == ".parquet":
        if resolved_engine == "shadow_compare" and parsed_start_date is None:
            raise ValueError("shadow_compare backtest input loads require start_date")
        screen_columns = _screen_query_columns(
            screen_file,
            metrics=metric_columns,
            benchmarks=benchmark_names,
            include_esg=include_esg,
            extra_screen_columns=extra_screen_columns,
        )
        screen = read_screen_aggregate(
            screen_file,
            columns=screen_columns,
            date_from=parsed_start_date,
            engine=resolved_engine,
        )
        sedols = _screen_sedols(screen, benchmark_names)
        return_columns = available_return_columns(returns_file, sorted(sedols))
        returns = read_returns(
            returns_file,
            columns=return_columns,
            date_from=parsed_start_date,
            engine=reader_engine("official_backtest_input", run_type=run_type),
        )
        return screen, prepare_returns_dataframe(returns)

    if screen_file.suffix.lower() == ".parquet":
        screen = _read_screen_parquet(
            screen_file,
            metrics=metric_columns,
            benchmarks=benchmark_names,
            start_date=parsed_start_date,
            include_esg=include_esg,
            extra_screen_columns=extra_screen_columns,
        )
    else:
        screen = _read_screen_fallback(
            screen_file,
            metrics=metric_columns,
            benchmarks=benchmark_names,
            start_date=parsed_start_date,
            include_esg=include_esg,
            extra_screen_columns=extra_screen_columns,
        )

    sedols = _screen_sedols(screen, benchmark_names)
    if returns_file.suffix.lower() == ".parquet":
        returns = _read_returns_parquet(
            returns_file,
            sedols=sedols,
            start_date=parsed_start_date,
        )
    else:
        returns = _read_returns_fallback(
            returns_file,
            sedols=sedols,
            start_date=parsed_start_date,
        )

    if parsed_start_date is not None:
        returns = returns.loc[returns.index >= parsed_start_date]
    return screen, returns

"""Run the preregistered STOXX 600 sparse-core and fixed-sleeve study.

The study deliberately keeps the deployable architecture small:

* one frozen three-leg core;
* zero or one fixed 25% sleeve;
* seven single-variable controls;
* only the pairs and leave-one-out variants needed to support or reject a
  synergy claim.

All official portfolios use ``tp_core.backtesting.OfficialPortfolioBacktest``.
The shared research executor owns gates, resumable shards, waves and deduping.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from math import sqrt
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


SCRIPT_DIR = Path(__file__).resolve().parent
BACKTEST_ROOT = SCRIPT_DIR.parent
TP_ROOT = BACKTEST_ROOT.parent
SRC_ROOT = BACKTEST_ROOT / "src"
OPTIMIZER_ROOT = TP_ROOT / "06_optimiser"
from tp_research.executor import (  # noqa: E402
    GateThresholds,
    RelativeLevelSpec,
    build_same_security_relative_variables,
    dedupe_official_results,
    evaluate_official_top_worst_gate,
    incomplete_official_metrics,
    new_wave_id,
    read_official_results,
    shard_metric_names,
    shard_result_path,
)
from backtest_code.runner.input_loader import load_pruned_backtest_inputs  # noqa: E402
from tp_portfolio import OPTIMIZER_ID, OPTIMIZER_VERSION
from tp_core.backtesting import OfficialPortfolioBacktest, nav_engine_metadata  # noqa: E402


BENCHMARK = "STOXX EUROPE 600"
WEIGHT_COL = f"Weight in {BENCHMARK}"
DATE_COL = "Date"
ISIN_COL = "ISIN"
SEDOL_COL = "Company SEDOL"
SECTOR_COL = " Benchmark ICB Supersector "
MKT_CAP_COL = "Benchmark Market Value Millions in EUR"
PERCENTILE = 0.20
MIN_COVERAGE = 0.75
RESEARCH_START = pd.Timestamp("2009-06-30")
DEFAULT_WORKERS = 8
DEFAULT_SCREEN = TP_ROOT / "00_screen" / "screen_aggregate.parquet"
DEFAULT_RETURNS = TP_ROOT / "00_screen" / "returns.parquet"
DEFAULT_OUTPUT = (
    BACKTEST_ROOT
    / "runs"
    / "ad_hoc"
    / "stoxx600_sparse_core_sleeve_20260723"
)


@dataclass(frozen=True)
class SignalSpec:
    key: str
    metric: str
    raw_column: str
    family: str
    direction: float
    source: str
    economic_role: str
    transform: str = "level"
    lag_observations: int = 0
    role: str = "diagnostic"


SIGNALS: tuple[SignalSpec, ...] = (
    SignalSpec(
        key="revision",
        metric="stoxx600_momentum_eps_revision_ratio_score",
        raw_column="EPS Revision Ratio",
        family="momentum",
        direction=1.0,
        source="local_or_derived",
        economic_role="分析师盈利预期扩散",
        role="core",
    ),
    SignalSpec(
        key="pmom",
        metric="stoxx600_momentum_pmom_12m1m_score",
        raw_column="PMOM 12M1M",
        family="momentum",
        direction=1.0,
        source="local_or_derived",
        economic_role="价格信息扩散",
        role="core",
    ),
    SignalSpec(
        key="quality_improvement",
        metric="stoxx600_reldelta_quality_oper_margin_lag3_score",
        raw_column="Oper Margin",
        family="quality",
        direction=1.0,
        source="FactSet_or_database",
        economic_role="三个月经营利润率改善",
        transform="directional_delta",
        lag_observations=3,
        role="core",
    ),
    SignalSpec(
        key="earnings_yield_improvement",
        metric="stoxx600_reldelta_value_earns_yield_fy1_lag1_score",
        raw_column="Earns Yield FY1",
        family="value",
        direction=1.0,
        source="FactSet_or_database",
        economic_role="一个月远期盈利收益率改善",
        transform="directional_delta",
        lag_observations=1,
        role="sleeve",
    ),
    SignalSpec(
        key="deleveraging",
        metric="stoxx600_reldelta_quality_netdebt_to_ebitda_exfin_lag3_score",
        raw_column="NetDebt to EBITDA exFIN",
        family="quality",
        direction=-1.0,
        source="FactSet_or_database",
        economic_role="三个月去杠杆",
        transform="directional_delta",
        lag_observations=3,
        role="sleeve",
    ),
    SignalSpec(
        key="growth",
        metric="stoxx600_growth_gross_income_growth_fy1_score",
        raw_column="Gross Income Growth FY1",
        family="growth",
        direction=1.0,
        source="FactSet_or_database",
        economic_role="远期毛收入增长",
        role="sleeve",
    ),
    SignalSpec(
        key="dividend",
        metric="stoxx600_dividend_dps_1y_growth_ntm_score",
        raw_column="DPS 1Y Growth NTM",
        family="dividend",
        direction=1.0,
        source="FactSet_or_database",
        economic_role="远期股息增长",
        role="sleeve",
    ),
)

CORE_KEYS = ("revision", "pmom", "quality_improvement")
SLEEVE_KEYS = (
    "earnings_yield_improvement",
    "deleveraging",
    "growth",
    "dividend",
)
SIGNAL_BY_KEY = {spec.key: spec for spec in SIGNALS}
SIGNAL_BY_RAW = {spec.raw_column: spec for spec in SIGNALS}


def parse_csv_arg(raw: str | None, default: Sequence[str]) -> list[str]:
    if not raw or raw.strip().lower() == "all":
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def json_dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def input_fingerprint(path: Path) -> dict[str, object]:
    stat = path.stat()
    parquet = pq.ParquetFile(path)
    return {
        "path": str(path.resolve()),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": file_sha256(path),
        "rows": int(parquet.metadata.num_rows),
        "columns": int(parquet.metadata.num_columns),
        "row_groups": int(parquet.metadata.num_row_groups),
    }


def winsorize_by_date(values: pd.Series, dates: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").replace(
        [np.inf, -np.inf],
        np.nan,
    )
    grouped = numeric.groupby(dates, observed=True)
    lower = grouped.transform(lambda item: item.quantile(0.01))
    upper = grouped.transform(lambda item: item.quantile(0.99))
    return numeric.clip(lower=lower, upper=upper)


def sector_rank_score(
    values: pd.Series,
    dates: pd.Series,
    sectors: pd.Series,
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return (
        numeric.groupby([dates, sectors], observed=True)
        .rank(method="average", pct=True)
        .mul(10.0)
    )


def score_level(
    screen: pd.DataFrame,
    raw_column: str,
    direction: float,
) -> pd.Series:
    directional = (
        pd.to_numeric(screen[raw_column], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .mul(float(direction))
    )
    winsorized = winsorize_by_date(directional, screen[DATE_COL])
    return sector_rank_score(
        winsorized,
        screen[DATE_COL],
        screen[SECTOR_COL],
    )


def strict_equal_score(
    screen: pd.DataFrame,
    components: Sequence[str],
) -> pd.Series:
    values = screen.loc[:, list(components)].apply(pd.to_numeric, errors="coerce")
    return values.mean(axis=1, skipna=False)


def relative_column_name(
    spec: RelativeLevelSpec,
    transform: str,
    lag: int,
) -> str:
    signal = SIGNAL_BY_RAW[spec.raw_column]
    if signal.transform != transform or signal.lag_observations != lag:
        raise ValueError(
            f"unexpected relative request for {spec.raw_column}: "
            f"{transform} lag{lag}"
        )
    return signal.metric


def signal_definition_rows() -> list[dict[str, object]]:
    rows = []
    for spec in SIGNALS:
        rows.append(
            {
                "metric": spec.metric,
                "label": spec.key,
                "candidate_type": "single",
                "bucket": spec.key,
                "components": json.dumps([spec.metric]),
                "component_weights": json.dumps({spec.metric: 1.0}),
                "component_count": 1,
                "parent_metric": "",
                "left_out_component": "",
                "deployable_architecture": False,
                "trial_role": "single_variable_control",
                **asdict(spec),
            }
        )
    return rows


def build_candidate_registry(
    screen: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = signal_definition_rows()
    metric_by_key = {spec.key: spec.metric for spec in SIGNALS}
    seen = set(metric_by_key.values())

    def add(
        metric: str,
        label: str,
        candidate_type: str,
        keys: Sequence[str],
        *,
        parent_metric: str = "",
        left_out_component: str = "",
        deployable: bool = False,
        trial_role: str = "evidence",
    ) -> None:
        if metric in seen:
            return
        components = [metric_by_key[key] for key in keys]
        screen[metric] = strict_equal_score(screen, components)
        weight = 1.0 / len(components)
        rows.append(
            {
                "metric": metric,
                "label": label,
                "candidate_type": candidate_type,
                "bucket": "|".join(keys),
                "components": json.dumps(components),
                "component_weights": json.dumps(
                    {component: weight for component in components}
                ),
                "component_count": len(components),
                "parent_metric": parent_metric,
                "left_out_component": left_out_component,
                "deployable_architecture": bool(deployable),
                "trial_role": trial_role,
                "key": "",
                "raw_column": "",
                "family": "",
                "direction": np.nan,
                "source": "constructed_from_gated_signals",
                "economic_role": "固定等权组合",
                "transform": "strict_equal_mean",
                "lag_observations": 0,
                "role": "architecture" if deployable else "diagnostic",
            }
        )
        seen.add(metric)

    for left_index, left in enumerate(CORE_KEYS):
        for right in CORE_KEYS[left_index + 1 :]:
            add(
                f"stoxx600_core_pair_{left}__{right}",
                f"{left} + {right}",
                "core_pair",
                [left, right],
                trial_role="core_leave_one_out_control",
            )

    core_metric = "stoxx600_sparse_core3_equal"
    add(
        core_metric,
        "shared core: revision + pmom + quality improvement",
        "core_model",
        CORE_KEYS,
        deployable=True,
        trial_role="deployable_no_sleeve",
    )

    for sleeve in SLEEVE_KEYS:
        for core_key in CORE_KEYS:
            add(
                f"stoxx600_pair_{core_key}__{sleeve}",
                f"{core_key} + {sleeve}",
                "core_sleeve_pair",
                [core_key, sleeve],
                parent_metric=f"stoxx600_core3_plus_{sleeve}",
                trial_role="pair_synergy_evidence",
            )

        full_metric = f"stoxx600_core3_plus_{sleeve}"
        full_keys = [*CORE_KEYS, sleeve]
        add(
            full_metric,
            f"shared core + fixed 25% {sleeve} sleeve",
            "core_plus_fixed_sleeve",
            full_keys,
            deployable=True,
            trial_role="deployable_fixed_sleeve",
        )
        for left_out in CORE_KEYS:
            kept = [key for key in full_keys if key != left_out]
            add(
                f"{full_metric}_loo_without_{left_out}",
                f"{sleeve} model without {left_out}",
                "leave_one_out",
                kept,
                parent_metric=full_metric,
                left_out_component=left_out,
                trial_role="full_model_leave_one_out",
            )

    registry = pd.DataFrame(rows)
    if registry["metric"].duplicated().any():
        raise ValueError("candidate registry contains duplicate metric names")
    return screen, registry


def read_canonical_screen(screen_path: Path) -> pd.DataFrame:
    available = set(pq.ParquetFile(screen_path).schema_arrow.names)
    required = [
        DATE_COL,
        ISIN_COL,
        SEDOL_COL,
        "Name",
        SECTOR_COL,
        MKT_CAP_COL,
        WEIGHT_COL,
        *[spec.raw_column for spec in SIGNALS],
    ]
    missing = sorted(set(required).difference(available))
    if missing:
        raise KeyError(f"canonical screen is missing columns: {missing}")
    screen = pd.read_parquet(screen_path, columns=required)
    if ISIN_COL not in screen.columns and screen.index.name == ISIN_COL:
        screen = screen.reset_index()
    screen[DATE_COL] = pd.to_datetime(screen[DATE_COL], errors="coerce")
    screen[WEIGHT_COL] = pd.to_numeric(screen[WEIGHT_COL], errors="coerce")
    return screen


def build_research_screen(
    screen_path: Path,
    output_dir: Path,
    *,
    force: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    research_path = output_dir / "stoxx600_sparse_core_sleeve_screen.parquet"
    registry_path = output_dir / "candidate_registry.csv"
    if research_path.exists() and registry_path.exists() and not force:
        return pd.read_parquet(research_path), pd.read_csv(registry_path)

    canonical = read_canonical_screen(screen_path)
    benchmark = canonical.loc[
        canonical[WEIGHT_COL].gt(0)
        & canonical[DATE_COL].ge(RESEARCH_START)
    ].copy()
    benchmark = benchmark.dropna(
        subset=[DATE_COL, ISIN_COL, SEDOL_COL, SECTOR_COL]
    )
    benchmark = benchmark.sort_values([SEDOL_COL, DATE_COL]).reset_index(
        drop=True
    )

    for spec in SIGNALS:
        if spec.transform == "level":
            benchmark[spec.metric] = score_level(
                benchmark,
                spec.raw_column,
                spec.direction,
            )

    for spec in SIGNALS:
        if spec.transform != "directional_delta":
            continue
        relative_spec = RelativeLevelSpec(
            raw_column=spec.raw_column,
            score_column=f"__level_score_{spec.key}",
            family=spec.family,
            direction=spec.direction,
            role=spec.role,
            source=spec.source,
            note=spec.economic_role,
        )
        benchmark[relative_spec.score_column] = score_level(
            benchmark,
            spec.raw_column,
            spec.direction,
        )
        benchmark, _ = build_same_security_relative_variables(
            benchmark,
            [relative_spec],
            lags=[spec.lag_observations],
            transforms=[spec.transform],
            date_col=DATE_COL,
            security_col=SEDOL_COL,
            sector_col=SECTOR_COL,
            raw_score=lambda frame, item: frame[item.score_column],
            sector_score=sector_rank_score,
            winsorize=winsorize_by_date,
            column_name=relative_column_name,
        )
        benchmark = benchmark.drop(columns=[relative_spec.score_column])

    benchmark, registry = build_candidate_registry(benchmark)
    benchmark = benchmark.sort_values([DATE_COL, ISIN_COL]).reset_index(
        drop=True
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    benchmark.to_parquet(research_path, index=False)
    registry.to_csv(registry_path, index=False)
    return benchmark, registry


def metric_monthly_diagnostics(
    screen: pd.DataFrame,
    metrics: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    monthly_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    universe_by_date = screen.groupby(DATE_COL, observed=True).size()
    for metric in metrics:
        valid = pd.to_numeric(screen[metric], errors="coerce").notna()
        valid_by_date = valid.groupby(screen[DATE_COL], observed=True).sum()
        eligible_dates: list[pd.Timestamp] = []
        for date, universe_count in universe_by_date.items():
            valid_count = int(valid_by_date.get(date, 0))
            target_count = int(round(int(universe_count) * PERCENTILE))
            coverage = valid_count / int(universe_count) if universe_count else np.nan
            disjoint_possible = bool(
                target_count > 0 and valid_count >= 2 * target_count
            )
            eligible = bool(
                coverage >= MIN_COVERAGE and disjoint_possible
            )
            if eligible:
                eligible_dates.append(pd.Timestamp(date))
            monthly_rows.append(
                {
                    "metric": metric,
                    "date": pd.Timestamp(date),
                    "universe_count": int(universe_count),
                    "valid_count": valid_count,
                    "coverage": coverage,
                    "target_count_per_side": target_count,
                    "top_worst_disjoint_possible": disjoint_possible,
                    "eligible_month": eligible,
                }
            )
        overall_valid = int(valid.sum())
        summary_rows.append(
            {
                "metric": metric,
                "coverage": overall_valid / len(screen) if len(screen) else np.nan,
                "non_null_rows": overall_valid,
                "first_date": (
                    min(eligible_dates).strftime("%Y-%m-%d")
                    if eligible_dates
                    else ""
                ),
                "last_date": (
                    max(eligible_dates).strftime("%Y-%m-%d")
                    if eligible_dates
                    else ""
                ),
                "eligible_months": len(eligible_dates),
                "months_disjoint_impossible": int(
                    sum(
                        1
                        for row in monthly_rows
                        if row["metric"] == metric
                        and not row["top_worst_disjoint_possible"]
                    )
                ),
            }
        )
    return pd.DataFrame(monthly_rows), pd.DataFrame(summary_rows)


def audit_data(
    canonical_screen_path: Path,
    returns_path: Path,
    research_screen: pd.DataFrame,
    output_dir: Path,
) -> dict[str, object]:
    canonical = pd.read_parquet(
        canonical_screen_path,
        columns=[
            DATE_COL,
            ISIN_COL,
            SEDOL_COL,
            "Name",
            SECTOR_COL,
            WEIGHT_COL,
        ],
    )
    if ISIN_COL not in canonical.columns and canonical.index.name == ISIN_COL:
        canonical = canonical.reset_index()
    canonical[DATE_COL] = pd.to_datetime(canonical[DATE_COL], errors="coerce")
    canonical[WEIGHT_COL] = pd.to_numeric(
        canonical[WEIGHT_COL],
        errors="coerce",
    )
    benchmark = canonical.loc[canonical[WEIGHT_COL].gt(0)].copy()
    grouped = benchmark.groupby(DATE_COL, observed=True)
    monthly = grouped.agg(
        rows=(ISIN_COL, "size"),
        unique_isins=(ISIN_COL, "nunique"),
        unique_sedols=(SEDOL_COL, "nunique"),
        weight_sum=(WEIGHT_COL, "sum"),
    ).reset_index()
    monthly["missing_isin"] = grouped[ISIN_COL].apply(
        lambda values: int(values.isna().sum())
    ).to_numpy()
    monthly["missing_sedol"] = grouped[SEDOL_COL].apply(
        lambda values: int(values.isna().sum())
    ).to_numpy()
    monthly["missing_sector"] = grouped[SECTOR_COL].apply(
        lambda values: int(values.isna().sum())
    ).to_numpy()
    monthly.to_csv(output_dir / "benchmark_monthly_audit.csv", index=False)

    return_columns = set(pq.ParquetFile(returns_path).schema_arrow.names)
    sedols = benchmark[SEDOL_COL].dropna().astype(str)
    unique_sedols = set(sedols)
    matched_sedols = sorted(unique_sedols.intersection(return_columns))
    returns = pd.read_parquet(returns_path, columns=matched_sedols)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.loc[returns.index.notna()].sort_index()

    period_rows: list[dict[str, object]] = []
    potential_total = 0
    valid_total = 0
    active_min = np.inf
    active_max = -np.inf
    active_gt_100 = 0
    active_lt_minus_100 = 0
    dates = sorted(pd.to_datetime(benchmark[DATE_COL].unique()))
    for index, start in enumerate(dates):
        end = dates[index + 1] if index + 1 < len(dates) else returns.index.max()
        active = (
            benchmark.loc[benchmark[DATE_COL].eq(start), SEDOL_COL]
            .dropna()
            .astype(str)
            .tolist()
        )
        available = [security for security in active if security in returns.columns]
        trading_days = returns.index[
            (returns.index > pd.Timestamp(start))
            & (returns.index <= pd.Timestamp(end))
        ]
        potential = len(trading_days) * len(active)
        values = (
            returns.loc[trading_days, available].to_numpy(dtype=float)
            if len(trading_days) and available
            else np.empty((0, 0))
        )
        finite = values[np.isfinite(values)]
        valid_count = int(finite.size)
        if finite.size:
            active_min = min(active_min, float(finite.min()))
            active_max = max(active_max, float(finite.max()))
            active_gt_100 += int((finite > 1.0).sum())
            active_lt_minus_100 += int((finite < -1.0).sum())
        potential_total += potential
        valid_total += valid_count
        period_rows.append(
            {
                "signal_date": pd.Timestamp(start),
                "next_signal_date": pd.Timestamp(end),
                "trading_days": len(trading_days),
                "active_securities": len(active),
                "matched_return_columns": len(available),
                "potential_security_days": potential,
                "valid_security_days": valid_count,
                "coverage": valid_count / potential if potential else np.nan,
            }
        )
    period_audit = pd.DataFrame(period_rows)
    period_audit.to_csv(
        output_dir / "returns_holding_period_audit.csv",
        index=False,
    )

    benchmark_months = pd.DatetimeIndex(monthly[DATE_COL]).to_period("M")
    complete_months = pd.period_range(
        benchmark_months.min(),
        benchmark_months.max(),
        freq="M",
    )
    missing_months = complete_months.difference(benchmark_months)
    unmatched = benchmark.loc[
        ~benchmark[SEDOL_COL].astype(str).isin(return_columns),
        [DATE_COL, ISIN_COL, SEDOL_COL, "Name"],
    ]
    exceptions: list[dict[str, object]] = []
    for period in missing_months:
        exceptions.append(
            {
                "exception_type": "missing_benchmark_snapshot",
                "date": str(period.end_time.date()),
                "severity": "controlled",
                "handling": "no rebalance; previous portfolio drifts with realized returns",
                "details": "No positive STOXX 600 benchmark weights in this month.",
            }
        )
    for _, row in unmatched.iterrows():
        exceptions.append(
            {
                "exception_type": "benchmark_security_missing_returns",
                "date": str(pd.Timestamp(row[DATE_COL]).date()),
                "severity": "minor",
                "handling": "security unavailable to NAV; retain explicit audit row",
                "details": (
                    f"{row[ISIN_COL]} | {row[SEDOL_COL]} | {row['Name']}"
                ),
            }
        )
    exceptions.extend(
        [
            {
                "exception_type": "financial_publication_timestamp",
                "date": "",
                "severity": "unverified",
                "handling": "do not claim audited filing-date PIT",
                "details": (
                    "Canonical screen has monthly snapshots but no per-row "
                    "publication/announcement timestamp."
                ),
            },
            {
                "exception_type": "historical_fundamental_revision",
                "date": "",
                "severity": "unverified",
                "handling": "treat archived monthly snapshot semantics as source assertion",
                "details": (
                    "Current schema cannot independently prove that vendor "
                    "history was never revised after the original snapshot."
                ),
            },
        ]
    )
    pd.DataFrame(exceptions).to_csv(
        output_dir / "data_quality_exceptions.csv",
        index=False,
    )

    audit = {
        "benchmark": BENCHMARK,
        "benchmark_weight_column": WEIGHT_COL,
        "security_identifier": {
            "screen_primary_key": [ISIN_COL, DATE_COL],
            "returns_join_key": SEDOL_COL,
        },
        "date_field": DATE_COL,
        "screen_rows": int(len(canonical)),
        "screen_start": str(canonical[DATE_COL].min().date()),
        "screen_end": str(canonical[DATE_COL].max().date()),
        "screen_dates": int(canonical[DATE_COL].nunique()),
        "benchmark_rows": int(len(benchmark)),
        "benchmark_start": str(benchmark[DATE_COL].min().date()),
        "benchmark_end": str(benchmark[DATE_COL].max().date()),
        "benchmark_rebalance_snapshots": int(benchmark[DATE_COL].nunique()),
        "benchmark_unique_isins": int(benchmark[ISIN_COL].nunique()),
        "benchmark_unique_sedols": int(benchmark[SEDOL_COL].nunique()),
        "benchmark_names_per_month": {
            "min": int(monthly["unique_isins"].min()),
            "median": float(monthly["unique_isins"].median()),
            "max": int(monthly["unique_isins"].max()),
        },
        "benchmark_weight_sum": {
            "min": float(monthly["weight_sum"].min()),
            "median": float(monthly["weight_sum"].median()),
            "max": float(monthly["weight_sum"].max()),
        },
        "duplicate_date_isin_rows": int(
            benchmark.duplicated([DATE_COL, ISIN_COL], keep=False).sum()
        ),
        "duplicate_date_sedol_rows": int(
            benchmark.duplicated([DATE_COL, SEDOL_COL], keep=False).sum()
        ),
        "missing_benchmark_months": [
            str(period.end_time.date()) for period in missing_months
        ],
        "missing_month_execution_rule": (
            "no rebalance; retain prior holdings and drift with realized returns"
        ),
        "returns_rows": int(len(returns)),
        "returns_start": str(returns.index.min().date()),
        "returns_end": str(returns.index.max().date()),
        "returns_duplicate_dates": int(returns.index.duplicated().sum()),
        "benchmark_sedol_row_column_match": float(
            sedols.isin(return_columns).mean()
        ),
        "benchmark_unique_sedol_column_match": float(
            len(set(matched_sedols)) / len(unique_sedols)
        ),
        "active_security_day_coverage": (
            valid_total / potential_total if potential_total else np.nan
        ),
        "active_return_min": (
            float(active_min) if np.isfinite(active_min) else np.nan
        ),
        "active_return_max": (
            float(active_max) if np.isfinite(active_max) else np.nan
        ),
        "active_returns_gt_100pct": int(active_gt_100),
        "active_returns_lt_minus_100pct": int(active_lt_minus_100),
        "point_in_time_audit": {
            "benchmark_membership": (
                "historical positive benchmark weights by month; pass with "
                "documented early-history intersection limits"
            ),
            "signal_snapshot": (
                "monthly archived FactSet/database snapshot keyed by screen date"
            ),
            "publication_timestamp": "not present; not independently verifiable",
            "lookahead_execution": (
                "first returns date strictly after signal date; target weights "
                "take effect after close"
            ),
            "survivorship": (
                "historical benchmark membership is used; delisted-name coverage "
                "is limited by the historical screen/returns intersection"
            ),
        },
        "research_screen_rows": int(len(research_screen)),
        "research_start": str(RESEARCH_START.date()),
    }
    json_dump(output_dir / "data_audit_summary.json", audit)
    return audit


def read_nav(path_text: str) -> pd.Series:
    path = Path(path_text)
    if not path.exists():
        return pd.Series(dtype=float)
    frame = pd.read_parquet(path)
    if isinstance(frame, pd.Series):
        result = frame
    elif frame.shape[1]:
        result = frame.iloc[:, 0]
    else:
        return pd.Series(dtype=float)
    result.index = pd.to_datetime(result.index, errors="coerce")
    return pd.to_numeric(result, errors="coerce").dropna().sort_index()


def save_series(series: pd.Series, path: Path, name: str) -> None:
    output = pd.Series(series, name=name)
    output.index.name = DATE_COL
    output.to_frame().to_parquet(path)


def safe_frame(value: object) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        frame = value.copy()
    elif isinstance(value, pd.Series):
        frame = value.to_frame()
    else:
        return pd.DataFrame()
    if any(name is not None for name in frame.index.names):
        frame = frame.reset_index()
    return frame


def run_one_official(
    *,
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    metric: str,
    side: str,
    start_date: str,
    run_dir: Path,
    monthly_base_cache: dict,
    benchmark_cache: dict,
) -> dict[str, object]:
    run_dir.mkdir(parents=True, exist_ok=False)
    record: dict[str, object] = {
        "benchmark": BENCHMARK,
        "metric": metric,
        "side": side,
        "top": side == "Top",
        "start_date": start_date,
        "status": "failed",
        "message": "",
        "run_dir": str(run_dir),
        "sec_list": str(run_dir / "sec_list.parquet"),
        "weights": str(run_dir / "weights.parquet"),
        "exclusions": str(run_dir / "exclusions.parquet"),
        "perf_ptf": str(run_dir / "perf_ptf.parquet"),
        "perf_bench": str(run_dir / "perf_bench.parquet"),
    }
    try:
        builder = OfficialPortfolioBacktest(
            screen=screen,
            returns=returns,
            bench=BENCHMARK,
            percentile=PERCENTILE,
            metrics=metric,
            ptf_name=f"STOXX600_{hashlib.sha1(metric.encode()).hexdigest()[:10]}_{side}",
            ponderation="Market cap",
            esg_exclusion=0.0,
            cut_mkt_cap=0.0,
            score_neutral="ICB 19",
            weight_neutral="ICB 19",
            Top=side == "Top",
            multiprocessing=False,
            mode_monthly_prod=False,
            copy_inputs=False,
            monthly_base_cache=monthly_base_cache,
            benchmark_cache=benchmark_cache,
        )
        builder.build_historical_security_lists(
            start_date=pd.Timestamp(start_date),
            freq_rebal=None,
            screen_start_date=None,
            fill_method="drift",
        )
        builder.run_portfolio_nav(max_weight=1.0, sector_neutral=False)
        builder.run_benchmark_nav(builder.screen, builder.start_date, BENCHMARK)

        safe_frame(builder.sec_list_historical).to_parquet(record["sec_list"])
        safe_frame(builder.buy_list).to_parquet(record["weights"])
        safe_frame(builder.list_exclusion_histo).to_parquet(
            record["exclusions"]
        )
        save_series(builder.perf_ptf, Path(record["perf_ptf"]), "NAV")
        save_series(builder.perf_bench, Path(record["perf_bench"]), "NAV")
        engine = nav_engine_metadata(
            strictly_after_rebalance=True,
            apply_weights_at_close=True,
        )
        json_dump(
            run_dir / "run_metadata.json",
            {
                **engine,
                "benchmark": BENCHMARK,
                "metric": metric,
                "side": side,
                "start_date": start_date,
                "fill_method": "drift",
                "missing_month_rule": (
                    "no rebalance; previous portfolio drifts with realized returns"
                ),
                "ponderation": "Market cap",
                "score_neutral": "ICB 19",
                "weight_neutral": "ICB 19",
                "percentile": PERCENTILE,
                "optimizer_used": False,
                "optimizer_id": OPTIMIZER_ID,
                "optimizer_version": OPTIMIZER_VERSION,
                "optimizer_objective": "not_applicable_factor_sort_evidence",
            },
        )
        record["status"] = "success"
        record["message"] = "official unified API run completed"
    except Exception as exc:
        record["message"] = f"{type(exc).__name__}: {exc}"
        (run_dir / "error.txt").write_text(record["message"], encoding="utf-8")
    return record


def worker_run(payload: Mapping[str, object]) -> dict[str, object]:
    metrics = [str(value) for value in payload["metrics"]]
    screen_path = Path(str(payload["screen_path"]))
    returns_path = Path(str(payload["returns_path"]))
    shard_path = Path(str(payload["shard_path"]))
    output_dir = Path(str(payload["output_dir"]))
    wave = str(payload["wave"])
    shard_id = int(payload["shard_id"])
    start_dates = {
        str(key): str(value)
        for key, value in dict(payload["start_dates"]).items()
    }
    screen, returns = load_pruned_backtest_inputs(
        screen_path,
        returns_path,
        metrics=metrics,
        benchmarks=BENCHMARK,
        include_esg=False,
    )
    if ISIN_COL not in screen.columns and screen.index.name == ISIN_COL:
        screen = screen.reset_index()
    screen[DATE_COL] = pd.to_datetime(screen[DATE_COL], errors="coerce")
    monthly_base_cache: dict = {}
    benchmark_cache: dict = {}
    records: list[dict[str, object]] = []
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    for metric in metrics:
        for side in ("Top", "Worst"):
            digest = hashlib.sha1(f"{metric}|{side}".encode()).hexdigest()[:12]
            run_dir = (
                output_dir
                / "official_runs"
                / wave
                / f"shard_{shard_id:02d}"
                / digest
            )
            records.append(
                run_one_official(
                    screen=screen,
                    returns=returns,
                    metric=metric,
                    side=side,
                    start_date=start_dates[metric],
                    run_dir=run_dir,
                    monthly_base_cache=monthly_base_cache,
                    benchmark_cache=benchmark_cache,
                )
            )
            pd.DataFrame(records).to_csv(shard_path, index=False)
    return {
        "shard_id": shard_id,
        "metrics": len(metrics),
        "records": len(records),
        "success": int(
            sum(record["status"] == "success" for record in records)
        ),
        "path": str(shard_path),
    }


def nav_stats(nav: pd.Series) -> dict[str, float]:
    nav = nav.dropna().sort_index()
    if len(nav) < 30:
        return {}
    daily = nav.pct_change().dropna()
    years = max((nav.index[-1] - nav.index[0]).days / 365.25, 1e-9)
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1.0 / years) - 1.0
    vol = daily.std() * sqrt(252)
    return {
        "days": int(len(nav)),
        "cagr": float(cagr),
        "vol": float(vol),
        "sharpe": float(cagr / vol) if vol else np.nan,
        "max_drawdown": float((nav / nav.cummax() - 1.0).min()),
    }


def relative_stats(nav: pd.Series, benchmark: pd.Series) -> dict[str, float]:
    aligned = pd.concat(
        [nav.rename("nav"), benchmark.rename("benchmark")],
        axis=1,
    ).dropna()
    if len(aligned) < 30:
        return {}
    ratio = aligned["nav"] / aligned["benchmark"]
    years = max((ratio.index[-1] - ratio.index[0]).days / 365.25, 1e-9)
    active = (
        aligned["nav"].pct_change()
        - aligned["benchmark"].pct_change()
    ).dropna()
    tracking_error = active.std() * sqrt(252)
    annual = aligned.resample("YE").last().pct_change().dropna()
    rolling_min = np.nan
    if len(ratio) >= 756:
        rolling = ratio / ratio.shift(756)
        rolling = rolling.dropna().pow(252 / 756).sub(1)
        if not rolling.empty:
            rolling_min = float(rolling.min())
    return {
        "ratio_return": float(ratio.iloc[-1] / ratio.iloc[0] - 1.0),
        "ratio_cagr": float(
            (ratio.iloc[-1] / ratio.iloc[0]) ** (1.0 / years) - 1.0
        ),
        "ratio_max_drawdown": float(
            (ratio / ratio.cummax() - 1.0).min()
        ),
        "tracking_error": float(tracking_error),
        "information_ratio": (
            float(active.mean() * 252 / tracking_error)
            if tracking_error
            else np.nan
        ),
        "rolling_3y_min_ratio_cagr": rolling_min,
        "annual_active_hit_rate": (
            float((annual["nav"] > annual["benchmark"]).mean())
            if not annual.empty
            else np.nan
        ),
    }


def average_turnover(path_text: str) -> float:
    path = Path(path_text)
    if not path.exists():
        return np.nan
    frame = pd.read_parquet(path)
    if DATE_COL not in frame.columns:
        return np.nan
    id_col = ISIN_COL if ISIN_COL in frame.columns else SEDOL_COL
    weight_col = "Weight" if "Weight" in frame.columns else "Portfolio weight"
    prior: pd.Series | None = None
    values: list[float] = []
    for _, group in frame.groupby(DATE_COL, sort=True):
        current = (
            group.drop_duplicates(id_col, keep="last")
            .set_index(id_col)[weight_col]
            .astype(float)
        )
        if prior is not None:
            aligned = pd.concat(
                [prior.rename("prior"), current.rename("current")],
                axis=1,
            ).fillna(0.0)
            values.append(
                float((aligned["current"] - aligned["prior"]).abs().sum() / 2)
            )
        prior = current
    return float(np.mean(values)) if values else np.nan


def average_holdings(path_text: str) -> float:
    path = Path(path_text)
    if not path.exists():
        return np.nan
    frame = pd.read_parquet(path)
    if DATE_COL not in frame.columns:
        return np.nan
    return float(frame.groupby(DATE_COL, observed=True).size().mean())


def summarize_official_runs(
    results: pd.DataFrame,
    diagnostics: pd.DataFrame,
) -> pd.DataFrame:
    diagnostic_map = diagnostics.set_index("metric").to_dict(orient="index")
    rows: list[dict[str, object]] = []
    for _, run in results.iterrows():
        row = {
            "benchmark": run.get("benchmark", BENCHMARK),
            "metric": run["metric"],
            "side": run["side"],
            "status": run["status"],
            "message": run.get("message", ""),
            "start_date": run.get("start_date", ""),
            "run_dir": run.get("run_dir", ""),
            **diagnostic_map.get(str(run["metric"]), {}),
        }
        if run["status"] == "success":
            nav = read_nav(str(run["perf_ptf"]))
            bench = read_nav(str(run["perf_bench"]))
            row.update(nav_stats(nav))
            row.update(relative_stats(nav, bench))
            row["avg_turnover"] = average_turnover(str(run["sec_list"]))
            row["avg_holdings"] = average_holdings(str(run["sec_list"]))
            row["perf_ptf"] = run["perf_ptf"]
            row["perf_bench"] = run["perf_bench"]
            row["sec_list"] = run["sec_list"]
        rows.append(row)
    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary

    pair_rows: list[dict[str, object]] = []
    for metric, group in summary.loc[
        summary["status"].eq("success")
    ].groupby("metric", observed=True):
        top = group.loc[group["side"].eq("Top")]
        worst = group.loc[group["side"].eq("Worst")]
        if top.empty or worst.empty:
            continue
        top_row = top.iloc[-1]
        worst_row = worst.iloc[-1]
        top_nav = read_nav(str(top_row["perf_ptf"]))
        worst_nav = read_nav(str(worst_row["perf_ptf"]))
        aligned = pd.concat(
            [top_nav.rename("top"), worst_nav.rename("worst")],
            axis=1,
        ).dropna()
        top_worst_return = np.nan
        top_worst_mdd = np.nan
        if len(aligned) >= 2:
            ratio = aligned["top"] / aligned["worst"]
            top_worst_return = float(
                ratio.iloc[-1] / ratio.iloc[0] - 1.0
            )
            top_worst_mdd = float(
                (ratio / ratio.cummax() - 1.0).min()
            )
        robust_score = (
            np.nan_to_num(top_row.get("ratio_return"), nan=0.0)
            + 0.5 * np.nan_to_num(top_worst_return, nan=0.0)
            - 2.0
            * abs(
                np.nan_to_num(
                    top_row.get("ratio_max_drawdown"),
                    nan=0.0,
                )
            )
            - np.nan_to_num(top_row.get("tracking_error"), nan=0.0)
            - abs(
                min(
                    np.nan_to_num(
                        top_row.get("rolling_3y_min_ratio_cagr"),
                        nan=0.0,
                    ),
                    0.0,
                )
            )
        )
        pair_rows.append(
            {
                "metric": metric,
                "top_worst_ratio_return": top_worst_return,
                "top_worst_ratio_max_drawdown": top_worst_mdd,
                "worst_ratio_return": worst_row.get("ratio_return", np.nan),
                "robust_score": float(robust_score),
            }
        )
    if pair_rows:
        summary = summary.merge(pd.DataFrame(pair_rows), on="metric", how="left")
    return summary


def build_synergy_evidence(
    summary: pd.DataFrame,
    gate: pd.DataFrame,
    registry: pd.DataFrame,
) -> pd.DataFrame:
    top = (
        summary.loc[
            summary["side"].eq("Top") & summary["status"].eq("success")
        ]
        .drop_duplicates("metric", keep="last")
        .set_index("metric")
    )
    gate_map = gate.set_index("metric")["pass_gate"].to_dict()
    evidence_rows: list[dict[str, object]] = []
    core_metric = "stoxx600_sparse_core3_equal"
    for sleeve in SLEEVE_KEYS:
        sleeve_metric = SIGNAL_BY_KEY[sleeve].metric
        full_metric = f"stoxx600_core3_plus_{sleeve}"
        pair_metrics = [
            f"stoxx600_pair_{core_key}__{sleeve}"
            for core_key in CORE_KEYS
        ]
        loo_rows = registry.loc[
            registry["parent_metric"].eq(full_metric)
            & registry["candidate_type"].eq("leave_one_out")
        ]
        required = [core_metric, sleeve_metric, full_metric, *pair_metrics]
        required.extend(loo_rows["metric"].astype(str).tolist())
        complete = all(metric in top.index for metric in required)
        if not complete:
            evidence_rows.append(
                {
                    "sleeve": sleeve,
                    "core_metric": core_metric,
                    "sleeve_metric": sleeve_metric,
                    "full_metric": full_metric,
                    "evidence_complete": False,
                    "classification": "incomplete",
                    "reason": "missing official Top evidence",
                }
            )
            continue
        core = top.loc[core_metric]
        single = top.loc[sleeve_metric]
        full = top.loc[full_metric]
        pair_gate_passes = int(
            sum(bool(gate_map.get(metric, False)) for metric in pair_metrics)
        )
        loo_metrics = loo_rows["metric"].astype(str).tolist()
        loo_robust = [
            float(top.loc[metric, "robust_score"]) for metric in loo_metrics
        ]
        all_single_gates = all(
            bool(gate_map.get(SIGNAL_BY_KEY[key].metric, False))
            for key in [*CORE_KEYS, sleeve]
        )
        full_gate = bool(gate_map.get(full_metric, False))
        core_gate = bool(gate_map.get(core_metric, False))
        ratio_beats_core = (
            float(full["ratio_cagr"]) > float(core["ratio_cagr"])
        )
        ratio_beats_sleeve = (
            float(full["ratio_cagr"]) > float(single["ratio_cagr"])
        )
        robust_beats_core = (
            float(full["robust_score"]) > float(core["robust_score"])
        )
        robust_beats_all_core_leg_loo = all(
            float(full["robust_score"]) > value for value in loo_robust
        )
        strict = bool(
            all_single_gates
            and core_gate
            and full_gate
            and pair_gate_passes >= 2
            and ratio_beats_core
            and ratio_beats_sleeve
            and robust_beats_core
            and robust_beats_all_core_leg_loo
        )
        additive = bool(
            all_single_gates
            and core_gate
            and full_gate
            and pair_gate_passes >= 1
            and (
                ratio_beats_core
                or robust_beats_core
                or robust_beats_all_core_leg_loo
            )
        )
        classification = (
            "strict_synergy"
            if strict
            else "additive_or_diversifying"
            if additive
            else "no_synergy_support"
        )
        evidence_rows.append(
            {
                "sleeve": sleeve,
                "core_metric": core_metric,
                "sleeve_metric": sleeve_metric,
                "full_metric": full_metric,
                "evidence_complete": True,
                "all_single_gates_pass": all_single_gates,
                "core_gate_pass": core_gate,
                "full_gate_pass": full_gate,
                "pair_gate_passes": pair_gate_passes,
                "pair_gate_total": len(pair_metrics),
                "full_ratio_cagr": float(full["ratio_cagr"]),
                "core_ratio_cagr": float(core["ratio_cagr"]),
                "sleeve_ratio_cagr": float(single["ratio_cagr"]),
                "full_robust_score": float(full["robust_score"]),
                "core_robust_score": float(core["robust_score"]),
                "max_core_leg_loo_robust_score": max(loo_robust),
                "ratio_beats_core": ratio_beats_core,
                "ratio_beats_sleeve": ratio_beats_sleeve,
                "robust_beats_core": robust_beats_core,
                "robust_beats_all_core_leg_loo": (
                    robust_beats_all_core_leg_loo
                ),
                "classification": classification,
                "reason": (
                    "Synergy requires singles, pair, subset and leave-one-out "
                    "evidence; no label is inferred from the full model alone."
                ),
            }
        )
    return pd.DataFrame(evidence_rows)


def verify_missing_month_drift(results: pd.DataFrame) -> pd.DataFrame:
    preferred = results.loc[
        results["metric"].eq(SIGNAL_BY_KEY["revision"].metric)
        & results["side"].eq("Top")
        & results["status"].eq("success")
    ]
    if preferred.empty:
        return pd.DataFrame(
            [
                {
                    "missing_signal_month": "2009-11-30",
                    "verified": False,
                    "reason": "revision control run unavailable",
                }
            ]
        )
    sec = pd.read_parquet(preferred.iloc[-1]["sec_list"])
    sec[DATE_COL] = pd.to_datetime(sec[DATE_COL], errors="coerce")
    dates = set(sec[DATE_COL].dropna())
    expected_drift_date = pd.Timestamp("2009-12-01")
    prior_date = pd.Timestamp("2009-11-01")
    prior_ids = set(
        sec.loc[sec[DATE_COL].eq(prior_date), ISIN_COL].astype(str)
    )
    drift_ids = set(
        sec.loc[sec[DATE_COL].eq(expected_drift_date), ISIN_COL].astype(str)
    )
    prior_weights = (
        sec.loc[
            sec[DATE_COL].eq(prior_date),
            [ISIN_COL, "Weight"],
        ]
        .assign(Weight=lambda frame: pd.to_numeric(frame["Weight"], errors="coerce"))
        .set_index(ISIN_COL)["Weight"]
    )
    drift_weights = (
        sec.loc[
            sec[DATE_COL].eq(expected_drift_date),
            [ISIN_COL, "Weight"],
        ]
        .assign(Weight=lambda frame: pd.to_numeric(frame["Weight"], errors="coerce"))
        .set_index(ISIN_COL)["Weight"]
    )
    aligned_weights = pd.concat(
        [
            prior_weights.rename("prior"),
            drift_weights.rename("drift"),
        ],
        axis=1,
    )
    changed_weights = int(
        (
            aligned_weights["prior"] - aligned_weights["drift"]
        ).abs().gt(1e-12).sum()
    )
    normalized = bool(
        np.isclose(prior_weights.sum(), 1.0, atol=1e-8)
        and np.isclose(drift_weights.sum(), 1.0, atol=1e-8)
    )
    verified = bool(
        prior_ids
        and drift_ids
        and prior_ids == drift_ids
        and expected_drift_date in dates
        and changed_weights > 0
        and normalized
    )
    return pd.DataFrame(
        [
            {
                "missing_signal_month": "2009-11-30",
                "prior_effective_date": str(prior_date.date()),
                "drift_effective_date": str(expected_drift_date.date()),
                "prior_holdings": len(prior_ids),
                "drift_holdings": len(drift_ids),
                "same_security_set": prior_ids == drift_ids,
                "changed_weight_count": changed_weights,
                "prior_weight_sum": float(prior_weights.sum()),
                "drift_weight_sum": float(drift_weights.sum()),
                "weights_normalized": normalized,
                "verified": verified,
                "reason": (
                    "No new benchmark snapshot; same holdings retained and "
                    "weights drifted with realized returns."
                ),
            }
        ]
    )


def markdown_table(frame: pd.DataFrame, columns: Sequence[str], limit: int = 20) -> str:
    if frame.empty:
        return "无可用记录。"
    return frame.reindex(columns=list(columns)).head(limit).to_markdown(
        index=False
    )


def write_report(
    *,
    output_dir: Path,
    audit: Mapping[str, object],
    registry: pd.DataFrame,
    gate: pd.DataFrame,
    summary: pd.DataFrame,
    synergy: pd.DataFrame,
    drift_check: pd.DataFrame,
) -> Path:
    top = summary.loc[
        summary["side"].eq("Top") & summary["status"].eq("success")
    ].copy()
    top = top.merge(
        registry[
            [
                "metric",
                "label",
                "candidate_type",
                "deployable_architecture",
            ]
        ],
        on="metric",
        how="left",
    )
    top = top.merge(
        gate[["metric", "pass_gate", "fail_reasons"]],
        on="metric",
        how="left",
    )
    deployable = top.loc[top["deployable_architecture"].fillna(False)].sort_values(
        "robust_score",
        ascending=False,
    )
    singles = top.loc[top["candidate_type"].eq("single")].sort_values(
        "robust_score",
        ascending=False,
    )
    report = f"""# STOXX Europe 600 稀疏 Core 与固定 Sleeve 研究

## 研究状态

本轮是预注册的低自由度验证，不是对全部组合的事后暴力搜索。运行前锁定
`{len(registry)}` 个唯一指标，其中可部署架构只有 5 个：一个三腿静态 core，
以及四个“core + 单一固定 25% sleeve”。其余指标只用于 raw control、pair 和
leave-one-out 证据。任何 synergy 判断都要求单变量、pair、完整组合与
leave-one-out 同时具备官方 Top/Worst 结果。

## 数据与执行口径

- Benchmark 权重列：`{WEIGHT_COL}`
- 证券主键：`(ISIN, Date)`；收益连接键：`Company SEDOL`
- Benchmark 历史：{audit['benchmark_start']} 至 {audit['benchmark_end']}，
  {audit['benchmark_rebalance_snapshots']} 个有效截面
- 每月成分数：{audit['benchmark_names_per_month']}
- 持仓证券日收益覆盖率：{audit['active_security_day_coverage']:.4%}
- 2009-11 缺失截面：不调仓，上一期组合按真实收益漂移；验证结果见
  `missing_month_drift_check.csv`
- NAV：`tp.security_nav 3.0.0`，signal date 之后首个收益日开始执行，
  权重在当日收盘收益后生效
- 优化器：本轮因子排序证据不调用优化器；如进入组合优化，唯一允许入口为
  `tp.optimizer 3.0.0 / optimize_portfolio()`

财务字段没有逐行公告日或 publication timestamp。因此，月度快照和历史
benchmark 成分是 point-in-time 的，但“每个财报值在当时已公开”无法由当前
schema 独立复核，本报告把它保留为明确的未验证风险，而不是写成已通过。

## 单变量

{markdown_table(
    singles,
    [
        'label',
        'coverage',
        'ratio_cagr',
        'top_worst_ratio_return',
        'robust_score',
        'avg_turnover',
        'pass_gate',
    ],
)}

## 可部署架构

{markdown_table(
    deployable,
    [
        'label',
        'coverage',
        'ratio_cagr',
        'top_worst_ratio_return',
        'robust_score',
        'avg_turnover',
        'pass_gate',
    ],
)}

## 协同证据

{markdown_table(
    synergy,
    [
        'sleeve',
        'pair_gate_passes',
        'pair_gate_total',
        'full_ratio_cagr',
        'core_ratio_cagr',
        'sleeve_ratio_cagr',
        'robust_beats_all_core_leg_loo',
        'classification',
    ],
)}

`strict_synergy` 只在完整证据链全部通过时出现；
`additive_or_diversifying` 不是 synergy 声明；`no_synergy_support` 表示组合
可能仍通过绝对 gate，但没有证据证明变量之间存在协同。

## 已知边界

1. 这仍是历史样本验证，不是 2026-07 之后的真实未来 OOS。
2. 候选来自既有研究，因此本轮属于受约束的再验证；最终选择仍需 nested
   regime、walk-forward、DSR 与 PBO。
3. 缺失值保持 NaN。Top/Worst 必须有足够有效证券且可构造互斥组合，不以
   中性值填充来强行扩大样本。
4. 2009 年早段的 benchmark 历史是 point-in-time workbook 与历史 screen
   的交集，主模型因三期相对变量自然从 2010 年开始。
"""
    path = output_dir / "stoxx600_sparse_core_sleeve_report.md"
    path.write_text(report, encoding="utf-8")
    return path


def collect_result_paths(output_dir: Path) -> list[Path]:
    paths = [
        output_dir / "official_run_results.csv",
        output_dir / "admission_skips.csv",
    ]
    paths.extend(
        sorted(
            output_dir.glob(
                "parallel_shards/*/shard_*/official_run_results.csv"
            )
        )
    )
    return paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen", type=Path, default=DEFAULT_SCREEN)
    parser.add_argument("--returns", type=Path, default=DEFAULT_RETURNS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--metrics", default="all")
    parser.add_argument("--max-runs", type=int, default=0)
    parser.add_argument("--wave")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--force-build", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    research_screen_path = (
        output_dir / "stoxx600_sparse_core_sleeve_screen.parquet"
    )

    fingerprints_path = output_dir / "input_fingerprints.json"
    current_fingerprints = {
        "screen": input_fingerprint(args.screen.resolve()),
        "returns": input_fingerprint(args.returns.resolve()),
    }
    if fingerprints_path.exists():
        prior = json.loads(fingerprints_path.read_text(encoding="utf-8"))
        if prior != current_fingerprints:
            raise RuntimeError(
                "Input fingerprint changed. Use a new output directory; "
                "completed shards cannot be mixed across data versions."
            )
    else:
        json_dump(fingerprints_path, current_fingerprints)

    screen, registry = build_research_screen(
        args.screen.resolve(),
        output_dir,
        force=args.force_build,
    )
    metrics = registry["metric"].astype(str).tolist()
    requested = parse_csv_arg(args.metrics, metrics)
    unknown = sorted(set(requested).difference(metrics))
    if unknown:
        raise KeyError(f"unknown metrics requested: {unknown}")

    monthly_diagnostics, diagnostics = metric_monthly_diagnostics(
        screen,
        metrics,
    )
    monthly_diagnostics.to_csv(
        output_dir / "candidate_monthly_coverage.csv",
        index=False,
    )
    diagnostics.to_csv(output_dir / "metric_diagnostics.csv", index=False)
    start_dates = diagnostics.set_index("metric")["first_date"].to_dict()
    missing_starts = [
        metric for metric in requested if not str(start_dates.get(metric, ""))
    ]
    if missing_starts:
        prior_unstartable = read_official_results(
            [output_dir / "admission_skips.csv"]
        )
        unstartable_records = prior_unstartable.to_dict("records")
        known_unstartable = {
            (str(row.get("metric")), str(row.get("side")))
            for row in unstartable_records
        }
        for metric in missing_starts:
            for side in ("Top", "Worst"):
                if (metric, side) in known_unstartable:
                    continue
                unstartable_records.append(
                    {
                        "benchmark": BENCHMARK,
                        "metric": metric,
                        "side": side,
                        "top": side == "Top",
                        "start_date": "",
                        "status": "skipped",
                        "message": (
                            "no eligible month satisfies minimum coverage "
                            "and disjoint Top/Worst construction"
                        ),
                        "run_dir": "",
                        "sec_list": "",
                        "weights": "",
                        "exclusions": "",
                        "perf_ptf": "",
                        "perf_bench": "",
                    }
                )
        dedupe_official_results(pd.DataFrame(unstartable_records)).to_csv(
            output_dir / "admission_skips.csv",
            index=False,
        )

    audit = audit_data(
        args.screen.resolve(),
        args.returns.resolve(),
        screen,
        output_dir,
    )
    engine = nav_engine_metadata(
        strictly_after_rebalance=True,
        apply_weights_at_close=True,
    )
    preregistration = {
        "created_at": datetime.now().isoformat(),
        "research_question": (
            "Can a frozen three-leg shared core be improved by at most one "
            "fixed 25% economically distinct sleeve without relying on a "
            "high-capacity model?"
        ),
        "core_keys": list(CORE_KEYS),
        "sleeve_keys": list(SLEEVE_KEYS),
        "missing_value_policy": "keep NaN; never impute neutral score",
        "research_start": str(RESEARCH_START.date()),
        "selection_fraction": PERCENTILE,
        "minimum_coverage": MIN_COVERAGE,
        "admission_sequence": (
            "complete all required single-variable official Top/Worst runs; "
            "apply raw gate; only then admit composites whose every component "
            "passed"
        ),
        "synergy_rule": (
            "Singles, pairs, full model and leave-one-out must all have "
            "official evidence before a synergy label is allowed."
        ),
        "candidate_count": len(registry),
        "deployable_architecture_count": int(
            registry["deployable_architecture"].sum()
        ),
        "engine": engine,
        "optimizer": {
            "optimizer_used": False,
            "optimizer_id": OPTIMIZER_ID,
            "optimizer_version": OPTIMIZER_VERSION,
            "objective": "not_applicable_factor_sort_evidence",
            "constraint_policy": (
                "Top/Worst 20%; market-cap weighting; ICB19 score and "
                "weight neutrality; no post-optimizer processing"
            ),
        },
    }
    json_dump(output_dir / "preregistration.json", preregistration)

    if args.build_only:
        print(
            json.dumps(
                {
                    "status": "built",
                    "output_dir": str(output_dir),
                    "candidate_count": len(registry),
                },
                ensure_ascii=False,
            )
        )
        return 0

    wave = new_wave_id(args.wave)
    worker_results: list[dict[str, object]] = []
    launched_run_count = 0

    def launch_stage(stage_metrics: Sequence[str], stage_name: str) -> None:
        nonlocal launched_run_count
        existing_stage = read_official_results(collect_result_paths(output_dir))
        pending_stage = incomplete_official_metrics(
            stage_metrics,
            existing_stage,
        )
        pending_stage = [
            metric
            for metric in pending_stage
            if str(start_dates.get(metric, ""))
        ]
        if args.max_runs > 0:
            remaining_runs = max(0, int(args.max_runs) - launched_run_count)
            pending_stage = pending_stage[: remaining_runs // 2]
        if not pending_stage:
            return
        stage_wave = f"{wave}_{stage_name}"
        worker_count = max(
            1,
            min(int(args.workers), len(pending_stage)),
        )
        shards = shard_metric_names(pending_stage, worker_count)
        payloads = []
        for shard_id, shard in enumerate(shards):
            payloads.append(
                {
                    "metrics": shard,
                    "screen_path": str(research_screen_path),
                    "returns_path": str(args.returns.resolve()),
                    "shard_path": str(
                        shard_result_path(
                            output_dir,
                            stage_wave,
                            shard_id,
                        )
                    ),
                    "output_dir": str(output_dir),
                    "wave": stage_wave,
                    "shard_id": shard_id,
                    "start_dates": {
                        metric: start_dates[metric] for metric in shard
                    },
                }
            )
        stage_results: list[dict[str, object]] = []
        if len(payloads) == 1:
            stage_results.append(worker_run(payloads[0]))
        else:
            with ProcessPoolExecutor(max_workers=len(payloads)) as executor:
                futures = [
                    executor.submit(worker_run, payload) for payload in payloads
                ]
                for future in as_completed(futures):
                    stage_results.append(future.result())
        launched_run_count += 2 * len(pending_stage)
        for result in stage_results:
            result["stage"] = stage_name
        worker_results.extend(stage_results)

    requested_rows = registry.loc[
        registry["metric"].astype(str).isin(requested)
    ]
    required_single_metrics: list[str] = []
    for raw_components in requested_rows["components"]:
        for component in json.loads(str(raw_components)):
            if component not in required_single_metrics:
                required_single_metrics.append(component)

    launch_stage(required_single_metrics, "raw")

    after_raw = read_official_results(collect_result_paths(output_dir))
    raw_results = after_raw.loc[
        after_raw["metric"].astype(str).isin(required_single_metrics)
    ].copy()
    raw_summary = summarize_official_runs(raw_results, diagnostics)
    raw_gate = evaluate_official_top_worst_gate(
        raw_summary,
        diagnostics,
        thresholds=GateThresholds(
            min_coverage=MIN_COVERAGE,
            min_ratio_cagr=0.0,
            min_top_worst_ratio=0.0,
            min_robust_score=0.0,
        ),
        metadata=registry,
        metrics=required_single_metrics,
    )
    raw_gate.to_csv(output_dir / "raw_admission_gate.csv", index=False)
    raw_pass = raw_gate.set_index("metric")["pass_gate"].to_dict()

    admission_rows: list[dict[str, object]] = []
    for _, candidate in registry.iterrows():
        metric = str(candidate["metric"])
        components = json.loads(str(candidate["components"]))
        if candidate["candidate_type"] == "single":
            admitted = bool(raw_pass.get(metric, False))
            reason = (
                "single_passed_official_gate"
                if admitted
                else "single_failed_or_incomplete_official_gate"
            )
        else:
            failed_components = [
                component
                for component in components
                if not bool(raw_pass.get(component, False))
            ]
            admitted = not failed_components
            reason = (
                "all_raw_components_passed"
                if admitted
                else "blocked_by_raw_gate:"
                + "|".join(failed_components)
            )
        admission_rows.append(
            {
                "metric": metric,
                "candidate_type": candidate["candidate_type"],
                "components": candidate["components"],
                "admitted": admitted,
                "admission_reason": reason,
            }
        )
    admission = pd.DataFrame(admission_rows)
    admission.to_csv(output_dir / "candidate_admission.csv", index=False)
    admission_map = admission.set_index("metric")["admitted"].to_dict()

    blocked = [
        metric
        for metric in requested
        if registry.set_index("metric").loc[metric, "candidate_type"] != "single"
        and not bool(admission_map.get(metric, False))
    ]
    prior_skips = read_official_results(
        [output_dir / "admission_skips.csv"]
    )
    skip_records = prior_skips.to_dict("records")
    known_skips = {
        (str(row.get("metric")), str(row.get("side")))
        for row in skip_records
    }
    admission_reason_map = admission.set_index("metric")[
        "admission_reason"
    ].to_dict()
    for metric in blocked:
        for side in ("Top", "Worst"):
            if (metric, side) in known_skips:
                continue
            skip_records.append(
                {
                    "benchmark": BENCHMARK,
                    "metric": metric,
                    "side": side,
                    "top": side == "Top",
                    "start_date": str(start_dates.get(metric, "")),
                    "status": "skipped",
                    "message": admission_reason_map[metric],
                    "run_dir": "",
                    "sec_list": "",
                    "weights": "",
                    "exclusions": "",
                    "perf_ptf": "",
                    "perf_bench": "",
                }
            )
    if skip_records:
        dedupe_official_results(pd.DataFrame(skip_records)).to_csv(
            output_dir / "admission_skips.csv",
            index=False,
        )

    admitted_composites = [
        metric
        for metric in requested
        if registry.set_index("metric").loc[metric, "candidate_type"] != "single"
        and bool(admission_map.get(metric, False))
    ]
    launch_stage(admitted_composites, "composite")

    all_results = read_official_results(collect_result_paths(output_dir))
    all_results = dedupe_official_results(all_results)
    all_results.to_csv(output_dir / "official_run_results.csv", index=False)
    selected_results = all_results.loc[
        all_results["metric"].astype(str).isin(requested)
    ].copy()
    summary = summarize_official_runs(selected_results, diagnostics)
    summary.to_csv(output_dir / "performance_summary.csv", index=False)

    gate = evaluate_official_top_worst_gate(
        summary,
        diagnostics,
        thresholds=GateThresholds(
            min_coverage=MIN_COVERAGE,
            min_ratio_cagr=0.0,
            min_top_worst_ratio=0.0,
            min_robust_score=0.0,
        ),
        metadata=registry,
        metrics=requested,
    )
    gate.to_csv(output_dir / "official_validation_gate.csv", index=False)
    synergy = build_synergy_evidence(summary, gate, registry)
    synergy.to_csv(output_dir / "synergy_evidence.csv", index=False)
    drift_check = verify_missing_month_drift(selected_results)
    drift_check.to_csv(
        output_dir / "missing_month_drift_check.csv",
        index=False,
    )
    report_path = write_report(
        output_dir=output_dir,
        audit=audit,
        registry=registry,
        gate=gate,
        summary=summary,
        synergy=synergy,
        drift_check=drift_check,
    )
    completed = {
        (str(row["metric"]), str(row["side"]))
        for _, row in selected_results.loc[
            selected_results["status"].isin(["success", "skipped"])
        ].iterrows()
    }
    expected = {(metric, side) for metric in requested for side in ("Top", "Worst")}
    manifest = {
        **engine,
        "status": "complete" if completed == expected else "partial",
        "created_at": datetime.now().isoformat(),
        "output_dir": str(output_dir),
        "screen": str(args.screen.resolve()),
        "returns": str(args.returns.resolve()),
        "research_screen": str(research_screen_path),
        "benchmark": BENCHMARK,
        "metrics": requested,
        "candidate_count": len(requested),
        "expected_official_runs": len(expected),
        "terminal_official_runs": len(completed),
        "success_count": int(
            selected_results["status"].eq("success").sum()
        ),
        "gate_pass_count": int(gate["pass_gate"].sum()) if not gate.empty else 0,
        "strict_synergy_count": int(
            synergy["classification"].eq("strict_synergy").sum()
        )
        if not synergy.empty
        else 0,
        "wave": wave,
        "worker_results": worker_results,
        "resume": bool(args.resume),
        "report": str(report_path),
        "optimizer_id": OPTIMIZER_ID,
        "optimizer_version": OPTIMIZER_VERSION,
        "optimizer_used": False,
        "optimizer_objective": "not_applicable_factor_sort_evidence",
        "constraint_policy": (
            "Top/Worst 20%; market-cap weighting; ICB19 score and "
            "weight neutrality; missing months drift"
        ),
    }
    json_dump(output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())

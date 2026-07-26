"""Run immutable lag-6 relative-variable supplements for TP factor markets.

The frozen lag-1/3/12 definition table is the experiment registry source.  This
runner adds only lag 6, runs every new variable through official exact
Top/Worst evidence, and keeps benchmark identity explicit in worker payloads.
"""

from __future__ import annotations
from tp_research.runtime import recorded_workflow

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from tp_research.paths import BACKTEST_ROOT, TP_ROOT

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
from tp_backtest.runner.input_loader import load_pruned_backtest_inputs  # noqa: E402
from tp_core.backtesting import (  # noqa: E402
    OfficialPortfolioBacktest,
    nav_engine_metadata,
)


DATE_COL = "Date"
ISIN_COL = "ISIN"
SEDOL_COL = "Company SEDOL"
SECTOR_COL = " Benchmark ICB Supersector "
MKT_CAP_COL = "Benchmark Market Value Millions in EUR"
PERCENTILE = 0.20
MIN_COVERAGE = 0.75
LAG = 6
TRANSFORMS = ("directional_delta", "score_delta")
DEFAULT_SCREEN = TP_ROOT / "00_screen" / "screen_aggregate.parquet"
DEFAULT_RETURNS = TP_ROOT / "00_screen" / "returns.parquet"
AD_HOC_ROOT = BACKTEST_ROOT / "runs" / "ad_hoc"


@dataclass(frozen=True)
class MarketProfile:
    key: str
    display_name: str
    benchmark: str
    output_prefix: str
    frozen_relative_run: str
    output_name: str
    research_start: str

    @property
    def weight_col(self) -> str:
        return f"Weight in {self.benchmark}"


PROFILES: dict[str, MarketProfile] = {
    "nasdaq": MarketProfile(
        key="nasdaq",
        display_name="NASDAQ Composite",
        benchmark="NASDAQ COMP",
        output_prefix="nasdaq",
        frozen_relative_run="nasdaq_relative_variables_20260709",
        output_name="nasdaq_relative_lag6_20260725",
        research_start="2013-12-31",
    ),
    "sp500": MarketProfile(
        key="sp500",
        display_name="S&P 500",
        benchmark="SP500",
        output_prefix="sp500",
        frozen_relative_run="sp500_relative_variables_20260709",
        output_name="sp500_relative_lag6_20260725",
        research_start="2004-10-31",
    ),
    "eu-small": MarketProfile(
        key="eu-small",
        display_name="MSCI Europe Small",
        benchmark="MSCI EUR SMALL",
        output_prefix="eu_small",
        frozen_relative_run="eu_small_relative_variables_20260709",
        output_name="eu_small_relative_lag6_20260725",
        research_start="2005-03-31",
    ),
}


@dataclass(frozen=True)
class LevelSpec:
    raw_column: str
    family: str
    role: str
    source: str
    direction: float
    note: str


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
    resolved = path.resolve()
    stat = resolved.stat()
    payload: dict[str, object] = {
        "path": str(resolved),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": file_sha256(resolved),
    }
    if resolved.suffix.lower() == ".parquet":
        parquet = pq.ParquetFile(resolved)
        payload.update(
            {
                "rows": int(parquet.metadata.num_rows),
                "columns": int(parquet.metadata.num_columns),
                "row_groups": int(parquet.metadata.num_row_groups),
            }
        )
    return payload


def ensure_input_fingerprints(
    output_dir: Path,
    *,
    screen_path: Path,
    returns_path: Path,
    registry_source: Path,
) -> dict[str, object]:
    path = output_dir / "input_fingerprints.json"
    current = {
        "screen": input_fingerprint(screen_path),
        "returns": input_fingerprint(returns_path),
        "frozen_registry_source": input_fingerprint(registry_source),
    }
    if path.exists():
        prior = json.loads(path.read_text(encoding="utf-8"))
        if prior != current:
            raise RuntimeError(
                "input fingerprints changed; preserve this run and use a new "
                "output directory instead of resuming"
            )
    else:
        json_dump(path, current)
    return current


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def frozen_definition_path(profile: MarketProfile) -> Path:
    return (
        AD_HOC_ROOT
        / profile.frozen_relative_run
        / "relative_variable_definitions.csv"
    )


def load_level_specs(profile: MarketProfile) -> tuple[LevelSpec, ...]:
    definitions = pd.read_csv(frozen_definition_path(profile))
    required = {
        "raw_column",
        "base_family",
        "role",
        "source",
        "base_direction",
        "base_note",
    }
    missing = required.difference(definitions.columns)
    if missing:
        raise KeyError(f"frozen definitions missing columns: {sorted(missing)}")
    rows = (
        definitions.sort_values(["raw_column", "lag_observations", "transform"])
        .drop_duplicates("raw_column", keep="first")
    )
    return tuple(
        LevelSpec(
            raw_column=str(row.raw_column),
            family=str(row.base_family),
            role=str(row.role),
            source=str(row.source),
            direction=float(row.base_direction),
            note=str(row.base_note),
        )
        for row in rows.itertuples(index=False)
    )


def relative_metric(
    profile: MarketProfile,
    spec: LevelSpec,
    transform: str,
) -> str:
    prefix = "reldelta" if transform == "directional_delta" else "relrank"
    return (
        f"{profile.output_prefix}_{prefix}_{slugify(spec.family)}_"
        f"{slugify(spec.raw_column)}_lag{LAG}_score"
    )


def winsorize_by_date(values: pd.Series, dates: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").replace(
        [np.inf, -np.inf], np.nan
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
    return sector_rank_score(
        winsorize_by_date(directional, screen[DATE_COL]),
        screen[DATE_COL],
        screen[SECTOR_COL],
    )


def build_registry(
    profile: MarketProfile,
    definitions: pd.DataFrame,
    level_specs: Sequence[LevelSpec],
) -> pd.DataFrame:
    spec_by_raw = {spec.raw_column: spec for spec in level_specs}
    rows: list[dict[str, object]] = []
    for definition in definitions.itertuples(index=False):
        spec = spec_by_raw[str(definition.raw_column)]
        transform = str(definition.transform)
        metric = str(definition.metric)
        rows.append(
            {
                "metric": metric,
                "label": f"{spec.raw_column} {transform} lag{LAG}",
                "candidate_type": "single",
                "bucket": spec.raw_column,
                "components": json.dumps([metric]),
                "component_count": 1,
                "raw_column": spec.raw_column,
                "family": spec.family,
                "direction": spec.direction,
                "source": spec.source,
                "economic_role": spec.note,
                "transform": transform,
                "lag_observations": LAG,
                "role": spec.role,
                "trial_role": "lag6_relative_raw_control",
            }
        )
    registry = pd.DataFrame(rows)
    expected = 2 * len(level_specs)
    if len(registry) != expected:
        raise ValueError(f"expected {expected} lag6 variants, got {len(registry)}")
    if registry["metric"].duplicated().any():
        raise ValueError("lag6 registry contains duplicate metric names")
    return registry


def build_research_screen(
    profile: MarketProfile,
    screen_path: Path,
    output_dir: Path,
    *,
    force: bool,
) -> tuple[Path, pd.DataFrame, pd.DataFrame]:
    output_path = output_dir / f"{profile.output_prefix}_lag6_screen.parquet"
    registry_path = output_dir / "candidate_registry.csv"
    definitions_path = output_dir / "relative_variable_definitions.csv"
    if (
        output_path.exists()
        and registry_path.exists()
        and definitions_path.exists()
        and not force
    ):
        return output_path, pd.read_csv(registry_path), pd.read_csv(definitions_path)

    level_specs = load_level_specs(profile)
    available = set(pq.ParquetFile(screen_path).schema_arrow.names)
    required = [
        DATE_COL,
        ISIN_COL,
        SEDOL_COL,
        "Name",
        SECTOR_COL,
        MKT_CAP_COL,
        profile.weight_col,
        *[spec.raw_column for spec in level_specs],
    ]
    missing = sorted(set(required).difference(available))
    if missing:
        raise KeyError(f"canonical screen missing columns: {missing}")
    screen = pd.read_parquet(screen_path, columns=list(dict.fromkeys(required)))
    if ISIN_COL not in screen.columns and screen.index.name == ISIN_COL:
        screen = screen.reset_index()
    screen[DATE_COL] = pd.to_datetime(screen[DATE_COL], errors="coerce")
    screen[profile.weight_col] = pd.to_numeric(
        screen[profile.weight_col], errors="coerce"
    )
    screen = screen.loc[
        screen[profile.weight_col].gt(0)
        & screen[DATE_COL].ge(pd.Timestamp(profile.research_start))
    ].copy()
    screen = screen.dropna(subset=[DATE_COL, ISIN_COL, SEDOL_COL, SECTOR_COL])
    screen = screen.sort_values([ISIN_COL, DATE_COL]).reset_index(drop=True)

    relative_specs: list[RelativeLevelSpec] = []
    hidden_columns: list[str] = []
    spec_by_raw = {spec.raw_column: spec for spec in level_specs}
    for index, spec in enumerate(level_specs):
        hidden = f"__lag6_level_score_{index:02d}"
        screen[hidden] = score_level(screen, spec.raw_column, spec.direction)
        hidden_columns.append(hidden)
        relative_specs.append(
            RelativeLevelSpec(
                raw_column=spec.raw_column,
                score_column=hidden,
                family=spec.family,
                direction=spec.direction,
                role=spec.role,
                source=spec.source,
                note=spec.note,
            )
        )
    screen, definitions = build_same_security_relative_variables(
        screen,
        relative_specs,
        lags=[LAG],
        transforms=list(TRANSFORMS),
        date_col=DATE_COL,
        security_col=ISIN_COL,
        sector_col=SECTOR_COL,
        raw_score=lambda frame, item: frame[item.score_column],
        sector_score=sector_rank_score,
        winsorize=winsorize_by_date,
        column_name=lambda item, transform, lag: relative_metric(
            profile,
            spec_by_raw[item.raw_column],
            transform,
        ),
    )
    screen = screen.drop(columns=hidden_columns)
    registry = build_registry(profile, definitions, level_specs)
    output_dir.mkdir(parents=True, exist_ok=True)
    screen.to_parquet(output_path, index=False)
    registry.to_csv(registry_path, index=False)
    definitions.to_csv(definitions_path, index=False)
    return output_path, registry, definitions


def metric_diagnostics(
    screen_path: Path,
    metrics: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    screen = pd.read_parquet(screen_path, columns=[DATE_COL, *metrics])
    universe_by_date = screen.groupby(DATE_COL, observed=True).size()
    monthly_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    for metric in metrics:
        valid = pd.to_numeric(screen[metric], errors="coerce").notna()
        valid_by_date = valid.groupby(screen[DATE_COL], observed=True).sum()
        eligible_dates: list[pd.Timestamp] = []
        impossible = 0
        for date, universe_count in universe_by_date.items():
            valid_count = int(valid_by_date.get(date, 0))
            target_count = int(round(int(universe_count) * PERCENTILE))
            coverage = valid_count / int(universe_count)
            disjoint = target_count > 0 and valid_count >= 2 * target_count
            eligible = coverage >= MIN_COVERAGE and disjoint
            impossible += int(not disjoint)
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
                    "top_worst_disjoint_possible": disjoint,
                    "eligible_month": eligible,
                }
            )
        non_null = int(valid.sum())
        summary_rows.append(
            {
                "metric": metric,
                "coverage": non_null / len(screen) if len(screen) else np.nan,
                "non_null_rows": non_null,
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
                "months_disjoint_impossible": impossible,
            }
        )
    return pd.DataFrame(monthly_rows), pd.DataFrame(summary_rows)


def construction_checks(
    profile: MarketProfile,
    screen_path: Path,
    registry: pd.DataFrame,
    diagnostics: pd.DataFrame,
) -> pd.DataFrame:
    screen = pd.read_parquet(
        screen_path,
        columns=[
            DATE_COL,
            ISIN_COL,
            SEDOL_COL,
            profile.weight_col,
            *registry["metric"].astype(str).tolist(),
        ],
    )
    checks: list[dict[str, object]] = []

    def add(check: str, value: object, status: str, details: str = "") -> None:
        checks.append(
            {
                "check": check,
                "value": value,
                "status": status,
                "details": details,
            }
        )

    dates = pd.to_datetime(screen[DATE_COL], errors="coerce")
    duplicate_rows = int(screen.duplicated([DATE_COL, ISIN_COL], keep=False).sum())
    weights = pd.to_numeric(screen[profile.weight_col], errors="coerce")
    metric_values = screen[registry["metric"].astype(str).tolist()].apply(
        pd.to_numeric,
        errors="coerce",
    )
    finite_or_nan = bool(
        (
            np.isfinite(metric_values.to_numpy(dtype=float, na_value=np.nan))
            | metric_values.isna().to_numpy()
        ).all()
    )
    add("research_rows", len(screen), "pass" if len(screen) else "fail")
    add("research_dates", int(dates.nunique()), "pass" if dates.nunique() else "fail")
    add(
        "date_range",
        f"{dates.min().date()}..{dates.max().date()}",
        "pass" if dates.notna().all() else "fail",
    )
    add(
        "unique_isin",
        int(screen[ISIN_COL].nunique()),
        "pass" if screen[ISIN_COL].notna().all() else "fail",
    )
    add(
        "unique_sedol",
        int(screen[SEDOL_COL].nunique()),
        "pass" if screen[SEDOL_COL].notna().all() else "fail",
    )
    add(
        "duplicate_date_isin_rows",
        duplicate_rows,
        "pass" if duplicate_rows == 0 else "fail",
    )
    add(
        "positive_benchmark_weights",
        int(weights.gt(0).sum()),
        "pass" if weights.gt(0).all() else "fail",
    )
    add(
        "candidate_count",
        len(registry),
        "pass" if len(registry) == 2 * registry["raw_column"].nunique() else "fail",
        "exactly directional_delta and score_delta for every level field",
    )
    add(
        "candidate_columns_present",
        int(metric_values.shape[1]),
        "pass" if metric_values.shape[1] == len(registry) else "fail",
    )
    add(
        "candidate_values_finite_or_nan",
        finite_or_nan,
        "pass" if finite_or_nan else "fail",
    )
    add(
        "metric_coverage_min",
        float(diagnostics["coverage"].min()),
        "diagnostic",
    )
    add(
        "metric_coverage_median",
        float(diagnostics["coverage"].median()),
        "diagnostic",
    )
    add(
        "coverage_blocked_metrics",
        int(diagnostics["first_date"].fillna("").eq("").sum()),
        "diagnostic",
    )
    return pd.DataFrame(checks)


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
    profile: MarketProfile,
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
        "benchmark": profile.benchmark,
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
            bench=profile.benchmark,
            percentile=PERCENTILE,
            metrics=metric,
            ptf_name=(
                f"{profile.output_prefix}_{hashlib.sha1(metric.encode()).hexdigest()[:8]}"
                f"_{side}"
            ),
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
        builder.run_benchmark_nav(builder.screen, builder.start_date, profile.benchmark)
        safe_frame(builder.sec_list_historical).to_parquet(record["sec_list"])
        safe_frame(builder.buy_list).to_parquet(record["weights"])
        safe_frame(builder.list_exclusion_histo).to_parquet(record["exclusions"])
        save_series(builder.perf_ptf, Path(record["perf_ptf"]), "NAV")
        save_series(builder.perf_bench, Path(record["perf_bench"]), "NAV")
        json_dump(
            run_dir / "run_metadata.json",
            {
                **nav_engine_metadata(
                    strictly_after_rebalance=True,
                    apply_weights_at_close=True,
                ),
                "benchmark": profile.benchmark,
                "metric": metric,
                "side": side,
                "start_date": start_date,
                "fill_method": "drift",
                "missing_month_rule": (
                    "no rebalance; previous portfolio drifts with realized returns"
                ),
                "optimizer_used": False,
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
    profile = MarketProfile(**dict(payload["profile"]))
    metrics = [str(value) for value in payload["metrics"]]
    start_dates = {
        str(key): str(value) for key, value in dict(payload["start_dates"]).items()
    }
    screen, returns = load_pruned_backtest_inputs(
        Path(str(payload["screen_path"])),
        Path(str(payload["returns_path"])),
        metrics=metrics,
        benchmarks=profile.benchmark,
        include_esg=False,
    )
    screen[DATE_COL] = pd.to_datetime(screen[DATE_COL], errors="coerce")
    monthly_base_cache: dict = {}
    benchmark_cache: dict = {}
    records: list[dict[str, object]] = []
    shard_path = Path(str(payload["shard_path"]))
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    for metric in metrics:
        for side in ("Top", "Worst"):
            digest = hashlib.sha1(f"{metric}|{side}".encode()).hexdigest()[:12]
            run_dir = (
                Path(str(payload["output_dir"]))
                / "official_runs"
                / str(payload["wave"])
                / f"shard_{int(payload['shard_id']):02d}"
                / digest
            )
            records.append(
                run_one_official(
                    profile=profile,
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
        "shard_id": int(payload["shard_id"]),
        "records": len(records),
        "success": sum(row["status"] == "success" for row in records),
        "path": str(shard_path),
    }


def read_nav(path_text: str) -> pd.Series:
    path = Path(path_text)
    if not path.exists():
        return pd.Series(dtype=float)
    frame = pd.read_parquet(path)
    series = frame.iloc[:, 0] if isinstance(frame, pd.DataFrame) else frame
    series.index = pd.to_datetime(series.index, errors="coerce")
    return pd.to_numeric(series, errors="coerce").dropna().sort_index()


def nav_stats(nav: pd.Series) -> dict[str, float]:
    if len(nav) < 30:
        return {}
    daily = nav.pct_change().dropna()
    years = max((nav.index[-1] - nav.index[0]).days / 365.25, 1e-9)
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1.0 / years) - 1.0
    vol = daily.std() * np.sqrt(252.0)
    return {
        "days": len(nav),
        "cagr": cagr,
        "vol": vol,
        "sharpe": cagr / vol if vol else np.nan,
        "max_drawdown": float((nav / nav.cummax() - 1.0).min()),
    }


def relative_stats(nav: pd.Series, benchmark: pd.Series) -> dict[str, float]:
    aligned = pd.concat(
        [nav.rename("nav"), benchmark.rename("benchmark")], axis=1
    ).dropna()
    if len(aligned) < 30:
        return {}
    ratio = aligned["nav"] / aligned["benchmark"]
    years = max((ratio.index[-1] - ratio.index[0]).days / 365.25, 1e-9)
    active = aligned["nav"].pct_change() - aligned["benchmark"].pct_change()
    tracking_error = active.dropna().std() * np.sqrt(252.0)
    annual = aligned.resample("YE").last().pct_change().dropna()
    rolling_min = np.nan
    if len(ratio) >= 756:
        rolling = ratio.div(ratio.shift(756)).dropna().pow(252 / 756).sub(1)
        if not rolling.empty:
            rolling_min = float(rolling.min())
    return {
        "ratio_return": float(ratio.iloc[-1] / ratio.iloc[0] - 1.0),
        "ratio_cagr": float(
            (ratio.iloc[-1] / ratio.iloc[0]) ** (1.0 / years) - 1.0
        ),
        "ratio_max_drawdown": float((ratio / ratio.cummax() - 1.0).min()),
        "tracking_error": float(tracking_error),
        "rolling_3y_min_ratio_cagr": rolling_min,
        "annual_active_hit_rate": (
            float((annual["nav"] > annual["benchmark"]).mean())
            if not annual.empty
            else np.nan
        ),
    }


def average_holdings(path_text: str) -> float:
    path = Path(path_text)
    if not path.exists():
        return np.nan
    frame = pd.read_parquet(path)
    return float(frame.groupby(DATE_COL, observed=True).size().mean())


def average_turnover(path_text: str) -> float:
    path = Path(path_text)
    if not path.exists():
        return np.nan
    frame = pd.read_parquet(path)
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
                [prior.rename("prior"), current.rename("current")], axis=1
            ).fillna(0.0)
            values.append(float((aligned.current - aligned.prior).abs().sum() / 2))
        prior = current
    return float(np.mean(values)) if values else np.nan


def summarize_runs(
    results: pd.DataFrame,
    diagnostics: pd.DataFrame,
) -> pd.DataFrame:
    diagnostic_map = diagnostics.set_index("metric").to_dict("index")
    rows: list[dict[str, object]] = []
    for run in results.itertuples(index=False):
        raw = run._asdict()
        row = {
            "benchmark": raw.get("benchmark", ""),
            "metric": raw["metric"],
            "side": raw["side"],
            "status": raw["status"],
            "message": raw.get("message", ""),
            "start_date": raw.get("start_date", ""),
            "run_dir": raw.get("run_dir", ""),
            **diagnostic_map.get(str(raw["metric"]), {}),
        }
        if raw["status"] == "success":
            nav = read_nav(str(raw["perf_ptf"]))
            bench = read_nav(str(raw["perf_bench"]))
            row.update(nav_stats(nav))
            row.update(relative_stats(nav, bench))
            row["avg_turnover"] = average_turnover(str(raw["sec_list"]))
            row["avg_holdings"] = average_holdings(str(raw["sec_list"]))
            row["perf_ptf"] = raw["perf_ptf"]
            row["perf_bench"] = raw["perf_bench"]
            row["sec_list"] = raw["sec_list"]
        rows.append(row)
    summary = pd.DataFrame(rows)
    pair_rows: list[dict[str, object]] = []
    for metric, group in summary[summary["status"].eq("success")].groupby("metric"):
        top = group[group["side"].eq("Top")]
        worst = group[group["side"].eq("Worst")]
        if top.empty or worst.empty:
            continue
        top_row, worst_row = top.iloc[-1], worst.iloc[-1]
        aligned = pd.concat(
            [
                read_nav(str(top_row.perf_ptf)).rename("top"),
                read_nav(str(worst_row.perf_ptf)).rename("worst"),
            ],
            axis=1,
        ).dropna()
        top_worst_return = np.nan
        top_worst_mdd = np.nan
        if len(aligned) >= 2:
            ratio = aligned.top / aligned.worst
            top_worst_return = float(ratio.iloc[-1] / ratio.iloc[0] - 1)
            top_worst_mdd = float((ratio / ratio.cummax() - 1).min())
        robust = (
            np.nan_to_num(top_row.get("ratio_return"), nan=0.0)
            + 0.5 * np.nan_to_num(top_worst_return, nan=0.0)
            - 2.0 * abs(np.nan_to_num(top_row.get("ratio_max_drawdown"), nan=0.0))
            - np.nan_to_num(top_row.get("tracking_error"), nan=0.0)
            - abs(
                min(
                    np.nan_to_num(
                        top_row.get("rolling_3y_min_ratio_cagr"), nan=0.0
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
                "robust_score": float(robust),
            }
        )
    if pair_rows:
        summary = summary.merge(pd.DataFrame(pair_rows), on="metric", how="left")
    return summary


def collect_result_paths(output_dir: Path) -> list[Path]:
    return [
        output_dir / "official_run_results.csv",
        output_dir / "admission_skips.csv",
        *output_dir.glob("parallel_shards/*/shard_*/official_run_results.csv"),
    ]


def audit_inputs(
    profile: MarketProfile,
    canonical_path: Path,
    returns_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    canonical = pd.read_parquet(
        canonical_path,
        columns=[DATE_COL, ISIN_COL, SEDOL_COL, SECTOR_COL, profile.weight_col],
    )
    if ISIN_COL not in canonical.columns and canonical.index.name == ISIN_COL:
        canonical = canonical.reset_index()
    canonical[DATE_COL] = pd.to_datetime(canonical[DATE_COL], errors="coerce")
    canonical[profile.weight_col] = pd.to_numeric(
        canonical[profile.weight_col], errors="coerce"
    )
    benchmark = canonical[canonical[profile.weight_col].gt(0)].copy()
    monthly = (
        benchmark.groupby(DATE_COL, observed=True)
        .agg(
            rows=(ISIN_COL, "size"),
            securities=(ISIN_COL, "nunique"),
            sedols=(SEDOL_COL, "nunique"),
            weight_sum=(profile.weight_col, "sum"),
        )
        .reset_index()
    )
    monthly.to_csv(output_dir / "benchmark_monthly_audit.csv", index=False)
    monthly_dates = pd.DatetimeIndex(monthly[DATE_COL]).sort_values()
    yearly_rows: list[dict[str, object]] = []
    observed_periods = set(monthly_dates.to_period("M"))
    scheduled_missing: list[pd.Period] = []
    for year in range(monthly_dates.min().year, monthly_dates.max().year + 1):
        dates = monthly_dates[monthly_dates.year == year]
        count = len(dates)
        if count >= 8:
            cadence = "monthly"
            expected = pd.period_range(f"{year}-01", f"{year}-12", freq="M")
        elif count >= 3:
            cadence = "quarterly_or_irregular"
            expected = pd.PeriodIndex([], freq="M")
        elif count:
            cadence = "sparse_or_partial"
            expected = pd.PeriodIndex([], freq="M")
        else:
            cadence = "data_gap"
            expected = pd.PeriodIndex([], freq="M")
        expected = expected[
            (expected >= monthly_dates.min().to_period("M"))
            & (expected <= monthly_dates.max().to_period("M"))
        ]
        missing = [period for period in expected if period not in observed_periods]
        scheduled_missing.extend(missing)
        yearly_rows.append(
            {
                "year": year,
                "snapshot_count": count,
                "cadence": cadence,
                "first_snapshot": str(dates.min().date()) if count else "",
                "last_snapshot": str(dates.max().date()) if count else "",
                "missing_monthly_schedule_count": len(missing),
                "missing_monthly_schedule": ",".join(str(item) for item in missing),
            }
        )
    pd.DataFrame(yearly_rows).to_csv(
        output_dir / "benchmark_frequency_audit.csv",
        index=False,
    )
    consecutive = pd.DataFrame(
        {
            "prior_date": monthly_dates[:-1],
            "next_date": monthly_dates[1:],
        }
    )
    consecutive["gap_days"] = (
        consecutive["next_date"] - consecutive["prior_date"]
    ).dt.days
    consecutive["gap_months"] = [
        right.ordinal - left.ordinal
        for left, right in zip(
            consecutive["prior_date"].dt.to_period("M"),
            consecutive["next_date"].dt.to_period("M"),
        )
    ]
    consecutive.to_csv(output_dir / "benchmark_snapshot_gaps.csv", index=False)
    return_columns = set(pq.ParquetFile(returns_path).schema_arrow.names)
    unique_sedols = set(benchmark[SEDOL_COL].dropna().astype(str))
    matched_sedols = sorted(unique_sedols & return_columns)
    returns = pd.read_parquet(returns_path, columns=matched_sedols)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.loc[
        (returns.index >= monthly_dates.min())
        & (returns.index <= monthly_dates.max())
    ]
    available_days = returns.notna().sum()
    return_coverage = pd.DataFrame(
        {
            SEDOL_COL: matched_sedols,
            "return_days": available_days.reindex(matched_sedols).to_numpy(),
            "research_return_days": len(returns),
        }
    )
    return_coverage["return_cell_coverage"] = (
        return_coverage["return_days"] / max(len(returns), 1)
    )
    return_coverage.to_csv(
        output_dir / "returns_coverage_audit.csv",
        index=False,
    )
    long_gaps = consecutive.loc[
        consecutive["gap_days"].gt(120),
        ["prior_date", "next_date", "gap_days", "gap_months"],
    ]
    audit = {
        "benchmark": profile.benchmark,
        "benchmark_weight_column": profile.weight_col,
        "security_identifier": {
            "screen_primary_key": [ISIN_COL, DATE_COL],
            "returns_join_key": SEDOL_COL,
        },
        "date_field": DATE_COL,
        "benchmark_rows": len(benchmark),
        "benchmark_start": str(benchmark[DATE_COL].min().date()),
        "benchmark_end": str(benchmark[DATE_COL].max().date()),
        "benchmark_snapshots": int(benchmark[DATE_COL].nunique()),
        "benchmark_unique_securities": int(benchmark[ISIN_COL].nunique()),
        "rebalance_frequency": {
            "yearly_snapshot_audit": "benchmark_frequency_audit.csv",
            "cadence_is_inferred_from_observed_historical_snapshots": True,
        },
        "names_per_month": {
            "min": int(monthly.securities.min()),
            "median": float(monthly.securities.median()),
            "max": int(monthly.securities.max()),
        },
        "weight_sum": {
            "min": float(monthly.weight_sum.min()),
            "median": float(monthly.weight_sum.median()),
            "max": float(monthly.weight_sum.max()),
        },
        "duplicate_date_isin_rows": int(
            benchmark.duplicated([DATE_COL, ISIN_COL], keep=False).sum()
        ),
        "returns_column_match": len(matched_sedols) / len(unique_sedols),
        "returns_research_days": len(returns),
        "returns_cell_coverage": (
            float(returns.notna().to_numpy().mean())
            if len(returns) and matched_sedols
            else np.nan
        ),
        "returns_security_coverage": {
            "min": float(return_coverage["return_cell_coverage"].min()),
            "median": float(return_coverage["return_cell_coverage"].median()),
            "max": float(return_coverage["return_cell_coverage"].max()),
        },
        "scheduled_missing_months": [
            str(period.end_time.date()) for period in sorted(set(scheduled_missing))
        ],
        "long_snapshot_gaps": long_gaps.assign(
            prior_date=long_gaps["prior_date"].astype(str),
            next_date=long_gaps["next_date"].astype(str),
        ).to_dict("records"),
        "missing_month_execution_rule": (
            "no rebalance; retain prior holdings and drift with realized returns"
        ),
        "point_in_time_audit": {
            "benchmark_membership": "historical positive benchmark weights",
            "signal_snapshot": "monthly archived vendor/database snapshot",
            "publication_timestamp": "not present; not independently verifiable",
            "lookahead_execution": (
                "first returns date strictly after signal date; weights apply after close"
            ),
            "survivorship": (
                "historical membership used; delisted coverage limited by source history"
            ),
        },
    }
    json_dump(output_dir / "data_audit_summary.json", audit)
    return audit


def execution_benchmark(output_dir: Path, results: pd.DataFrame) -> dict[str, object]:
    artifacts = list((output_dir / "official_runs").glob("**/*"))
    artifacts = [path for path in artifacts if path.is_file()]
    mtimes = [path.stat().st_mtime for path in artifacts]
    return {
        "wall_time_seconds": (
            float(max(mtimes) - min(mtimes)) if len(mtimes) >= 2 else np.nan
        ),
        "wall_time_measurement": (
            "artifact_mtime_span_across_all_resume_waves; includes interruptions"
        ),
        "successful_runs": int(results["status"].eq("success").sum()),
        "failed_runs": int(results["status"].eq("failed").sum()),
        "terminal_runs": int(
            results["status"].isin(["success", "skipped"]).sum()
        ),
        "worker_memory": (
            "not captured by the initial launcher; initial 18-process attempt "
            "exhausted memory, final runs used 4/4/3 workers sequentially"
        ),
    }


def write_plotly_outputs(
    profile: MarketProfile,
    output_dir: Path,
    gate: pd.DataFrame,
    results: pd.DataFrame,
) -> list[str]:
    try:
        import plotly.graph_objects as go
    except Exception as exc:  # pragma: no cover
        return [f"Plotly unavailable: {exc}"]

    plot_dir = output_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    ranked = gate.sort_values("robust_score", ascending=False).head(30)
    fig = go.Figure()
    fig.add_bar(
        x=ranked["label"],
        y=ranked["robust_score"],
        marker_color=[
            "#188977" if value else "#9aa6b2" for value in ranked["pass_gate"]
        ],
        name="robust score",
    )
    fig.update_layout(
        title=f"{profile.display_name} lag6 relative-variable robustness",
        xaxis_title="Raw variable and transform",
        yaxis_title="Robust score",
    )
    path = plot_dir / "robust_score.html"
    fig.write_html(path, include_plotlyjs=True)
    written.append(str(path))

    best = gate[gate["pass_gate"]].sort_values(
        "robust_score",
        ascending=False,
    ).head(6)
    nav_fig = go.Figure()
    ratio_fig = go.Figure()
    benchmark_added = False
    for row in best.itertuples(index=False):
        metric_runs = results[
            results["metric"].astype(str).eq(str(row.metric))
            & results["status"].eq("success")
        ]
        top = metric_runs[metric_runs["side"].eq("Top")]
        worst = metric_runs[metric_runs["side"].eq("Worst")]
        if top.empty or worst.empty:
            continue
        top_nav = read_nav(str(top.iloc[-1]["perf_ptf"]))
        worst_nav = read_nav(str(worst.iloc[-1]["perf_ptf"]))
        benchmark_nav = read_nav(str(top.iloc[-1]["perf_bench"]))
        aligned = pd.concat(
            [
                top_nav.rename("Top"),
                worst_nav.rename("Worst"),
                benchmark_nav.rename("Benchmark"),
            ],
            axis=1,
        ).dropna()
        if aligned.empty:
            continue
        normalized = aligned / aligned.iloc[0] * 100.0
        nav_fig.add_scatter(
            x=normalized.index,
            y=normalized["Top"],
            mode="lines",
            name=f"{row.label} Top",
        )
        nav_fig.add_scatter(
            x=normalized.index,
            y=normalized["Worst"],
            mode="lines",
            line={"dash": "dot"},
            name=f"{row.label} Worst",
        )
        ratio = aligned["Top"] / aligned["Worst"]
        ratio_fig.add_scatter(
            x=ratio.index,
            y=ratio / ratio.iloc[0] * 100.0,
            mode="lines",
            name=str(row.label),
        )
        if not benchmark_added:
            nav_fig.add_scatter(
                x=normalized.index,
                y=normalized["Benchmark"],
                mode="lines",
                line={"color": "#315d8a", "width": 3},
                name=f"{profile.benchmark} Benchmark",
            )
            benchmark_added = True
    if nav_fig.data:
        nav_fig.update_layout(
            title=f"{profile.display_name} lag6 passed variables: Top/Worst/Benchmark",
            xaxis_title="Date",
            yaxis_title="NAV (first common date = 100)",
        )
        path = plot_dir / "passed_nav.html"
        nav_fig.write_html(path, include_plotlyjs=True)
        written.append(str(path))
    if ratio_fig.data:
        ratio_fig.update_layout(
            title=f"{profile.display_name} lag6 passed variables: Top/Worst ratio",
            xaxis_title="Date",
            yaxis_title="Top/Worst ratio index",
        )
        path = plot_dir / "passed_top_worst_ratio.html"
        ratio_fig.write_html(path, include_plotlyjs=True)
        written.append(str(path))
    return written


def write_report(
    profile: MarketProfile,
    output_dir: Path,
    registry: pd.DataFrame,
    gate: pd.DataFrame,
    audit: Mapping[str, object],
) -> Path:
    table = (
        gate.merge(
            registry[["metric", "label"]],
            on="metric",
            how="left",
            suffixes=("", "_registry"),
        )
        .sort_values(["pass_gate", "robust_score"], ascending=[False, False])
        .loc[
            :,
            [
                "label",
                "coverage",
                "ratio_cagr",
                "top_worst_ratio_return",
                "robust_score",
                "pass_gate",
                "fail_reasons",
            ],
        ]
        .to_markdown(index=False)
    )
    report = f"""# {profile.display_name} lag6 相对变量补充研究

## 设计

从冻结的 lag1/3/12 定义表恢复 {len(registry) // 2} 个绝对水平 raw
variables，只新增 `directional_delta lag6` 与 `score_delta lag6`，共
{len(registry)} 个独立 trials。每个变量先单独运行统一引擎官方 Top/Worst，
没有任何来源、core/supplement 标签或经济故事自动放行。

## 数据与口径

- Benchmark：`{profile.benchmark}`
- 权重列：`{profile.weight_col}`
- Benchmark 历史：{audit['benchmark_start']} 至 {audit['benchmark_end']}
- Benchmark 快照数：{audit['benchmark_snapshots']}；真实月度缺口：
  {', '.join(audit['scheduled_missing_months']) or '无'}
- Returns 证券列覆盖：{audit['returns_column_match']:.2%}；研究区间 cell
  coverage：{audit['returns_cell_coverage']:.2%}
- 同证券 lag 键：`ISIN`
- 中性化：ICB 19；Top/Worst 各 20%；缺失值保持 NaN
- 缺失 benchmark 月：不调仓，上一期持仓按真实收益漂移
- 引擎：`tp.security_nav 3.0.0`
- 优化器：未调用

## Gate

{table}

## 解释边界

通过 gate 只允许变量进入后续 pair/subset/leave-one-out；本轮单变量证据
本身不构成 synergy，也不把 2026-07 之前的历史变成真正未来 OOS。
"""
    path = output_dir / f"{profile.output_prefix}_lag6_relative_report.md"
    path.write_text(report, encoding="utf-8")
    return path


def parse_csv_arg(raw: str, default: Sequence[str]) -> list[str]:
    if raw.strip().lower() == "all":
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=sorted(PROFILES), required=True)
    parser.add_argument("--screen", type=Path, default=DEFAULT_SCREEN)
    parser.add_argument("--returns", type=Path, default=DEFAULT_RETURNS)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--metrics", default="all")
    parser.add_argument("--max-runs", type=int, default=0)
    parser.add_argument("--wave")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--force-build", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser


@recorded_workflow
def main(argv: Iterable[str] | None = None) -> int:
    finalization_started = time.perf_counter()
    args = build_parser().parse_args(argv)
    profile = PROFILES[args.market]
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else (AD_HOC_ROOT / profile.output_name).resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    fingerprints = ensure_input_fingerprints(
        output_dir,
        screen_path=args.screen.resolve(),
        returns_path=args.returns.resolve(),
        registry_source=frozen_definition_path(profile),
    )
    screen_path, registry, definitions = build_research_screen(
        profile,
        args.screen.resolve(),
        output_dir,
        force=args.force_build,
    )
    metrics = registry["metric"].astype(str).tolist()
    requested = parse_csv_arg(args.metrics, metrics)
    unknown = sorted(set(requested).difference(metrics))
    if unknown:
        raise KeyError(f"unknown metrics: {unknown}")
    monthly, diagnostics = metric_diagnostics(screen_path, metrics)
    monthly.to_csv(output_dir / "candidate_monthly_coverage.csv", index=False)
    diagnostics.to_csv(output_dir / "metric_diagnostics.csv", index=False)
    json_dump(
        output_dir / "metric_definitions.json",
        {
            "score_direction": "higher_is_better",
            "lag_observations": LAG,
            "same_security_key": ISIN_COL,
            "different_lags_same_raw_are_mutually_exclusive": True,
            "metrics": registry.to_dict("records"),
        },
    )
    checks = construction_checks(profile, screen_path, registry, diagnostics)
    checks.to_csv(output_dir / "data_construction_checks.csv", index=False)
    start_dates = diagnostics.set_index("metric")["first_date"].fillna("").to_dict()

    skip_rows: list[dict[str, object]] = []
    for metric in requested:
        if str(start_dates.get(metric, "")):
            continue
        for side in ("Top", "Worst"):
            skip_rows.append(
                {
                    "benchmark": profile.benchmark,
                    "metric": metric,
                    "side": side,
                    "top": side == "Top",
                    "start_date": "",
                    "status": "skipped",
                    "message": (
                        "no eligible month satisfies minimum coverage and "
                        "disjoint Top/Worst construction"
                    ),
                    "run_dir": "",
                    "sec_list": "",
                    "weights": "",
                    "exclusions": "",
                    "perf_ptf": "",
                    "perf_bench": "",
                }
            )
    if skip_rows:
        pd.DataFrame(skip_rows).to_csv(output_dir / "admission_skips.csv", index=False)

    audit = audit_inputs(
        profile,
        args.screen.resolve(),
        args.returns.resolve(),
        output_dir,
    )
    engine = nav_engine_metadata(
        strictly_after_rebalance=True,
        apply_weights_at_close=True,
    )
    preregistration_path = output_dir / "preregistration.json"
    if not preregistration_path.exists():
        json_dump(
            preregistration_path,
            {
            "study_id": f"{profile.output_prefix}_relative_lag6",
            "created_at": datetime.now().isoformat(),
            "market": asdict(profile),
            "frozen_registry_source": str(frozen_definition_path(profile)),
            "level_variable_count": len(registry) // 2,
            "lags": [LAG],
            "transforms": list(TRANSFORMS),
            "candidate_count": len(registry),
            "gate": asdict(
                GateThresholds(
                    min_coverage=MIN_COVERAGE,
                    min_ratio_cagr=0.0,
                    min_top_worst_ratio=0.0,
                    min_robust_score=0.0,
                )
            ),
            "engine": engine,
            },
        )
    if args.build_only:
        return 0

    existing = read_official_results(collect_result_paths(output_dir))
    pending = incomplete_official_metrics(requested, existing)
    pending = [metric for metric in pending if str(start_dates.get(metric, ""))]
    if args.max_runs > 0:
        pending = pending[: args.max_runs // 2]
    wave = new_wave_id(args.wave)
    worker_results: list[dict[str, object]] = []
    if pending:
        shards = shard_metric_names(pending, min(args.workers, len(pending)))
        payloads = [
            {
                "profile": asdict(profile),
                "metrics": shard,
                "screen_path": str(screen_path),
                "returns_path": str(args.returns.resolve()),
                "shard_path": str(
                    shard_result_path(output_dir, wave, shard_id)
                ),
                "output_dir": str(output_dir),
                "wave": wave,
                "shard_id": shard_id,
                "start_dates": {
                    metric: start_dates[metric] for metric in shard
                },
            }
            for shard_id, shard in enumerate(shards)
        ]
        if len(payloads) == 1:
            worker_results.append(worker_run(payloads[0]))
        else:
            with ProcessPoolExecutor(max_workers=len(payloads)) as executor:
                futures = [executor.submit(worker_run, payload) for payload in payloads]
                for future in as_completed(futures):
                    worker_results.append(future.result())

    results = dedupe_official_results(
        read_official_results(collect_result_paths(output_dir))
    )
    results.to_csv(output_dir / "official_run_results.csv", index=False)
    selected = results[results["metric"].astype(str).isin(requested)].copy()
    summary = summarize_runs(selected, diagnostics)
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
    gate.to_csv(output_dir / "relative_validation_gate.csv", index=False)
    definitions.to_csv(
        output_dir / "relative_variable_definitions.csv", index=False
    )
    prior_level = pd.read_csv(
        AD_HOC_ROOT
        / profile.frozen_relative_run
        / "relative_vs_level_comparison.csv"
    )
    level_columns = [
        column
        for column in (
            "raw_column",
            "level_metric",
            "level_pass_gate",
            "level_ratio_cagr",
            "level_robust_score",
        )
        if column in prior_level.columns
    ]
    (
        gate.merge(registry, on="metric", how="left", suffixes=("", "_registry"))
        .merge(
            prior_level[level_columns].drop_duplicates("raw_column"),
            on="raw_column",
            how="left",
        )
        .to_csv(output_dir / "relative_vs_level_comparison.csv", index=False)
    )
    report_path = write_report(profile, output_dir, registry, gate, audit)
    plot_paths = write_plotly_outputs(profile, output_dir, gate, selected)
    benchmark_evidence = execution_benchmark(output_dir, selected)
    benchmark_evidence["finalization_elapsed_seconds"] = (
        time.perf_counter() - finalization_started
    )
    json_dump(output_dir / "execution_benchmark.json", benchmark_evidence)

    completed = {
        (str(row.metric), str(row.side))
        for row in selected[selected["status"].isin(["success", "skipped"])].itertuples()
    }
    expected = {
        (metric, side) for metric in requested for side in ("Top", "Worst")
    }
    manifest = {
        **engine,
        "status": "complete" if completed == expected else "partial",
        "created_at": datetime.now().isoformat(),
        "study_id": f"{profile.output_prefix}_relative_lag6",
        "market": asdict(profile),
        "output_dir": str(output_dir),
        "research_screen": str(screen_path),
        "candidate_count": len(requested),
        "expected_official_runs": len(expected),
        "terminal_official_runs": len(completed),
        "success_count": int(selected["status"].eq("success").sum()),
        "skipped_count": int(selected["status"].eq("skipped").sum()),
        "failed_count": int(selected["status"].eq("failed").sum()),
        "gate_pass_count": int(gate["pass_gate"].sum()),
        "worker_results": worker_results,
        "wave": wave,
        "resume": bool(args.resume),
        "input_fingerprints": fingerprints,
        "data_construction_checks": str(
            output_dir / "data_construction_checks.csv"
        ),
        "metric_definitions": str(output_dir / "metric_definitions.json"),
        "plot_paths": plot_paths,
        "execution_benchmark": benchmark_evidence,
        "report": str(report_path),
        "optimizer_used": False,
        "optimizer_objective": "not_applicable_factor_sort_evidence",
    }
    json_dump(output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Research runner for STOXX Europe 600 six-style factor models.

The script builds point-in-time, sector-neutral factor scores on the
`Weight in STOXX EUROPE 600` universe, compares them with existing style scores,
and launches official Top/Worst backtests through the current 07_backtest_code
service.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime
import hashlib
from itertools import combinations
import io
import json
from math import sqrt
from pathlib import Path
import re
import sys
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


BACKTEST_ROOT = Path(__file__).resolve().parents[1]
TP_ROOT = BACKTEST_ROOT.parent

for path in (TP_ROOT, BACKTEST_ROOT, BACKTEST_ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import sitecustomize  # noqa: F401,E402

from backtest_code.config.loader import load_settings  # noqa: E402
from backtest_code.runner.artifacts import (  # noqa: E402
    create_run_directory,
    save_config_snapshot,
    save_dataframe,
    save_manifest,
    save_series,
    save_text,
)
from backtest_code.runner.service import BacktestService  # noqa: E402
from backtest_code.runner.validators import load_tabular_file, prepare_returns_dataframe, validate_settings  # noqa: E402


DEFAULT_SCREEN = TP_ROOT / "00_screen" / "screen_aggregate.parquet"
DEFAULT_RETURNS = TP_ROOT / "00_screen" / "returns.parquet"
AD_HOC_ROOT = BACKTEST_ROOT / "runs" / "ad_hoc"

BENCHMARK = "STOXX EUROPE 600"
WEIGHT_COL = f"Weight in {BENCHMARK}"
DATE_COL = "Date"
ISIN_COL = "ISIN"
SEDOL_COL = "Company SEDOL"
SECTOR_COL = " Benchmark ICB Supersector "
MKT_CAP_COL = "Benchmark Market Value Millions in EUR"
PERCENTILE = 0.2
DEFAULT_PARALLEL_WORKERS = 8
FAMILY_ORDER = ["growth", "value", "quality", "lowvol", "momentum", "dividend"]
OFFICIAL_TECHNICAL_COLUMNS = (
    DATE_COL,
    ISIN_COL,
    SEDOL_COL,
    "Name",
    SECTOR_COL,
    " Benchmark ICB Industry ",
    MKT_CAP_COL,
    WEIGHT_COL,
    "ESG_ANALYST_SCORE",
)


def load_official_worker_inputs(
    screen_path: Path,
    returns_path: Path,
    metrics: Iterable[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load only the screen and return columns needed by one metric shard."""

    metric_columns = list(dict.fromkeys(str(metric) for metric in metrics))
    requested_screen_columns = list(
        dict.fromkeys([*OFFICIAL_TECHNICAL_COLUMNS, *metric_columns])
    )
    if screen_path.suffix.lower() == ".parquet":
        available_screen_columns = set(pq.ParquetFile(screen_path).schema.names)
        missing_metrics = [
            metric for metric in metric_columns if metric not in available_screen_columns
        ]
        if missing_metrics:
            raise KeyError(f"Missing screen metrics: {missing_metrics}")
        screen_columns = [
            column
            for column in requested_screen_columns
            if column in available_screen_columns
        ]
        screen = pd.read_parquet(screen_path, columns=screen_columns)
    else:
        screen = load_tabular_file(screen_path)
        missing_metrics = [
            metric for metric in metric_columns if metric not in screen.columns
        ]
        if missing_metrics:
            raise KeyError(f"Missing screen metrics: {missing_metrics}")
        screen = screen.loc[
            :,
            [
                column
                for column in requested_screen_columns
                if column in screen.columns
            ],
        ].copy()

    sedols = set(
        screen[SEDOL_COL]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda values: values.ne("")]
    )
    if returns_path.suffix.lower() == ".parquet":
        available_returns_columns = set(pq.ParquetFile(returns_path).schema.names)
        returns_columns = sorted(sedols.intersection(available_returns_columns))
        returns = pd.read_parquet(returns_path, columns=returns_columns)
    else:
        returns = load_tabular_file(returns_path)
        returns = returns.loc[
            :,
            [column for column in returns.columns if str(column) in sedols],
        ].copy()
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index()
    return screen, returns


@dataclass(frozen=True)
class RawMetricSpec:
    column: str
    family: str
    direction: int
    role: str
    note: str

    @property
    def score_column(self) -> str:
        return f"stoxx600_{slugify(self.family)}_{slugify(self.column)}_score"


@dataclass(frozen=True)
class ModelSpec:
    column: str
    label: str
    family: str
    components: dict[str, float]
    note: str


RAW_METRICS: tuple[RawMetricSpec, ...] = (
    RawMetricSpec("Sales Growth NTM", "growth", 1, "core", "forward sales growth"),
    RawMetricSpec("Sales Growth FY1", "growth", 1, "core", "forward sales growth"),
    RawMetricSpec("Gross Income Growth NTM", "growth", 1, "core", "gross income growth"),
    RawMetricSpec("Gross Income Growth FY1", "growth", 1, "core", "gross income growth"),
    RawMetricSpec("EPS Growth NTM", "growth", 1, "core", "forward EPS growth"),
    RawMetricSpec("EPS Growth FY1", "growth", 1, "core", "forward EPS growth"),
    RawMetricSpec("Revenue 5Y CAGR", "growth", 1, "supplement", "CIQ long-term growth, low coverage"),
    RawMetricSpec("EPS Growth FY1 CIQ", "growth", 1, "supplement", "CIQ FY1 growth, low coverage"),
    RawMetricSpec("EBITDA Growth FY1 CIQ", "growth", 1, "supplement", "CIQ EBITDA growth, low coverage"),
    RawMetricSpec("Ebitda 5Y CAGR", "growth", 1, "supplement", "CIQ long-term EBITDA growth, low coverage"),
    RawMetricSpec("Earns Yield FY1", "value", 1, "core", "earnings yield"),
    RawMetricSpec("Earns Yield NTM", "value", 1, "core", "earnings yield"),
    RawMetricSpec("PE FY1", "value", -1, "core", "lower valuation multiple"),
    RawMetricSpec("PE NTM", "value", -1, "core", "lower valuation multiple"),
    RawMetricSpec("EV To EBITDA FY1", "value", -1, "core", "lower valuation multiple"),
    RawMetricSpec("EV To EBITDA NTM", "value", -1, "core", "lower valuation multiple"),
    RawMetricSpec("EV to Sales FY1", "value", -1, "core", "lower valuation multiple"),
    RawMetricSpec("EV to Sales NTM", "value", -1, "core", "lower valuation multiple"),
    RawMetricSpec("PB LTM", "value", -1, "core", "lower book multiple"),
    RawMetricSpec("PFCF LTM", "value", -1, "core", "lower cash-flow multiple"),
    RawMetricSpec("Price to FreeCF FY1", "value", -1, "core", "lower forward cash-flow multiple"),
    RawMetricSpec("Price to Book FY1", "value", -1, "core", "lower forward book multiple"),
    RawMetricSpec("ROE avg FY0", "quality", 1, "core", "profitability"),
    RawMetricSpec("Oper Margin", "quality", 1, "core", "operating margin"),
    RawMetricSpec("FCF Conversion", "quality", 1, "core", "cash conversion, low coverage"),
    RawMetricSpec("Gross Margin", "quality", 1, "supplement", "gross margin, low coverage"),
    RawMetricSpec("Ebitda Margin", "quality", 1, "supplement", "EBITDA margin, low coverage"),
    RawMetricSpec("Cont Op Earning Margin", "quality", 1, "supplement", "continuing operations margin, low coverage"),
    RawMetricSpec("NetDebt to EBITDA exFIN", "quality", -1, "core", "lower leverage"),
    RawMetricSpec("Net Debt to Market Cap", "quality", -1, "supplement", "lower leverage, low coverage"),
    RawMetricSpec("Net Debt to Tot Equity", "quality", -1, "supplement", "lower leverage, low coverage"),
    RawMetricSpec("Daily Vol 260J", "lowvol", -1, "core", "lower 1Y volatility"),
    RawMetricSpec("Daily Vol 90J", "lowvol", -1, "core", "lower 3M volatility"),
    RawMetricSpec("Daily Vol 60J", "lowvol", -1, "core", "lower 2M volatility"),
    RawMetricSpec("Maximum Drawdown Rolling 250D", "lowvol", 1, "supplement", "less negative drawdown, short history"),
    RawMetricSpec("Beta vs Regional Benchmark (Rolling ewma 250D)", "lowvol", -1, "supplement", "lower regional beta, short history"),
    RawMetricSpec("PMOM 12M1M", "momentum", 1, "core", "12M minus 1M price momentum"),
    RawMetricSpec("Total Return", "momentum", 1, "core", "total return momentum"),
    RawMetricSpec("EPS Revision Ratio", "momentum", 1, "core", "earnings revision"),
    RawMetricSpec("EPS NTM 3M Growth", "momentum", 1, "core", "3M estimate change"),
    RawMetricSpec("DVD Yield NTM", "dividend", 1, "core", "forward dividend yield"),
    RawMetricSpec("DVD Yield FY1", "dividend", 1, "core", "forward dividend yield"),
    RawMetricSpec("DPS 1Y Growth NTM", "dividend", 1, "core", "dividend growth"),
    RawMetricSpec("DPS 1Y Growth FY1", "dividend", 1, "core", "dividend growth"),
    RawMetricSpec("DVD Payout FY0", "dividend", -1, "core", "lower payout pressure"),
    RawMetricSpec("FCF Div Cov Ratio", "dividend", 1, "supplement", "dividend coverage, low coverage"),
    RawMetricSpec("CFO Div Cov Ratio", "dividend", 1, "supplement", "dividend coverage, low coverage"),
)

EXISTING_STYLE_COLUMNS = [
    "Growth Avg Percentile",
    "Value Avg Percentile",
    "Quality Avg Percentile",
    "LowVol Avg Percentile",
    "Mom Avg Percentile",
    "Dividend Avg Percentile",
    "Multi Avg Percentile",
]

FS_STYLE_COLUMNS = [
    "GROWTH_SCORE_FS_SECTOR",
    "VALUE_SCORE_FS_SECTOR",
    "MARGIN_SCORE_FS_SECTOR",
    "LEVERAGE_SCORE_FS_SECTOR",
    "MOMENTUM_SCORE_FS_SECTOR",
    "LOW_VOL_SCORE_FS_SECTOR",
    "FIVE_FACTOR_SCORE_FS_SECTOR",
]


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", text.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned.lower() or "item"


def available_columns(path: Path) -> set[str]:
    return set(pq.ParquetFile(path).schema_arrow.names)


def existing(items: Iterable[str], columns: set[str]) -> list[str]:
    return [item for item in items if item in columns]


def frame_to_markdown(frame: pd.DataFrame, *, max_rows: int | None = None) -> str:
    if max_rows is not None:
        frame = frame.head(max_rows)
    try:
        return frame.to_markdown(index=False)
    except Exception:
        return frame.to_csv(index=False)


def winsorize_by_date(values: pd.Series, dates: pd.Series) -> pd.Series:
    def clip_one(group: pd.Series) -> pd.Series:
        valid = group.dropna()
        if len(valid) < 20:
            return group
        return group.clip(valid.quantile(0.01), valid.quantile(0.99))

    return values.groupby(dates, group_keys=False).transform(clip_one)


def sector_rank_score(values: pd.Series, dates: pd.Series, sectors: pd.Series) -> pd.Series:
    frame = pd.DataFrame({"value": values, "Date": dates, "sector": sectors})
    ranked = frame.groupby(["Date", "sector"], observed=True)["value"].rank(pct=True)
    return ranked * 10.0


def score_raw_metric(screen: pd.DataFrame, spec: RawMetricSpec) -> pd.Series:
    raw = (pd.to_numeric(screen[spec.column], errors="coerce") * spec.direction).replace([np.inf, -np.inf], np.nan)
    clipped = winsorize_by_date(raw, screen[DATE_COL])
    return sector_rank_score(clipped, screen[DATE_COL], screen[SECTOR_COL])


def average_scores(frame: pd.DataFrame, columns: list[str], min_count: int) -> pd.Series:
    present = [column for column in columns if column in frame.columns]
    if not present:
        return pd.Series(np.nan, index=frame.index)
    return frame[present].mean(axis=1, skipna=True).where(frame[present].notna().sum(axis=1) >= min_count)


def weighted_scores(frame: pd.DataFrame, weights: dict[str, float], min_count: int) -> pd.Series:
    columns = [column for column in weights if column in frame.columns]
    if not columns:
        return pd.Series(np.nan, index=frame.index)
    data = frame[columns].apply(pd.to_numeric, errors="coerce")
    weight = pd.Series({column: weights[column] for column in columns}, dtype=float)
    valid_weight_sum = data.notna().mul(weight, axis=1).sum(axis=1)
    weighted = data.mul(weight, axis=1).sum(axis=1) / valid_weight_sum.replace(0, np.nan)
    return weighted.where(data.notna().sum(axis=1) >= min_count)


def compute_forward_returns(screen: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    out = pd.Series(np.nan, index=screen.index, dtype=float)
    returns = returns.copy()
    returns.index = pd.to_datetime(returns.index)
    returns = returns.sort_index()
    dates = sorted(pd.to_datetime(screen[DATE_COL].dropna().unique()))
    for idx, date in enumerate(dates):
        future = returns.index[returns.index > date]
        if future.empty:
            continue
        start = future[0]
        if idx + 1 < len(dates):
            future_next = returns.index[returns.index > dates[idx + 1]]
            end = future_next[0] if len(future_next) else returns.index[-1] + pd.Timedelta(days=1)
        else:
            end = returns.index[-1] + pd.Timedelta(days=1)
        window = returns.loc[(returns.index >= start) & (returns.index < end)]
        if window.empty:
            continue
        mask = screen[DATE_COL].eq(date)
        sedols = screen.loc[mask, SEDOL_COL].dropna().astype(str)
        ids = [sedol for sedol in sedols.unique() if sedol in returns.columns]
        if not ids:
            continue
        forward = (1.0 + window[ids].apply(pd.to_numeric, errors="coerce").fillna(0.0)).prod() - 1.0
        out.loc[mask] = screen.loc[mask, SEDOL_COL].map(forward)
    return out


def build_adaptive_score(screen: pd.DataFrame, returns: pd.DataFrame, columns: list[str], output_dir: Path) -> pd.Series:
    forward = compute_forward_returns(screen, returns)
    ic_rows = []
    for date, month in screen.groupby(DATE_COL, sort=True, observed=True):
        row: dict[str, object] = {"Date": pd.Timestamp(date)}
        fwd = forward.loc[month.index]
        for column in columns:
            pair = pd.concat([month[column], fwd], axis=1).dropna()
            row[column] = pair.iloc[:, 0].corr(pair.iloc[:, 1], method="spearman") if len(pair) >= 30 else np.nan
        ic_rows.append(row)
    ic = pd.DataFrame(ic_rows).sort_values(DATE_COL)
    ic.to_csv(output_dir / "adaptive_monthly_ic.csv", index=False)

    weights_rows = []
    adaptive = pd.Series(np.nan, index=screen.index, dtype=float)
    for date, month in screen.groupby(DATE_COL, sort=True, observed=True):
        history = ic[ic[DATE_COL] < pd.Timestamp(date)].tail(36)
        raw_weights: dict[str, float] = {}
        for column in columns:
            series = pd.to_numeric(history[column], errors="coerce").dropna() if column in history else pd.Series(dtype=float)
            if len(series) >= 12:
                vol = series.std()
                raw_weights[column] = max(float(series.mean() / vol), 0.0) if vol and not pd.isna(vol) else max(float(series.mean()), 0.0)
            else:
                raw_weights[column] = 0.0
        if sum(raw_weights.values()) <= 0:
            raw_weights = {column: 1.0 for column in columns}
        total = sum(raw_weights.values())
        norm = {column: raw_weights[column] / total for column in columns}
        data = month[columns].apply(pd.to_numeric, errors="coerce")
        weight = pd.Series(norm)
        valid_weight_sum = data.notna().mul(weight, axis=1).sum(axis=1)
        adaptive.loc[month.index] = data.mul(weight, axis=1).sum(axis=1) / valid_weight_sum.replace(0, np.nan)
        weights_rows.append({"Date": pd.Timestamp(date), **norm})
    pd.DataFrame(weights_rows).to_csv(output_dir / "adaptive_factor_weights.csv", index=False)
    return adaptive


def metric_diagnostics(screen: pd.DataFrame, metrics: list[ModelSpec], raw_specs: list[RawMetricSpec]) -> pd.DataFrame:
    raw_notes = {spec.score_column: spec for spec in raw_specs}
    rows = []
    for metric in metrics:
        if metric.column not in screen.columns:
            continue
        series = pd.to_numeric(screen[metric.column], errors="coerce")
        valid = series.notna()
        dates = pd.to_datetime(screen.loc[valid, DATE_COL], errors="coerce").dropna()
        by_date = screen.assign(_valid=valid).groupby(DATE_COL, observed=True)["_valid"].sum()
        raw = raw_notes.get(metric.column)
        rows.append(
            {
                "metric": metric.column,
                "label": metric.label,
                "family": metric.family,
                "role": raw.role if raw else metric.family,
                "direction": raw.direction if raw else "",
                "coverage": float(valid.mean()) if len(valid) else np.nan,
                "non_null_rows": int(valid.sum()),
                "first_date": dates.min() if not dates.empty else pd.NaT,
                "last_date": dates.max() if not dates.empty else pd.NaT,
                "avg_names_per_month": float(by_date.mean(skipna=True)) if len(by_date) else np.nan,
                "note": raw.note if raw else metric.note,
            }
        )
    return pd.DataFrame(rows)


def construction_checks(screen: pd.DataFrame, returns: pd.DataFrame, source_rows: int) -> pd.DataFrame:
    small_mask = pd.to_numeric(screen[WEIGHT_COL], errors="coerce").fillna(0) > 0
    small = screen.loc[small_mask]
    sedol = small[SEDOL_COL].dropna().astype(str)
    in_returns = sedol.isin(set(map(str, returns.columns)))
    rows = [
        {"check": "source_screen_rows", "value": source_rows},
        {"check": "research_screen_rows", "value": len(screen)},
        {"check": "benchmark", "value": BENCHMARK},
        {"check": "universe_rule", "value": f"{WEIGHT_COL} > 0"},
        {"check": "first_small_date", "value": str(pd.to_datetime(small[DATE_COL]).min().date()) if not small.empty else ""},
        {"check": "last_small_date", "value": str(pd.to_datetime(small[DATE_COL]).max().date()) if not small.empty else ""},
        {"check": "small_date_count", "value": int(pd.to_datetime(small[DATE_COL]).nunique())},
        {"check": "avg_small_names_per_month", "value": float(small.groupby(DATE_COL, observed=True).size().mean()) if not small.empty else np.nan},
        {"check": "sedol_rows", "value": int(len(sedol))},
        {"check": "sedol_rows_in_returns", "value": int(in_returns.sum())},
        {"check": "sedol_return_coverage", "value": float(in_returns.mean()) if len(in_returns) else np.nan},
        {"check": "lookahead_rule", "value": "monthly screen date; official engine trades after signal date"},
    ]
    return pd.DataFrame(rows)


def build_research_screen(screen_path: Path, returns: pd.DataFrame, output_dir: Path, force: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[ModelSpec]]:
    output_path = output_dir / "stoxx600_multifactor_screen.parquet"
    specs_path = output_dir / "metric_definitions.json"
    if output_path.exists() and specs_path.exists() and not force:
        screen = pd.read_parquet(output_path)
        definitions = json.loads(specs_path.read_text(encoding="utf-8"))
        metrics = [ModelSpec(**item) for item in definitions]
        checks = construction_checks(screen, returns, pq.ParquetFile(screen_path).metadata.num_rows)
        diag = metric_diagnostics(screen, metrics, list(RAW_METRICS))
        return screen, checks, diag, metrics

    columns = available_columns(screen_path)
    required = [DATE_COL, ISIN_COL, SEDOL_COL, "Name", SECTOR_COL, MKT_CAP_COL, WEIGHT_COL]
    metric_inputs = existing([spec.column for spec in RAW_METRICS], columns)
    old_inputs = existing(EXISTING_STYLE_COLUMNS + FS_STYLE_COLUMNS, columns)
    read_columns = list(dict.fromkeys(existing(required, columns) + metric_inputs + old_inputs))
    missing_required = sorted(set(required).difference(read_columns))
    if missing_required:
        raise ValueError(f"Missing required screen columns: {missing_required}")

    screen = pd.read_parquet(screen_path, columns=read_columns)
    if ISIN_COL not in screen.columns and screen.index.name == ISIN_COL:
        screen = screen.reset_index()
    if ISIN_COL not in screen.columns and "__index_level_0__" in screen.columns:
        screen = screen.rename(columns={"__index_level_0__": ISIN_COL})
    screen[DATE_COL] = pd.to_datetime(screen[DATE_COL], errors="coerce")
    screen = screen[pd.to_numeric(screen[WEIGHT_COL], errors="coerce").fillna(0) > 0].copy()
    screen = screen.dropna(subset=[DATE_COL, ISIN_COL, SEDOL_COL, SECTOR_COL])
    screen = screen.sort_values([DATE_COL, ISIN_COL]).reset_index(drop=True)

    raw_specs = [spec for spec in RAW_METRICS if spec.column in screen.columns]
    metrics: list[ModelSpec] = []
    for spec in raw_specs:
        screen[spec.score_column] = score_raw_metric(screen, spec)
        metrics.append(
            ModelSpec(
                column=spec.score_column,
                label=f"{spec.family}: {spec.column}",
                family=f"raw_{spec.family}",
                components={spec.column: float(spec.direction)},
                note=spec.note,
            )
        )

    family_scores: dict[str, str] = {}
    min_counts = {"growth": 3, "value": 4, "quality": 2, "lowvol": 2, "momentum": 2, "dividend": 2}
    for family in ["growth", "value", "quality", "lowvol", "momentum", "dividend"]:
        cols = [spec.score_column for spec in raw_specs if spec.family == family and spec.role == "core"]
        score_col = f"stoxx600_{family}_rebuilt"
        screen[score_col] = average_scores(screen, cols, min_counts[family])
        family_scores[family] = score_col
        metrics.append(ModelSpec(score_col, f"{family} rebuilt", f"rebuilt_{family}", {col: 1.0 for col in cols}, "core raw-variable average"))

    family_order = ["growth", "value", "quality", "lowvol", "momentum", "dividend"]
    composite_specs = [
        ModelSpec(
            "stoxx600_mf_6_equal",
            "Six-factor equal weight",
            "candidate",
            {family_scores[key]: 1 / 6 for key in family_order},
            "equal-weight rebuilt six-factor model",
        ),
        ModelSpec(
            "stoxx600_mf_defensive_tilt",
            "Lowvol/quality defensive tilt",
            "candidate",
            {
                family_scores["lowvol"]: 0.25,
                family_scores["quality"]: 0.25,
                family_scores["value"]: 0.15,
                family_scores["momentum"]: 0.15,
                family_scores["growth"]: 0.10,
                family_scores["dividend"]: 0.10,
            },
            "drawdown-aware tilt toward lowvol and quality",
        ),
        ModelSpec(
            "stoxx600_mf_lowvol_quality_value",
            "Lowvol + quality + value core",
            "candidate",
            {family_scores["lowvol"]: 0.40, family_scores["quality"]: 0.30, family_scores["value"]: 0.30},
            "defensive core candidate",
        ),
        ModelSpec(
            "stoxx600_mf_5_no_dividend",
            "Five-factor model excluding dividend",
            "candidate",
            {family_scores[key]: 0.20 for key in ["growth", "value", "quality", "lowvol", "momentum"]},
            "rebuilt model excluding lower-coverage dividend style",
        ),
    ]
    subset_specs = []
    for size in range(1, len(family_order) + 1):
        for subset in combinations(family_order, size):
            col = "stoxx600_combo_" + "_".join(subset)
            subset_specs.append(
                ModelSpec(
                    col,
                    " + ".join(subset),
                    "all_family_combinations",
                    {family_scores[key]: 1.0 / size for key in subset},
                    "equal-weight non-empty subset of rebuilt family scores",
                )
            )
    existing_combo_cols = {spec.column for spec in composite_specs}
    composite_specs.extend([spec for spec in subset_specs if spec.column not in existing_combo_cols])
    for spec in composite_specs:
        min_count = 4 if spec.column == "stoxx600_mf_6_equal" else max(1, min(4, len(spec.components)))
        screen[spec.column] = weighted_scores(screen, spec.components, min_count)
        metrics.append(spec)

    adaptive_col = "stoxx600_mf_adaptive_36m"
    adaptive_components = {family_scores[key]: 1 / 6 for key in family_order}
    screen[adaptive_col] = build_adaptive_score(screen, returns, list(adaptive_components), output_dir)
    metrics.append(
        ModelSpec(
            adaptive_col,
            "Adaptive trailing 36M IC blend",
            "candidate",
            adaptive_components,
            "uses only past 36 monthly IC observations; falls back to equal weights",
        )
    )

    for column in old_inputs:
        if column in screen.columns:
            family = "existing_fs" if column in FS_STYLE_COLUMNS else "existing_style"
            metrics.append(ModelSpec(column, column, family, {column: 1.0}, "database existing factor"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    screen.to_parquet(output_path, index=False)
    specs_path.write_text(json.dumps([metric.__dict__ for metric in metrics], ensure_ascii=False, indent=2), encoding="utf-8")
    checks = construction_checks(screen, returns, pq.ParquetFile(screen_path).metadata.num_rows)
    diag = metric_diagnostics(screen, metrics, raw_specs)
    return screen, checks, diag, metrics


def first_eligible_start(screen: pd.DataFrame, metric: str) -> pd.Timestamp | None:
    mask = pd.to_numeric(screen[WEIGHT_COL], errors="coerce").fillna(0).gt(0) & pd.to_numeric(screen[metric], errors="coerce").notna()
    dates = pd.to_datetime(screen.loc[mask, DATE_COL], errors="coerce").dropna()
    return None if dates.empty else dates.min()


def parse_csv_arg(raw: str | None, default: list[str]) -> list[str]:
    if not raw or raw.lower() == "all":
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def raw_source(spec: RawMetricSpec) -> str:
    text = f"{spec.column} {spec.note}".lower()
    if "ciq" in text:
        return "CIQ"
    if any(token in text for token in ["daily vol", "drawdown", "beta", "pmom", "total return", "revision", "3m estimate"]):
        return "local_or_derived"
    return "FactSet_or_database"


def raw_gate_table(
    *,
    summary: pd.DataFrame,
    metric_diag: pd.DataFrame,
    metric_specs: list[ModelSpec],
    min_coverage: float,
    min_ratio_cagr: float,
    min_top_worst_ratio: float,
    min_robust_score: float,
) -> pd.DataFrame:
    spec_map = {spec.column: spec for spec in metric_specs}
    raw_lookup = {spec.score_column: spec for spec in RAW_METRICS}
    diag_map = (
        metric_diag.drop_duplicates("metric", keep="last").set_index("metric").to_dict(orient="index")
        if not metric_diag.empty
        else {}
    )
    top = summary[(summary["status"].eq("success")) & (summary["side"].eq("Top"))].copy()
    top = top[top["metric"].isin(raw_lookup)]
    rows = []
    for _, row in top.iterrows():
        metric = str(row["metric"])
        raw_spec = raw_lookup[metric]
        coverage = float(row.get("coverage", diag_map.get(metric, {}).get("coverage", np.nan)))
        ratio_cagr = float(row.get("ratio_cagr", np.nan))
        top_worst = float(row.get("top_worst_ratio_return", np.nan))
        robust = float(row.get("robust_score", np.nan))
        failures = []
        if not np.isfinite(coverage) or coverage < min_coverage:
            failures.append(f"coverage<{min_coverage:g}")
        if not np.isfinite(ratio_cagr) or ratio_cagr <= min_ratio_cagr:
            failures.append(f"ratio_cagr<={min_ratio_cagr:g}")
        if not np.isfinite(top_worst) or top_worst <= min_top_worst_ratio:
            failures.append(f"top_worst_ratio_return<={min_top_worst_ratio:g}")
        if not np.isfinite(robust) or robust <= min_robust_score:
            failures.append(f"robust_score<={min_robust_score:g}")
        rows.append(
            {
                "metric": metric,
                "raw_column": raw_spec.column,
                "family": raw_spec.family,
                "role": raw_spec.role,
                "source": raw_source(raw_spec),
                "direction": raw_spec.direction,
                "label": spec_map.get(metric, ModelSpec(metric, metric, "", {}, "")).label,
                "coverage": coverage,
                "ratio_cagr": ratio_cagr,
                "top_worst_ratio_return": top_worst,
                "robust_score": robust,
                "ratio_max_drawdown": row.get("ratio_max_drawdown", np.nan),
                "tracking_error": row.get("tracking_error", np.nan),
                "annual_active_hit_rate": row.get("annual_active_hit_rate", np.nan),
                "pass_gate": not failures,
                "fail_reasons": "; ".join(failures),
                "note": raw_spec.note,
            }
        )
    gate = pd.DataFrame(rows)
    if gate.empty:
        return gate
    return gate.sort_values(["pass_gate", "family", "robust_score"], ascending=[False, True, False]).reset_index(drop=True)


def apply_validated_families(
    *,
    screen: pd.DataFrame,
    metric_specs: list[ModelSpec],
    gate: pd.DataFrame,
) -> tuple[pd.DataFrame, list[ModelSpec], list[str], list[str]]:
    if gate.empty or "pass_gate" not in gate.columns:
        raise ValueError("Raw validation gate is empty; run --raw-only official backtests first.")
    passed = gate[gate["pass_gate"].astype(bool)].copy()
    family_scores: dict[str, str] = {}
    new_specs: list[ModelSpec] = []
    for family in FAMILY_ORDER:
        cols = [metric for metric in passed.loc[passed["family"].eq(family), "metric"].tolist() if metric in screen.columns]
        if not cols:
            continue
        score_col = f"stoxx600_validated_{family}"
        min_count = max(1, (len(cols) + 1) // 2)
        screen[score_col] = average_scores(screen, cols, min_count)
        family_scores[family] = score_col
        new_specs.append(
            ModelSpec(
                score_col,
                f"validated {family}",
                "validated_family",
                {col: 1.0 for col in cols},
                f"raw-gated family; min_count={min_count}; core/supplement labels diagnostic only",
            )
        )
        if len(cols) >= 2:
            for omitted in cols:
                loo_cols = [col for col in cols if col != omitted]
                loo_col = f"{score_col}_loo_without_{slugify(omitted)}"
                screen[loo_col] = average_scores(screen, loo_cols, max(1, (len(loo_cols) + 1) // 2))
                new_specs.append(
                    ModelSpec(
                        loo_col,
                        f"{family} leave-one-out without {omitted}",
                        "validated_raw_leave_one_out",
                        {col: 1.0 for col in loo_cols},
                        "family internal leave-one-out evidence; not a final model candidate",
                    )
                )

    combo_specs: list[ModelSpec] = []
    valid_families = [family for family in FAMILY_ORDER if family in family_scores]
    for size in range(1, len(valid_families) + 1):
        for subset in combinations(valid_families, size):
            col = "stoxx600_validated_combo_" + "_".join(subset)
            combo_specs.append(
                ModelSpec(
                    col,
                    " + ".join(subset),
                    "validated_family_combinations",
                    {family_scores[key]: 1.0 / size for key in subset},
                    "equal-weight subset of raw-gated family scores",
                )
            )
    for spec in combo_specs:
        screen[spec.column] = weighted_scores(screen, spec.components, max(1, min(4, len(spec.components))))
    updated_specs = metric_specs + new_specs + combo_specs
    default_metrics = [spec.column for spec in combo_specs + new_specs if spec.family in {"validated_family_combinations", "validated_raw_leave_one_out"}]
    return screen, updated_specs, default_metrics, valid_families


def add_raw_pair_metrics(
    *,
    screen: pd.DataFrame,
    metric_specs: list[ModelSpec],
    gate: pd.DataFrame,
) -> tuple[pd.DataFrame, list[ModelSpec], list[str]]:
    if gate.empty or "pass_gate" not in gate.columns:
        raise ValueError("Raw validation gate is empty; run --raw-only official backtests first.")
    passed = gate[gate["pass_gate"].astype(bool)].copy()
    passed = passed[passed["metric"].isin(screen.columns)].sort_values(["family", "robust_score"], ascending=[True, False])
    pair_specs: list[ModelSpec] = []
    for left, right in combinations(passed.to_dict("records"), 2):
        left_metric = str(left["metric"])
        right_metric = str(right["metric"])
        digest = hashlib.md5(f"{left_metric}|{right_metric}".encode("utf-8")).hexdigest()[:8]
        column = (
            f"stoxx600_rawpair_{slugify(str(left['raw_column']))[:24]}__"
            f"{slugify(str(right['raw_column']))[:24]}_{digest}"
        )
        screen[column] = weighted_scores(screen, {left_metric: 0.5, right_metric: 0.5}, 2)
        pair_specs.append(
            ModelSpec(
                column,
                f"{left['raw_column']} + {right['raw_column']}",
                "validated_raw_pairs",
                {left_metric: 0.5, right_metric: 0.5},
                f"raw-variable pair synergy candidate; {left['family']} + {right['family']}",
            )
        )
    return screen, metric_specs + pair_specs, [spec.column for spec in pair_specs]


def run_official_backtests(
    *,
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    screen_path: Path,
    returns_path: Path,
    run_root_name: str,
    metrics: list[str],
    max_runs: int | None,
    results_path: Path | None = None,
    existing_results: pd.DataFrame | None = None,
) -> pd.DataFrame:
    service = BacktestService()
    completed_pairs: set[tuple[str, str]] = set()
    records = []
    if existing_results is not None and not existing_results.empty:
        reusable = existing_results[existing_results["status"].isin(["success", "skipped"])].copy()
        for _, row in reusable.iterrows():
            completed_pairs.add((str(row["metric"]), str(row["side"])))
        records.extend(reusable.to_dict("records"))
    launched = 0

    def flush() -> None:
        if results_path is not None:
            pd.DataFrame(records).to_csv(results_path, index=False)

    flush()
    for metric in metrics:
        if metric not in screen.columns:
            continue
        start = first_eligible_start(screen, metric)
        for side, top in (("Top", True), ("Worst", False)):
            if (metric, side) in completed_pairs:
                continue
            if max_runs is not None and launched >= max_runs:
                flush()
                return pd.DataFrame(records)
            record = {
                "benchmark": BENCHMARK,
                "metric": metric,
                "side": side,
                "top": top,
                "start_date": start.strftime("%Y-%m-%d") if start is not None else "",
                "status": "skipped",
                "message": "no eligible benchmark/signal intersection",
                "run_dir": "",
            }
            if start is None:
                records.append(record)
                completed_pairs.add((metric, side))
                flush()
                continue

            settings = load_settings("default")
            settings.user.name = f"{run_root_name}/official_runs"
            settings.paths.screen = str(screen_path)
            settings.paths.returns = str(returns_path)
            settings.run.mode = "research"
            settings.run.ptf_name = f"STOXX600_{slugify(metric)}_{side.upper()}"
            settings.run.bench = BENCHMARK
            settings.run.metrics = [metric]
            settings.run.percentile = PERCENTILE
            settings.run.top = top
            settings.run.ponderation = "Market cap"
            settings.run.esg_exclusion = 0.0
            settings.run.cut_mkt_cap = 0.0
            settings.run.score_neutral = "ICB 19"
            settings.run.weight_neutral = "ICB 19"
            settings.run.max_weight = 1.0
            settings.run.fill_method = "drift"
            settings.run.start_date = start.strftime("%Y-%m-%d")
            settings.run.screen_start_date = None
            settings.run.mode_monthly_prod = False

            record.update(run_single_official_engine(service, settings, screen=screen, returns=returns, side=side))
            records.append(record)
            completed_pairs.add((metric, side))
            launched += 1
            flush()
    return pd.DataFrame(records)


def run_single_official_engine(
    service: BacktestService,
    settings,
    *,
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    side: str,
) -> dict[str, str]:
    """Run the official engine without the GUI logger relay, which can recurse on stderr."""

    metric_name = settings.run.metrics[0]
    metric_label = metric_name
    if len(metric_label) > 80:
        digest = hashlib.md5(metric_label.encode("utf-8")).hexdigest()[:10]
        metric_label = f"{metric_label[:68]}_{digest}"
    run_label = (
        f"{settings.run.mode}_{settings.run.bench}_{metric_label}_"
        f"{side}_{settings.run.start_date}"
    )
    run_dir = create_run_directory(settings.user.name, run_label)
    artifacts = {
        "run_dir": run_dir,
        "sec_list": run_dir / "sec_list.parquet",
        "exclusions": run_dir / "exclusions.parquet",
        "perf_ptf": run_dir / "perf_ptf.parquet",
        "perf_bench": run_dir / "perf_bench.parquet",
        "plot": run_dir / "plot.html",
        "run_log": run_dir / "run.log",
    }
    save_config_snapshot(settings, run_dir)

    engine_module = service._load_engine_module()  # noqa: SLF001
    validation = validate_settings(settings, screen_df=screen, returns_df=returns)
    if not validation.is_valid:
        message = validation.as_text() or "Validation bloquante"
        save_text(message, artifacts["run_log"])
        save_manifest(
            run_dir,
            {
                "status": "failed",
                "message": message,
                "mode": settings.run.mode,
                "bench": settings.run.bench,
                "metrics": settings.run.metrics,
                "start_date": settings.run.start_date,
                "side": side,
            },
        )
        return official_record_payload("failed", message, artifacts)

    prepared_screen = service._prepare_screen_for_engine(screen, engine_module)  # noqa: SLF001
    prepared_returns = service._prepare_returns_for_engine(returns)  # noqa: SLF001
    log_buffer = io.StringIO()
    try:
        with redirect_stdout(log_buffer), redirect_stderr(log_buffer):
            builder = engine_module.PtfBuilder(
                screen=prepared_screen,
                returns=prepared_returns,
                bench=settings.run.bench,
                percentile=settings.run.percentile,
                metrics=settings.run.metrics[0],
                ptf_name=settings.run.ptf_name,
                ponderation=settings.run.ponderation,
                esg_exclusion=settings.run.esg_exclusion,
                cut_mkt_cap=settings.run.cut_mkt_cap,
                liste_noire=settings.paths.liste_noire or None,
                reco_secto=settings.run.reco_secto,
                reco_facto=settings.run.reco_facto,
                score_neutral=settings.run.score_neutral,
                weight_neutral=settings.run.weight_neutral,
                Top=settings.run.top,
                top_mandatory=settings.run.top_mandatory,
                multiprocessing=False,
                mode_monthly_prod=settings.run.mode_monthly_prod,
                output_dir=settings.paths.output_dir or None,
                cap_weight_threshold=settings.run.cap_weight_threshold,
                score_pivot_esg=service._parse_score_pivot(settings.run.score_pivot_esg),  # noqa: SLF001
                score_pivot_esg_path=settings.paths.score_pivot_esg_path or None,
                copy_inputs=False,
                monthly_base_cache=service._monthly_base_cache,  # noqa: SLF001
                benchmark_cache=service._benchmark_cache,  # noqa: SLF001
            )
            builder.generic_histo_seclist(
                start_date=pd.to_datetime(settings.run.start_date),
                freq_rebal=settings.run.freq_rebal,
                screen_start_date=settings.run.screen_start_date,
                fill_method=settings.run.fill_method,
            )
            builder.backtest(max_weight=settings.run.max_weight, sector_neutral=settings.run.sector_neutral)
            builder.backtest_get_bench_perf(prepared_screen, builder.start_date, settings.run.bench)
            builder.backtest_plot_ptf_bench(title=run_label, save_path=str(artifacts["plot"]), show_plot=False)

        save_dataframe(builder.sec_list_historical, artifacts["sec_list"])
        save_dataframe(builder.list_exclusion_histo, artifacts["exclusions"])
        save_series(builder.perf_ptf, artifacts["perf_ptf"])
        save_series(builder.perf_bench, artifacts["perf_bench"])
        save_text(log_buffer.getvalue(), artifacts["run_log"])
        save_manifest(
            run_dir,
            {
                "status": "success",
                "message": "Run termine avec succes",
                "mode": settings.run.mode,
                "bench": settings.run.bench,
                "metrics": settings.run.metrics,
                "start_date": settings.run.start_date,
                "side": side,
            },
        )
        return official_record_payload("success", "Run termine avec succes", artifacts)
    except Exception as exc:  # pragma: no cover - execution depends on local data.
        import traceback

        message = f"{type(exc).__name__}: {exc}"
        details = log_buffer.getvalue() + "\nTraceback complet :\n" + "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        save_text(details.strip(), artifacts["run_log"])
        save_manifest(
            run_dir,
            {
                "status": "failed",
                "message": message,
                "mode": settings.run.mode,
                "bench": settings.run.bench,
                "metrics": settings.run.metrics,
                "start_date": settings.run.start_date,
                "side": side,
            },
        )
        return official_record_payload("failed", message, artifacts)


def official_record_payload(status: str, message: str, artifacts: dict[str, Path]) -> dict[str, str]:
    return {
        "status": status,
        "message": message,
        "run_dir": str(artifacts["run_dir"]),
        "sec_list": str(artifacts["sec_list"] if artifacts["sec_list"].exists() else ""),
        "perf_ptf": str(artifacts["perf_ptf"] if artifacts["perf_ptf"].exists() else ""),
        "perf_bench": str(artifacts["perf_bench"] if artifacts["perf_bench"].exists() else ""),
        "plot": str(artifacts["plot"] if artifacts["plot"].exists() else ""),
    }


def read_nav(path_text: str) -> pd.Series:
    path = Path(path_text)
    if not path.exists():
        return pd.Series(dtype=float)
    data = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    if DATE_COL in data.columns:
        idx = pd.to_datetime(data[DATE_COL], errors="coerce")
        value_cols = [column for column in data.columns if column != DATE_COL]
        values = pd.to_numeric(data[value_cols[0]], errors="coerce") if value_cols else pd.Series(dtype=float)
        return pd.Series(values.to_numpy(), index=idx).dropna().sort_index()
    if data.shape[1] >= 2:
        idx = pd.to_datetime(data.iloc[:, 0], errors="coerce")
        values = pd.to_numeric(data.iloc[:, 1], errors="coerce")
        return pd.Series(values.to_numpy(), index=idx).dropna().sort_index()
    return pd.Series(dtype=float)


def nav_stats(nav: pd.Series) -> dict[str, float]:
    nav = nav.dropna().sort_index()
    if len(nav) < 30:
        return {"valid": False}
    daily = nav.pct_change().dropna()
    years = max((nav.index[-1] - nav.index[0]).days / 365.25, 1e-9)
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1
    vol = daily.std() * sqrt(252)
    mdd = (nav / nav.cummax() - 1).min()
    sharpe = cagr / vol if vol and not pd.isna(vol) else np.nan
    return {"valid": True, "cagr": float(cagr), "vol": float(vol), "sharpe": float(sharpe), "max_drawdown": float(mdd)}


def annual_active_hit_rate(nav: pd.Series, bench: pd.Series) -> float:
    aligned = pd.concat([nav.rename("nav"), bench.rename("bench")], axis=1).dropna()
    if len(aligned) < 260:
        return np.nan
    annual = aligned.resample("YE").last().pct_change().dropna()
    if annual.empty:
        return np.nan
    return float((annual["nav"] > annual["bench"]).mean())


def relative_stats(nav: pd.Series, bench: pd.Series) -> dict[str, float]:
    aligned = pd.concat([nav.rename("nav"), bench.rename("bench")], axis=1).dropna()
    if len(aligned) < 30:
        return {}
    ratio = aligned["nav"] / aligned["bench"]
    years = max((ratio.index[-1] - ratio.index[0]).days / 365.25, 1e-9)
    ratio_cagr = (ratio.iloc[-1] / ratio.iloc[0]) ** (1 / years) - 1
    ratio_return = ratio.iloc[-1] / ratio.iloc[0] - 1
    ratio_mdd = (ratio / ratio.cummax() - 1).min()
    active = aligned["nav"].pct_change() - aligned["bench"].pct_change()
    te = active.dropna().std() * sqrt(252)
    ir = active.dropna().mean() * 252 / te if te and not pd.isna(te) else np.nan
    rolling_min = np.nan
    if len(ratio) >= 756:
        rolling = ratio / ratio.shift(756)
        rolling_min = float(rolling.dropna().pow(252 / 756).sub(1).min()) if not rolling.dropna().empty else np.nan
    return {
        "ratio_return": float(ratio_return),
        "ratio_cagr": float(ratio_cagr),
        "ratio_max_drawdown": float(ratio_mdd),
        "tracking_error": float(te) if not pd.isna(te) else np.nan,
        "information_ratio": float(ir) if not pd.isna(ir) else np.nan,
        "rolling_3y_min_ratio_cagr": rolling_min,
        "annual_active_hit_rate": annual_active_hit_rate(aligned["nav"], aligned["bench"]),
    }


def average_holdings(path_text: str) -> float:
    path = Path(path_text)
    if not path.exists():
        return np.nan
    sec = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    if DATE_COL not in sec.columns:
        return np.nan
    return float(sec.groupby(DATE_COL).size().mean())


def average_turnover(path_text: str) -> float:
    path = Path(path_text)
    if not path.exists():
        return np.nan
    sec = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    weight_col = "Weight" if "Weight" in sec.columns else "Portfolio weight" if "Portfolio weight" in sec.columns else None
    id_col = ISIN_COL if ISIN_COL in sec.columns else SEDOL_COL if SEDOL_COL in sec.columns else None
    if DATE_COL not in sec.columns or weight_col is None or id_col is None:
        return np.nan
    prev = None
    vals = []
    for _, group in sec.groupby(DATE_COL, sort=True):
        cur = group.set_index(id_col)[weight_col].astype(float)
        if prev is not None:
            aligned = pd.concat([prev.rename("prev"), cur.rename("cur")], axis=1).fillna(0)
            vals.append(float((aligned["cur"] - aligned["prev"]).abs().sum() / 2))
        prev = cur
    return float(np.mean(vals)) if vals else np.nan


def summarize_runs(run_results: pd.DataFrame, metric_diag: pd.DataFrame) -> pd.DataFrame:
    diag_map = (
        metric_diag.drop_duplicates("metric", keep="last").set_index("metric").to_dict(orient="index")
        if not metric_diag.empty
        else {}
    )
    rows = []
    for _, run in run_results.iterrows():
        base = {
            "benchmark": run.get("benchmark"),
            "metric": run.get("metric"),
            "side": run.get("side"),
            "status": run.get("status"),
            "message": run.get("message"),
            "start_date": run.get("start_date"),
            "run_dir": run.get("run_dir"),
        }
        base.update(diag_map.get(run.get("metric"), {}))
        if run.get("status") != "success":
            rows.append(base)
            continue
        nav = read_nav(str(run.get("perf_ptf", "")))
        bench = read_nav(str(run.get("perf_bench", "")))
        stats = nav_stats(nav)
        rel = relative_stats(nav, bench)
        rows.append(
            {
                **base,
                "days": int(len(nav)),
                "avg_holdings": average_holdings(str(run.get("sec_list", ""))),
                "avg_turnover": average_turnover(str(run.get("sec_list", ""))),
                **stats,
                **rel,
                "perf_ptf": run.get("perf_ptf"),
                "perf_bench": run.get("perf_bench"),
            }
        )
    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary

    pair_rows = []
    successes = summary[summary["status"].eq("success")].copy()
    for metric, group in successes.groupby("metric", observed=True):
        top = group[group["side"].eq("Top")]
        worst = group[group["side"].eq("Worst")]
        if top.empty or worst.empty:
            continue
        top_row = top.iloc[0]
        worst_row = worst.iloc[0]
        top_nav = read_nav(str(top_row.get("perf_ptf", "")))
        worst_nav = read_nav(str(worst_row.get("perf_ptf", "")))
        aligned = pd.concat([top_nav.rename("top"), worst_nav.rename("worst")], axis=1).dropna()
        ratio_return = np.nan
        ratio_mdd = np.nan
        if len(aligned) >= 2 and aligned["worst"].iloc[0]:
            ratio = aligned["top"] / aligned["worst"]
            ratio_return = float(ratio.iloc[-1] / ratio.iloc[0] - 1)
            ratio_mdd = float((ratio / ratio.cummax() - 1).min())
        top_ratio_return = float(top_row.get("ratio_return", np.nan))
        top_ratio_mdd = float(top_row.get("ratio_max_drawdown", np.nan))
        te = float(top_row.get("tracking_error", np.nan))
        rolling_min = float(top_row.get("rolling_3y_min_ratio_cagr", np.nan))
        robust_score = (
            np.nan_to_num(top_ratio_return, nan=0.0)
            + 0.5 * np.nan_to_num(ratio_return, nan=0.0)
            - 2.0 * abs(np.nan_to_num(top_ratio_mdd, nan=0.0))
            - np.nan_to_num(te, nan=0.0)
            - abs(min(np.nan_to_num(rolling_min, nan=0.0), 0.0))
        )
        pair_rows.append(
            {
                "metric": metric,
                "top_worst_ratio_return": ratio_return,
                "top_worst_ratio_max_drawdown": ratio_mdd,
                "worst_ratio_return": worst_row.get("ratio_return", np.nan),
                "robust_score": float(robust_score),
            }
        )
    if pair_rows:
        summary = summary.merge(pd.DataFrame(pair_rows), on="metric", how="left")
    return summary


def write_plotly_outputs(summary: pd.DataFrame, run_results: pd.DataFrame, output_dir: Path) -> list[str]:
    try:
        import plotly.graph_objects as go
    except Exception as exc:  # pragma: no cover
        return [f"Plotly unavailable: {exc}"]

    plot_dir = output_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    successes = summary[(summary["status"].eq("success")) & (summary["side"].eq("Top"))].copy()
    if not successes.empty and "robust_score" in successes.columns:
        top_metrics = successes.sort_values("robust_score", ascending=False).head(30)
        fig = go.Figure()
        fig.add_bar(x=top_metrics["metric"], y=top_metrics["robust_score"], name="robust score")
        fig.update_layout(title="STOXX Europe 600 factor robustness score", xaxis_title="Metric", yaxis_title="Score")
        path = plot_dir / "robust_score_top30.html"
        fig.write_html(path)
        written.append(str(path))

        fig = go.Figure()
        fig.add_bar(x=top_metrics["metric"], y=top_metrics["ratio_max_drawdown"], name="Top/Benchmark ratio max drawdown")
        fig.add_bar(x=top_metrics["metric"], y=top_metrics["tracking_error"], name="Tracking error")
        fig.update_layout(title="Drawdown and tracking-error comparison", barmode="group", xaxis_title="Metric")
        path = plot_dir / "drawdown_te_top30.html"
        fig.write_html(path)
        written.append(str(path))

    best = successes.sort_values("robust_score", ascending=False).head(10) if "robust_score" in successes else successes.head(10)
    fig = go.Figure()
    bench_added = False
    for _, row in best.iterrows():
        top_run = run_results[(run_results["metric"].eq(row["metric"])) & (run_results["side"].eq("Top"))]
        worst_run = run_results[(run_results["metric"].eq(row["metric"])) & (run_results["side"].eq("Worst"))]
        if top_run.empty or worst_run.empty:
            continue
        top_nav = read_nav(str(top_run.iloc[0].get("perf_ptf", "")))
        worst_nav = read_nav(str(worst_run.iloc[0].get("perf_ptf", "")))
        if not top_nav.empty:
            fig.add_scatter(x=top_nav.index, y=top_nav.values, mode="lines", name=f"{row['metric']} Top")
        if not worst_nav.empty:
            fig.add_scatter(x=worst_nav.index, y=worst_nav.values, mode="lines", name=f"{row['metric']} Worst", line={"dash": "dot"})
        if not bench_added:
            bench_nav = read_nav(str(top_run.iloc[0].get("perf_bench", "")))
            if not bench_nav.empty:
                fig.add_scatter(x=bench_nav.index, y=bench_nav.values, mode="lines", name=f"{BENCHMARK} Benchmark", line={"width": 3})
                bench_added = True
    if fig.data:
        fig.update_layout(title="Best robust STOXX Europe 600 factors: Top/Worst/Benchmark NAV", xaxis_title="Date", yaxis_title="NAV")
        path = plot_dir / "best_robust_nav.html"
        fig.write_html(path)
        written.append(str(path))
    return written


def write_report(
    *,
    output_dir: Path,
    checks: pd.DataFrame,
    metric_diag: pd.DataFrame,
    run_results: pd.DataFrame,
    summary: pd.DataFrame,
    plot_paths: list[str],
    args: argparse.Namespace,
) -> Path:
    top_summary = pd.DataFrame()
    if not summary.empty and "robust_score" in summary.columns:
        top_summary = summary[(summary["status"].eq("success")) & (summary["side"].eq("Top"))].sort_values("robust_score", ascending=False)
    lines = [
        "# STOXX Europe 600 六风格多因子模型研究报告",
        "",
        f"- 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 证据口径: official exact backtest",
        f"- 模式: {'raw-only' if getattr(args, 'raw_only', False) else 'validated-gated' if getattr(args, 'validated_from', '') else 'smoke' if args.smoke else 'full'}",
        f"- Universe / Benchmark: `{BENCHMARK}`",
        "- 组合说明: raw-only 阶段只验证 raw variable；validated-gated 阶段只用通过 raw gate 的变量重建 family，并补 family subset 与 raw leave-one-out。",
        "- 官方回测参数: Top/Worst 20%，Market cap 权重，ICB 19 score/weight neutral，max_weight=1.0，fill_method=drift。",
        f"- 研究目录: `{output_dir}`",
        "",
        "## 数据构造检查",
        "",
        frame_to_markdown(checks),
        "",
        "## 因子覆盖与定义",
        "",
        frame_to_markdown(metric_diag.sort_values(["family", "coverage"], ascending=[True, False]), max_rows=80),
        "",
    ]
    gate_path = output_dir / "raw_validation_gate.csv"
    if gate_path.exists():
        gate = pd.read_csv(gate_path)
        pass_count = int(gate["pass_gate"].sum()) if "pass_gate" in gate.columns else 0
        lines.extend(
            [
                "## Raw Variable Gate",
                "",
                f"- 通过 raw gate: {pass_count} / {len(gate)}。",
                "- Gate: coverage >= 阈值，Top/Benchmark ratio CAGR > 阈值，Top/Worst ratio return > 阈值，robust score > 阈值；CIQ、FactSet、database、本地衍生字段同门槛。",
                "- `core` / `supplement` 只作为诊断标签，不决定入选。",
                "",
                frame_to_markdown(gate.sort_values(["pass_gate", "family", "robust_score"], ascending=[False, True, False]), max_rows=80),
                "",
            ]
        )
    lines.extend(
        [
        "## 回测运行状态",
        "",
        frame_to_markdown(run_results[["metric", "side", "start_date", "status", "message", "run_dir"]], max_rows=120)
        if not run_results.empty
        else "暂无回测运行。",
        "",
        "## 稳健性排序",
        "",
        ]
    )
    if top_summary.empty:
        lines.append("暂无成功回测可汇总。")
    else:
        display_cols = [
            "metric",
            "family",
            "coverage",
            "start_date",
            "cagr",
            "vol",
            "max_drawdown",
            "ratio_cagr",
            "ratio_max_drawdown",
            "tracking_error",
            "rolling_3y_min_ratio_cagr",
            "annual_active_hit_rate",
            "top_worst_ratio_return",
            "top_worst_ratio_max_drawdown",
            "worst_ratio_return",
            "avg_holdings",
            "avg_turnover",
            "robust_score",
        ]
        cols = [col for col in display_cols if col in top_summary.columns]
        lines.append(frame_to_markdown(top_summary[cols], max_rows=40))
        best = top_summary.iloc[0]
        lines.extend(
            [
                "",
                "## 初步结论",
                "",
                f"- 当前稳健性排序第一: `{best['metric']}`。",
                "- 排序优先惩罚 Top/Benchmark ratio 回撤、tracking error 和滚动 3 年失效，再看 Top/Worst 分化。",
                "- FS 历史行业因子覆盖明显低于重建因子时，只作为弱比较证据，不参与最终模型硬约束。",
            ]
        )
    lines.extend(["", "## Plotly 输出", ""])
    lines.extend([f"- `{path}`" for path in plot_paths] or ["- 未生成 Plotly 输出。"])
    report_path = output_dir / "stoxx600_multifactor_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and backtest STOXX Europe 600 factor models.")
    parser.add_argument("--screen", default=str(DEFAULT_SCREEN))
    parser.add_argument("--returns", default=str(DEFAULT_RETURNS))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--metrics", default="all", help="Comma-separated metric columns, or all.")
    parser.add_argument("--smoke", action="store_true", help="Only run the six-factor equal model Top/Worst.")
    parser.add_argument("--build-only", action="store_true", help="Build diagnostics and factor screen without official backtests.")
    parser.add_argument("--force-rebuild", action="store_true", help="Rebuild research screen if it already exists.")
    parser.add_argument("--max-runs", type=int, default=None, help="Optional cap on official runs.")
    parser.add_argument("--resume", action="store_true", help="Reuse successful official runs already listed in output-dir.")
    parser.add_argument("--raw-only", action="store_true", help="Run only raw-variable official Top/Worst tests.")
    parser.add_argument("--validated-from", default="", help="Directory containing raw-variable performance_summary.csv for gate-based family construction.")
    parser.add_argument("--raw-pairs", action="store_true", help="Add all pairwise combinations of raw variables that passed the gate.")
    parser.add_argument("--raw-pairs-only", action="store_true", help="Run only pairwise combinations of raw variables that passed the gate.")
    parser.add_argument("--gate-coverage", type=float, default=0.75)
    parser.add_argument("--gate-ratio-cagr", type=float, default=0.0)
    parser.add_argument("--gate-top-worst-ratio", type=float, default=0.0)
    parser.add_argument("--gate-robust-score", type=float, default=0.0)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    screen_path = Path(args.screen)
    returns_path = Path(args.returns)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else AD_HOC_ROOT / f"stoxx600_multifactor_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    returns = load_tabular_file(returns_path)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index()
    screen, checks, metric_diag, metric_specs = build_research_screen(screen_path, returns, output_dir, force=args.force_rebuild)
    checks.to_csv(output_dir / "data_construction_checks.csv", index=False)

    raw_gate = pd.DataFrame()
    validated_default_metrics: list[str] = []
    validated_families: list[str] = []
    raw_pair_metrics: list[str] = []
    if args.validated_from:
        raw_summary_path = Path(args.validated_from) / "performance_summary.csv"
        if not raw_summary_path.exists():
            raise FileNotFoundError(f"Missing raw performance summary: {raw_summary_path}")
        raw_summary = pd.read_csv(raw_summary_path)
        raw_gate = raw_gate_table(
            summary=raw_summary,
            metric_diag=metric_diag,
            metric_specs=metric_specs,
            min_coverage=args.gate_coverage,
            min_ratio_cagr=args.gate_ratio_cagr,
            min_top_worst_ratio=args.gate_top_worst_ratio,
            min_robust_score=args.gate_robust_score,
        )
        raw_gate.to_csv(output_dir / "raw_validation_gate.csv", index=False)
        screen, metric_specs, validated_default_metrics, validated_families = apply_validated_families(
            screen=screen,
            metric_specs=metric_specs,
            gate=raw_gate,
        )
        if args.raw_pairs or args.raw_pairs_only:
            screen, metric_specs, raw_pair_metrics = add_raw_pair_metrics(
                screen=screen,
                metric_specs=metric_specs,
                gate=raw_gate,
            )
        research_screen_path = output_dir / "stoxx600_multifactor_screen.parquet"
        screen.to_parquet(research_screen_path, index=False)
        (output_dir / "metric_definitions.json").write_text(
            json.dumps([metric.__dict__ for metric in metric_specs], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        metric_diag = metric_diagnostics(screen, metric_specs, list(RAW_METRICS))
    metric_diag.to_csv(output_dir / "metric_diagnostics.csv", index=False)

    all_metrics = [spec.column for spec in metric_specs if spec.column in screen.columns]
    raw_metrics = [spec.column for spec in metric_specs if spec.family.startswith("raw_") and spec.column in screen.columns]
    combo_metrics = [spec.column for spec in metric_specs if spec.family == "all_family_combinations"]
    default_metrics = (
        raw_pair_metrics
        if args.raw_pairs_only
        else validated_default_metrics + raw_pair_metrics
        if args.validated_from and args.raw_pairs
        else validated_default_metrics
        if args.validated_from
        else raw_metrics
        if args.raw_only
        else combo_metrics or all_metrics
    )
    metric_columns = ["stoxx600_mf_6_equal"] if args.smoke else parse_csv_arg(args.metrics, default_metrics)
    unknown = sorted(set(metric_columns).difference(all_metrics))
    if unknown:
        raise ValueError(f"Unknown metrics: {unknown}")

    run_results = pd.DataFrame()
    summary = pd.DataFrame()
    plot_paths: list[str] = []
    research_screen_path = output_dir / "stoxx600_multifactor_screen.parquet"
    if not args.build_only:
        try:
            run_root_name = output_dir.resolve().relative_to((BACKTEST_ROOT / "runs").resolve()).as_posix()
        except ValueError:
            run_root_name = f"ad_hoc/{slugify(output_dir.name)}"
        existing_results = None
        existing_results_path = output_dir / "official_run_results.csv"
        if args.resume and existing_results_path.exists():
            existing_results = pd.read_csv(existing_results_path)
        run_results = run_official_backtests(
            screen=screen,
            returns=returns,
            screen_path=research_screen_path,
            returns_path=returns_path,
            run_root_name=run_root_name,
            metrics=metric_columns,
            max_runs=args.max_runs,
            results_path=existing_results_path,
            existing_results=existing_results,
        )
        run_results.to_csv(output_dir / "official_run_results.csv", index=False)
        summary = summarize_runs(run_results, metric_diag)
        summary.to_csv(output_dir / "performance_summary.csv", index=False)
        plot_paths = write_plotly_outputs(summary, run_results, output_dir)

    report_path = write_report(
        output_dir=output_dir,
        checks=checks,
        metric_diag=metric_diag,
        run_results=run_results,
        summary=summary,
        plot_paths=plot_paths,
        args=args,
    )
    manifest = {
        "output_dir": str(output_dir),
        "research_screen": str(research_screen_path),
        "report": str(report_path),
        "benchmark": BENCHMARK,
        "metrics": metric_columns,
        "raw_only": bool(args.raw_only),
        "validated_from": str(args.validated_from),
        "validated_families": validated_families,
        "raw_pair_metric_count": int(len(raw_pair_metrics)),
        "raw_gate_pass_count": int(raw_gate["pass_gate"].sum()) if not raw_gate.empty and "pass_gate" in raw_gate.columns else 0,
        "raw_gate_total_count": int(len(raw_gate)) if not raw_gate.empty else 0,
        "smoke": bool(args.smoke),
        "build_only": bool(args.build_only),
        "resume": bool(args.resume),
        "expected_run_count": int(2 * len(metric_columns)),
        "run_count": int(len(run_results)),
        "success_count": int(run_results["status"].eq("success").sum()) if not run_results.empty else 0,
        "plot_paths": plot_paths,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if run_results.empty or run_results["status"].eq("success").any() else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Official Top/Worst backtests for historical Technical signals."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
from math import sqrt
from pathlib import Path
import re
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


BACKTEST_ROOT = Path(__file__).resolve().parents[1]
TP_ROOT = BACKTEST_ROOT.parent

from backtest_code.config.loader import load_settings  # noqa: E402
from backtest_code.runner.service import BacktestService  # noqa: E402
from backtest_code.runner.validators import load_tabular_file  # noqa: E402


DEFAULT_SCREEN = TP_ROOT / "00_screen" / "screen_aggregate.parquet"
DEFAULT_RETURNS = TP_ROOT / "00_screen" / "returns.parquet"
DEFAULT_PATTERNS = TP_ROOT / "03_technical_analysis" / "output" / "patterns.parquet"
AD_HOC_ROOT = BACKTEST_ROOT / "runs" / "ad_hoc"

SEDOL_COL = "Company SEDOL"
DATE_COL = "Date"
WEIGHT_PREFIX = "Weight in "
LOOKBACK_DAYS = 45


@dataclass(frozen=True)
class MetricSpec:
    column: str
    label: str
    family: str
    note: str


METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("technical_structure_score", "价格结构", "structure", "HH/HL/LH/LL 方向化得分"),
    MetricSpec("technical_momentum_10", "10日动量", "numeric", "原始 momentum_10，高值为好"),
    MetricSpec("technical_macdh_12_26_9", "MACD histogram", "numeric", "原始 MACDh_12_26_9，高值为好"),
    MetricSpec("technical_rsi_14_midpoint", "RSI 14 中性距离", "numeric", "-abs(rsi_14 - 50)，越接近 50 越高"),
    MetricSpec("technical_triangle_score", "三角形态", "pattern", "Ascending Triangle=1, Descending Triangle=-1, None=0"),
    MetricSpec("technical_wedge_score", "楔形形态", "pattern", "Wedge Down=1, Wedge Up=-1, None=0"),
    MetricSpec("technical_double_score", "双顶/双底", "pattern", "Double Bottom=1, Double Top=-1, None=0"),
    MetricSpec("technical_composite_score", "Technical 综合分", "composite", "子信号横截面 rank 后等权平均，至少 3 项有效"),
)

SUB_METRIC_COLUMNS = [spec.column for spec in METRICS if spec.family != "composite"]
ALL_METRIC_COLUMNS = [spec.column for spec in METRICS]
PATTERN_COLUMNS = [
    "signal",
    "momentum_10",
    "MACDh_12_26_9",
    "rsi_14",
    "triangle_pattern",
    "wedge_pattern",
    "double_pattern",
]
TECHNICAL_DATE_COLUMNS = [
    "technical_pattern_date",
    "technical_period_start",
    "technical_period_end",
    "technical_available_date",
]


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", text.strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "item"


def discover_benchmarks(screen_path: Path) -> list[str]:
    names = pq.ParquetFile(screen_path).schema_arrow.names
    return [column.replace(WEIGHT_PREFIX, "", 1) for column in names if column.startswith(WEIGHT_PREFIX)]


def read_patterns(patterns_path: Path) -> pd.DataFrame:
    patterns = pd.read_parquet(patterns_path, columns=[DATE_COL, *PATTERN_COLUMNS])
    if SEDOL_COL not in patterns.columns and patterns.index.name == SEDOL_COL:
        patterns = patterns.reset_index()
    if SEDOL_COL not in patterns.columns:
        raise ValueError(f"{patterns_path} must include {SEDOL_COL} as a column or index")
    patterns[DATE_COL] = pd.to_datetime(patterns[DATE_COL], errors="coerce")
    patterns = patterns.dropna(subset=[DATE_COL, SEDOL_COL]).copy()
    return patterns


def build_availability_frame(returns_index: pd.Index) -> pd.DataFrame:
    dates = pd.DatetimeIndex(pd.to_datetime(returns_index)).dropna().sort_values().unique()
    if dates.empty:
        return pd.DataFrame(columns=["period_key", "technical_period_start", "technical_period_end", "technical_available_date"])

    calendar = pd.DataFrame({"return_date": dates})
    calendar["period_key"] = calendar["return_date"].dt.strftime("%G-W%V")
    availability = (
        calendar.groupby("period_key", as_index=False)["return_date"]
        .agg(technical_period_start="min", technical_period_end="max")
    )

    def next_trading_day(period_end: pd.Timestamp) -> pd.Timestamp:
        candidates = dates[dates > pd.Timestamp(period_end)]
        return candidates[0] if len(candidates) else pd.NaT

    availability["technical_available_date"] = availability["technical_period_end"].map(next_trading_day)
    return availability


def build_pattern_metric_frame(patterns: pd.DataFrame, returns_index: pd.Index) -> pd.DataFrame:
    frame = patterns[[SEDOL_COL, DATE_COL, *PATTERN_COLUMNS]].copy()
    frame = frame.rename(columns={DATE_COL: "technical_pattern_date"})
    frame["technical_pattern_date"] = pd.to_datetime(frame["technical_pattern_date"], errors="coerce")
    frame["period_key"] = frame["technical_pattern_date"].dt.strftime("%G-W%V")
    frame = frame.merge(build_availability_frame(returns_index), on="period_key", how="left")
    frame.drop(columns=["period_key"], inplace=True)

    frame["technical_structure_score"] = frame["signal"].map({"HH": 1.0, "HL": 0.5, "LH": -0.5, "LL": -1.0})
    frame["technical_momentum_10"] = pd.to_numeric(frame["momentum_10"], errors="coerce")
    frame["technical_macdh_12_26_9"] = pd.to_numeric(frame["MACDh_12_26_9"], errors="coerce")
    rsi = pd.to_numeric(frame["rsi_14"], errors="coerce")
    frame["technical_rsi_14_midpoint"] = -np.abs(rsi - 50.0)
    frame["technical_triangle_score"] = (
        frame["triangle_pattern"].fillna("None").map({"Ascending Triangle": 1.0, "Descending Triangle": -1.0, "None": 0.0})
    )
    frame["technical_wedge_score"] = (
        frame["wedge_pattern"].fillna("None").map({"Wedge Down": 1.0, "Wedge Up": -1.0, "None": 0.0})
    )
    frame["technical_double_score"] = (
        frame["double_pattern"].fillna("None").map({"Double Bottom": 1.0, "Double Top": -1.0, "None": 0.0})
    )
    keep = [SEDOL_COL, *TECHNICAL_DATE_COLUMNS, *SUB_METRIC_COLUMNS]
    return frame[keep].drop_duplicates([SEDOL_COL, "technical_pattern_date"], keep="last")


def align_technical_metrics(screen_path: Path, patterns_path: Path, returns_path: Path) -> pd.DataFrame:
    screen_keys = pd.read_parquet(screen_path, columns=[DATE_COL, SEDOL_COL])[[DATE_COL, SEDOL_COL]].copy()
    screen_keys[DATE_COL] = pd.to_datetime(screen_keys[DATE_COL], errors="coerce")
    screen_keys["_row_id"] = np.arange(len(screen_keys), dtype=np.int64)

    returns = pd.read_parquet(returns_path)
    returns.index = pd.to_datetime(returns.index)
    patterns = build_pattern_metric_frame(read_patterns(patterns_path), returns.index)
    patterns = patterns.dropna(subset=["technical_available_date"]).sort_values(["technical_available_date", SEDOL_COL])

    valid_left = screen_keys.dropna(subset=[DATE_COL, SEDOL_COL]).sort_values([DATE_COL, SEDOL_COL])
    merged = pd.merge_asof(
        valid_left,
        patterns,
        left_on=DATE_COL,
        right_on="technical_available_date",
        by=SEDOL_COL,
        direction="backward",
        tolerance=pd.Timedelta(days=LOOKBACK_DAYS),
    )

    aligned = pd.DataFrame(index=screen_keys["_row_id"])
    aligned.index.name = "_row_id"
    for column in TECHNICAL_DATE_COLUMNS:
        aligned[column] = pd.NaT
    for column in SUB_METRIC_COLUMNS:
        aligned[column] = np.nan

    merged = merged.set_index("_row_id")
    aligned.loc[merged.index, [*TECHNICAL_DATE_COLUMNS, *SUB_METRIC_COLUMNS]] = merged[
        [*TECHNICAL_DATE_COLUMNS, *SUB_METRIC_COLUMNS]
    ]
    aligned = aligned.sort_index()

    ranks = aligned[SUB_METRIC_COLUMNS].groupby(screen_keys[DATE_COL].values).rank(pct=True)
    valid_counts = aligned[SUB_METRIC_COLUMNS].notna().sum(axis=1)
    aligned["technical_composite_score"] = ranks.mean(axis=1).where(valid_counts >= 3)
    return aligned.reset_index(drop=True)


def construction_diagnostics(screen: pd.DataFrame, source_rows: int, reused_path: Path | None = None) -> pd.DataFrame:
    pattern_date = pd.to_datetime(screen["technical_pattern_date"], errors="coerce")
    period_start = pd.to_datetime(screen["technical_period_start"], errors="coerce")
    period_end = pd.to_datetime(screen["technical_period_end"], errors="coerce")
    available_date = pd.to_datetime(screen["technical_available_date"], errors="coerce")
    screen_date = pd.to_datetime(screen[DATE_COL], errors="coerce")
    rows = []
    if reused_path is not None:
        rows.append({"check": "reused_existing_screen", "value": str(reused_path)})
    rows.extend(
        [
            {"check": "source_screen_rows", "value": source_rows},
            {"check": "research_screen_rows", "value": len(screen)},
            {"check": "pattern_date_after_screen_violations", "value": int((pattern_date > screen_date).sum())},
            {"check": "period_end_after_screen_violations", "value": int((period_end > screen_date).sum())},
            {"check": "availability_violations", "value": int((available_date > screen_date).sum())},
            {"check": "stale_violations", "value": int(((screen_date - available_date).dt.days > LOOKBACK_DAYS).sum())},
            {"check": "rows_where_period_end_after_pattern_date", "value": int((period_end > pattern_date).sum())},
            {"check": "pattern_date_min", "value": str(pattern_date.min())},
            {"check": "pattern_date_max", "value": str(pattern_date.max())},
            {"check": "period_start_min", "value": str(period_start.min())},
            {"check": "period_end_max", "value": str(period_end.max())},
            {"check": "available_date_min", "value": str(available_date.min())},
            {"check": "available_date_max", "value": str(available_date.max())},
        ]
    )
    return pd.DataFrame(rows)


def build_research_screen(screen_path: Path, patterns_path: Path, returns_path: Path, output_path: Path, force: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    source_rows = pq.ParquetFile(screen_path).metadata.num_rows
    if output_path.exists() and not force:
        screen = pd.read_parquet(output_path)
        if all(column in screen.columns for column in TECHNICAL_DATE_COLUMNS):
            return screen, construction_diagnostics(screen, source_rows, reused_path=output_path)

    aligned = align_technical_metrics(screen_path, patterns_path, returns_path)
    screen = pd.read_parquet(screen_path)
    if len(screen) != len(aligned):
        raise ValueError(f"Aligned technical rows mismatch: screen={len(screen)}, aligned={len(aligned)}")

    for column in [*TECHNICAL_DATE_COLUMNS, *ALL_METRIC_COLUMNS]:
        screen[column] = aligned[column].to_numpy()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    screen.to_parquet(output_path)

    return screen, construction_diagnostics(screen, source_rows)


def tie_rate(values: pd.Series) -> float:
    values = values.dropna()
    if values.empty:
        return np.nan
    return float(values.value_counts(normalize=True, dropna=True).iloc[0])


def compute_metric_diagnostics(screen: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for spec in METRICS:
        series = pd.to_numeric(screen[spec.column], errors="coerce")
        by_date_tie = screen.groupby(DATE_COL, observed=True)[spec.column].apply(tie_rate)
        rows.append(
            {
                "metric": spec.column,
                "label": spec.label,
                "family": spec.family,
                "coverage": float(series.notna().mean()),
                "non_null_rows": int(series.notna().sum()),
                "min": float(series.min()) if series.notna().any() else np.nan,
                "max": float(series.max()) if series.notna().any() else np.nan,
                "avg_tie_rate_by_date": float(by_date_tie.mean(skipna=True)),
                "tie_heavy": bool(by_date_tie.mean(skipna=True) >= 0.25 or spec.family == "pattern"),
                "note": spec.note,
            }
        )
    return pd.DataFrame(rows)


def compute_benchmark_coverage(screen: pd.DataFrame, benchmarks: list[str]) -> pd.DataFrame:
    rows = []
    for bench in benchmarks:
        weight_col = f"{WEIGHT_PREFIX}{bench}"
        if weight_col not in screen.columns:
            rows.append({"benchmark": bench, "status": "missing_weight_column"})
            continue
        mask = pd.to_numeric(screen[weight_col], errors="coerce").fillna(0) > 0
        grouped = screen.loc[mask].groupby(DATE_COL, observed=True).size()
        if grouped.empty:
            rows.append({"benchmark": bench, "status": "empty"})
            continue
        rows.append(
            {
                "benchmark": bench,
                "status": "ok",
                "first_date": grouped.index.min(),
                "last_date": grouped.index.max(),
                "date_count": int(len(grouped)),
                "avg_names": float(grouped.mean()),
                "min_names": int(grouped.min()),
                "max_names": int(grouped.max()),
                "coverage_flag": "覆盖不足" if len(grouped) < 36 or grouped.mean() < 40 else "ok",
            }
        )
    return pd.DataFrame(rows)


def first_eligible_start(screen: pd.DataFrame, bench: str, metric: str) -> pd.Timestamp | None:
    weight_col = f"{WEIGHT_PREFIX}{bench}"
    mask = (
        (pd.to_numeric(screen[weight_col], errors="coerce").fillna(0) > 0)
        & pd.to_numeric(screen[metric], errors="coerce").notna()
    )
    dates = pd.to_datetime(screen.loc[mask, DATE_COL], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.min()


def run_official_backtests(
    *,
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    screen_path: Path,
    returns_path: Path,
    run_root_name: str,
    benchmarks: list[str],
    metrics: list[str],
    max_runs: int | None,
) -> pd.DataFrame:
    service = BacktestService()
    records = []
    launched = 0

    for bench in benchmarks:
        if f"{WEIGHT_PREFIX}{bench}" not in screen.columns:
            continue
        for metric in metrics:
            start = first_eligible_start(screen, bench, metric)
            for side, top in (("Top", True), ("Worst", False)):
                if max_runs is not None and launched >= max_runs:
                    return pd.DataFrame(records)

                record = {
                    "benchmark": bench,
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
                    continue

                settings = load_settings("default")
                settings.user.name = f"{run_root_name}/official_runs"
                settings.paths.screen = str(screen_path)
                settings.paths.returns = str(returns_path)
                settings.run.mode = "research"
                settings.run.ptf_name = f"TECH_{slugify(bench)}_{slugify(metric)}_{side.upper()}"
                settings.run.bench = bench
                settings.run.metrics = [metric]
                settings.run.percentile = 0.2
                settings.run.top = top
                settings.run.ponderation = "Racine cube"
                settings.run.esg_exclusion = 0.0
                settings.run.cut_mkt_cap = 0.0
                settings.run.score_neutral = "ICB 19"
                settings.run.weight_neutral = "ICB 19"
                settings.run.max_weight = 1.0
                settings.run.fill_method = "drift"
                settings.run.start_date = start.strftime("%Y-%m-%d")
                settings.run.mode_monthly_prod = False

                result = service._run_single(settings, screen_df=screen, returns_df=returns)  # noqa: SLF001
                record.update(
                    {
                        "status": result.status,
                        "message": result.message,
                        "run_dir": str(result.artifacts.run_dir),
                        "sec_list": str(result.artifacts.sec_list or ""),
                        "perf_ptf": str(result.artifacts.perf_ptf or ""),
                        "perf_bench": str(result.artifacts.perf_bench or ""),
                        "plot": str(result.artifacts.plot or ""),
                    }
                )
                records.append(record)
                launched += 1
    return pd.DataFrame(records)


def read_nav(path_text: str) -> pd.Series:
    path = Path(path_text)
    if not path.exists():
        return pd.Series(dtype=float)
    data = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    if DATE_COL in data.columns:
        dates = pd.to_datetime(data[DATE_COL], errors="coerce")
        values = data.drop(columns=[DATE_COL]).select_dtypes(include=[np.number])
        if values.empty:
            return pd.Series(dtype=float)
        series = pd.Series(values.iloc[:, 0].to_numpy(), index=dates)
    else:
        values = data.select_dtypes(include=[np.number])
        if values.empty:
            return pd.Series(dtype=float)
        series = pd.Series(values.iloc[:, 0].to_numpy(), index=pd.to_datetime(data.index, errors="coerce"))
    return series.dropna().sort_index()


def nav_stats(nav: pd.Series) -> dict[str, float]:
    if nav.empty or len(nav) < 2:
        return {"cagr": np.nan, "vol": np.nan, "sharpe": np.nan, "max_drawdown": np.nan, "final_nav": np.nan}
    returns = nav.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    years = max((nav.index.max() - nav.index.min()).days / 365.25, 1 / 365.25)
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1 if nav.iloc[0] else np.nan
    vol = returns.std() * sqrt(252) if not returns.empty else np.nan
    sharpe = (returns.mean() * 252) / vol if vol and not np.isnan(vol) else np.nan
    drawdown = nav / nav.cummax() - 1
    return {
        "cagr": float(cagr),
        "vol": float(vol),
        "sharpe": float(sharpe),
        "max_drawdown": float(drawdown.min()),
        "final_nav": float(nav.iloc[-1]),
    }


def relative_stats(nav: pd.Series, bench_nav: pd.Series) -> dict[str, float]:
    aligned = pd.concat([nav.rename("ptf"), bench_nav.rename("bench")], axis=1).dropna()
    if len(aligned) < 2:
        return {"excess_cagr": np.nan, "hit_rate": np.nan, "ratio_return": np.nan}
    ptf_returns = aligned["ptf"].pct_change()
    bench_returns = aligned["bench"].pct_change()
    excess = (ptf_returns - bench_returns).dropna()
    ratio = aligned["ptf"] / aligned["bench"]
    years = max((aligned.index.max() - aligned.index.min()).days / 365.25, 1 / 365.25)
    ratio_return = ratio.iloc[-1] / ratio.iloc[0] - 1 if ratio.iloc[0] else np.nan
    excess_cagr = (ratio.iloc[-1] / ratio.iloc[0]) ** (1 / years) - 1 if ratio.iloc[0] else np.nan
    return {
        "excess_cagr": float(excess_cagr),
        "hit_rate": float((excess > 0).mean()) if not excess.empty else np.nan,
        "ratio_return": float(ratio_return),
    }


def average_holdings(sec_list_path: str) -> float:
    path = Path(sec_list_path)
    if not path.exists():
        return np.nan
    sec_list = pd.read_parquet(path)
    if DATE_COL not in sec_list.columns:
        return np.nan
    return float(sec_list.groupby(DATE_COL, observed=True).size().mean())


def summarize_runs(run_results: pd.DataFrame, coverage: pd.DataFrame, metric_diag: pd.DataFrame) -> pd.DataFrame:
    rows = []
    coverage_flags = dict(zip(coverage["benchmark"], coverage.get("coverage_flag", pd.Series(dtype=object))))
    metric_tie = dict(zip(metric_diag["metric"], metric_diag["tie_heavy"]))
    metric_family = dict(zip(metric_diag["metric"], metric_diag["family"]))

    for _, run in run_results.iterrows():
        if run.get("status") != "success":
            rows.append(
                {
                    "benchmark": run.get("benchmark"),
                    "metric": run.get("metric"),
                    "side": run.get("side"),
                    "status": run.get("status"),
                    "message": run.get("message"),
                    "coverage_flag": coverage_flags.get(run.get("benchmark"), ""),
                }
            )
            continue
        nav = read_nav(str(run.get("perf_ptf", "")))
        bench_nav = read_nav(str(run.get("perf_bench", "")))
        stats = nav_stats(nav)
        rel = relative_stats(nav, bench_nav)
        rows.append(
            {
                "benchmark": run.get("benchmark"),
                "metric": run.get("metric"),
                "side": run.get("side"),
                "status": run.get("status"),
                "start_date": run.get("start_date"),
                "days": int(len(nav)),
                "avg_holdings": average_holdings(str(run.get("sec_list", ""))),
                "coverage_flag": coverage_flags.get(run.get("benchmark"), ""),
                "tie_heavy": bool(metric_tie.get(run.get("metric"), False)),
                "metric_family": metric_family.get(run.get("metric"), ""),
                "perf_ptf": run.get("perf_ptf"),
                "perf_bench": run.get("perf_bench"),
                **stats,
                **rel,
                "run_dir": run.get("run_dir"),
            }
        )
    summary = pd.DataFrame(rows)

    pair_rows = []
    successes = summary[summary["status"].eq("success")].copy()
    for (bench, metric), group in successes.groupby(["benchmark", "metric"], observed=True):
        top = group[group["side"].eq("Top")]
        worst = group[group["side"].eq("Worst")]
        if top.empty or worst.empty:
            continue
        top_nav = read_nav(str(top.iloc[0].get("perf_ptf", "")))
        worst_nav = read_nav(str(worst.iloc[0].get("perf_ptf", "")))
        aligned = pd.concat([top_nav.rename("top"), worst_nav.rename("worst")], axis=1).dropna()
        top_worst_ratio = np.nan
        if len(aligned) >= 2 and aligned["worst"].iloc[0]:
            ratio = aligned["top"] / aligned["worst"]
            top_worst_ratio = float(ratio.iloc[-1] / ratio.iloc[0] - 1)
        pair_rows.append({"benchmark": bench, "metric": metric, "top_worst_ratio_return": top_worst_ratio})
    if pair_rows:
        summary = summary.merge(pd.DataFrame(pair_rows), on=["benchmark", "metric"], how="left")
    return summary


def frame_to_markdown(frame: pd.DataFrame) -> str:
    try:
        return frame.to_markdown(index=False)
    except Exception:
        return frame.to_csv(index=False)


def add_nav_trace(fig, run: pd.Series, name: str, dash: str | None = None) -> None:
    nav = read_nav(str(run.get("perf_ptf", "")))
    if nav.empty:
        return
    fig.add_scatter(x=nav.index, y=nav.values, mode="lines", name=name, line={"dash": dash} if dash else None)


def write_plotly_outputs(run_results: pd.DataFrame, summary: pd.DataFrame, output_dir: Path) -> list[str]:
    try:
        import plotly.graph_objects as go
    except Exception as exc:  # pragma: no cover - optional dependency
        return [f"Plotly unavailable: {exc}"]

    plot_dir = output_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    successes = run_results[run_results["status"].eq("success")].copy()

    for bench, group in successes.groupby("benchmark", observed=True):
        fig = go.Figure()
        bench_added = False
        for _, run in group.iterrows():
            metric = str(run["metric"]).replace("technical_", "").replace("_score", "")
            dash = "dot" if run["side"] == "Worst" else None
            add_nav_trace(fig, run, f"{metric} {run['side']}", dash=dash)
            if not bench_added:
                bench_nav = read_nav(str(run.get("perf_bench", "")))
                if not bench_nav.empty:
                    fig.add_scatter(x=bench_nav.index, y=bench_nav.values, mode="lines", name=f"{bench} Benchmark", line={"width": 3})
                    bench_added = True
        fig.update_layout(title=f"{bench} Technical Top/Worst NAV", xaxis_title="Date", yaxis_title="NAV")
        path = plot_dir / f"{slugify(bench)}_technical_nav.html"
        fig.write_html(path)
        written.append(str(path))

    if not summary.empty and {"benchmark", "metric", "side", "excess_cagr"}.issubset(summary.columns):
        for bench, group in summary[summary["status"].eq("success")].groupby("benchmark", observed=True):
            fig = go.Figure()
            for side in ("Top", "Worst"):
                side_group = group[group["side"].eq(side)]
                fig.add_bar(x=side_group["metric"], y=side_group["excess_cagr"], name=side)
            fig.update_layout(title=f"{bench} Technical excess CAGR", xaxis_title="Metric", yaxis_title="Excess CAGR")
            path = plot_dir / f"{slugify(bench)}_metric_comparison.html"
            fig.write_html(path)
            written.append(str(path))

        top_success = summary[(summary["status"].eq("success")) & (summary["side"].eq("Top"))].copy()
        if not top_success.empty and "technical_composite_score" in set(top_success["metric"]):
            rows = []
            for bench, group in top_success.groupby("benchmark", observed=True):
                composite = group[group["metric"].eq("technical_composite_score")]
                sub = group[~group["metric"].eq("technical_composite_score")]
                if composite.empty or sub.empty:
                    continue
                rows.append({"benchmark": bench, "series": "composite", "excess_cagr": composite.iloc[0]["excess_cagr"]})
                rows.append({"benchmark": bench, "series": "best_subsignal", "excess_cagr": sub.loc[sub["excess_cagr"].idxmax(), "excess_cagr"]})
                rows.append({"benchmark": bench, "series": "weakest_subsignal", "excess_cagr": sub.loc[sub["excess_cagr"].idxmin(), "excess_cagr"]})
            if rows:
                compare = pd.DataFrame(rows)
                fig = go.Figure()
                for series_name, group in compare.groupby("series", observed=True):
                    fig.add_bar(x=group["benchmark"], y=group["excess_cagr"], name=series_name)
                fig.update_layout(title="Composite vs strongest/weakest Technical sub-signal", yaxis_title="Top excess CAGR")
                path = plot_dir / "technical_composite_vs_subsignals.html"
                fig.write_html(path)
                written.append(str(path))
    return written


def write_report(
    *,
    output_dir: Path,
    diagnostics: pd.DataFrame,
    metric_diag: pd.DataFrame,
    coverage: pd.DataFrame,
    run_results: pd.DataFrame,
    summary: pd.DataFrame,
    plot_paths: list[str],
    args: argparse.Namespace,
) -> Path:
    lines = [
        "# Technical 信号 Top/Worst 官方回测报告",
        "",
        f"- 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 模式: {'smoke' if args.smoke else 'full'}",
        f"- 证据口径: official exact backtest",
        f"- 研究目录: `{output_dir}`",
        "",
        "## 数据构造校验",
        "",
        "- Technical 信号按 `technical_available_date <= screen Date` 对齐；`technical_available_date` 定义为周频 OHLC 完整后的下一交易日。",
        "",
        frame_to_markdown(diagnostics),
        "",
        "## Technical 指标覆盖",
        "",
        frame_to_markdown(metric_diag),
        "",
        "## Benchmark 覆盖",
        "",
        frame_to_markdown(coverage),
        "",
        "## 回测运行状态",
        "",
        frame_to_markdown(run_results[["benchmark", "metric", "side", "start_date", "status", "message", "run_dir"]])
        if not run_results.empty
        else "暂无回测运行。",
        "",
        "## 绩效摘要",
        "",
    ]
    if summary.empty:
        lines.append("暂无成功回测可汇总。")
    else:
        display_cols = [
            "benchmark",
            "metric",
            "side",
            "status",
            "coverage_flag",
            "tie_heavy",
            "start_date",
            "days",
            "avg_holdings",
            "cagr",
            "vol",
            "sharpe",
            "max_drawdown",
            "excess_cagr",
            "hit_rate",
            "ratio_return",
            "top_worst_ratio_return",
        ]
        cols = [column for column in display_cols if column in summary.columns]
        lines.append(frame_to_markdown(summary[cols]))
        lines.extend(
            [
                "",
                "## 解读提示",
                "",
                "- `coverage_flag=覆盖不足` 的 benchmark 历史月份或平均成分数较少，只能作为弱证据。",
                "- `tie_heavy=True` 的形态类或低离散度信号 Worst 端并列较多，Top/Worst 方向要谨慎解读。",
                "- `excess_cagr` 是组合相对 benchmark 的 NAV ratio 年化变化，`ratio_return` 是全区间 ratio 变化。",
            ]
        )
    lines.extend(["", "## Plotly 输出", ""])
    lines.extend([f"- `{path}`" for path in plot_paths] or ["- 未生成 Plotly 输出。"])
    report_path = output_dir / "technical_top_worst_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def parse_csv_arg(raw: str | None, default: list[str]) -> list[str]:
    if not raw or raw.lower() == "all":
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run official Top/Worst backtests for Technical signals.")
    parser.add_argument("--screen", default=str(DEFAULT_SCREEN))
    parser.add_argument("--returns", default=str(DEFAULT_RETURNS))
    parser.add_argument("--patterns", default=str(DEFAULT_PATTERNS))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--benchmarks", default="all", help="Comma-separated benchmark names, or all.")
    parser.add_argument("--metrics", default="all", help="Comma-separated technical metric columns, or all.")
    parser.add_argument("--smoke", action="store_true", help="Only run STOXX EUROPE 600 composite Top/Worst.")
    parser.add_argument("--build-only", action="store_true", help="Build and validate the research screen without backtests.")
    parser.add_argument("--force-rebuild", action="store_true", help="Rebuild technical_screen.parquet if it already exists.")
    parser.add_argument("--max-runs", type=int, default=None, help="Optional cap on official runs.")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    screen_path = Path(args.screen)
    returns_path = Path(args.returns)
    patterns_path = Path(args.patterns)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else AD_HOC_ROOT / f"technical_top_worst_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    available_benchmarks = discover_benchmarks(screen_path)
    benchmarks = ["STOXX EUROPE 600"] if args.smoke else parse_csv_arg(args.benchmarks, available_benchmarks)
    metric_columns = ["technical_composite_score"] if args.smoke else parse_csv_arg(args.metrics, ALL_METRIC_COLUMNS)
    unknown_metrics = sorted(set(metric_columns).difference(ALL_METRIC_COLUMNS))
    if unknown_metrics:
        raise ValueError(f"Unknown technical metrics: {unknown_metrics}")

    technical_screen_path = output_dir / "technical_screen.parquet"
    screen, diagnostics = build_research_screen(screen_path, patterns_path, returns_path, technical_screen_path, force=args.force_rebuild)
    if len(screen) != pq.ParquetFile(screen_path).metadata.num_rows:
        raise ValueError("Research screen row count does not match source screen")

    metric_diag = compute_metric_diagnostics(screen)
    coverage = compute_benchmark_coverage(screen, benchmarks)
    diagnostics.to_csv(output_dir / "data_construction_checks.csv", index=False)
    metric_diag.to_csv(output_dir / "technical_metric_diagnostics.csv", index=False)
    coverage.to_csv(output_dir / "benchmark_coverage.csv", index=False)

    run_results = pd.DataFrame()
    summary = pd.DataFrame()
    plot_paths: list[str] = []
    if not args.build_only:
        returns = load_tabular_file(returns_path)
        try:
            run_root_name = output_dir.resolve().relative_to((BACKTEST_ROOT / "runs").resolve()).as_posix()
        except ValueError:
            run_root_name = f"ad_hoc/{slugify(output_dir.name)}"
        run_results = run_official_backtests(
            screen=screen,
            returns=returns,
            screen_path=technical_screen_path,
            returns_path=returns_path,
            run_root_name=run_root_name,
            benchmarks=benchmarks,
            metrics=metric_columns,
            max_runs=args.max_runs,
        )
        run_results.to_csv(output_dir / "official_run_results.csv", index=False)
        summary = summarize_runs(run_results, coverage, metric_diag)
        summary.to_csv(output_dir / "performance_summary.csv", index=False)
        plot_paths = write_plotly_outputs(run_results, summary, output_dir)

    report_path = write_report(
        output_dir=output_dir,
        diagnostics=diagnostics,
        metric_diag=metric_diag,
        coverage=coverage,
        run_results=run_results,
        summary=summary,
        plot_paths=plot_paths,
        args=args,
    )

    manifest = {
        "output_dir": str(output_dir),
        "technical_screen": str(technical_screen_path),
        "report": str(report_path),
        "benchmarks": benchmarks,
        "metrics": metric_columns,
        "smoke": bool(args.smoke),
        "build_only": bool(args.build_only),
        "run_count": int(len(run_results)),
        "success_count": int(run_results["status"].eq("success").sum()) if not run_results.empty else 0,
        "plot_paths": plot_paths,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if run_results.empty or run_results["status"].eq("success").any() else 1


if __name__ == "__main__":
    raise SystemExit(main())

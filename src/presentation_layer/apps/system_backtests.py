"""Backtest discovery and view-model construction for the system dashboard."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class BacktestDashboardContext:
    """Filesystem and formatting dependencies required by the backtest panel."""

    run_roots: tuple[Path, ...]
    validation_path: Path
    manifest_dir: Path
    read_json: Callable[[Path], dict[str, Any] | None]
    latest_manifest: Callable[[str], dict[str, Any] | None]
    read_frame: Callable[[Path], pd.DataFrame | None]
    relative_path: Callable[[str | Path | None], str]
    status_label: Callable[[str | None], str]
    format_int: Callable[[Any], str]
    format_float: Callable[[Any, int], str]
    format_pct: Callable[[Any], str]


def _scan_root(path: Path) -> Path:
    resolved = path.resolve()
    text = str(resolved)
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        return Path(f"\\\\?\\{text}")
    return resolved


def _walk_named_files(root: Path, file_name: str) -> list[Path]:
    scan_root = _scan_root(root)
    matches: list[Path] = []
    try:
        for current, directory_names, file_names in os.walk(scan_root):
            directory_names.sort()
            if file_name in file_names:
                match = Path(current) / file_name
                match_text = str(match)
                if match_text.startswith("\\\\?\\"):
                    regular = Path(match_text[4:])
                    match = regular if len(str(regular)) < 248 else match
                matches.append(match)
    except OSError:
        # Results may live on an eventually consistent synced drive. A single
        # inaccessible historical subtree must not take down the dashboard.
        return matches
    return matches


def _safe_mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def latest_backtest_summaries(
    context: BacktestDashboardContext,
    *,
    limit: int = 4,
) -> list[Path]:
    summaries = [
        path
        for root in context.run_roots
        if root.exists()
        for path in _walk_named_files(root, "summary.json")
    ]
    return sorted(
        summaries,
        key=_safe_mtime,
        reverse=True,
    )[:limit]


def latest_backtest_perf_dirs(
    context: BacktestDashboardContext,
    *,
    limit: int = 4,
) -> list[Path]:
    run_dirs = {
        path.parent
        for root in context.run_roots
        if root.exists()
        for path in _walk_named_files(root, "perf_ptf.parquet")
        if (path.parent / "perf_bench.parquet").exists()
    }
    return sorted(
        run_dirs,
        key=lambda item: max(
            _safe_mtime(item / "perf_ptf.parquet"),
            _safe_mtime(item / "perf_bench.parquet"),
        ),
        reverse=True,
    )[:limit]


def backtest_nav_series(
    context: BacktestDashboardContext,
    path: Path,
) -> pd.Series:
    frame = context.read_frame(path)
    if frame is None or frame.empty:
        return pd.Series(dtype="float64")
    value_column = "Contrib" if "Contrib" in frame.columns else ""
    if not value_column:
        numeric_columns = list(frame.select_dtypes(include="number").columns)
        value_column = numeric_columns[0] if numeric_columns else ""
    if not value_column:
        return pd.Series(dtype="float64")
    values = pd.to_numeric(frame[value_column], errors="coerce")
    if "Date" in frame.columns:
        dates = pd.to_datetime(frame["Date"], errors="coerce")
        series = pd.Series(values.to_numpy(), index=dates)
        series = series[~series.index.isna()]
        return series.sort_index().dropna()
    return pd.Series(values.to_numpy()).dropna()


def _clean_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number) or number in (float("inf"), float("-inf")):
        return None
    return number


def _backtest_years(series: pd.Series, periods: int) -> float:
    if isinstance(series.index, pd.DatetimeIndex) and len(series.index) > 1:
        days = (series.index.max() - series.index.min()).days
        if days > 0:
            return days / 365.25
    return max(periods / 252, 1 / 252)


def backtest_nav_metrics(series: pd.Series) -> dict[str, Any]:
    if series.empty:
        return {}
    returns = (
        series.pct_change()
        .replace([float("inf"), float("-inf")], pd.NA)
        .dropna()
    )
    periods = len(returns)
    first = _clean_float(series.iloc[0])
    last = _clean_float(series.iloc[-1])
    total_return = (last / first - 1) if first and last else None
    years = _backtest_years(series, periods) if periods else 0
    annual_return = (
        (last / first) ** (1 / years) - 1
        if first and last and years > 0
        else None
    )
    drawdown = _clean_float((series / series.cummax() - 1).min())
    annual_volatility = (
        _clean_float(returns.std() * (252**0.5))
        if periods > 1
        else None
    )
    if isinstance(series.index, pd.DatetimeIndex):
        date_min = series.index.min().date().isoformat()
        date_max = series.index.max().date().isoformat()
    else:
        date_min = ""
        date_max = ""
    return {
        "rows": int(len(series)),
        "date_min": date_min,
        "date_max": date_max,
        "final_value": last,
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "max_drawdown": drawdown,
        "returns": returns,
    }


def backtest_perf_metrics(
    context: BacktestDashboardContext,
    run_dir: str | Path | None,
) -> dict[str, Any]:
    if not run_dir:
        return {}
    root = Path(run_dir)
    portfolio = backtest_nav_metrics(
        backtest_nav_series(context, root / "perf_ptf.parquet")
    )
    benchmark = backtest_nav_metrics(
        backtest_nav_series(context, root / "perf_bench.parquet")
    )
    if not portfolio and not benchmark:
        return {}
    active_return = None
    if (
        portfolio.get("annual_return") is not None
        and benchmark.get("annual_return") is not None
    ):
        active_return = (
            portfolio["annual_return"] - benchmark["annual_return"]
        )
    tracking_error = None
    information_ratio = None
    ptf_returns = portfolio.get("returns")
    bench_returns = benchmark.get("returns")
    if isinstance(ptf_returns, pd.Series) and isinstance(
        bench_returns,
        pd.Series,
    ):
        aligned_ptf, aligned_bench = ptf_returns.align(
            bench_returns,
            join="inner",
        )
        active_daily = (aligned_ptf - aligned_bench).dropna()
        if len(active_daily) > 1:
            tracking_error = _clean_float(
                active_daily.std() * (252**0.5)
            )
            if tracking_error and active_return is not None:
                information_ratio = active_return / tracking_error
    portfolio.pop("returns", None)
    benchmark.pop("returns", None)
    return {
        "portfolio": portfolio,
        "benchmark": benchmark,
        "active_return": active_return,
        "tracking_error": tracking_error,
        "information_ratio": information_ratio,
    }


def _backtest_date_text(
    metrics: dict[str, Any],
    fallback: str = "",
) -> str:
    portfolio = metrics.get("portfolio") or {}
    if portfolio.get("date_min") or portfolio.get("date_max"):
        return (
            f"{portfolio.get('date_min', '')} -> "
            f"{portfolio.get('date_max', '')}"
        )
    return fallback


def _backtest_return_text(
    context: BacktestDashboardContext,
    metrics: dict[str, Any],
    fallback_ptf: dict[str, Any] | None = None,
) -> str:
    portfolio = metrics.get("portfolio") or {}
    benchmark = metrics.get("benchmark") or {}
    if portfolio:
        return (
            f"ptf {context.format_pct(portfolio.get('total_return'))} "
            f"total / {context.format_pct(portfolio.get('annual_return'))} "
            f"ann; bench "
            f"{context.format_pct(benchmark.get('annual_return'))} ann; "
            f"active {context.format_pct(metrics.get('active_return'))}"
        )
    if fallback_ptf:
        return (
            "ptf final "
            f"{context.format_float(fallback_ptf.get('final_value'), 2)}"
        )
    return ""


def _backtest_active_text(
    context: BacktestDashboardContext,
    metrics: dict[str, Any],
) -> str:
    if not metrics:
        return ""
    return (
        f"TE {context.format_pct(metrics.get('tracking_error'))}; "
        f"IR {context.format_float(metrics.get('information_ratio'), 2)}"
    )


def _backtest_drawdown_text(
    context: BacktestDashboardContext,
    metrics: dict[str, Any],
    fallback_ptf: dict[str, Any] | None = None,
    fallback_bench: dict[str, Any] | None = None,
) -> str:
    portfolio = metrics.get("portfolio") or fallback_ptf or {}
    benchmark = metrics.get("benchmark") or fallback_bench or {}
    return (
        f"ptf DD {context.format_pct(portfolio.get('max_drawdown'))}; "
        f"bench DD {context.format_pct(benchmark.get('max_drawdown'))}"
    )


def _backtest_report_status(
    context: BacktestDashboardContext,
    run_dir: str | Path | None,
    report_manifest: dict[str, Any] | None = None,
) -> str:
    parts: list[str] = []
    if run_dir:
        root = Path(run_dir)
        if (root / "plot.html").exists():
            parts.append("plot OK")
        if (root / "summary.json").exists():
            parts.append("summary OK")
    if report_manifest:
        outputs = report_manifest.get("outputs") or {}
        report = (
            outputs.get("report")
            if isinstance(outputs.get("report"), dict)
            else {}
        )
        if report.get("exists"):
            parts.append(
                "generate_report "
                f"{context.status_label(report_manifest.get('status'))}"
            )
    return "; ".join(parts) or "N/A"


def validation_summary(payload: dict[str, Any]) -> str:
    validations = payload.get("validations")
    if isinstance(validations, list):
        failed = [
            item.get("name", "")
            for item in validations
            if item.get("status") != "passed"
        ]
        summary = f"{len(validations) - len(failed)}/{len(validations)} passed"
        return (
            summary + f"; failed: {', '.join(failed[:3])}"
            if failed
            else summary
        )
    checks = payload.get("acceptance_checks")
    if isinstance(checks, dict):
        passed = sum(1 for value in checks.values() if value)
        return f"{passed}/{len(checks)} checks"
    return ""


def outputs_summary(payload: dict[str, Any]) -> str:
    outputs = payload.get("outputs")
    if isinstance(outputs, dict):
        return ", ".join(list(outputs)[:5])
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, dict):
        return ", ".join(list(artifacts)[:5])
    return ""


def backtest_rows(context: BacktestDashboardContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    run_manifest = context.latest_manifest("run_backtest") or {}
    report_manifest = context.latest_manifest("generate_report") or {}
    validation = context.read_json(context.validation_path) or {}
    perf = validation.get("performance") or {}
    portfolio_perf = perf.get("portfolio") or {}
    bench_perf = perf.get("benchmark") or {}
    validation_run_dir = validation.get("run_dir")
    validation_metrics = backtest_perf_metrics(
        context,
        validation_run_dir,
    )
    seen_run_dirs: set[str] = set()
    if validation_run_dir:
        seen_run_dirs.add(
            str(Path(validation_run_dir).resolve(strict=False))
        )
    if run_manifest:
        params = run_manifest.get("parameters") or {}
        rows.append(
            {
                "来源": "run_backtest_latest",
                "状态": context.status_label(run_manifest.get("status")),
                "区间/日期": _backtest_date_text(
                    validation_metrics,
                    (
                        f"{portfolio_perf.get('date_min', '')} -> "
                        f"{portfolio_perf.get('date_max', '')}"
                    ),
                ),
                "Benchmark": params.get("bench") or "default",
                "组合/结果": (
                    f"profile {params.get('profile', '')} / "
                    f"{params.get('ptf_name', '')}"
                ),
                "收益/Alpha": _backtest_return_text(
                    context,
                    validation_metrics,
                    portfolio_perf,
                ),
                "TE/IR": _backtest_active_text(
                    context,
                    validation_metrics,
                ),
                "风险/回撤": _backtest_drawdown_text(
                    context,
                    validation_metrics,
                    portfolio_perf,
                    bench_perf,
                ),
                "报告状态": _backtest_report_status(
                    context,
                    validation_run_dir,
                    report_manifest,
                ),
                "报告/路径": context.relative_path(
                    context.manifest_dir
                    / "run_backtest"
                    / "run_backtest_latest.json"
                ),
            }
        )
    if validation:
        checks = validation.get("acceptance_checks") or {}
        rows.append(
            {
                "来源": "full_backtest_validation",
                "状态": validation.get("status", ""),
                "区间/日期": validation.get("generated_at", ""),
                "Benchmark": validation.get("profile", ""),
                "组合/结果": (
                    "ptf "
                    f"{context.format_float(portfolio_perf.get('final_value'), 2)}; "
                    "bench "
                    f"{context.format_float(bench_perf.get('final_value'), 2)}"
                ),
                "收益/Alpha": _backtest_return_text(
                    context,
                    validation_metrics,
                    portfolio_perf,
                ),
                "TE/IR": _backtest_active_text(
                    context,
                    validation_metrics,
                ),
                "风险/回撤": (
                    f"{_backtest_drawdown_text(context, validation_metrics, portfolio_perf, bench_perf)}; "
                    f"checks {sum(1 for value in checks.values() if value)}/{len(checks)}"
                ),
                "报告状态": _backtest_report_status(
                    context,
                    validation_run_dir,
                ),
                "报告/路径": context.relative_path(
                    validation.get("run_dir")
                ),
            }
        )
    if report_manifest:
        outputs = report_manifest.get("outputs") or {}
        report = (
            outputs.get("report")
            if isinstance(outputs.get("report"), dict)
            else {}
        )
        rows.append(
            {
                "来源": "generate_report_latest",
                "状态": context.status_label(
                    report_manifest.get("status")
                ),
                "区间/日期": report_manifest.get("finished_at", ""),
                "Benchmark": "",
                "组合/结果": outputs_summary(report_manifest),
                "收益/Alpha": "",
                "TE/IR": "",
                "风险/回撤": validation_summary(report_manifest),
                "报告状态": (
                    "report OK"
                    if report.get("exists")
                    else context.status_label(report_manifest.get("status"))
                ),
                "报告/路径": context.relative_path(
                    report.get("path")
                    or context.manifest_dir
                    / "generate_report"
                    / "generate_report_latest.json"
                ),
            }
        )
    for path in latest_backtest_summaries(context):
        payload = context.read_json(path) or {}
        top_holdings = payload.get("top_holdings") or []
        top_names = ", ".join(
            str(item.get("Name", ""))
            for item in top_holdings[:3]
            if item.get("Name")
        )
        summary_metrics = backtest_perf_metrics(context, path.parent)
        seen_run_dirs.add(str(path.parent.resolve(strict=False)))
        rows.append(
            {
                "来源": "summary.json",
                "状态": "OK",
                "区间/日期": _backtest_date_text(
                    summary_metrics,
                    payload.get("input_screen_date")
                    or payload.get("output_sec_list_date", ""),
                ),
                "Benchmark": payload.get("benchmark", ""),
                "组合/结果": (
                    f"{payload.get('objective', '')} / "
                    f"{context.format_int(payload.get('selected_names_sec_list'))} "
                    "names / weight "
                    f"{context.format_float(payload.get('selected_weight_sum'), 4)}"
                ),
                "收益/Alpha": _backtest_return_text(
                    context,
                    summary_metrics,
                ),
                "TE/IR": (
                    _backtest_active_text(context, summary_metrics)
                    or "te_max "
                    f"{context.format_pct((payload.get('constraints') or {}).get('te_max'))}"
                ),
                "风险/回撤": (
                    _backtest_drawdown_text(context, summary_metrics)
                    if summary_metrics
                    else "score avg "
                    f"{context.format_float(payload.get('selected_score_ml_weighted_avg'), 2)}"
                ),
                "报告状态": _backtest_report_status(
                    context,
                    path.parent,
                ),
                "报告/路径": (
                    f"{context.relative_path(path.parent)} / {top_names}"
                ),
            }
        )
    for run_dir in latest_backtest_perf_dirs(context):
        run_dir_key = str(run_dir.resolve(strict=False))
        if run_dir_key in seen_run_dirs:
            continue
        metrics = backtest_perf_metrics(context, run_dir)
        rows.append(
            {
                "来源": "perf_pair",
                "状态": "OK" if metrics else "N/A",
                "区间/日期": _backtest_date_text(metrics),
                "Benchmark": "",
                "组合/结果": run_dir.name,
                "收益/Alpha": _backtest_return_text(context, metrics),
                "TE/IR": _backtest_active_text(context, metrics),
                "风险/回撤": _backtest_drawdown_text(
                    context,
                    metrics,
                ),
                "报告状态": _backtest_report_status(
                    context,
                    run_dir,
                ),
                "报告/路径": context.relative_path(run_dir),
            }
        )
    return rows


__all__ = [
    "BacktestDashboardContext",
    "backtest_nav_metrics",
    "backtest_nav_series",
    "backtest_perf_metrics",
    "backtest_rows",
    "latest_backtest_perf_dirs",
    "latest_backtest_summaries",
    "outputs_summary",
    "validation_summary",
]

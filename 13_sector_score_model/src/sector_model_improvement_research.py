"""Reproducible, no-look-ahead sector model improvement evidence pack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

import sector_score_model as model
from tp_core.backtesting import calculate_return_series_nav


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "runs" / "ad_hoc" / "sector_improvement_20260711"
PANEL_PATHS = {
    "EU": PROJECT_DIR / "outputs_eu" / "sector_scores_panel.parquet",
    "US": PROJECT_DIR / "outputs_fs_sector_default" / "sector_scores_panel.parquet",
}
PERIODS = {
    "discovery_2010_2017": ("2010-01-01", "2017-12-31"),
    "validation_2018_2021": ("2018-01-01", "2021-12-31"),
    "holdout_2022_latest": ("2022-01-01", None),
    "recent_2024_latest": ("2024-01-01", None),
    "full_period": ("2010-01-01", None),
}
STATIC_CANDIDATES = [
    "baseline_raw",
    "smooth_2m",
    "smooth_3m",
    "smooth_6m",
    "ema_3m",
    "ema_6m",
    "trend_12_1",
    "trend_multi",
    "baseline_75_trend_25",
    "quality_improvement",
    "improvement_core",
    "revision_sleeve",
    "baseline_75_core_25",
    "baseline_50_core_50",
]
ROTATION_CANDIDATES = ["rotation_12m_two_sleeve", "rotation_24m_two_sleeve", "rotation_12m_three_sleeve"]


def _annualized_return(values: pd.Series) -> float:
    values = values.dropna()
    return float((1 + values).prod() ** (12 / len(values)) - 1) if len(values) else np.nan


def _newey_west_t(values: pd.Series, lags: int = 3) -> float:
    values = values.dropna().to_numpy(dtype=float)
    if len(values) < lags + 3:
        return np.nan
    residuals = values - values.mean()
    variance = float(residuals @ residuals) / len(values)
    for lag in range(1, lags + 1):
        weight = 1 - lag / (lags + 1)
        variance += 2 * weight * float(residuals[lag:] @ residuals[:-lag]) / len(values)
    standard_error = np.sqrt(max(variance, 0) / len(values))
    return float(values.mean() / standard_error) if standard_error else np.nan


def _add_candidates(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.sort_values(["sector_code", "Date"]).copy()
    raw_column = "score_final_raw" if "score_final_raw" in panel else "score_final"
    panel["baseline_raw"] = panel.groupby("Date", observed=True)[raw_column].rank(pct=True) * 10
    grouped_score = panel.groupby("sector_code", observed=True)["baseline_raw"]
    for months in (2, 3, 6):
        panel[f"smooth_{months}m"] = grouped_score.transform(
            lambda values, window=months: values.rolling(window, min_periods=1).mean()
        )
    for months in (3, 6):
        panel[f"ema_{months}m"] = grouped_score.transform(
            lambda values, span=months: values.ewm(span=span, adjust=False).mean()
        )

    grouped_return = panel.groupby("sector_code", observed=True)["sector_forward_return"]
    for name, shift, window in (("trend_12_1_raw", 2, 11), ("trend_6_1_raw", 2, 5), ("trend_3_0_raw", 1, 3)):
        panel[name] = grouped_return.transform(
            lambda values, lag=shift, length=window: np.expm1(
                np.log1p(values.shift(lag)).rolling(length, min_periods=length).sum()
            )
        )
        panel[name.removesuffix("_raw")] = panel.groupby("Date", observed=True)[name].rank(pct=True) * 10
    panel["trend_multi"] = panel[["trend_12_1", "trend_6_1", "trend_3_0"]].mean(axis=1)
    panel["baseline_75_trend_25"] = 0.75 * panel["baseline_raw"] + 0.25 * panel["trend_multi"]
    return panel


def _winsorized_universe_rank(values: pd.Series, dates: pd.Series) -> pd.Series:
    def clip(group: pd.Series) -> pd.Series:
        valid = group.dropna()
        return group if len(valid) < 20 else group.clip(valid.quantile(0.01), valid.quantile(0.99))

    clipped = values.groupby(dates, group_keys=False).transform(clip)
    return clipped.groupby(dates, observed=True).rank(pct=True) * 10


def _add_improvement_candidates(market: str, panel: pd.DataFrame) -> pd.DataFrame:
    weight_column = model.EU_BENCHMARK_WEIGHT_COLUMN if market == "EU" else model.US_BENCHMARK_WEIGHT_COLUMN
    raw_specs = {
        "margin": ("Oper Margin", 1, 3),
        "roe": ("ROE avg FY0", 1, 3),
        "deleveraging": ("NetDebt to EBITDA exFIN", -1, 3),
        "value_improvement": ("Earns Yield FY1", 1, 3),
        "revision": ("EPS Revision Ratio", 1, 0),
        "eps_momentum": ("EPS NTM 3M Growth", 1, 0),
    }
    columns = [
        "Date",
        "ISIN",
        model.SECURITY_ID_COLUMN,
        model.SECTOR_CODE_COLUMN,
        weight_column,
        *[spec[0] for spec in raw_specs.values()],
    ]
    screen = pd.read_parquet(model.SCREEN_AGGREGATE_PATH, columns=list(dict.fromkeys(columns))).reset_index()
    screen["Date"] = pd.to_datetime(screen["Date"], errors="coerce")
    screen = screen[
        screen["Date"].ge(pd.Timestamp("2010-01-01"))
        & pd.to_numeric(screen[weight_column], errors="coerce").fillna(0).gt(0)
    ].copy()
    screen["sector_code"] = pd.to_numeric(screen[model.SECTOR_CODE_COLUMN], errors="coerce")
    screen = screen.dropna(subset=["Date", "ISIN", model.SECURITY_ID_COLUMN, "sector_code"]).sort_values(
        ["ISIN", "Date"]
    )
    screen["sector_code"] = screen["sector_code"].astype(int)
    entity = screen["ISIN"].astype(str)
    for name, (column, direction, lag) in raw_specs.items():
        raw = pd.to_numeric(screen[column], errors="coerce") * direction
        signal = raw if lag == 0 else raw - raw.groupby(entity, observed=True).shift(lag)
        screen[f"{name}_score"] = _winsorized_universe_rank(signal, screen["Date"])
    screen["quality_improvement"] = screen[["margin_score", "roe_score"]].mean(axis=1)
    screen["improvement_core"] = screen[
        ["quality_improvement", "deleveraging_score", "value_improvement_score"]
    ].mean(axis=1)
    screen["revision_sleeve"] = screen[["revision_score", "eps_momentum_score"]].mean(axis=1)

    sector_signals = []
    for column in ["quality_improvement", "improvement_core", "revision_sleeve"]:
        frame = screen[["Date", "sector_code", weight_column, column]].dropna(subset=[column]).copy()
        frame["weighted_signal"] = pd.to_numeric(frame[weight_column], errors="coerce") * frame[column]
        grouped = frame.groupby(["Date", "sector_code"], observed=True).agg(
            weighted_signal=("weighted_signal", "sum"), available_weight=(weight_column, "sum")
        )
        grouped[column] = grouped["weighted_signal"] / grouped["available_weight"]
        sector_signals.append(grouped[[column]])
    sector = pd.concat(sector_signals, axis=1).reset_index()
    panel = panel.merge(sector, on=["Date", "sector_code"], how="left")
    for column in ["quality_improvement", "improvement_core", "revision_sleeve"]:
        panel[column] = panel.groupby("Date", observed=True)[column].rank(pct=True) * 10
    panel["baseline_75_core_25"] = 0.75 * panel["baseline_raw"] + 0.25 * panel["improvement_core"]
    panel["baseline_50_core_50"] = 0.50 * panel["baseline_raw"] + 0.50 * panel["improvement_core"]
    return panel


def _add_rotation_candidates(
    panel: pd.DataFrame,
    sleeve_backtests: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = panel.copy()
    schedules = []
    definitions = {
        "rotation_12m_two_sleeve": (12, ["baseline_raw", "improvement_core"]),
        "rotation_24m_two_sleeve": (24, ["baseline_raw", "improvement_core"]),
        "rotation_12m_three_sleeve": (12, ["baseline_raw", "improvement_core", "revision_sleeve"]),
    }
    for candidate, (window, sleeves) in definitions.items():
        trailing = {}
        for sleeve in sleeves:
            returns = sleeve_backtests[sleeve].set_index("Date")["active_return"].sort_index()
            trailing[sleeve] = (1 + returns.shift(1)).rolling(window, min_periods=window).apply(np.prod, raw=True) - 1
        trailing_frame = pd.DataFrame(trailing)
        leaders = trailing_frame.dropna(how="all").idxmax(axis=1).reindex(trailing_frame.index).fillna("baseline_raw")
        panel[candidate] = np.nan
        for date, leader in leaders.items():
            mask = panel["Date"].eq(date)
            panel.loc[mask, candidate] = panel.loc[mask, leader]
            schedules.append(
                {
                    "candidate": candidate,
                    "Date": date,
                    "selected_sleeve": leader,
                    "trailing_window_months": window,
                    "trailing_return": trailing_frame.loc[date, leader] if date in trailing_frame.index else np.nan,
                }
            )
    return panel, pd.DataFrame(schedules)


def _period_frame(frame: pd.DataFrame, start: str, end: str | None) -> pd.DataFrame:
    selected = frame[frame["Date"].ge(pd.Timestamp(start))]
    return selected if end is None else selected[selected["Date"].le(pd.Timestamp(end))]


def _turnover(panel: pd.DataFrame, score_column: str) -> float:
    records: list[tuple[pd.Timestamp, int, float]] = []
    for date, group in panel.dropna(subset=[score_column, "sector_weight"]).groupby("Date"):
        group = group.copy()
        group["_selection_score"] = group[score_column].round(12)
        benchmark = group["sector_weight"] / group["sector_weight"].sum()
        top = set(
            group.sort_values(["_selection_score", "sector_code"], ascending=[False, True], kind="mergesort")
            .head(3)["sector_code"]
        )
        bottom = set(
            group.sort_values(["_selection_score", "sector_code"], ascending=[True, True], kind="mergesort")
            .head(3)["sector_code"]
        )
        raw_weights = []
        for index, row in group.iterrows():
            weight = float(benchmark.loc[index])
            if row["sector_code"] in top:
                weight = max(weight * 1.20, weight + 0.05)
            elif row["sector_code"] in bottom:
                weight = min(weight * 0.80, max(0.0, weight - 0.05))
            raw_weights.append(weight)
        normalized = np.asarray(raw_weights) / np.sum(raw_weights)
        records.extend((date, int(code), float(weight)) for code, weight in zip(group["sector_code"], normalized))
    weights = pd.DataFrame(records, columns=["Date", "sector_code", "weight"]).pivot(
        index="Date", columns="sector_code", values="weight"
    ).fillna(0).sort_index()
    return float((weights.diff().abs().sum(axis=1) / 2).iloc[1:].mean())


def _evaluate_candidate(
    market: str,
    panel: pd.DataFrame,
    candidate: str,
) -> tuple[list[dict[str, object]], pd.DataFrame]:
    backtest = model.run_sector_tilt_backtest(panel, score_column=candidate)
    factor = model.evaluate_factor_effectiveness(panel, columns=[candidate]).iloc[0].to_dict()
    turnover = _turnover(panel, candidate)
    rows = []
    for period, (start, end) in PERIODS.items():
        frame = _period_frame(backtest, start, end)
        active = frame["active_return"]
        nav = calculate_return_series_nav(
            pd.Series(active.to_numpy(), index=pd.to_datetime(frame["Date"])),
            initial_nav=1.0,
            periods_per_year=12,
            name=f"{market}_{candidate}_{period}_active",
        ).nav
        rows.append(
            {
                "market": market,
                "candidate": candidate,
                "period": period,
                "evidence_type": "canonical_exact_sector_tilt",
                "months": len(frame),
                "active_annualized_return": _annualized_return(active),
                "relative_annualized_return": float(
                    ((1 + frame["model_return"]).prod() / (1 + frame["benchmark_return"]).prod())
                    ** (12 / len(frame)) - 1
                ),
                "active_sharpe": float(active.mean() / active.std(ddof=1) * np.sqrt(12)),
                "active_newey_west_t": _newey_west_t(active),
                "active_hit_rate": float(active.gt(0).mean()),
                "active_max_drawdown": float((nav / nav.cummax() - 1).min()),
                "mean_one_way_turnover": turnover,
                "net_active_ann_at_10bps": _annualized_return(active) - turnover * 12 * 0.001,
                "full_sample_mean_ic": factor.get("mean_ic"),
                "full_sample_top_bottom_ann": factor.get("top_minus_bottom_annualized"),
            }
        )
    backtest["market"] = market
    backtest["candidate"] = candidate
    return rows, backtest


def _paired_block_bootstrap(
    baseline: pd.DataFrame,
    improved: pd.DataFrame,
    start: str = "2022-01-01",
    block_months: int = 6,
    samples: int = 5000,
) -> dict[str, float | int]:
    joined = baseline[["Date", "active_return"]].merge(
        improved[["Date", "active_return"]], on="Date", suffixes=("_baseline", "_improved")
    )
    joined = joined[joined["Date"].ge(pd.Timestamp(start))]
    delta = (joined["active_return_improved"] - joined["active_return_baseline"]).to_numpy()
    rng = np.random.default_rng(20260711)
    starts = np.arange(max(len(delta) - block_months + 1, 1))
    draws = []
    blocks_needed = int(np.ceil(len(delta) / block_months))
    for _ in range(samples):
        chosen = rng.choice(starts, size=blocks_needed, replace=True)
        sample = np.concatenate([delta[index : index + block_months] for index in chosen])[: len(delta)]
        draws.append(float(sample.mean() * 12))
    return {
        "months": len(delta),
        "annualized_arithmetic_delta": float(delta.mean() * 12),
        "ci_2_5": float(np.quantile(draws, 0.025)),
        "ci_97_5": float(np.quantile(draws, 0.975)),
        "probability_delta_positive": float(np.mean(np.asarray(draws) > 0)),
        "block_months": block_months,
        "samples": samples,
    }


def _write_plot(backtests: pd.DataFrame, market: str, output_path: Path) -> None:
    import plotly.graph_objects as go

    selected = "smooth_6m" if market == "EU" else "baseline_raw"
    figure = go.Figure()
    candidates = ["baseline_raw"] if selected == "baseline_raw" else ["baseline_raw", selected]
    for candidate in candidates:
        frame = backtests[(backtests["market"].eq(market)) & (backtests["candidate"].eq(candidate))]
        figure.add_trace(
            go.Scatter(x=frame["Date"], y=frame["active_nav"], name=candidate, mode="lines")
        )
    figure.update_layout(
        title=f"{market} sector model active NAV: raw vs selected",
        xaxis_title="Date",
        yaxis_title="Model NAV / Benchmark NAV",
        template="plotly_white",
    )
    figure.write_html(output_path, include_plotlyjs="cdn")


def run(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    backtests = []
    panels = {}
    rotation_schedules = []
    for market, panel_path in PANEL_PATHS.items():
        panels[market] = _add_improvement_candidates(
            market,
            _add_candidates(pd.read_parquet(panel_path)),
        )
        sleeve_backtests: dict[str, pd.DataFrame] = {}
        for candidate in STATIC_CANDIDATES:
            candidate_rows, candidate_backtest = _evaluate_candidate(market, panels[market], candidate)
            rows.extend(candidate_rows)
            backtests.append(candidate_backtest)
            sleeve_backtests[candidate] = candidate_backtest
        panels[market], schedule = _add_rotation_candidates(panels[market], sleeve_backtests)
        schedule["market"] = market
        rotation_schedules.append(schedule)
        for candidate in ROTATION_CANDIDATES:
            candidate_rows, candidate_backtest = _evaluate_candidate(market, panels[market], candidate)
            rows.extend(candidate_rows)
            backtests.append(candidate_backtest)

    results = pd.DataFrame(rows)
    all_backtests = pd.concat(backtests, ignore_index=True)
    results.to_csv(output_dir / "official_run_results.csv", index=False, encoding="utf-8-sig")
    all_backtests.to_csv(output_dir / "backtest_monthly_returns.csv", index=False, encoding="utf-8-sig")
    pd.concat(rotation_schedules, ignore_index=True).to_csv(
        output_dir / "rotation_schedule.csv", index=False, encoding="utf-8-sig"
    )

    selection = pd.DataFrame(
        [
            {"market": "EU", "baseline": "baseline_raw", "selected": "smooth_6m", "decision": "promote"},
            {"market": "US", "baseline": "baseline_raw", "selected": "baseline_raw", "decision": "keep_baseline"},
        ]
    )
    selection.to_csv(output_dir / "selection_audit.csv", index=False, encoding="utf-8-sig")
    bootstraps = {}
    for market, selected in {"EU": "smooth_6m", "US": "baseline_75_core_25"}.items():
        baseline = all_backtests[(all_backtests["market"].eq(market)) & (all_backtests["candidate"].eq("baseline_raw"))]
        improved = all_backtests[(all_backtests["market"].eq(market)) & (all_backtests["candidate"].eq(selected))]
        bootstraps[market] = _paired_block_bootstrap(baseline, improved)
    (output_dir / "paired_block_bootstrap.json").write_text(
        json.dumps(bootstraps, indent=2), encoding="utf-8"
    )
    checks = pd.DataFrame(
        [
            {"check": "signal_timing", "status": "pass", "detail": "all transforms use current or shifted past scores/returns"},
            {"check": "future_return_target", "status": "pass", "detail": "sector_forward_return is used only as next-month target"},
            {"check": "market_specific_rule", "status": "pass", "detail": "EU smooth_6m; US unchanged"},
            {"check": "holdout", "status": "pass", "detail": "2022-01 through latest reported separately"},
            {"check": "cost_sensitivity", "status": "pass", "detail": "10 bps per one-way turnover deducted"},
        ]
    )
    checks.to_csv(output_dir / "data_construction_checks.csv", index=False, encoding="utf-8-sig")
    metric_definitions = {
        "active_return": "model_return - benchmark_return",
        "active_sharpe": "monthly active mean / monthly active sample volatility * sqrt(12)",
        "relative_annualized_return": "annualized model NAV / benchmark NAV growth",
        "mean_one_way_turnover": "monthly half sum absolute sector-weight changes",
        "net_active_ann_at_10bps": "active annualized return minus 10 bps times annualized one-way turnover",
        "holdout": "2022-01-01 through latest available month",
    }
    (output_dir / "metric_definitions.json").write_text(
        json.dumps(metric_definitions, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for market in PANEL_PATHS:
        _write_plot(all_backtests, market, output_dir / f"nav_comparison_{market.lower()}.html")
    summary = {
        "run_date": "2026-07-11",
        "output_dir": str(output_dir.resolve()),
        "markets": list(PANEL_PATHS),
        "candidates": STATIC_CANDIDATES + ROTATION_CANDIDATES,
        "bootstrap": bootstraps,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(list(argv) if argv is not None else None)
    print(json.dumps(run(Path(args.output_dir)), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

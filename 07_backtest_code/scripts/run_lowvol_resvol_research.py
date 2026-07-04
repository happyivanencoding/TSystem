from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


TP_ROOT = Path("C:/GoogleDrive/TP")
BACKTEST_ROOT = TP_ROOT / "07_backtest_code"
sys.path.insert(0, str(TP_ROOT / "01_tp_core"))
sys.path.insert(0, str(BACKTEST_ROOT))

from utils.constants import (  # noqa: E402
    COL_DATE,
    COL_ISIN,
    COL_MKT_CAP,
    COL_PORTFOLIO_WEIGHT,
    COL_SECTOR_ICB19,
    COL_SEDOL,
)
from utils.plotting import PlotlyVisualizer  # noqa: E402


BENCH = "STOXX EUROPE 600"
WEIGHT_COL = f"Weight in {BENCH}"
START_REQUESTED = pd.Timestamp("2005-01-31")
EFFECTIVE_START = pd.Timestamp("2009-06-30")
PERCENTILE = 0.2
MAX_WEIGHT = 1.0


@dataclass
class Candidate:
    name: str
    components: dict[str, float]
    family: str


def weighted_std(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    total_w = np.nansum(weights)
    if total_w <= 0:
        return np.full(values.shape[1], np.nan)
    mean = np.nansum(values * weights[:, None], axis=0) / total_w
    var = np.nansum(((values - mean) ** 2) * weights[:, None], axis=0) / total_w
    return np.sqrt(var)


def ewma_weights(n: int, half_life: float) -> np.ndarray:
    age = np.arange(n - 1, -1, -1, dtype=float)
    weights = 0.5 ** (age / half_life)
    return weights / weights.sum()


def score_low(raw: pd.Series, dates: pd.Series) -> pd.Series:
    return raw.groupby(dates, group_keys=False).rank(ascending=False, pct=True) * 10.0


def score_high(raw: pd.Series, dates: pd.Series) -> pd.Series:
    return raw.groupby(dates, group_keys=False).rank(ascending=True, pct=True) * 10.0


def nav_stats(nav: pd.Series, prefix: str) -> dict[str, object]:
    nav = nav.dropna().sort_index()
    if len(nav) < 30:
        return {f"{prefix}_valid": False}
    returns = nav.pct_change().dropna()
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    ann = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    vol = returns.std() * math.sqrt(252)
    mdd = (nav / nav.cummax() - 1).min()
    return {
        f"{prefix}_valid": True,
        f"{prefix}_start": str(nav.index[0].date()),
        f"{prefix}_end": str(nav.index[-1].date()),
        f"{prefix}_end_nav": float(nav.iloc[-1]),
        f"{prefix}_ann": float(ann),
        f"{prefix}_vol": float(vol),
        f"{prefix}_mdd": float(mdd),
    }


def information_ratio(top: pd.Series, benchmark: pd.Series) -> float | None:
    aligned = pd.concat([top.rename("top"), benchmark.rename("bench")], axis=1).dropna()
    if len(aligned) < 30:
        return None
    active = aligned["top"].pct_change() - aligned["bench"].pct_change()
    active = active.dropna()
    te = active.std() * math.sqrt(252)
    if te == 0 or pd.isna(te):
        return None
    return float(active.mean() * 252 / te)


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    cols = [
        COL_DATE,
        COL_SEDOL,
        COL_SECTOR_ICB19,
        WEIGHT_COL,
        COL_MKT_CAP,
        "PCT Mkt Value",
        "LowVol Avg Percentile",
        "Volatilite Rolling ewma 250D",
        "Daily Vol 260J",
    ]
    available = pd.read_parquet(TP_ROOT / "00_screen" / "screen_aggregate.parquet", engine="pyarrow").columns
    cols = [col for col in cols if col in available]
    screen = pd.read_parquet(TP_ROOT / "00_screen" / "screen_aggregate.parquet", columns=cols)
    screen[COL_DATE] = pd.to_datetime(screen[COL_DATE])
    screen = screen.reset_index()
    screen = screen[(screen[WEIGHT_COL].fillna(0) > 0) & (screen[COL_DATE] >= EFFECTIVE_START)].copy()
    returns = pd.read_parquet(TP_ROOT / "00_screen" / "returns.parquet")
    returns.index = pd.to_datetime(returns.index)
    sedols = sorted(set(screen[COL_SEDOL].dropna()).intersection(returns.columns))
    return screen, returns, sedols


def build_benchmark_returns(screen: pd.DataFrame, returns: pd.DataFrame, sedols: list[str]) -> pd.Series:
    bench_parts = []
    dates = sorted(screen[COL_DATE].dropna().unique())
    date_index = returns.index
    for idx, date in enumerate(dates):
        date = pd.Timestamp(date)
        future = date_index[date_index > date]
        if future.empty:
            continue
        start = future[0]
        if idx + 1 < len(dates):
            next_future = date_index[date_index > pd.Timestamp(dates[idx + 1])]
            end = next_future[0] if len(next_future) else date_index[-1]
            seg_idx = date_index[(date_index >= start) & (date_index < end)]
        else:
            seg_idx = date_index[date_index >= start]
        if len(seg_idx) == 0:
            continue
        month = screen[screen[COL_DATE].eq(date)]
        month = month[month[COL_SEDOL].isin(sedols)]
        weights = month.set_index(COL_SEDOL)[WEIGHT_COL].astype(float)
        weights = weights[weights > 0]
        if weights.empty:
            continue
        weights = weights / weights.sum()
        daily = returns.loc[seg_idx, weights.index].apply(pd.to_numeric, errors="coerce").fillna(0)
        bench_parts.append(daily.dot(weights).rename("BenchmarkReturn"))
    return pd.concat(bench_parts).sort_index()


def rolling_factor_table(
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    sedols: list[str],
    benchmark_returns: pd.Series,
) -> pd.DataFrame:
    records = []
    returns_sub = returns[sedols].apply(pd.to_numeric, errors="coerce")
    dates = sorted(screen[COL_DATE].dropna().unique())
    benchmark_returns = benchmark_returns.reindex(returns_sub.index).fillna(0)

    for date in dates:
        date = pd.Timestamp(date)
        if date < EFFECTIVE_START:
            continue
        month = screen[screen[COL_DATE].eq(date)].copy()
        month = month[month[COL_SEDOL].isin(sedols)]
        if month.empty:
            continue
        ids = month[COL_SEDOL].tolist()
        y_all = returns_sub.loc[:date, ids].tail(252)
        x_all = benchmark_returns.loc[y_all.index]
        if len(y_all) < 126:
            continue

        rec = month[[COL_ISIN, COL_SEDOL, COL_DATE]].copy()
        rec["TotalVol252_raw"] = y_all.std(skipna=True).reindex(ids).to_numpy()

        residual_raw_by_window: dict[int, np.ndarray] = {}
        for window, min_obs in [(20, 10), (60, 30), (252, 126)]:
            y = returns_sub.loc[:date, ids].tail(window)
            x = benchmark_returns.loc[y.index]
            if len(y) < min_obs:
                residual_raw_by_window[window] = np.full(len(ids), np.nan)
                rec[f"RV{window}_raw"] = np.nan
                continue
            yv = y.to_numpy(dtype=float)
            xv = x.to_numpy(dtype=float)
            valid = (~np.isnan(yv)) & (~np.isnan(xv[:, None]))
            n = valid.sum(axis=0)
            x_mean = np.nanmean(np.where(valid, xv[:, None], np.nan), axis=0)
            y_mean = np.nanmean(np.where(valid, yv, np.nan), axis=0)
            x_center = np.where(valid, xv[:, None] - x_mean, np.nan)
            y_center = np.where(valid, yv - y_mean, np.nan)
            var_x = np.nanmean(x_center**2, axis=0)
            cov_xy = np.nanmean(x_center * y_center, axis=0)
            beta = np.divide(cov_xy, var_x, out=np.zeros_like(cov_xy), where=var_x > 0)
            alpha = y_mean - beta * x_mean
            residual = yv - alpha - beta * xv[:, None]
            residual[~valid] = np.nan
            raw = np.nanstd(residual, axis=0)
            raw[n < min_obs] = np.nan
            residual_raw_by_window[window] = raw
            rec[f"RV{window}_raw"] = raw

            if window == 252:
                resid_std = np.nanstd(residual, axis=0)
                clipped = np.clip(residual, -3 * resid_std, 3 * resid_std)
                winsor = np.nanstd(clipped, axis=0)
                downside = np.sqrt(np.nanmean(np.where(residual < 0, residual**2, np.nan), axis=0))
                weights63 = ewma_weights(len(residual), 63)
                ewma = weighted_std(residual, weights63)
                rec["RV252_Winsor3_raw"] = winsor
                rec["RV252_Downside_raw"] = downside
                rec["RV252_EWMA63_raw"] = ewma

                weights42 = ewma_weights(len(yv), 42)
                rec["DASTD_raw"] = weighted_std(yv, weights42)
                cumulative = np.nancumsum(np.log1p(np.nan_to_num(yv, nan=0.0)), axis=0)
                rec["CMRA_raw"] = np.nanmax(cumulative, axis=0) - np.nanmin(cumulative, axis=0)

        rec["RV_Blend_20_60_252_raw"] = (
            0.2 * rec["RV20_raw"] + 0.3 * rec["RV60_raw"] + 0.5 * rec["RV252_raw"]
        )
        records.append(rec)

    factors = pd.concat(records, ignore_index=True)
    for raw_col in [col for col in factors.columns if col.endswith("_raw")]:
        score_col = raw_col.replace("_raw", "_Score")
        factors[score_col] = score_low(pd.to_numeric(factors[raw_col], errors="coerce"), factors[COL_DATE])

    factors["Barra_RESVOL_Score"] = (
        0.74 * factors["DASTD_Score"]
        + 0.16 * factors["CMRA_Score"]
        + 0.10 * factors["RV252_EWMA63_Score"]
    )
    return factors


def add_candidates(screen: pd.DataFrame, factors: pd.DataFrame) -> tuple[pd.DataFrame, list[Candidate]]:
    merged = screen.merge(
        factors[
            [
                COL_DATE,
                COL_ISIN,
                COL_SEDOL,
                "TotalVol252_Score",
                "RV252_Score",
                "RV252_Winsor3_Score",
                "RV252_Downside_Score",
                "RV20_Score",
                "RV60_Score",
                "RV_Blend_20_60_252_Score",
                "RV252_EWMA63_Score",
                "Barra_RESVOL_Score",
            ]
        ],
        on=[COL_DATE, COL_ISIN, COL_SEDOL],
        how="left",
    )
    base_components = {
        "LowVol": "LowVol Avg Percentile",
        "TotalVol252": "TotalVol252_Score",
        "RV252": "RV252_Score",
        "RV252Winsor3": "RV252_Winsor3_Score",
        "RV252Downside": "RV252_Downside_Score",
        "RV20": "RV20_Score",
        "RV60": "RV60_Score",
        "RVBlend": "RV_Blend_20_60_252_Score",
        "RVEWMA63": "RV252_EWMA63_Score",
        "BarraRESVOL": "Barra_RESVOL_Score",
    }

    candidates = []
    for name, col in base_components.items():
        candidates.append(Candidate(name=name, components={name: 1.0}, family="single"))
        merged[name] = pd.to_numeric(merged[col], errors="coerce")

    for name in [x for x in base_components if x != "LowVol"]:
        for lowvol_weight in [0.5, 0.6]:
            cand_name = f"LowVol{int(lowvol_weight * 100)}_{name}{int((1 - lowvol_weight) * 100)}"
            merged[cand_name] = (
                lowvol_weight * pd.to_numeric(merged["LowVol"], errors="coerce")
                + (1 - lowvol_weight) * pd.to_numeric(merged[name], errors="coerce")
            )
            merged.loc[merged["LowVol"].isna() | merged[name].isna(), cand_name] = np.nan
            candidates.append(
                Candidate(
                    name=cand_name,
                    components={"LowVol": lowvol_weight, name: 1 - lowvol_weight},
                    family="blend_lowvol",
                )
            )

    combos = [
        ("LowVol50_RVDownside25_RVBlend25", {"LowVol": 0.5, "RV252Downside": 0.25, "RVBlend": 0.25}),
        ("LowVol50_RVWinsor25_RVBlend25", {"LowVol": 0.5, "RV252Winsor3": 0.25, "RVBlend": 0.25}),
        ("LowVol50_RVEWMA25_Barra25", {"LowVol": 0.5, "RVEWMA63": 0.25, "BarraRESVOL": 0.25}),
        ("LowVol40_TotalVol30_RVDownside30", {"LowVol": 0.4, "TotalVol252": 0.3, "RV252Downside": 0.3}),
    ]
    for name, weights in combos:
        value = pd.Series(0.0, index=merged.index)
        valid = pd.Series(True, index=merged.index)
        for component, weight in weights.items():
            comp = pd.to_numeric(merged[component], errors="coerce")
            value += weight * comp
            valid &= comp.notna()
        merged[name] = value.where(valid)
        candidates.append(Candidate(name=name, components=weights, family="combo_resvol"))

    return merged, candidates


def neutralize_scores(df: pd.DataFrame, score_col: str) -> pd.DataFrame:
    out = df.copy()
    score = out[score_col].rank(pct=True)
    denom = score.max() - score.min()
    out[score_col] = (score - score.min()) / denom if denom and not pd.isna(denom) else score
    for sector in out[COL_SECTOR_ICB19].dropna().unique():
        mask = out[COL_SECTOR_ICB19].eq(sector)
        sector_score = out.loc[mask, score_col].rank(pct=True)
        sector_denom = sector_score.max() - sector_score.min()
        out.loc[mask, score_col] = (
            (sector_score - sector_score.min()) / sector_denom
            if sector_denom and not pd.isna(sector_denom)
            else sector_score
        )
    return out


def select_weights(screen: pd.DataFrame, score_col: str, top: bool) -> pd.DataFrame:
    pieces = []
    for date, month in screen.groupby(COL_DATE, sort=True):
        month = month[month[WEIGHT_COL].fillna(0) > 0].copy()
        df = month[[COL_ISIN, COL_SEDOL, COL_SECTOR_ICB19, COL_MKT_CAP, WEIGHT_COL, score_col]].copy()
        df = df[df[score_col].notna() & df[COL_SEDOL].notna() & df[COL_MKT_CAP].notna()]
        if df.empty:
            continue
        df = neutralize_scores(df, score_col)
        n = max(1, int(round(len(df) * PERCENTILE)))
        selected = df.nlargest(n, score_col) if top else df.nsmallest(n, score_col)
        sector_weights = month.groupby(COL_SECTOR_ICB19)[WEIGHT_COL].sum()
        sector_weights = sector_weights / sector_weights.sum()
        selected = selected.copy()
        sector_sum = selected.groupby(COL_SECTOR_ICB19)[COL_MKT_CAP].transform("sum")
        selected["Weight"] = selected[COL_MKT_CAP] * selected[COL_SECTOR_ICB19].map(sector_weights) / sector_sum
        selected["Weight"] = selected["Weight"].clip(lower=0, upper=MAX_WEIGHT).fillna(0)
        total = selected["Weight"].sum()
        if total <= 0 or pd.isna(total):
            continue
        selected["Weight"] = selected["Weight"] / total
        selected[COL_DATE] = pd.Timestamp(date) + pd.offsets.MonthBegin(1)
        pieces.append(selected[[COL_DATE, COL_ISIN, COL_SEDOL, COL_SECTOR_ICB19, "Weight"]])
    if not pieces:
        return pd.DataFrame(columns=[COL_DATE, COL_ISIN, COL_SEDOL, COL_SECTOR_ICB19, "Weight"])
    return pd.concat(pieces, ignore_index=True).sort_values([COL_DATE, COL_SEDOL])


def nav_from_weights(weights: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    if weights.empty:
        return pd.Series(dtype=float)
    nav_parts = []
    nav_base = 100.0
    date_index = returns.index
    rebal_dates = sorted(pd.to_datetime(weights[COL_DATE].unique()))
    for idx, date in enumerate(rebal_dates):
        future = date_index[date_index > date]
        if future.empty:
            break
        start = future[0]
        if idx + 1 < len(rebal_dates):
            future_next = date_index[date_index > rebal_dates[idx + 1]]
            end = future_next[0] if len(future_next) else date_index[-1]
            seg_idx = date_index[(date_index >= start) & (date_index < end)]
        else:
            seg_idx = date_index[date_index >= start]
        if len(seg_idx) == 0:
            continue
        w = weights[weights[COL_DATE].eq(date)].set_index(COL_SEDOL)["Weight"].astype(float)
        ids = [sedol for sedol in w.index if sedol in returns.columns]
        if not ids:
            continue
        w = w.loc[ids]
        w = w / w.sum()
        seg_ret = returns.loc[seg_idx, ids].apply(pd.to_numeric, errors="coerce").fillna(0)
        nav = (1.0 + seg_ret).cumprod().dot(w) * nav_base
        nav_base = float(nav.iloc[-1])
        nav_parts.append(nav)
    if not nav_parts:
        return pd.Series(dtype=float)
    nav = pd.concat(nav_parts)
    return nav[~nav.index.duplicated(keep="last")].sort_index()


def average_turnover(weights: pd.DataFrame) -> float | None:
    if weights.empty:
        return None
    rows = []
    previous = None
    for date, group in weights.groupby(COL_DATE, sort=True):
        current = group.set_index(COL_SEDOL)["Weight"].astype(float)
        if previous is not None:
            aligned = pd.concat([previous.rename("prev"), current.rename("cur")], axis=1).fillna(0)
            rows.append(float((aligned["cur"] - aligned["prev"]).abs().sum() / 2))
        previous = current
    return float(np.mean(rows)) if rows else None


def liquidity_profile(weights: pd.DataFrame, screen: pd.DataFrame) -> dict[str, float | None]:
    if weights.empty:
        return {"top_weighted_log_mcap": None, "top_weighted_pct_mkt_value": None}
    attrs = screen[[COL_DATE, COL_SEDOL, COL_MKT_CAP] + (["PCT Mkt Value"] if "PCT Mkt Value" in screen.columns else [])].copy()
    attrs[COL_DATE] = attrs[COL_DATE] + pd.offsets.MonthBegin(1)
    merged = weights.merge(attrs, on=[COL_DATE, COL_SEDOL], how="left")
    merged["log_mcap"] = np.log(pd.to_numeric(merged[COL_MKT_CAP], errors="coerce").clip(lower=1))
    result = {
        "top_weighted_log_mcap": float((merged["Weight"] * merged["log_mcap"]).sum() / merged["Weight"].sum())
        if merged["Weight"].sum() > 0
        else None,
        "top_weighted_pct_mkt_value": None,
    }
    if "PCT Mkt Value" in merged.columns:
        pct = pd.to_numeric(merged["PCT Mkt Value"], errors="coerce")
        valid = pct.notna()
        if valid.any():
            result["top_weighted_pct_mkt_value"] = float((merged.loc[valid, "Weight"] * pct.loc[valid]).sum() / merged.loc[valid, "Weight"].sum())
    return result


def evaluate_candidate(
    candidate: Candidate,
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    benchmark_nav: pd.Series,
    output_dir: Path,
) -> dict[str, object]:
    top_weights = select_weights(screen, candidate.name, top=True)
    worst_weights = select_weights(screen, candidate.name, top=False)
    top_nav = nav_from_weights(top_weights, returns)
    worst_nav = nav_from_weights(worst_weights, returns)
    perf = pd.concat([top_nav.rename("Top"), worst_nav.rename("Worst"), benchmark_nav.rename("Benchmark")], axis=1).dropna()
    candidate_dir = output_dir / candidate.name
    candidate_dir.mkdir(parents=True, exist_ok=True)
    top_weights.to_csv(candidate_dir / "sec_list_top_fast.csv", index=False)
    worst_weights.to_csv(candidate_dir / "sec_list_worst_fast.csv", index=False)
    perf.to_csv(candidate_dir / "performance_nav_fast.csv")
    ratios = pd.DataFrame(index=perf.index)
    ratios["Top / Benchmark"] = perf["Top"] / perf["Benchmark"]
    ratios["Worst / Benchmark"] = perf["Worst"] / perf["Benchmark"]
    ratios["Top / Worst"] = perf["Top"] / perf["Worst"]
    ratios.to_csv(candidate_dir / "performance_ratios_fast.csv")
    PlotlyVisualizer.plot_top_bottom_vs_benchmark(
        perf["Top"],
        perf["Worst"],
        perf["Benchmark"],
        title=f"{candidate.name} Top/Worst vs {BENCH}",
        save_path=str(candidate_dir / "top_worst_benchmark_fast.html"),
        show_plot=False,
    )
    row: dict[str, object] = {
        "candidate": candidate.name,
        "family": candidate.family,
        "components": json.dumps(candidate.components, sort_keys=True),
        "candidate_dir": str(candidate_dir),
    }
    row.update(nav_stats(perf["Top"], "top"))
    row.update(nav_stats(perf["Worst"], "worst"))
    row.update(nav_stats(perf["Benchmark"], "bench"))
    if not perf.empty:
        row["last_top_over_bench"] = float(ratios["Top / Benchmark"].iloc[-1])
        row["last_worst_over_bench"] = float(ratios["Worst / Benchmark"].iloc[-1])
        row["last_top_over_worst"] = float(ratios["Top / Worst"].iloc[-1])
        row["ann_spread_top_minus_worst"] = float(row["top_ann"] - row["worst_ann"])
        row["information_ratio"] = information_ratio(perf["Top"], perf["Benchmark"])
    row["avg_monthly_turnover_top"] = average_turnover(top_weights)
    row.update(liquidity_profile(top_weights, screen))
    (candidate_dir / "summary_fast.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-candidates", type=int, default=0)
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = BACKTEST_ROOT / "runs" / "ad_hoc" / f"lowvol_resvol_research_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    print(f"RUN_DIR {output_dir}", flush=True)

    screen, returns, sedols = load_inputs()
    benchmark_nav = pd.read_csv(
        BACKTEST_ROOT
        / "runs"
        / "ad_hoc"
        / "lowvol_avg_percentile_stoxx600_p20_earliest_top_worst_20260703_191938"
        / "performance_nav.csv",
        index_col=0,
        parse_dates=True,
    )["Benchmark"]

    benchmark_returns = build_benchmark_returns(screen, returns, sedols)
    benchmark_returns.to_csv(output_dir / "benchmark_returns_reconstructed.csv", header=["BenchmarkReturn"])

    factors = rolling_factor_table(screen, returns, sedols, benchmark_returns)
    factors.to_parquet(output_dir / "lowvol_resvol_factor_table.parquet", index=False)
    factors.to_csv(output_dir / "lowvol_resvol_factor_table.csv", index=False)

    screen_with_candidates, candidates = add_candidates(screen, factors)
    screen_with_candidates.to_parquet(output_dir / "screen_with_candidates.parquet", index=False)
    if args.limit_candidates > 0:
        candidates = candidates[: args.limit_candidates]
    (output_dir / "candidate_definitions.json").write_text(
        json.dumps([candidate.__dict__ for candidate in candidates], indent=2),
        encoding="utf-8",
    )

    results = []
    for idx, candidate in enumerate(candidates, start=1):
        print(f"evaluate {idx}/{len(candidates)} {candidate.name}", flush=True)
        results.append(evaluate_candidate(candidate, screen_with_candidates, returns, benchmark_nav, output_dir))
        pd.DataFrame(results).to_csv(output_dir / "results_fast_partial.csv", index=False)

    results_df = pd.DataFrame(results).sort_values(
        ["top_end_nav", "information_ratio", "last_top_over_bench"], ascending=False
    )
    results_df.to_csv(output_dir / "results_fast.csv", index=False)
    summary = {
        "run_dir": str(output_dir),
        "parameters": {
            "bench": BENCH,
            "percentile": PERCENTILE,
            "start_requested": str(START_REQUESTED.date()),
            "effective_start": str(EFFECTIVE_START.date()),
            "max_weight": MAX_WEIGHT,
            "score_neutral": "ICB 19 replicated by rank neutralization",
            "weight_neutral": "ICB 19 replicated by sector benchmark weights",
            "benchmark_nav_source": "lowvol_avg_percentile_stoxx600_p20_earliest_top_worst_20260703_191938/performance_nav.csv",
        },
        "candidate_count": len(candidates),
        "best_by_top_end_nav": results_df.head(1).to_dict("records")[0] if not results_df.empty else None,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(results_df.head(20).to_string(index=False), flush=True)
    print(f"SUMMARY {output_dir / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()

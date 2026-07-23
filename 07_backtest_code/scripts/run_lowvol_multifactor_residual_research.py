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
from tp_core.general_backtest import BacktestSchema, backtest_weight_table  # noqa: E402


BENCH = "STOXX EUROPE 600"
WEIGHT_COL = f"Weight in {BENCH}"
EFFECTIVE_START = pd.Timestamp("2009-06-30")
PERCENTILE = 0.2


@dataclass
class Candidate:
    name: str
    components: dict[str, float]
    family: str


def nav_stats(nav: pd.Series, prefix: str) -> dict[str, object]:
    nav = nav.dropna().sort_index()
    if len(nav) < 30:
        return {f"{prefix}_valid": False}
    returns = nav.pct_change().dropna()
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    ann = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1
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
    active = aligned["top"].pct_change() - aligned["bench"].pct_change()
    active = active.dropna()
    if len(active) < 30:
        return None
    te = active.std() * math.sqrt(252)
    if te == 0 or pd.isna(te):
        return None
    return float(active.mean() * 252 / te)


def score_low(raw: pd.Series, dates: pd.Series) -> pd.Series:
    return raw.groupby(dates, group_keys=False).rank(ascending=False, pct=True) * 10.0


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    cols = [
        COL_DATE,
        COL_SEDOL,
        COL_SECTOR_ICB19,
        WEIGHT_COL,
        COL_MKT_CAP,
        "PCT Mkt Value",
        "LowVol Avg Percentile",
        "Size Avg Percentile",
        "Value Avg Percentile",
        "Mom Avg Percentile",
        "Quality Avg Percentile",
        "Growth Avg Percentile",
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


def standardize_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame[columns].apply(pd.to_numeric, errors="coerce")
    for col in columns:
        values = out[col]
        std = values.std(skipna=True)
        if std and not pd.isna(std):
            out[col] = (values - values.mean(skipna=True)) / std
    return out


def exposure_matrix(month: pd.DataFrame, factor_cols: list[str], include_sector: bool) -> tuple[np.ndarray, pd.Series]:
    exposure = standardize_columns(month, factor_cols)
    valid = exposure.notna().all(axis=1)
    pieces = [pd.Series(1.0, index=month.index, name="Intercept"), exposure]
    if include_sector:
        sectors = pd.get_dummies(month[COL_SECTOR_ICB19].astype("Int64").astype(str), prefix="Sector", dtype=float)
        if sectors.shape[1] > 1:
            sectors = sectors.iloc[:, 1:]
        pieces.append(sectors)
        valid &= sectors.notna().all(axis=1)
    matrix = pd.concat(pieces, axis=1)
    return matrix.loc[valid].to_numpy(dtype=float), valid


def compute_multifactor_residual_scores(
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    sedols: list[str],
    variants: dict[str, tuple[list[str], bool]],
) -> pd.DataFrame:
    returns_sub = returns[sedols].apply(pd.to_numeric, errors="coerce")
    records = []
    dates = sorted(screen[COL_DATE].dropna().unique())

    for date in dates:
        date = pd.Timestamp(date)
        month = screen[screen[COL_DATE].eq(date)].copy()
        month = month[month[COL_SEDOL].isin(sedols)].reset_index(drop=True)
        if month.empty:
            continue
        ids = month[COL_SEDOL].tolist()
        window = returns_sub.loc[:date, ids].tail(252)
        if len(window) < 126:
            continue
        base = month[[COL_DATE, COL_ISIN, COL_SEDOL]].copy()
        for name, (factor_cols, include_sector) in variants.items():
            x, valid = exposure_matrix(month, factor_cols, include_sector)
            valid_ids = month.loc[valid, COL_SEDOL].tolist()
            if len(valid_ids) <= x.shape[1] + 5:
                base[f"{name}_raw"] = np.nan
                continue
            y = window[valid_ids]
            obs_count = y.notna().sum(axis=0)
            y_matrix = y.fillna(0.0).to_numpy(dtype=float).T
            try:
                pinv = np.linalg.pinv(x)
                fitted = x @ (pinv @ y_matrix)
                residual = y_matrix - fitted
            except np.linalg.LinAlgError:
                base[f"{name}_raw"] = np.nan
                continue
            residual[y.to_numpy(dtype=float).T != y.to_numpy(dtype=float).T] = np.nan
            raw = pd.Series(np.nan, index=month.index)
            values = np.nanstd(residual, axis=1)
            values[obs_count.to_numpy() < 126] = np.nan
            raw.loc[valid] = values
            base[f"{name}_raw"] = raw.to_numpy()
        records.append(base)

    factors = pd.concat(records, ignore_index=True)
    for col in [col for col in factors.columns if col.endswith("_raw")]:
        factors[col.replace("_raw", "_Score")] = score_low(pd.to_numeric(factors[col], errors="coerce"), factors[COL_DATE])
    return factors


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
        selected[COL_PORTFOLIO_WEIGHT] = (
            selected[COL_MKT_CAP]
            * selected[COL_SECTOR_ICB19].map(sector_weights)
            / sector_sum
        )
        selected[COL_PORTFOLIO_WEIGHT] = selected[
            COL_PORTFOLIO_WEIGHT
        ].clip(lower=0, upper=1.0).fillna(0)
        total = selected[COL_PORTFOLIO_WEIGHT].sum()
        if total <= 0 or pd.isna(total):
            continue
        selected[COL_PORTFOLIO_WEIGHT] = (
            selected[COL_PORTFOLIO_WEIGHT] / total
        )
        selected[COL_DATE] = pd.Timestamp(date) + pd.offsets.MonthBegin(1)
        pieces.append(
            selected[
                [
                    COL_DATE,
                    COL_ISIN,
                    COL_SEDOL,
                    COL_SECTOR_ICB19,
                    COL_PORTFOLIO_WEIGHT,
                ]
            ]
        )
    if not pieces:
        return pd.DataFrame(
            columns=[
                COL_DATE,
                COL_ISIN,
                COL_SEDOL,
                COL_SECTOR_ICB19,
                COL_PORTFOLIO_WEIGHT,
            ]
        )
    return pd.concat(pieces, ignore_index=True).sort_values([COL_DATE, COL_SEDOL])


def nav_from_weights(weights: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    if weights.empty:
        return pd.Series(dtype=float)
    return backtest_weight_table(
        weights=weights,
        returns=returns,
        schema=BacktestSchema(
            date_col=COL_DATE,
            id_col=COL_SEDOL,
            weight_col=COL_PORTFOLIO_WEIGHT,
        ),
        strictly_after_rebalance=True,
        apply_weights_at_close=False,
    ).nav


def average_turnover(weights: pd.DataFrame) -> float | None:
    prev = None
    vals = []
    for _, group in weights.groupby(COL_DATE, sort=True):
        cur = group.set_index(COL_SEDOL)[COL_PORTFOLIO_WEIGHT].astype(float)
        if prev is not None:
            aligned = pd.concat([prev.rename("prev"), cur.rename("cur")], axis=1).fillna(0)
            vals.append(float((aligned["cur"] - aligned["prev"]).abs().sum() / 2))
        prev = cur
    return float(np.mean(vals)) if vals else None


def evaluate(candidate: Candidate, screen: pd.DataFrame, returns: pd.DataFrame, benchmark_nav: pd.Series, output_dir: Path) -> dict[str, object]:
    cdir = output_dir / candidate.name
    cdir.mkdir(parents=True, exist_ok=True)
    top_weights = select_weights(screen, candidate.name, top=True)
    worst_weights = select_weights(screen, candidate.name, top=False)
    top_nav = nav_from_weights(top_weights, returns)
    worst_nav = nav_from_weights(worst_weights, returns)
    perf = pd.concat([top_nav.rename("Top"), worst_nav.rename("Worst"), benchmark_nav.rename("Benchmark")], axis=1).dropna()
    perf.to_csv(cdir / "performance_nav_fast.csv")
    ratios = pd.DataFrame(index=perf.index)
    ratios["Top / Benchmark"] = perf["Top"] / perf["Benchmark"]
    ratios["Worst / Benchmark"] = perf["Worst"] / perf["Benchmark"]
    ratios["Top / Worst"] = perf["Top"] / perf["Worst"]
    ratios.to_csv(cdir / "performance_ratios_fast.csv")
    PlotlyVisualizer.plot_top_bottom_vs_benchmark(
        perf["Top"],
        perf["Worst"],
        perf["Benchmark"],
        title=f"{candidate.name} Top/Worst vs {BENCH}",
        save_path=str(cdir / "top_worst_benchmark_fast.html"),
        show_plot=False,
    )
    row: dict[str, object] = {
        "candidate": candidate.name,
        "family": candidate.family,
        "components": json.dumps(candidate.components, sort_keys=True),
        "candidate_dir": str(cdir),
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
    (cdir / "summary_fast.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-candidates", type=int, default=0)
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = BACKTEST_ROOT / "runs" / "ad_hoc" / f"lowvol_multifactor_resvol_{stamp}"
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

    variants = {
        "MF_Size": (["Size Avg Percentile"], False),
        "MF_Size_Value": (["Size Avg Percentile", "Value Avg Percentile"], False),
        "MF_Size_Value_Mom": (["Size Avg Percentile", "Value Avg Percentile", "Mom Avg Percentile"], False),
        "MF_Size_Value_Mom_Quality": (
            ["Size Avg Percentile", "Value Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile"],
            False,
        ),
        "MF_Size_Value_Mom_Quality_Growth": (
            [
                "Size Avg Percentile",
                "Value Avg Percentile",
                "Mom Avg Percentile",
                "Quality Avg Percentile",
                "Growth Avg Percentile",
            ],
            False,
        ),
        "MF_Size_Value_Mom_Quality_Growth_Sector": (
            [
                "Size Avg Percentile",
                "Value Avg Percentile",
                "Mom Avg Percentile",
                "Quality Avg Percentile",
                "Growth Avg Percentile",
            ],
            True,
        ),
    }
    factors = compute_multifactor_residual_scores(screen, returns, sedols, variants)
    factors.to_parquet(output_dir / "multifactor_residual_scores.parquet", index=False)
    factors.to_csv(output_dir / "multifactor_residual_scores.csv", index=False)

    score_cols = [col for col in factors.columns if col.endswith("_Score")]
    merged = screen.merge(factors[[COL_DATE, COL_ISIN, COL_SEDOL] + score_cols], on=[COL_DATE, COL_ISIN, COL_SEDOL], how="left")
    candidates: list[Candidate] = []
    for score_col in score_cols:
        name = score_col.replace("_Score", "")
        merged[name] = pd.to_numeric(merged[score_col], errors="coerce")
        candidates.append(Candidate(name=name, components={name: 1.0}, family="multifactor_residual"))
        for lowvol_weight in [0.5, 0.6]:
            blend = f"LowVol{int(lowvol_weight * 100)}_{name}{int((1 - lowvol_weight) * 100)}"
            merged[blend] = lowvol_weight * pd.to_numeric(merged["LowVol Avg Percentile"], errors="coerce") + (
                1 - lowvol_weight
            ) * merged[name]
            merged.loc[merged["LowVol Avg Percentile"].isna() | merged[name].isna(), blend] = np.nan
            candidates.append(
                Candidate(
                    name=blend,
                    components={"LowVol": lowvol_weight, name: 1 - lowvol_weight},
                    family="lowvol_multifactor_blend",
                )
            )

    if args.limit_candidates > 0:
        candidates = candidates[: args.limit_candidates]
    merged.to_parquet(output_dir / "screen_with_multifactor_candidates.parquet", index=False)
    (output_dir / "candidate_definitions.json").write_text(
        json.dumps([candidate.__dict__ for candidate in candidates], indent=2),
        encoding="utf-8",
    )

    results = []
    for idx, candidate in enumerate(candidates, start=1):
        print(f"evaluate {idx}/{len(candidates)} {candidate.name}", flush=True)
        results.append(evaluate(candidate, merged, returns, benchmark_nav, output_dir))
        pd.DataFrame(results).to_csv(output_dir / "results_fast_partial.csv", index=False)

    results_df = pd.DataFrame(results).sort_values(["top_end_nav", "information_ratio"], ascending=False)
    results_df.to_csv(output_dir / "results_fast.csv", index=False)
    summary = {
        "run_dir": str(output_dir),
        "candidate_count": len(candidates),
        "variants": {key: {"factors": val[0], "include_sector": val[1]} for key, val in variants.items()},
        "best_by_top_end_nav": results_df.head(1).to_dict("records")[0] if not results_df.empty else None,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(results_df.head(20).to_string(index=False), flush=True)
    print(f"SUMMARY {output_dir / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()

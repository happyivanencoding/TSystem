from __future__ import annotations

from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd


TP_ROOT = Path(r"C:\GoogleDrive\TP")
RAW_RUN = TP_ROOT / "07_backtest_code" / "runs" / "ad_hoc" / "stoxx600_raw_gated_20260708_0100"
PAIR_RUN = TP_ROOT / "07_backtest_code" / "runs" / "ad_hoc" / "stoxx600_raw_pair_synergy_20260708_1400"
OUT_DIR = TP_ROOT / "07_backtest_code" / "runs" / "ad_hoc" / "stoxx600_2020_regime_break_20260709"

PERIODS = {
    "pre_2020": ("2009-07-02", "2019-12-31"),
    "post_2020": ("2020-01-02", "2026-07-02"),
    "covid_reopening": ("2020-01-02", "2021-12-31"),
    "inflation_rate_shock": ("2022-01-03", "2023-12-29"),
    "disinflation_quality_growth": ("2024-01-02", "2026-07-02"),
}


def read_nav(path_text: str) -> pd.Series:
    path = Path(path_text)
    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)
    if "Date" in df.columns:
        date_col = "Date"
    else:
        date_col = df.columns[0]
    nav_col = "nav" if "nav" in df.columns else df.columns[-1]
    out = df[[date_col, nav_col]].copy()
    out[date_col] = pd.to_datetime(out[date_col])
    out = out.dropna().sort_values(date_col)
    return out.set_index(date_col)[nav_col].astype(float)


def cagr(series: pd.Series) -> float:
    series = series.dropna()
    if len(series) < 2 or series.iloc[0] == 0:
        return np.nan
    years = max((series.index[-1] - series.index[0]).days / 365.25, 1e-9)
    return float((series.iloc[-1] / series.iloc[0]) ** (1 / years) - 1)


def total_return(series: pd.Series) -> float:
    series = series.dropna()
    if len(series) < 2 or series.iloc[0] == 0:
        return np.nan
    return float(series.iloc[-1] / series.iloc[0] - 1)


def max_drawdown(series: pd.Series) -> float:
    series = series.dropna()
    if len(series) < 2:
        return np.nan
    return float((series / series.cummax() - 1).min())


def relative_stats(nav: pd.Series, bench: pd.Series, start: str, end: str) -> dict[str, float]:
    aligned = pd.concat([nav.rename("nav"), bench.rename("bench")], axis=1).dropna()
    aligned = aligned.loc[(aligned.index >= pd.Timestamp(start)) & (aligned.index <= pd.Timestamp(end))]
    if len(aligned) < 30:
        return {}
    ratio = aligned["nav"] / aligned["bench"]
    active = aligned["nav"].pct_change() - aligned["bench"].pct_change()
    te = active.dropna().std() * sqrt(252)
    ir = active.dropna().mean() * 252 / te if te and not pd.isna(te) else np.nan
    rolling_min = np.nan
    if len(ratio) >= 756:
        rolling = ratio / ratio.shift(756)
        clean = rolling.dropna()
        rolling_min = float(clean.pow(252 / 756).sub(1).min()) if not clean.empty else np.nan
    annual = aligned.resample("YE").last().pct_change().dropna()
    hit_rate = float((annual["nav"] > annual["bench"]).mean()) if not annual.empty else np.nan
    return {
        "days": int(len(aligned)),
        "ratio_return": total_return(ratio),
        "ratio_cagr": cagr(ratio),
        "ratio_max_drawdown": max_drawdown(ratio),
        "tracking_error": float(te) if not pd.isna(te) else np.nan,
        "information_ratio": float(ir) if not pd.isna(ir) else np.nan,
        "rolling_3y_min_ratio_cagr": rolling_min,
        "annual_active_hit_rate": hit_rate,
    }


def top_worst_stats(top_nav: pd.Series, worst_nav: pd.Series, start: str, end: str) -> dict[str, float]:
    aligned = pd.concat([top_nav.rename("top"), worst_nav.rename("worst")], axis=1).dropna()
    aligned = aligned.loc[(aligned.index >= pd.Timestamp(start)) & (aligned.index <= pd.Timestamp(end))]
    if len(aligned) < 30:
        return {}
    ratio = aligned["top"] / aligned["worst"]
    return {
        "top_worst_ratio_return": total_return(ratio),
        "top_worst_ratio_cagr": cagr(ratio),
        "top_worst_ratio_max_drawdown": max_drawdown(ratio),
    }


def robust_score(stats: dict[str, float]) -> float:
    return float(
        np.nan_to_num(stats.get("ratio_return"), nan=0.0)
        + 0.5 * np.nan_to_num(stats.get("top_worst_ratio_return"), nan=0.0)
        - 2.0 * abs(np.nan_to_num(stats.get("ratio_max_drawdown"), nan=0.0))
        - np.nan_to_num(stats.get("tracking_error"), nan=0.0)
        - abs(min(np.nan_to_num(stats.get("rolling_3y_min_ratio_cagr"), nan=0.0), 0.0))
    )


def load_metric_navs(summary: pd.DataFrame, metrics: set[str]) -> dict[str, dict[str, pd.Series]]:
    navs: dict[str, dict[str, pd.Series]] = {}
    success = summary[(summary["status"].eq("success")) & (summary["metric"].isin(metrics))]
    for _, row in success.iterrows():
        metric = str(row["metric"])
        side = str(row["side"])
        navs.setdefault(metric, {})[side] = read_nav(str(row["perf_ptf"]))
        navs.setdefault(metric, {})[f"{side}_bench"] = read_nav(str(row["perf_bench"]))
    return navs


def summarize_periods(
    metrics: pd.DataFrame,
    summary: pd.DataFrame,
    id_col: str,
    label_cols: list[str],
) -> pd.DataFrame:
    navs = load_metric_navs(summary, set(metrics[id_col]))
    rows: list[dict[str, object]] = []
    for _, meta in metrics.iterrows():
        metric = str(meta[id_col])
        sides = navs.get(metric, {})
        if "Top" not in sides or "Worst" not in sides:
            continue
        base = {col: meta.get(col) for col in label_cols}
        for period_id, (start, end) in PERIODS.items():
            stats = relative_stats(sides["Top"], sides["Top_bench"], start, end)
            stats.update(top_worst_stats(sides["Top"], sides["Worst"], start, end))
            if not stats:
                continue
            stats["robust_score"] = robust_score(stats)
            rows.append(
                {
                    id_col: metric,
                    **base,
                    "period_id": period_id,
                    "period_start": start,
                    "period_end": end,
                    **stats,
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["period_rank"] = out.groupby("period_id")["robust_score"].rank(ascending=False, method="min")
    return out.sort_values(["period_id", "period_rank", id_col]).reset_index(drop=True)


def classify(pre: float, post: float) -> str:
    pre_ok = np.isfinite(pre) and pre > 0
    post_ok = np.isfinite(post) and post > 0
    if pre_ok and post_ok:
        return "persistent_positive"
    if pre_ok and not post_ok:
        return "pre_only_faded"
    if post_ok and not pre_ok:
        return "post_only_emerged"
    return "weak_both"


def make_pre_post(period_stats: pd.DataFrame, id_col: str, label_cols: list[str]) -> pd.DataFrame:
    keep = [
        "ratio_cagr",
        "ratio_return",
        "ratio_max_drawdown",
        "tracking_error",
        "top_worst_ratio_return",
        "top_worst_ratio_cagr",
        "robust_score",
        "period_rank",
    ]
    pivot = period_stats[period_stats["period_id"].isin(["pre_2020", "post_2020"])].pivot_table(
        index=[id_col, *label_cols],
        columns="period_id",
        values=keep,
        aggfunc="first",
    )
    pivot.columns = [f"{metric}_{period}" for metric, period in pivot.columns]
    out = pivot.reset_index()
    out["robust_delta_post_minus_pre"] = out["robust_score_post_2020"] - out["robust_score_pre_2020"]
    out["ratio_cagr_delta_post_minus_pre"] = out["ratio_cagr_post_2020"] - out["ratio_cagr_pre_2020"]
    out["rank_improvement"] = out["period_rank_pre_2020"] - out["period_rank_post_2020"]
    out["regime_class"] = [
        classify(pre, post)
        for pre, post in zip(out["robust_score_pre_2020"], out["robust_score_post_2020"], strict=False)
    ]
    return out.sort_values(["robust_score_post_2020", "robust_delta_post_minus_pre"], ascending=False).reset_index(drop=True)


def family_shift_table(pre_post: pd.DataFrame, family_col: str) -> pd.DataFrame:
    rows = []
    for fam, g in pre_post.groupby(family_col, dropna=False):
        rows.append(
            {
                family_col: fam,
                "count": len(g),
                "pre_positive": int((g["robust_score_pre_2020"] > 0).sum()),
                "post_positive": int((g["robust_score_post_2020"] > 0).sum()),
                "median_pre_robust": float(g["robust_score_pre_2020"].median()),
                "median_post_robust": float(g["robust_score_post_2020"].median()),
                "median_delta": float(g["robust_delta_post_minus_pre"].median()),
                "best_post_label": g.sort_values("robust_score_post_2020", ascending=False).iloc[0].get("label")
                if "label" in g.columns
                else g.sort_values("robust_score_post_2020", ascending=False).iloc[0].get("raw_column"),
            }
        )
    return pd.DataFrame(rows).sort_values("median_delta", ascending=False).reset_index(drop=True)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plot_dir = OUT_DIR / "plots"
    plot_dir.mkdir(exist_ok=True)

    raw_gate = pd.read_csv(RAW_RUN / "raw_validation_gate.csv")
    raw_summary = pd.read_csv(RAW_RUN / "performance_summary.csv")
    raw_metrics = raw_gate.rename(columns={"top_ratio_cagr": "full_ratio_cagr"}).copy()
    raw_metrics = raw_metrics.rename(columns={"passed": "pass_gate"}) if "passed" in raw_metrics.columns else raw_metrics
    raw_stats = summarize_periods(
        raw_metrics,
        raw_summary,
        "metric",
        ["raw_column", "family", "source", "role", "coverage", "pass_gate"],
    )
    raw_pre_post = make_pre_post(raw_stats, "metric", ["raw_column", "family", "source", "role", "coverage", "pass_gate"])

    pair_metrics = pd.read_csv(PAIR_RUN / "raw_pair_full_period_rank.csv")
    pair_summary = pd.read_csv(PAIR_RUN / "performance_summary.csv")
    pair_stats = summarize_periods(
        pair_metrics,
        pair_summary,
        "metric",
        ["label", "family_pair", "component_1_raw", "component_1_family", "component_2_raw", "component_2_family"],
    )
    pair_pre_post = make_pre_post(
        pair_stats,
        "metric",
        ["label", "family_pair", "component_1_raw", "component_1_family", "component_2_raw", "component_2_family"],
    )

    # Period-aware synergy uses the same strict idea as the full-period report:
    # pair must beat the better component in robust, Top/BM CAGR, and Top/Worst return.
    comp = raw_stats[
        [
            "metric",
            "raw_column",
            "period_id",
            "ratio_cagr",
            "top_worst_ratio_return",
            "robust_score",
        ]
    ].rename(
        columns={
            "metric": "component_metric",
            "raw_column": "component_raw",
            "ratio_cagr": "component_ratio_cagr",
            "top_worst_ratio_return": "component_top_worst_ratio_return",
            "robust_score": "component_robust_score",
        }
    )
    pair_component_map = pair_metrics[
        ["metric", "component_1_metric", "component_1_raw", "component_2_metric", "component_2_raw"]
    ]
    left = pair_component_map.merge(
        comp,
        left_on=["component_1_metric", "component_1_raw"],
        right_on=["component_metric", "component_raw"],
        how="left",
    )
    right = pair_component_map.merge(
        comp,
        left_on=["component_2_metric", "component_2_raw"],
        right_on=["component_metric", "component_raw"],
        how="left",
    )
    best = left[["metric", "period_id", "component_ratio_cagr", "component_top_worst_ratio_return", "component_robust_score"]].merge(
        right[["metric", "period_id", "component_ratio_cagr", "component_top_worst_ratio_return", "component_robust_score"]],
        on=["metric", "period_id"],
        suffixes=("_left", "_right"),
    )
    best["best_component_ratio_cagr"] = best[["component_ratio_cagr_left", "component_ratio_cagr_right"]].max(axis=1)
    best["best_component_top_worst_ratio_return"] = best[
        ["component_top_worst_ratio_return_left", "component_top_worst_ratio_return_right"]
    ].max(axis=1)
    best["best_component_robust_score"] = best[["component_robust_score_left", "component_robust_score_right"]].max(axis=1)
    pair_period_synergy = pair_stats.merge(
        best[["metric", "period_id", "best_component_ratio_cagr", "best_component_top_worst_ratio_return", "best_component_robust_score"]],
        on=["metric", "period_id"],
        how="left",
    )
    pair_period_synergy["robust_uplift_vs_best_single"] = (
        pair_period_synergy["robust_score"] - pair_period_synergy["best_component_robust_score"]
    )
    pair_period_synergy["ratio_cagr_uplift_vs_best_single"] = (
        pair_period_synergy["ratio_cagr"] - pair_period_synergy["best_component_ratio_cagr"]
    )
    pair_period_synergy["top_worst_uplift_vs_best_single"] = (
        pair_period_synergy["top_worst_ratio_return"] - pair_period_synergy["best_component_top_worst_ratio_return"]
    )
    pair_period_synergy["strict_synergy_flag"] = (
        (pair_period_synergy["robust_uplift_vs_best_single"] > 0)
        & (pair_period_synergy["ratio_cagr_uplift_vs_best_single"] > 0)
        & (pair_period_synergy["top_worst_uplift_vs_best_single"] > 0)
    )

    raw_stats.to_csv(OUT_DIR / "raw_period_2020_break_stats.csv", index=False, encoding="utf-8-sig")
    raw_pre_post.to_csv(OUT_DIR / "raw_pre_post_2020.csv", index=False, encoding="utf-8-sig")
    pair_stats.to_csv(OUT_DIR / "pair_period_2020_break_stats.csv", index=False, encoding="utf-8-sig")
    pair_pre_post.to_csv(OUT_DIR / "pair_pre_post_2020.csv", index=False, encoding="utf-8-sig")
    pair_period_synergy.to_csv(OUT_DIR / "pair_period_synergy_2020_break.csv", index=False, encoding="utf-8-sig")
    family_shift_table(raw_pre_post, "family").to_csv(OUT_DIR / "raw_family_pre_post_shift.csv", index=False, encoding="utf-8-sig")
    family_shift_table(pair_pre_post, "family_pair").to_csv(OUT_DIR / "pair_family_pre_post_shift.csv", index=False, encoding="utf-8-sig")

    summary = {
        "raw_count": int(len(raw_pre_post)),
        "raw_pre_positive": int((raw_pre_post["robust_score_pre_2020"] > 0).sum()),
        "raw_post_positive": int((raw_pre_post["robust_score_post_2020"] > 0).sum()),
        "raw_pre_only_faded": int((raw_pre_post["regime_class"] == "pre_only_faded").sum()),
        "raw_post_only_emerged": int((raw_pre_post["regime_class"] == "post_only_emerged").sum()),
        "raw_persistent_positive": int((raw_pre_post["regime_class"] == "persistent_positive").sum()),
        "pair_count": int(len(pair_pre_post)),
        "pair_pre_positive": int((pair_pre_post["robust_score_pre_2020"] > 0).sum()),
        "pair_post_positive": int((pair_pre_post["robust_score_post_2020"] > 0).sum()),
        "pair_pre_only_faded": int((pair_pre_post["regime_class"] == "pre_only_faded").sum()),
        "pair_post_only_emerged": int((pair_pre_post["regime_class"] == "post_only_emerged").sum()),
        "pair_persistent_positive": int((pair_pre_post["regime_class"] == "persistent_positive").sum()),
        "post_2020_strict_synergy_pairs": int(
            pair_period_synergy[
                pair_period_synergy["period_id"].eq("post_2020") & pair_period_synergy["strict_synergy_flag"]
            ].shape[0]
        ),
        "pre_2020_strict_synergy_pairs": int(
            pair_period_synergy[
                pair_period_synergy["period_id"].eq("pre_2020") & pair_period_synergy["strict_synergy_flag"]
            ].shape[0]
        ),
    }
    pd.Series(summary).to_csv(OUT_DIR / "regime_break_summary.csv", header=["value"], encoding="utf-8-sig")

    try:
        import plotly.express as px

        raw_plot = raw_pre_post.copy()
        raw_plot["short_label"] = raw_plot["raw_column"]
        raw_plot = raw_plot.sort_values("robust_delta_post_minus_pre", ascending=False)
        fig = px.bar(
            raw_plot,
            x="short_label",
            y="robust_delta_post_minus_pre",
            color="family",
            hover_data=[
                "regime_class",
                "ratio_cagr_pre_2020",
                "ratio_cagr_post_2020",
                "robust_score_pre_2020",
                "robust_score_post_2020",
            ],
            title="STOXX600 raw variables: post-2020 robust-score shift",
        )
        fig.update_layout(xaxis_tickangle=-55, height=720)
        fig.write_html(plot_dir / "raw_pre_post_robust_shift.html")

        pair_plot = pair_pre_post.sort_values("robust_score_post_2020", ascending=False).head(40).copy()
        fig = px.scatter(
            pair_plot,
            x="robust_score_pre_2020",
            y="robust_score_post_2020",
            color="family_pair",
            size=np.maximum(pair_plot["top_worst_ratio_return_post_2020"].fillna(0), 0.01),
            hover_name="label",
            hover_data=[
                "regime_class",
                "ratio_cagr_pre_2020",
                "ratio_cagr_post_2020",
                "top_worst_ratio_return_post_2020",
            ],
            title="STOXX600 top post-2020 raw-pairs: pre vs post robust score",
        )
        fig.add_shape(type="line", x0=-1, y0=-1, x1=1.2, y1=1.2, line={"dash": "dash", "color": "gray"})
        fig.update_layout(height=720)
        fig.write_html(plot_dir / "pair_pre_post_robust_scatter.html")
    except Exception as exc:  # Plot generation should not block the evidence tables.
        (OUT_DIR / "plot_error.txt").write_text(str(exc), encoding="utf-8")

    print(f"Wrote {OUT_DIR}")
    print(summary)


if __name__ == "__main__":
    main()

from __future__ import annotations
from tp_research.runtime import recorded_workflow

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


from tp_core.workspace import BACKTEST_RUNS_DIR, REPORTS_DIR

LORO_RUN = (
    BACKTEST_RUNS_DIR
    / "ad_hoc"
    / "stoxx600_leave_one_regime_out_20260723"
)
RAW_RUN = BACKTEST_RUNS_DIR / "ad_hoc" / "stoxx600_raw_gated_20260708_0100"
RELATIVE_RUN = (
    BACKTEST_RUNS_DIR
    / "ad_hoc"
    / "stoxx600_relative_variables_20260709"
)
SYNERGY_RUN = (
    BACKTEST_RUNS_DIR
    / "ad_hoc"
    / "stoxx600_relative_synergy_20260709"
)
DEFAULT_OUTPUT = REPORTS_DIR / "stoxx600-factor-explorer.html"
DEFAULT_SOURCE_COPY = (
    REPORTS_DIR
    / "factor_explorer_sources"
    / "stoxx600-factor-explorer.html"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the self-contained STOXX Europe 600 factor research explorer."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-copy", type=Path, default=DEFAULT_SOURCE_COPY)
    return parser.parse_args()


def json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if pd.isna(value):
        return None
    return value


def read_nav(path_text: str) -> pd.Series:
    path = Path(path_text)
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    date_col = "Date" if "Date" in frame.columns else frame.columns[0]
    nav_col = "nav" if "nav" in frame.columns else frame.columns[-1]
    out = frame[[date_col, nav_col]].copy()
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
    out[nav_col] = pd.to_numeric(out[nav_col], errors="coerce")
    out = out.dropna().drop_duplicates(date_col, keep="last").sort_values(date_col)
    return out.set_index(date_col)[nav_col].astype(float)


def build_path_map() -> dict[str, dict[str, str]]:
    frames = []
    for run in (RAW_RUN, RELATIVE_RUN, SYNERGY_RUN):
        summary = pd.read_csv(run / "performance_summary.csv", low_memory=False)
        summary = summary[summary["status"].eq("success")].copy()
        frames.append(summary[["metric", "side", "perf_ptf", "perf_bench"]])
    paths: dict[str, dict[str, str]] = {}
    for row in pd.concat(frames, ignore_index=True).itertuples(index=False):
        ptf = Path(str(row.perf_ptf))
        bench = Path(str(row.perf_bench))
        if ptf.exists() and bench.exists():
            paths.setdefault(str(row.metric), {})[str(row.side)] = str(ptf)
            paths.setdefault(str(row.metric), {})[f"{row.side}_bench"] = str(bench)
    return paths


def monthly_nav_payload(metric: str, path_map: dict[str, dict[str, str]]) -> list[dict[str, object]]:
    paths = path_map.get(metric, {})
    required = ("Top", "Worst", "Top_bench")
    if any(key not in paths for key in required):
        return []
    nav = pd.concat(
        {
            "top": read_nav(paths["Top"]),
            "worst": read_nav(paths["Worst"]),
            "benchmark": read_nav(paths["Top_bench"]),
        },
        axis=1,
        join="inner",
    ).dropna()
    if nav.empty:
        return []
    nav = nav / nav.iloc[0] * 100.0
    month_end = nav.groupby(nav.index.to_period("M")).tail(1)
    if month_end.index[0] != nav.index[0]:
        month_end = pd.concat([nav.iloc[[0]], month_end]).sort_index()
    if month_end.index[-1] != nav.index[-1]:
        month_end = pd.concat([month_end, nav.iloc[[-1]]]).sort_index()
    month_end = month_end[~month_end.index.duplicated(keep="last")]
    return [
        {
            "date": index.strftime("%Y-%m-%d"),
            "top": round(float(row.top), 4),
            "worst": round(float(row.worst), 4),
            "benchmark": round(float(row.benchmark), 4),
        }
        for index, row in month_end.iterrows()
    ]


def top_rows(frame: pd.DataFrame, limit: int) -> list[dict[str, object]]:
    columns = [
        "metric",
        "label",
        "candidate_class",
        "candidate_type",
        "family",
        "bucket",
        "coverage",
        "avg_turnover",
        "train_gate_passes",
        "holdout_joint_positive_rate",
        "mean_holdout_active_cagr",
        "min_holdout_active_cagr",
        "mean_holdout_top_worst_cagr",
        "min_holdout_top_worst_cagr",
        "mean_train_robust_objective",
        "loro_classification",
    ]
    selected = frame.head(limit).reindex(columns=columns)
    return json_ready(selected.to_dict(orient="records"))  # type: ignore[return-value]


def build_payload() -> dict[str, object]:
    registry = pd.read_csv(LORO_RUN / "candidate_registry.csv", low_memory=False)
    regime_defs = pd.read_csv(LORO_RUN / "regime_definitions.csv")
    regime_metrics = pd.read_csv(LORO_RUN / "candidate_regime_metrics.csv", low_memory=False)
    singles = pd.read_csv(LORO_RUN / "single_loro_selection_summary.csv", low_memory=False)
    combinations = pd.read_csv(
        LORO_RUN / "combination_loro_selection_summary.csv", low_memory=False
    )
    synergy = pd.read_csv(LORO_RUN / "synergy_loro_summary.csv", low_memory=False)
    loo = pd.read_csv(LORO_RUN / "leave_one_out_regime_contribution.csv")
    raw_gate = pd.read_csv(RAW_RUN / "raw_validation_gate.csv", low_memory=False)
    relative_gate = pd.read_csv(
        RELATIVE_RUN / "relative_validation_gate.csv", low_memory=False
    )

    classification_order = {"cross_regime_core": 0, "cross_regime_resilient": 1}
    singles = singles[singles["loro_classification"].isin(classification_order)].copy()
    singles["class_order"] = singles["loro_classification"].map(classification_order)
    singles = singles.sort_values(
        ["class_order", "holdout_joint_positive_rate", "min_holdout_active_cagr", "mean_holdout_active_cagr"],
        ascending=[True, False, False, False],
    )

    combinations = combinations[
        combinations["loro_classification"].isin(classification_order)
    ].copy()
    combinations["class_order"] = combinations["loro_classification"].map(
        classification_order
    )
    combinations = combinations.sort_values(
        ["class_order", "holdout_joint_positive_rate", "min_holdout_active_cagr", "mean_holdout_active_cagr"],
        ascending=[True, False, False, False],
    )

    strict_synergy = synergy[
        synergy["loro_synergy_classification"].eq("cross_regime_synergistic")
    ].copy()
    strict_synergy = strict_synergy.sort_values(
        ["holdout_synergy_confirmation_rate", "mean_holdout_active_cagr"],
        ascending=False,
    )

    single_table = singles.head(25)
    combination_table = combinations.head(25)
    selected_metrics = list(
        dict.fromkeys(
            single_table["metric"].astype(str).tolist()
            + combination_table["metric"].astype(str).tolist()
            + strict_synergy["metric"].astype(str).tolist()
            + ["stoxx600_syn_full_bucket_equal"]
        )
    )

    registry_by_metric = registry.drop_duplicates("metric", keep="last").set_index("metric")
    summary_by_metric = pd.concat(
        [
            pd.read_csv(LORO_RUN / "single_loro_selection_summary.csv", low_memory=False),
            pd.read_csv(
                LORO_RUN / "combination_loro_selection_summary.csv", low_memory=False
            ),
        ],
        ignore_index=True,
    ).drop_duplicates("metric", keep="last").set_index("metric")
    regimes_by_metric = {
        metric: group.sort_values("regime_start")
        for metric, group in regime_metrics.groupby("metric", sort=False)
    }
    path_map = build_path_map()

    candidates = []
    for metric in selected_metrics:
        if metric not in registry_by_metric.index or metric not in summary_by_metric.index:
            continue
        meta = registry_by_metric.loc[metric]
        summary = summary_by_metric.loc[metric]
        candidate_regimes = regimes_by_metric.get(metric, pd.DataFrame())
        candidates.append(
            {
                "metric": metric,
                "label": meta.get("label"),
                "candidateClass": meta.get("candidate_class"),
                "candidateType": meta.get("candidate_type"),
                "family": meta.get("family"),
                "bucket": meta.get("bucket"),
                "coverage": meta.get("coverage"),
                "turnover": meta.get("avg_turnover"),
                "classification": summary.get("loro_classification"),
                "trainPasses": summary.get("train_gate_passes"),
                "holdoutJointRate": summary.get("holdout_joint_positive_rate"),
                "meanActive": summary.get("mean_holdout_active_cagr"),
                "minActive": summary.get("min_holdout_active_cagr"),
                "meanTopWorst": summary.get("mean_holdout_top_worst_cagr"),
                "minTopWorst": summary.get("min_holdout_top_worst_cagr"),
                "regimes": [
                    {
                        "id": row.regime_id,
                        "label": regime_defs.set_index("regime_id")
                        .at[row.regime_id, "label_zh"],
                        "active": row.active_cagr,
                        "topWorst": row.top_worst_cagr,
                        "top": row.top_cagr,
                        "benchmark": row.benchmark_cagr,
                    }
                    for row in candidate_regimes.itertuples(index=False)
                ],
                "nav": monthly_nav_payload(metric, path_map),
            }
        )

    single_regime = regime_metrics[
        regime_metrics["candidate_class"].isin(["raw", "relative"])
    ].copy()
    regime_winners = (
        single_regime.sort_values(
            ["regime_id", "active_cagr", "top_worst_cagr"],
            ascending=[True, False, False],
        )
        .groupby("regime_id", sort=False)
        .head(5)
        .merge(regime_defs[["regime_id", "label_zh"]], on="regime_id", how="left")
    )
    winner_columns = [
        "regime_id",
        "label_zh",
        "label",
        "candidate_class",
        "family",
        "active_cagr",
        "top_worst_cagr",
    ]

    loo_summary = (
        loo.groupby("left_out_bucket", as_index=False)
        .agg(
            training_positive_folds=("training_positive_contribution", "sum"),
            holdout_positive_folds=("holdout_any_positive_contribution", "sum"),
            folds=("holdout_regime", "count"),
            mean_holdout_active_contribution=(
                "holdout_active_positive_contribution",
                "mean",
            ),
        )
        .sort_values(["holdout_positive_folds", "training_positive_folds"], ascending=False)
    )

    raw_pass = raw_gate["pass_gate"].fillna(False).astype(bool).sum()
    relative_pass = relative_gate["pass_gate"].fillna(False).astype(bool).sum()
    manifest = json.loads((LORO_RUN / "manifest.json").read_text(encoding="utf-8"))

    return json_ready(
        {
            "meta": {
                "title": "STOXX Europe 600 因子研究浏览器",
                "asOf": "2026-07-23",
                "navEnd": "2026-07-02",
                "candidateCount": manifest["candidate_count"],
                "singleCount": manifest["single_candidate_count"],
                "combinationCount": manifest["combination_candidate_count"],
                "regimeCount": manifest["regime_count"],
                "candidateRegimeRows": manifest["candidate_regime_row_count"],
                "resilientSingles": len(singles),
                "resilientCombinations": len(combinations),
                "strictSynergy": len(strict_synergy),
                "rawTested": len(raw_gate),
                "rawPassed": int(raw_pass),
                "relativeTested": len(relative_gate),
                "relativePassed": int(relative_pass),
                "futureOosStart": manifest["future_oos_start"],
            },
            "regimes": regime_defs.to_dict(orient="records"),
            "candidates": candidates,
            "singleTable": top_rows(single_table, 25),
            "combinationTable": top_rows(combination_table, 25),
            "strictSynergy": strict_synergy.to_dict(orient="records"),
            "regimeWinners": regime_winners[winner_columns].to_dict(orient="records"),
            "loo": loo_summary.to_dict(orient="records"),
            "method": {
                "coverage": 0.75,
                "positiveTrainRegimes": "至少 4/5",
                "worstTrainActiveCagr": -0.03,
                "costBps": 20,
                "selectionRule": "每个 fold 先让全部底层单变量通过训练 gate，再评价组合；被留出的完整阶段不参与选择。",
                "synergyRule": "训练期相对最强单腿至少改善三项风险收益指标，并在留出阶段重复确认；否则只称 additive。",
            },
        }
    )  # type: ignore[return-value]


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>STOXX Europe 600 因子研究浏览器</title>
  <style>
    :root {
      --paper: #f4f5f1;
      --surface: #ffffff;
      --surface-2: #e8ece7;
      --ink: #18252e;
      --muted: #617079;
      --line: #ccd3cf;
      --teal: #087f74;
      --coral: #bd5849;
      --blue: #3f6f9f;
      --gold: #a87816;
      --green-soft: #dcece5;
      --red-soft: #f2dfdc;
      --gold-soft: #f2e7c9;
      --shadow: 0 8px 24px rgba(24, 37, 46, .08);
      --radius: 6px;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: Inter, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      line-height: 1.45;
      letter-spacing: 0;
    }
    button, select, input { font: inherit; letter-spacing: 0; }
    button:focus-visible, select:focus-visible, input:focus-visible {
      outline: 3px solid rgba(8, 127, 116, .25);
      outline-offset: 2px;
    }
    .masthead {
      background: var(--ink);
      color: white;
      border-bottom: 5px solid var(--teal);
    }
    .masthead-inner, .nav-inner, .section-inner {
      width: min(1440px, calc(100% - 40px));
      margin: 0 auto;
    }
    .masthead-inner {
      min-height: 168px;
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) minmax(360px, .8fr);
      align-items: end;
      gap: 36px;
      padding: 28px 0 24px;
    }
    .eyebrow {
      margin: 0 0 8px;
      color: #9dd5cc;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }
    h1 {
      margin: 0;
      max-width: 900px;
      font-size: clamp(30px, 4vw, 52px);
      line-height: 1.05;
      letter-spacing: 0;
    }
    .dek {
      margin: 14px 0 0;
      max-width: 900px;
      color: #ced7da;
      font-size: 15px;
    }
    .headline-finding {
      border-left: 3px solid var(--gold);
      padding: 0 0 2px 18px;
    }
    .headline-finding strong {
      display: block;
      margin-bottom: 4px;
      color: #f6d98e;
      font-size: 30px;
    }
    .headline-finding span { color: #d7dfe1; font-size: 14px; }
    .sticky-nav {
      position: sticky;
      top: 0;
      z-index: 20;
      background: rgba(244, 245, 241, .96);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(10px);
    }
    .nav-inner {
      display: flex;
      gap: 4px;
      overflow-x: auto;
      scrollbar-width: thin;
      padding: 8px 0;
    }
    .nav-link {
      flex: 0 0 auto;
      border: 0;
      border-radius: 4px;
      background: transparent;
      color: var(--muted);
      padding: 8px 12px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
    }
    .nav-link:hover, .nav-link.active { background: var(--ink); color: white; }
    .section-band { padding: 34px 0; border-bottom: 1px solid var(--line); }
    .section-band.alt { background: #e9ece7; }
    .section-head {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 20px;
    }
    .section-head h2 {
      margin: 0;
      font-size: 25px;
      line-height: 1.15;
    }
    .section-head p {
      margin: 0;
      max-width: 760px;
      color: var(--muted);
      font-size: 13px;
      text-align: right;
    }
    .metric-strip {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }
    .metric {
      min-height: 112px;
      padding: 16px;
      border: 1px solid var(--line);
      border-top: 4px solid var(--blue);
      border-radius: var(--radius);
      background: var(--surface);
    }
    .metric:nth-child(2) { border-top-color: var(--teal); }
    .metric:nth-child(3) { border-top-color: var(--coral); }
    .metric:nth-child(4) { border-top-color: var(--gold); }
    .metric:nth-child(5) { border-top-color: var(--ink); }
    .metric .value { display: block; font-size: 28px; font-weight: 800; }
    .metric .label { color: var(--muted); font-size: 12px; }
    .conclusion-grid {
      display: grid;
      grid-template-columns: 1.25fr .75fr;
      gap: 18px;
      margin-top: 18px;
    }
    .conclusion-main, .conclusion-side {
      padding: 20px;
      border-radius: var(--radius);
      background: var(--surface);
      border: 1px solid var(--line);
    }
    .conclusion-main { border-left: 5px solid var(--teal); }
    .conclusion-side { border-left: 5px solid var(--gold); }
    .conclusion-grid h3 { margin: 0 0 8px; font-size: 17px; }
    .conclusion-grid p { margin: 0; color: var(--muted); font-size: 14px; }
    .explorer-controls {
      display: grid;
      grid-template-columns: auto minmax(280px, 1fr) minmax(180px, .35fr);
      gap: 12px;
      align-items: end;
      margin-bottom: 16px;
    }
    .field label { display: block; margin-bottom: 5px; color: var(--muted); font-size: 12px; font-weight: 700; }
    select, input[type="search"] {
      width: 100%;
      min-height: 40px;
      border: 1px solid #aeb8b3;
      border-radius: 4px;
      background: white;
      color: var(--ink);
      padding: 8px 10px;
    }
    .segmented {
      display: inline-flex;
      min-height: 40px;
      border: 1px solid #aeb8b3;
      border-radius: 4px;
      overflow: hidden;
      background: white;
    }
    .segment {
      border: 0;
      border-right: 1px solid #aeb8b3;
      border-radius: 0;
      background: transparent;
      color: var(--muted);
      padding: 8px 12px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
    }
    .segment:last-child { border-right: 0; }
    .segment.active { background: var(--teal); color: white; }
    .explorer-layout {
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(300px, .65fr);
      gap: 16px;
      align-items: stretch;
    }
    .chart-panel, .detail-panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }
    .chart-panel { min-height: 510px; padding: 16px; }
    .detail-panel { padding: 18px; }
    .candidate-title { margin: 0; font-size: 19px; overflow-wrap: anywhere; }
    .candidate-meta { margin: 5px 0 14px; color: var(--muted); font-size: 12px; }
    #nav-chart { width: 100%; height: 390px; display: block; }
    .legend { display: flex; flex-wrap: wrap; gap: 16px; margin: 8px 0 0; color: var(--muted); font-size: 12px; }
    .legend-item { display: inline-flex; align-items: center; gap: 6px; }
    .swatch { width: 18px; height: 3px; }
    .detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .detail-stat {
      min-height: 82px;
      border-bottom: 1px solid var(--line);
      padding: 8px 0;
    }
    .detail-stat .value { display: block; font-size: 23px; font-weight: 800; }
    .detail-stat .label { color: var(--muted); font-size: 11px; }
    .classification {
      display: inline-block;
      margin: 15px 0 8px;
      border-radius: 3px;
      padding: 5px 8px;
      background: var(--green-soft);
      color: #176047;
      font-size: 12px;
      font-weight: 800;
    }
    .economic-note {
      margin: 8px 0 0;
      padding-top: 12px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 13px;
    }
    .heatmap {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 8px;
      margin-top: 16px;
    }
    .regime-cell {
      min-height: 118px;
      border: 1px solid rgba(24, 37, 46, .14);
      border-radius: 4px;
      padding: 12px;
      color: var(--ink);
    }
    .regime-cell .regime-name { display: block; min-height: 36px; font-size: 12px; font-weight: 800; }
    .regime-cell .regime-value { display: block; margin-top: 7px; font-size: 24px; font-weight: 800; }
    .regime-cell .regime-sub { font-size: 11px; opacity: .75; }
    .table-tools { display: flex; justify-content: flex-end; margin-bottom: 10px; }
    .table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--surface);
    }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th {
      position: sticky;
      top: 0;
      z-index: 2;
      background: var(--ink);
      color: white;
      text-align: left;
      white-space: nowrap;
      padding: 10px;
    }
    td { border-bottom: 1px solid #e1e5e2; padding: 9px 10px; vertical-align: top; }
    tbody tr:hover { background: #f0f4f1; }
    .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .positive { color: #08735a; font-weight: 700; }
    .negative { color: #a63e34; font-weight: 700; }
    .tag {
      display: inline-block;
      border-radius: 3px;
      background: var(--surface-2);
      color: var(--ink);
      padding: 3px 6px;
      font-size: 11px;
      font-weight: 700;
    }
    .synergy-band {
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(320px, .9fr);
      gap: 18px;
      align-items: stretch;
    }
    .synergy-proof {
      padding: 22px;
      border: 1px solid var(--line);
      border-left: 6px solid var(--coral);
      border-radius: var(--radius);
      background: white;
    }
    .synergy-proof h3 { margin: 0 0 10px; font-size: 21px; }
    .proof-numbers { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 18px; }
    .proof-number { background: var(--red-soft); border-radius: 4px; padding: 12px; }
    .proof-number strong { display: block; font-size: 22px; }
    .proof-number span { color: var(--muted); font-size: 11px; }
    .boundary {
      padding: 22px;
      border: 1px solid var(--line);
      border-left: 6px solid var(--gold);
      border-radius: var(--radius);
      background: white;
    }
    .boundary h3 { margin: 0 0 10px; }
    .boundary ul { margin: 0; padding-left: 19px; color: var(--muted); font-size: 13px; }
    .boundary li { margin: 7px 0; }
    .regime-timeline {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      border: 1px solid var(--line);
      border-radius: var(--radius);
      overflow: hidden;
      background: white;
    }
    .timeline-block { min-height: 164px; padding: 15px; border-right: 1px solid var(--line); }
    .timeline-block:last-child { border-right: 0; }
    .timeline-block .years { color: var(--teal); font-size: 12px; font-weight: 800; }
    .timeline-block h3 { margin: 7px 0; font-size: 14px; }
    .timeline-block p { margin: 0; color: var(--muted); font-size: 11px; }
    .watch-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 18px;
    }
    .watch-item {
      min-height: 150px;
      padding: 17px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: white;
    }
    .watch-item h3 { margin: 0 0 8px; font-size: 15px; }
    .watch-item p { margin: 0; color: var(--muted); font-size: 13px; }
    .method-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }
    .method-block {
      border-top: 4px solid var(--blue);
      padding: 16px 0 0;
    }
    .method-block:nth-child(2) { border-top-color: var(--gold); }
    .method-block h3 { margin: 0 0 10px; }
    .method-block p, .method-block li { color: var(--muted); font-size: 13px; }
    footer { background: var(--ink); color: #cdd7d8; padding: 28px 0; }
    footer p { margin: 4px 0; font-size: 12px; }
    .empty { padding: 40px; color: var(--muted); text-align: center; }
    @media (max-width: 1000px) {
      .masthead-inner { grid-template-columns: 1fr; align-items: center; }
      .metric-strip { grid-template-columns: repeat(3, 1fr); }
      .explorer-layout, .conclusion-grid, .synergy-band { grid-template-columns: 1fr; }
      .heatmap, .regime-timeline { grid-template-columns: repeat(3, 1fr); }
      .timeline-block { border-bottom: 1px solid var(--line); }
      .watch-grid { grid-template-columns: 1fr 1fr; }
    }
    @media (max-width: 680px) {
      .masthead-inner, .nav-inner, .section-inner { width: min(100% - 24px, 1440px); }
      .masthead-inner { min-height: 0; padding: 24px 0; gap: 22px; }
      h1 { font-size: 34px; }
      .headline-finding strong { font-size: 25px; }
      .section-band { padding: 26px 0; }
      .section-head { display: block; }
      .section-head p { margin-top: 8px; text-align: left; }
      .metric-strip { grid-template-columns: 1fr 1fr; }
      .metric { min-height: 100px; }
      .explorer-controls { grid-template-columns: 1fr; }
      .segmented { width: 100%; }
      .segment { flex: 1; }
      .chart-panel { min-height: 430px; padding: 10px; }
      #nav-chart { height: 320px; }
      .heatmap, .regime-timeline, .watch-grid, .method-grid { grid-template-columns: 1fr; }
      .regime-cell { min-height: 94px; }
      .timeline-block { min-height: 0; border-right: 0; }
      .proof-numbers { grid-template-columns: 1fr; }
      table { min-width: 780px; }
    }
  </style>
</head>
<body>
  <header class="masthead">
    <div class="masthead-inner">
      <div>
        <p class="eyebrow">Official exact Top / Worst · Leave-one-regime-out</p>
        <h1>STOXX Europe 600 因子研究浏览器</h1>
        <p class="dek">先让每个 raw/relative 单变量通过证据门槛，再进入 pair、subset 与 leave-one-out。这里展示的是完整历史阶段阻塞验证，不把全样本漂亮曲线误称为未来样本。</p>
      </div>
      <div class="headline-finding">
        <strong>2020 是断点，不是清零键</strong>
        <span>静态水平变量大面积失灵；盈利改善、分析师修正和价格动量在断点两侧都留下重复证据。</span>
      </div>
    </div>
  </header>

  <nav class="sticky-nav" aria-label="研究章节">
    <div class="nav-inner">
      <button class="nav-link active" data-target="overview">总览</button>
      <button class="nav-link" data-target="explore">候选浏览器</button>
      <button class="nav-link" data-target="singles">单变量</button>
      <button class="nav-link" data-target="synergy">组合与协同</button>
      <button class="nav-link" data-target="regimes">阶段轮动</button>
      <button class="nav-link" data-target="method">方法与边界</button>
    </div>
  </nav>

  <main>
    <section id="overview" class="section-band">
      <div class="section-inner">
        <div class="section-head">
          <h2>研究覆盖</h2>
          <p>所有候选均来自已完成的官方精确净值；阶段边界由宏观事件预先定义，不依据因子曲线寻找最佳切点。</p>
        </div>
        <div id="metric-strip" class="metric-strip"></div>
        <div class="conclusion-grid">
          <article class="conclusion-main">
            <h3>跨阶段核心</h3>
            <p>最稳定的单变量不是“高利润率”本身，而是同一证券经营利润率、ROE、持续经营利润率的改善；EPS NTM 3M Growth、EPS Revision Ratio、PMOM 12M1M 和盈利收益率改善提供独立的信息更新与价格确认。</p>
          </article>
          <aside class="conclusion-side">
            <h3>协同口径</h3>
            <p>79 个组合通过稳健门槛，但只有“经营利润率改善 + EPS NTM 3M Growth”在训练和留出阶段重复击败最强单腿。其余只称稳健加法，不自动升级为 synergy。</p>
          </aside>
        </div>
      </div>
    </section>

    <section id="explore" class="section-band alt">
      <div class="section-inner">
        <div class="section-head">
          <h2>候选浏览器</h2>
          <p>曲线为官方 Top、Worst 与 benchmark 的月末抽样展示；门槛与统计由完整日频净值计算。</p>
        </div>
        <div class="explorer-controls">
          <div class="field">
            <label>候选类型</label>
            <div class="segmented" role="group" aria-label="候选类型">
              <button class="segment active" data-filter="all">全部</button>
              <button class="segment" data-filter="single">单变量</button>
              <button class="segment" data-filter="combination">组合</button>
            </div>
          </div>
          <div class="field">
            <label for="candidate-select">候选</label>
            <select id="candidate-select"></select>
          </div>
          <div class="field">
            <label for="candidate-search">快速筛选</label>
            <input id="candidate-search" type="search" placeholder="变量、family、bucket">
          </div>
        </div>
        <div class="explorer-layout">
          <div class="chart-panel">
            <h3 id="candidate-title" class="candidate-title"></h3>
            <p id="candidate-meta" class="candidate-meta"></p>
            <svg id="nav-chart" role="img" aria-label="Top、Worst 与基准净值曲线"></svg>
            <div class="legend">
              <span class="legend-item"><i class="swatch" style="background:#087f74"></i>Top</span>
              <span class="legend-item"><i class="swatch" style="background:#bd5849"></i>Worst</span>
              <span class="legend-item"><i class="swatch" style="background:#3f6f9f"></i>Benchmark</span>
            </div>
          </div>
          <aside class="detail-panel">
            <div id="detail-grid" class="detail-grid"></div>
            <span id="classification" class="classification"></span>
            <p id="economic-note" class="economic-note"></p>
          </aside>
        </div>
        <div id="regime-heatmap" class="heatmap"></div>
      </div>
    </section>

    <section id="singles" class="section-band">
      <div class="section-inner">
        <div class="section-head">
          <h2>有效单变量</h2>
          <p>排名优先考虑跨阶段分类、留出期同时跑赢 benchmark 与 Worst 的比例，以及最差留出期表现。</p>
        </div>
        <div class="table-tools">
          <input id="single-search" type="search" placeholder="筛选单变量">
        </div>
        <div class="table-wrap"><table id="single-table"></table></div>
      </div>
    </section>

    <section id="synergy" class="section-band alt">
      <div class="section-inner">
        <div class="section-head">
          <h2>组合与协同</h2>
          <p>组合有效不等于存在交互项。严格结论需要底层单腿 gate、pair/subset 和跨阶段 leave-one-out 共同支持。</p>
        </div>
        <div class="synergy-band">
          <article id="synergy-proof" class="synergy-proof"></article>
          <aside class="boundary">
            <h3>解释边界</h3>
            <ul>
              <li>稳健组合多数是互补的加法分散，不能声称内部存在经济协同。</li>
              <li>完整模型的 leave-one-out 说明哪些 bucket 在留出期有用，不自动证明其对训练目标有正贡献。</li>
              <li>组合库覆盖 190 个 pair、84 个 subset、完整模型与 8 个 LOO，不是 227 个单变量的全笛卡尔积。</li>
            </ul>
          </aside>
        </div>
        <div style="height:18px"></div>
        <div class="table-wrap"><table id="combination-table"></table></div>
        <div style="height:18px"></div>
        <div class="table-wrap"><table id="loo-table"></table></div>
      </div>
    </section>

    <section id="regimes" class="section-band">
      <div class="section-inner">
        <div class="section-head">
          <h2>阶段轮动</h2>
          <p>阶段赢家用于解释 rotation，不自动进入跨阶段核心；这里尤其检验 2020 前后信号载体的变化。</p>
        </div>
        <div id="regime-timeline" class="regime-timeline"></div>
        <div style="height:18px"></div>
        <div class="table-wrap"><table id="winner-table"></table></div>
        <div class="watch-grid">
          <article class="watch-item">
            <h3>2020 后持续有效</h3>
            <p>利润率/ROE 改善、EPS 修正和 PMOM 仍有重复证据。它们共同描述企业适应能力、预期更新与价格确认，而不是押注单一静态估值水平。</p>
          </article>
          <article class="watch-item">
            <h3>截至 2026-07-23</h3>
            <p>不能把当前状态写成“2026 年终已确认”。更准确的描述是高波动名义环境仍在演化，能源、通胀和融资条件会改变不同腿的相对权重。</p>
          </article>
          <article class="watch-item">
            <h3>2027 执行原则</h3>
            <p>冻结核心定义做真正未来 OOS；核心保持质量改善、revision 与 PMOM，有限配置去杠杆/盈利收益率改善的 regime sleeve，并监控动量反转风险。</p>
          </article>
        </div>
      </div>
    </section>

    <section id="method" class="section-band alt">
      <div class="section-inner">
        <div class="section-head">
          <h2>方法与边界</h2>
          <p>这个设计接受金融数据低信噪比与非平稳性，不用模型复杂度掩盖选择自由度。</p>
        </div>
        <div class="method-grid">
          <article class="method-block">
            <h3>Leave-one-regime-out</h3>
            <p>每次留出一个完整经济阶段，其余五段重新执行 gate。组合只有在全部底层单变量先通过该 fold 的训练门槛后，才有资格被评价。</p>
            <p id="method-gate"></p>
          </article>
          <article class="method-block">
            <h3>仍未消除的风险</h3>
            <p>这是历史阶段阻塞验证，不是真正未来样本；研究者已经看过 2009-2026。完整 trial count 已记录，但相关候选下的 Deflated Sharpe/PBO 仍需谨慎解释。</p>
            <p>从 <strong>2026-07-03</strong> 起冻结变量、方向、gate 与权重，才是下一轮可审计的 live paper OOS。</p>
          </article>
        </div>
      </div>
    </section>
  </main>

  <footer>
    <div class="section-inner">
      <p>研究截至 2026-07-23；官方净值截至 2026-07-02。Benchmark: STOXX Europe 600。</p>
      <p>页面为研究证据浏览器，不构成投资建议。曲线展示使用月末抽样，所有 gate 与结论使用完整日频官方净值。</p>
    </div>
  </footer>

  <script id="research-data" type="application/json">__DATA__</script>
  <script>
    const report = JSON.parse(document.getElementById('research-data').textContent);
    const state = { filter: 'all', query: '', metric: report.candidates[0]?.metric || '' };
    const pct = value => value == null ? '—' : `${(value * 100).toFixed(2)}%`;
    const num = (value, digits = 0) => value == null ? '—' : Number(value).toFixed(digits);
    const clean = value => value == null ? '—' : String(value);
    const classLabel = value => ({
      cross_regime_core: '跨阶段核心',
      cross_regime_resilient: '跨阶段韧性',
    }[value] || clean(value));
    const typeLabel = item => item.candidateClass === 'combination' ? '组合' : item.candidateClass === 'relative' ? '相对变量' : 'Raw 变量';
    const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]));
    const evidenceNote = item => {
      const label = String(item.label || '');
      if (/Oper Margin|ROE|Earning Margin/i.test(label)) return '经济含义：企业自身盈利能力正在改善，反映成本转嫁、经营杠杆和管理执行，而非仅拥有较高的静态利润率。';
      if (/EPS NTM|Revision/i.test(label)) return '经济含义：分析师盈利预期被上调，信息扩散尚未完全进入价格；与经营改善配对时可形成基本面确认。';
      if (/PMOM|Total Return/i.test(label)) return '经济含义：价格对持续信息逐步反应，但在恐慌后的急速反弹中需要防范动量崩塌。';
      if (/Earns Yield/i.test(label)) return '经济含义：同一证券的盈利收益率正在变得更有吸引力，比静态便宜更接近估值方向改善。';
      if (/NetDebt|deleveraging/i.test(label)) return '经济含义：资产负债表缓冲正在改善，在融资成本和能源冲击较高时更具防御价值。';
      return '经济含义：该信号通过多个完整经济阶段的留出验证，但仍应结合其底层变量和阶段暴露解释。';
    };

    function renderOverview() {
      const m = report.meta;
      const cards = [
        [`${m.candidateCount}`, '候选：raw、relative 与组合'],
        [`${m.candidateRegimeRows.toLocaleString()}`, '候选 × 阶段证据单元'],
        [`${m.resilientSingles}`, '跨阶段核心/韧性单变量'],
        [`${m.resilientCombinations}`, '稳健组合（多数为 additive）'],
        [`${m.strictSynergy}`, '严格跨阶段协同'],
      ];
      document.getElementById('metric-strip').innerHTML = cards.map(([value,label]) =>
        `<div class="metric"><span class="value">${value}</span><span class="label">${label}</span></div>`
      ).join('');
    }

    function filteredCandidates() {
      return report.candidates.filter(item => {
        const typeOk = state.filter === 'all'
          || (state.filter === 'single' && item.candidateClass !== 'combination')
          || (state.filter === 'combination' && item.candidateClass === 'combination');
        const haystack = `${item.label} ${item.family} ${item.bucket}`.toLowerCase();
        return typeOk && haystack.includes(state.query.toLowerCase());
      });
    }

    function refreshSelect() {
      const select = document.getElementById('candidate-select');
      const candidates = filteredCandidates();
      if (!candidates.some(item => item.metric === state.metric)) state.metric = candidates[0]?.metric || '';
      select.innerHTML = candidates.map(item =>
        `<option value="${escapeHtml(item.metric)}">${escapeHtml(typeLabel(item))} · ${escapeHtml(item.label)}</option>`
      ).join('');
      select.value = state.metric;
      renderCandidate();
    }

    function svgNode(name, attrs = {}) {
      const node = document.createElementNS('http://www.w3.org/2000/svg', name);
      Object.entries(attrs).forEach(([key,value]) => node.setAttribute(key, value));
      return node;
    }

    function renderChart(item) {
      const svg = document.getElementById('nav-chart');
      svg.replaceChildren();
      const data = item?.nav || [];
      if (!data.length) {
        const text = svgNode('text', {x:'50%', y:'50%', 'text-anchor':'middle', fill:'#617079'});
        text.textContent = '此候选没有可显示的净值路径';
        svg.appendChild(text);
        return;
      }
      const width = Math.max(720, svg.clientWidth || 720);
      const height = Math.max(320, svg.clientHeight || 390);
      svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
      const margin = {top:16, right:18, bottom:34, left:54};
      const plotW = width - margin.left - margin.right;
      const plotH = height - margin.top - margin.bottom;
      const values = data.flatMap(d => [d.top,d.worst,d.benchmark]).filter(Number.isFinite);
      const minY = Math.min(...values);
      const maxY = Math.max(...values);
      const pad = Math.max((maxY - minY) * .08, 4);
      const y0 = minY - pad, y1 = maxY + pad;
      const x = index => margin.left + index / Math.max(data.length - 1, 1) * plotW;
      const y = value => margin.top + (y1 - value) / Math.max(y1 - y0, 1) * plotH;

      for (let i=0;i<=4;i++) {
        const value = y0 + (y1-y0) * i / 4;
        const yy = y(value);
        svg.appendChild(svgNode('line',{x1:margin.left,y1:yy,x2:width-margin.right,y2:yy,stroke:'#dfe4e1','stroke-width':'1'}));
        const label = svgNode('text',{x:margin.left-8,y:yy+4,'text-anchor':'end',fill:'#617079','font-size':'11'});
        label.textContent = value.toFixed(0);
        svg.appendChild(label);
      }
      const tickIndexes = [0, Math.floor((data.length-1)/3), Math.floor((data.length-1)*2/3), data.length-1];
      [...new Set(tickIndexes)].forEach(index => {
        const label = svgNode('text',{x:x(index),y:height-10,'text-anchor':index===0?'start':index===data.length-1?'end':'middle',fill:'#617079','font-size':'11'});
        label.textContent = data[index].date.slice(0,4);
        svg.appendChild(label);
      });
      [
        ['top','#087f74',2.7],
        ['worst','#bd5849',2.2],
        ['benchmark','#3f6f9f',2.2],
      ].forEach(([key,color,strokeWidth]) => {
        const points = data.map((row,index) => `${x(index)},${y(row[key])}`).join(' ');
        svg.appendChild(svgNode('polyline',{
          points, fill:'none', stroke:color, 'stroke-width':strokeWidth,
          'stroke-linejoin':'round', 'stroke-linecap':'round',
        }));
      });
    }

    function heatColor(value) {
      if (value == null) return '#ecefeb';
      const magnitude = Math.min(Math.abs(value) / .10, 1);
      if (value >= 0) return `color-mix(in srgb, #dcece5 ${(1-magnitude)*100}%, #52a88a)`;
      return `color-mix(in srgb, #f2dfdc ${(1-magnitude)*100}%, #cf6659)`;
    }

    function renderCandidate() {
      const item = report.candidates.find(candidate => candidate.metric === state.metric);
      if (!item) return;
      document.getElementById('candidate-title').textContent = item.label;
      document.getElementById('candidate-meta').textContent =
        `${typeLabel(item)} · ${clean(item.family || item.bucket)} · coverage ${pct(item.coverage)} · 月均单边换手 ${pct(item.turnover)}`;
      const stats = [
        [pct(item.meanActive), '平均留出期主动 CAGR'],
        [pct(item.minActive), '最差留出期主动 CAGR'],
        [pct(item.meanTopWorst), '平均 Top/Worst CAGR'],
        [pct(item.holdoutJointRate), '留出期双重为正比例'],
        [`${num(item.trainPasses)}/6`, '训练 gate 通过 folds'],
        [pct(item.minTopWorst), '最差 Top/Worst CAGR'],
      ];
      document.getElementById('detail-grid').innerHTML = stats.map(([value,label]) =>
        `<div class="detail-stat"><span class="value">${value}</span><span class="label">${label}</span></div>`
      ).join('');
      document.getElementById('classification').textContent = classLabel(item.classification);
      document.getElementById('economic-note').textContent = evidenceNote(item);
      document.getElementById('regime-heatmap').innerHTML = item.regimes.map(regime =>
        `<div class="regime-cell" style="background:${heatColor(regime.active)}">
          <span class="regime-name">${escapeHtml(regime.label)}</span>
          <span class="regime-value">${pct(regime.active)}</span>
          <span class="regime-sub">主动 CAGR · Top/Worst ${pct(regime.topWorst)}</span>
        </div>`
      ).join('');
      renderChart(item);
    }

    function renderRankTable(id, rows, searchId) {
      const table = document.getElementById(id);
      const render = query => {
        const filtered = rows.filter(row => `${row.label} ${row.family} ${row.bucket}`.toLowerCase().includes(query.toLowerCase()));
        table.innerHTML = `
          <thead><tr>
            <th>#</th><th>候选</th><th>类型 / family</th><th class="num">训练 gate</th>
            <th class="num">留出双正</th><th class="num">平均主动 CAGR</th>
            <th class="num">最差主动 CAGR</th><th class="num">平均 Top/Worst</th><th>结论</th>
          </tr></thead>
          <tbody>${filtered.map((row,index) => `<tr>
            <td>${index+1}</td>
            <td><strong>${escapeHtml(row.label)}</strong></td>
            <td><span class="tag">${escapeHtml(row.candidate_class === 'combination' ? row.candidate_type : row.candidate_class)}</span><br>${escapeHtml(row.family || row.bucket)}</td>
            <td class="num">${num(row.train_gate_passes)}/6</td>
            <td class="num">${pct(row.holdout_joint_positive_rate)}</td>
            <td class="num ${row.mean_holdout_active_cagr >= 0 ? 'positive':'negative'}">${pct(row.mean_holdout_active_cagr)}</td>
            <td class="num ${row.min_holdout_active_cagr >= 0 ? 'positive':'negative'}">${pct(row.min_holdout_active_cagr)}</td>
            <td class="num">${pct(row.mean_holdout_top_worst_cagr)}</td>
            <td>${classLabel(row.loro_classification)}</td>
          </tr>`).join('')}</tbody>`;
      };
      render('');
      if (searchId) document.getElementById(searchId).addEventListener('input', event => render(event.target.value));
    }

    function renderSynergy() {
      const proof = report.strictSynergy[0];
      const container = document.getElementById('synergy-proof');
      if (!proof) {
        container.innerHTML = '<h3>没有组合达到严格跨阶段协同门槛</h3>';
        return;
      }
      container.innerHTML = `
        <span class="tag">唯一严格协同</span>
        <h3>${escapeHtml(proof.label)}</h3>
        <p>经营改善提供“企业已经变好”的实绩信号，EPS NTM 3M Growth 提供“市场预期正在跟上”的前瞻确认。两条信息链在训练期和留出期都需要击败最强单腿。</p>
        <div class="proof-numbers">
          <div class="proof-number"><strong>${num(proof.train_synergy_folds)}/${num(proof.eligible_folds)}</strong><span>训练期协同 folds</span></div>
          <div class="proof-number"><strong>${num(proof.holdout_synergy_confirmed_folds)}/${num(proof.eligible_folds)}</strong><span>留出期确认 folds</span></div>
          <div class="proof-number"><strong>${pct(proof.mean_holdout_active_cagr)}</strong><span>平均留出主动 CAGR</span></div>
        </div>`;
      renderRankTable('combination-table', report.combinationTable);
      const table = document.getElementById('loo-table');
      table.innerHTML = `
        <thead><tr><th>Leave-one-out bucket</th><th class="num">训练期正贡献 folds</th><th class="num">留出期任一正贡献 folds</th><th class="num">folds</th><th>解释</th></tr></thead>
        <tbody>${report.loo.map(row => `<tr>
          <td><strong>${escapeHtml(row.left_out_bucket)}</strong></td>
          <td class="num">${num(row.training_positive_folds)}</td>
          <td class="num">${num(row.holdout_positive_folds)}</td>
          <td class="num">${num(row.folds)}</td>
          <td>${row.training_positive_folds >= 3 ? '训练与留出均有重复贡献' : row.holdout_positive_folds >= 5 ? '留出期保护明显，训练目标中未稳定增益' : '贡献依赖阶段，不能作核心协同声明'}</td>
        </tr>`).join('')}</tbody>`;
    }

    function renderRegimes() {
      document.getElementById('regime-timeline').innerHTML = report.regimes.map(regime =>
        `<article class="timeline-block">
          <span class="years">${escapeHtml(regime.start.slice(0,4))}–${escapeHtml(regime.end.slice(0,4))}</span>
          <h3>${escapeHtml(regime.label_zh)}</h3>
          <p>${escapeHtml(regime.economic_definition)}</p>
        </article>`
      ).join('');
      const table = document.getElementById('winner-table');
      table.innerHTML = `
        <thead><tr><th>阶段</th><th>阶段特殊赢家</th><th>类型 / family</th><th class="num">主动 CAGR</th><th class="num">Top/Worst CAGR</th></tr></thead>
        <tbody>${report.regimeWinners.map(row => `<tr>
          <td>${escapeHtml(row.label_zh)}</td>
          <td><strong>${escapeHtml(row.label)}</strong></td>
          <td><span class="tag">${escapeHtml(row.candidate_class)}</span> ${escapeHtml(row.family)}</td>
          <td class="num ${row.active_cagr >= 0 ? 'positive':'negative'}">${pct(row.active_cagr)}</td>
          <td class="num">${pct(row.top_worst_cagr)}</td>
        </tr>`).join('')}</tbody>`;
    }

    function bindInteractions() {
      document.querySelectorAll('.segment').forEach(button => button.addEventListener('click', () => {
        document.querySelectorAll('.segment').forEach(item => item.classList.remove('active'));
        button.classList.add('active');
        state.filter = button.dataset.filter;
        refreshSelect();
      }));
      document.getElementById('candidate-select').addEventListener('change', event => {
        state.metric = event.target.value;
        renderCandidate();
      });
      document.getElementById('candidate-search').addEventListener('input', event => {
        state.query = event.target.value;
        refreshSelect();
      });
      document.querySelectorAll('.nav-link').forEach(button => button.addEventListener('click', () => {
        document.querySelectorAll('.nav-link').forEach(item => item.classList.remove('active'));
        button.classList.add('active');
        document.getElementById(button.dataset.target).scrollIntoView({behavior:'smooth',block:'start'});
      }));
      window.addEventListener('resize', () => renderCandidate());
    }

    function init() {
      renderOverview();
      refreshSelect();
      renderRankTable('single-table', report.singleTable, 'single-search');
      renderSynergy();
      renderRegimes();
      document.getElementById('method-gate').textContent =
        `Gate：coverage ≥ ${pct(report.method.coverage)}；训练阶段主动与 Top/Worst 至少 ${report.method.positiveTrainRegimes} 为正；最差训练主动 CAGR ≥ ${pct(report.method.worstTrainActiveCagr)}；换手压力 ${report.method.costBps} bps。`;
      bindInteractions();
    }
    init();
  </script>
</body>
</html>
"""


@recorded_workflow
def main() -> None:
    args = parse_args()
    payload = build_payload()
    json_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    html = HTML_TEMPLATE.replace("__DATA__", json_text.replace("</", "<\\/"))
    for path in dict.fromkeys([args.output.resolve(), args.source_copy.resolve()]):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8", newline="\n")
        print(f"Wrote {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()

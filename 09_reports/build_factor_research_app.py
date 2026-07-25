"""Build the self-contained four-market TP factor research web app."""

from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


TP_ROOT = Path(__file__).resolve().parent.parent
RUN_ROOT = TP_ROOT / "07_backtest_code" / "runs" / "ad_hoc"
DEFAULT_OUTPUT = TP_ROOT / "09_reports" / "factor-research-app.html"


MARKETS = {
    "stoxx600": {
        "name": "STOXX Europe 600",
        "benchmark": "STOXX EUROPE 600",
        "oop": "stoxx600_leave_one_regime_out_20260723",
        "lag_old": "stoxx600_relative_variables_20260709",
        "lag6": "stoxx600_relative_lag6_20260723",
        "matrix": "stoxx600_sparse_lag_extension_20260723",
        "method": "LORO v1 + sparse robustness",
    },
    "sp500": {
        "name": "S&P 500",
        "benchmark": "SP500",
        "oop": "sp500_leave_one_period_out_20260725",
        "lag_old": "sp500_relative_variables_20260709",
        "lag6": "sp500_relative_lag6_20260725",
        "matrix": "sp500_lag6_anchor_synergy_20260725",
        "method": "signal-aware LOPO v2",
    },
    "nasdaq": {
        "name": "NASDAQ Composite",
        "benchmark": "NASDAQ COMP",
        "oop": "nasdaq_leave_one_period_out_20260725",
        "lag_old": "nasdaq_relative_variables_20260709",
        "lag6": "nasdaq_relative_lag6_20260725",
        "matrix": "nasdaq_lag6_anchor_synergy_20260725",
        "method": "signal-aware LOPO v2",
    },
    "eu-small": {
        "name": "MSCI Europe Small",
        "benchmark": "MSCI EUR SMALL",
        "oop": "eu_small_leave_one_period_out_20260725",
        "lag_old": "eu_small_relative_variables_20260709",
        "lag6": "eu_small_relative_lag6_20260725",
        "matrix": "eu_small_lag6_anchor_synergy_20260725",
        "method": "signal-aware LOPO v2",
    },
}


def read_csv(run: str, filename: str) -> pd.DataFrame:
    path = RUN_ROOT / run / filename
    return pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame()


def read_json(run: str, filename: str) -> dict[str, object]:
    path = RUN_ROOT / run / filename
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def records(frame: pd.DataFrame, columns: Sequence[str] | None = None) -> list[dict[str, object]]:
    output = frame.copy()
    if columns is not None:
        for column in columns:
            if column not in output:
                output[column] = np.nan
        output = output[list(columns)]
    output = output.replace([np.inf, -np.inf], np.nan)
    return json.loads(output.to_json(orient="records", date_format="iso"))


def normalize_lag_gate(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if "pass_gate" not in output and "passed" in output:
        output["pass_gate"] = output["passed"]
    if "label" not in output:
        output["label"] = (
            output["raw_column"].astype(str)
            + " "
            + output["transform"].astype(str)
            + " lag"
            + output["lag_observations"].astype("Int64").astype(str)
        )
    output["lag_observations"] = pd.to_numeric(
        output["lag_observations"],
        errors="coerce",
    )
    return output


def lopo_single_data(config: Mapping[str, str]) -> pd.DataFrame:
    run = config["oop"]
    filename = (
        "single_loro_selection_summary.csv"
        if config["name"] == "STOXX Europe 600"
        else "single_lopo_selection_summary.csv"
    )
    frame = read_csv(run, filename)
    return frame.rename(
        columns={
            "folds_evaluated": "eligible_holdout_folds",
            "loro_classification": "lopo_classification",
        }
    )


def lopo_period_data(
    config: Mapping[str, str],
    selected_metrics: set[str],
) -> pd.DataFrame:
    run = config["oop"]
    filename = (
        "candidate_regime_metrics.csv"
        if config["name"] == "STOXX Europe 600"
        else "candidate_period_metrics.csv"
    )
    frame = read_csv(run, filename)
    if "signal_validation_available" not in frame:
        frame["signal_validation_available"] = frame.get("available", False)
    if "regime_label_zh" not in frame:
        definitions = read_csv(run, "regime_definitions.csv")
        if "label_zh" in definitions:
            label_map = definitions.set_index("regime_id")["label_zh"]
            frame["regime_label_zh"] = frame["regime_id"].map(label_map)
        else:
            frame["regime_label_zh"] = frame["regime_id"]
    return frame[
        frame["metric"].astype(str).isin(selected_metrics)
        & frame["candidate_class"].isin(["raw", "relative"])
    ]


def official_combination_data(config: Mapping[str, str]) -> pd.DataFrame:
    run = config["matrix"]
    if config["name"] == "STOXX Europe 600":
        gate = read_csv(run, "architecture_gate_results.csv")
        loro = read_csv(run, "architecture_loro_summary.csv")
        output = gate.merge(loro, on="metric", how="left", suffixes=("", "_loro"))
        output["classification"] = np.where(
            output["pass_gate"].fillna(False),
            "architecture_pass",
            "architecture_fail",
        )
        return output
    pairs = read_csv(run, "pair_synergy_results.csv")
    subsets = read_csv(run, "family_subset_results.csv")
    return pd.concat([pairs, subsets], ignore_index=True)


def strict_synergy_data(config: Mapping[str, str]) -> pd.DataFrame:
    run = config["oop"]
    frame = read_csv(run, "synergy_loro_summary.csv")
    if frame.empty:
        frame = read_csv(run, "synergy_lopo_summary.csv")
    return frame.rename(
        columns={
            "loro_synergy_classification": "classification",
            "eligible_folds": "eligible_lopo_folds",
            "holdout_synergy_confirmed_folds": "confirmed_synergy_folds",
            "holdout_synergy_confirmation_rate": "confirmed_synergy_rate",
        }
    )


def dsr_data(config: Mapping[str, str]) -> pd.DataFrame:
    if config["name"] == "STOXX Europe 600":
        frame = read_csv(config["matrix"], "architecture_deflated_sharpe.csv")
        return frame.rename(
            columns={
                "annualized_sharpe": "annualized_active_sharpe",
                "trial_count": "documented_trial_count",
                "deflated_sharpe_probability": "dsr_probability",
            }
        ).assign(
            label=lambda item: item["metric"],
            candidate_class="architecture",
        )
    return read_csv(config["oop"], "deflated_sharpe_results.csv")


def audit_data(config: Mapping[str, str]) -> pd.DataFrame:
    frame = read_csv(config["oop"], "regime_definitions.csv")
    if frame.empty:
        return frame
    frame = frame.rename(
        columns={
            "market_signal_validation_available": "signal_available",
        }
    )
    if "market_snapshot_count" not in frame:
        monthly = read_csv(config["lag6"], "benchmark_monthly_audit.csv")
        dates = pd.to_datetime(monthly.get("Date"), errors="coerce")
        frame["market_snapshot_count"] = [
            int(
                (
                    dates.ge(pd.Timestamp(row.start))
                    & dates.le(pd.Timestamp(row.end))
                ).sum()
            )
            for row in frame.itertuples(index=False)
        ]
    if "minimum_snapshots_for_period_validation" not in frame:
        frame["minimum_snapshots_for_period_validation"] = 2
    if "signal_available" not in frame:
        frame["signal_available"] = frame["market_snapshot_count"].ge(2)
    return frame


def market_payload(key: str, config: Mapping[str, str]) -> dict[str, object]:
    singles = lopo_single_data(config)
    singles = singles.sort_values(
        [
            "lopo_classification",
            "train_gate_passes",
            "mean_holdout_active_cagr",
        ],
        ascending=[True, False, False],
    )
    selected = set(singles.head(60)["metric"].astype(str))
    periods = lopo_period_data(config, selected)
    lag = pd.concat(
        [
            normalize_lag_gate(
                read_csv(config["lag_old"], "relative_validation_gate.csv")
            ),
            normalize_lag_gate(
                read_csv(config["lag6"], "relative_validation_gate.csv")
            ),
        ],
        ignore_index=True,
    ).drop_duplicates("metric", keep="last")
    official = official_combination_data(config).sort_values(
        "robust_score",
        ascending=False,
        na_position="last",
    )
    strict = strict_synergy_data(config)
    strict_sort = (
        "confirmed_synergy_rate"
        if "confirmed_synergy_rate" in strict
        else strict.columns[0] if len(strict.columns) else ""
    )
    if strict_sort:
        strict = strict.sort_values(strict_sort, ascending=False, na_position="last")
    dsr = dsr_data(config).sort_values(
        "dsr_probability",
        ascending=False,
        na_position="last",
    )
    audit = audit_data(config)
    manifest = read_json(config["oop"], "manifest.json")
    lag6_manifest = read_json(config["lag6"], "manifest.json")
    matrix_manifest = read_json(config["matrix"], "manifest.json")
    core = singles[
        singles["lopo_classification"].isin(
            ["cross_regime_core", "cross_regime_resilient"]
        )
    ]
    signal_periods = (
        int(audit["signal_available"].fillna(False).sum())
        if "signal_available" in audit
        else int(manifest.get("signal_validation_period_count", len(audit)))
    )
    return {
        "key": key,
        "name": config["name"],
        "benchmark": config["benchmark"],
        "method": config["method"],
        "summary": {
            "documentedCandidates": int(
                manifest.get("candidate_count", len(singles))
            ),
            "signalPeriods": signal_periods,
            "totalPeriods": len(audit),
            "crossRegimeSingles": len(core),
            "lag6Passed": int(
                lag6_manifest.get(
                    "gate_pass_count",
                    lag["lag_observations"].eq(6)
                    & lag["pass_gate"].fillna(False),
                )
                if isinstance(
                    lag6_manifest.get("gate_pass_count", 0),
                    (int, float),
                )
                else 0
            ),
            "matrixCandidates": int(
                matrix_manifest.get(
                    "combination_candidate_count",
                    matrix_manifest.get("candidate_count", len(official)),
                )
            ),
            "strictSynergy": int(
                manifest.get(
                    "cross_period_synergy_supported_count",
                    0,
                )
            ),
            "engine": str(
                lag6_manifest.get("engine_id", "historical official")
            )
            + " "
            + str(lag6_manifest.get("engine_version", "")),
        },
        "singles": records(
            singles.head(350),
            [
                "metric",
                "label",
                "candidate_class",
                "family",
                "eligible_holdout_folds",
                "train_gate_passes",
                "holdout_joint_positive_rate",
                "mean_holdout_active_cagr",
                "min_holdout_active_cagr",
                "mean_holdout_top_worst_cagr",
                "lopo_classification",
            ],
        ),
        "lags": records(
            lag,
            [
                "metric",
                "raw_column",
                "transform",
                "lag_observations",
                "coverage",
                "ratio_cagr",
                "top_worst_ratio_return",
                "robust_score",
                "pass_gate",
                "fail_reasons",
            ],
        ),
        "periods": records(
            periods,
            [
                "metric",
                "label",
                "candidate_class",
                "regime_id",
                "regime_label_zh",
                "active_cagr",
                "top_worst_cagr",
                "portfolio_formation_count",
                "signal_validation_available",
            ],
        ),
        "officialCombinations": records(
            official.head(180),
            [
                "metric",
                "label",
                "candidate_type",
                "ratio_cagr",
                "top_worst_ratio_return",
                "robust_score",
                "robust_uplift_vs_best_component",
                "classification",
                "pass_gate",
                "holdout_joint_positive_rate",
                "mean_holdout_active_cagr",
                "min_holdout_active_cagr",
            ],
        ),
        "strictSynergy": records(strict.head(150)),
        "dsr": records(
            dsr.head(120),
            [
                "metric",
                "label",
                "candidate_class",
                "annualized_active_sharpe",
                "documented_trial_count",
                "expected_max_null_annualized_sharpe",
                "dsr_probability",
            ],
        ),
        "audit": records(
            audit,
            [
                "regime_id",
                "label_zh",
                "start",
                "end",
                "market_snapshot_count",
                "minimum_snapshots_for_period_validation",
                "signal_available",
            ],
        ),
    }


def format_pct(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number * 100:.2f}%"


def static_fallback(payload: Mapping[str, object]) -> str:
    rows = payload["singles"][:12]
    body = "".join(
        "<tr>"
        f"<td>{escape(str(row.get('label', '')))}</td>"
        f"<td>{escape(str(row.get('candidate_class', '')))}</td>"
        f"<td>{escape(str(row.get('lopo_classification', '')))}</td>"
        f"<td>{format_pct(row.get('mean_holdout_active_cagr'))}</td>"
        f"<td>{format_pct(row.get('min_holdout_active_cagr'))}</td>"
        "</tr>"
        for row in rows
    )
    return (
        '<section class="static-fallback">'
        "<h2>STOXX Europe 600 跨时期单变量证据</h2>"
        "<p>交互层尚未加载时保留的静态证据。变量名使用原始字段名。</p>"
        "<div class=\"table-wrap\"><table><thead><tr>"
        "<th>Raw variable</th><th>Class</th><th>LOPO class</th>"
        "<th>Mean holdout active CAGR</th><th>Worst holdout active CAGR</th>"
        f"</tr></thead><tbody>{body}</tbody></table></div></section>"
    )


CSS = r"""
:root {
  color-scheme: light;
  --ink: #173143;
  --muted: #637480;
  --line: #d7dfe4;
  --soft: #f4f7f8;
  --paper: #ffffff;
  --green: #16836f;
  --green-soft: #e7f5f1;
  --red: #b84f5e;
  --red-soft: #faecee;
  --blue: #315f8c;
  --yellow: #d7a923;
  --radius: 6px;
}
* { box-sizing: border-box; }
html { background: var(--soft); }
body {
  margin: 0;
  color: var(--ink);
  background: var(--soft);
  font-family: Inter, "Segoe UI", Arial, sans-serif;
  font-size: 14px;
  letter-spacing: 0;
}
button, input, select { font: inherit; letter-spacing: 0; }
button { cursor: pointer; }
.app-shell { min-height: 100vh; }
.topbar {
  background: var(--paper);
  border-bottom: 1px solid var(--line);
}
.topbar-inner, .workspace { width: min(1540px, 100%); margin: 0 auto; min-width: 0; }
.topbar-inner { padding: 18px 24px 0; }
.title-row { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; }
h1 { margin: 0; font-size: 26px; line-height: 1.15; font-weight: 720; }
.subtitle { margin: 6px 0 14px; color: var(--muted); }
.status {
  display: inline-flex; align-items: center; gap: 7px; white-space: nowrap;
  color: var(--green); font-size: 12px; font-weight: 650;
}
.status::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--green); }
.market-tabs, .view-tabs { display: flex; overflow-x: auto; scrollbar-width: thin; }
.market-tab, .view-tab {
  border: 0; background: transparent; color: var(--muted); white-space: nowrap;
  border-bottom: 3px solid transparent; font-weight: 650;
}
.market-tab { padding: 12px 17px 11px; }
.market-tab:first-child { padding-left: 0; }
.market-tab.active { color: var(--ink); border-bottom-color: var(--green); }
.workspace { padding: 18px 24px 42px; }
.market-heading { display: flex; justify-content: space-between; gap: 20px; align-items: baseline; }
.market-heading h2 { margin: 0; font-size: 20px; }
.market-heading p { margin: 0; color: var(--muted); font-size: 12px; }
.metrics {
  display: grid; grid-template-columns: repeat(6, minmax(130px, 1fr));
  gap: 1px; margin: 14px 0 18px; border: 1px solid var(--line);
  background: var(--line); border-radius: var(--radius); overflow: hidden;
}
.metric { min-height: 78px; padding: 13px 14px; background: var(--paper); }
.metric-label { color: var(--muted); font-size: 11px; text-transform: uppercase; }
.metric-value { margin-top: 7px; font-size: 22px; font-weight: 720; }
.metric-value small { font-size: 12px; color: var(--muted); font-weight: 500; }
.view-tabs {
  gap: 4px; padding: 0 0 10px; border-bottom: 1px solid var(--line);
}
.view-tab {
  padding: 8px 12px; border: 1px solid transparent; border-radius: var(--radius);
}
.view-tab.active { color: var(--ink); background: var(--paper); border-color: var(--line); }
.panel { display: none; padding-top: 18px; min-width: 0; }
.panel.active { display: block; }
.section-head {
  display: flex; justify-content: space-between; align-items: flex-end;
  gap: 16px; margin-bottom: 11px;
}
.section-head h3 { margin: 0; font-size: 16px; }
.section-head p { margin: 4px 0 0; color: var(--muted); font-size: 12px; max-width: 820px; }
.controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
input[type="search"], select {
  min-height: 34px; border: 1px solid #bec9cf; border-radius: var(--radius);
  background: var(--paper); color: var(--ink); padding: 6px 10px;
}
input[type="search"] { width: min(330px, 70vw); }
.segmented { display: inline-flex; border: 1px solid #bec9cf; border-radius: var(--radius); overflow: hidden; }
.segmented button { min-height: 32px; border: 0; border-right: 1px solid #bec9cf; background: var(--paper); padding: 5px 10px; color: var(--muted); }
.segmented button:last-child { border-right: 0; }
.segmented button.active { background: var(--ink); color: white; }
.table-wrap {
  width: 100%; overflow: auto; border: 1px solid var(--line);
  border-radius: var(--radius); background: var(--paper);
}
table { width: 100%; border-collapse: collapse; min-width: 900px; }
th {
  position: sticky; top: 0; z-index: 1; text-align: left; padding: 9px 10px;
  background: #edf2f4; color: #526671; font-size: 11px; white-space: nowrap;
  border-bottom: 1px solid var(--line);
}
td { padding: 9px 10px; border-bottom: 1px solid #e8edef; white-space: nowrap; }
tbody tr:hover { background: #f8fbfb; }
tbody tr:last-child td { border-bottom: 0; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.badge {
  display: inline-block; padding: 3px 6px; border-radius: 4px;
  font-size: 11px; font-weight: 650; background: #e9eef1; color: #4e626d;
}
.badge.good { color: #096a58; background: var(--green-soft); }
.badge.bad { color: #983846; background: var(--red-soft); }
.badge.warn { color: #765b06; background: #fbf3d9; }
.chart-band {
  background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 14px; margin-bottom: 12px;
}
.term-chart { width: 100%; height: 310px; display: block; overflow: visible; }
.chart-grid { stroke: #dde5e8; stroke-width: 1; }
.chart-zero { stroke: #8798a1; stroke-dasharray: 4 4; }
.chart-line { fill: none; stroke: var(--green); stroke-width: 3; }
.chart-point { fill: var(--paper); stroke: var(--green); stroke-width: 3; }
.chart-label { fill: var(--muted); font-size: 11px; }
.chart-value { fill: var(--ink); font-size: 11px; font-weight: 650; }
.heatmap-wrap { overflow: auto; border: 1px solid var(--line); border-radius: var(--radius); background: var(--paper); }
.heatmap { display: grid; min-width: 1050px; }
.heat-cell {
  min-height: 36px; padding: 8px; border-right: 1px solid white;
  border-bottom: 1px solid white; font-size: 11px; font-variant-numeric: tabular-nums;
}
.heat-label { background: #edf2f4; font-weight: 600; color: var(--ink); }
.heat-head { background: #e4ebee; font-weight: 650; color: #50636d; }
.evidence-note {
  border-left: 3px solid var(--yellow); background: #fffdf4;
  padding: 10px 12px; margin: 0 0 14px; color: #5f5a42;
}
.audit-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 18px; }
.audit-grid > div { min-width: 0; }
.static-fallback { padding: 18px 0; }
.js-ready .static-fallback { display: none; }
.empty { padding: 28px; color: var(--muted); text-align: center; background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius); }
@media (max-width: 1050px) {
  .metrics { grid-template-columns: repeat(3, 1fr); }
  .audit-grid { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .topbar-inner, .workspace { padding-left: 14px; padding-right: 14px; }
  h1 { font-size: 22px; }
  .title-row, .market-heading, .section-head { align-items: flex-start; flex-direction: column; }
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metric { min-height: 72px; }
  .metric-value { font-size: 19px; }
  .term-chart { height: 250px; }
}
"""


JS = r"""
const state = { market: "stoxx600", view: "singles", search: "", singleClass: "all", lagTransform: "directional_delta" };
const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
const pct = value => value === null || value === undefined || Number.isNaN(Number(value)) ? "—" : `${(Number(value)*100).toFixed(2)}%`;
const num = (value, digits=2) => value === null || value === undefined || Number.isNaN(Number(value)) ? "—" : Number(value).toFixed(digits);
const bool = value => value === true || value === "True" || value === "true" || value === 1;
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const classOrder = {cross_regime_core:0, cross_regime_resilient:1, regime_sensitive:2, weak_or_unstable:3};
function badge(value) {
  const text = String(value ?? "—");
  const kind = /core|resilient|synergistic|pass|additive/.test(text) ? "good" : /harmful|fail|weak/.test(text) ? "bad" : "warn";
  return `<span class="badge ${kind}">${esc(text)}</span>`;
}
function table(headers, rows) {
  if (!rows.length) return `<div class="empty">当前筛选没有可用证据</div>`;
  return `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th class="${h.num?"num":""}">${esc(h.label)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${headers.map(h=>`<td class="${h.num?"num":""}">${h.render ? h.render(row[h.key],row) : esc(row[h.key] ?? "—")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function renderShell() {
  const market = DATA[state.market];
  $("#market-title").textContent = market.name;
  $("#market-meta").textContent = `${market.benchmark} · ${market.method}`;
  const s = market.summary;
  const values = [
    ["Documented trials", s.documentedCandidates],
    ["Signal periods", `${s.signalPeriods}/${s.totalPeriods}`],
    ["Core / resilient singles", s.crossRegimeSingles],
    ["Lag6 passed", s.lag6Passed],
    ["Combination matrix", s.matrixCandidates],
    ["Strict synergy", s.strictSynergy],
  ];
  $("#metrics").innerHTML = values.map(([label,value])=>`<div class="metric"><div class="metric-label">${esc(label)}</div><div class="metric-value">${esc(value)}</div></div>`).join("");
  $$(".market-tab").forEach(button=>button.classList.toggle("active",button.dataset.market===state.market));
  $$(".view-tab").forEach(button=>button.classList.toggle("active",button.dataset.view===state.view));
  $$(".panel").forEach(panel=>panel.classList.toggle("active",panel.id===`panel-${state.view}`));
  renderCurrent();
}
function renderCurrent() {
  ({singles:renderSingles,lags:renderLags,regimes:renderRegimes,synergy:renderSynergy,audit:renderAudit}[state.view])();
}
function renderSingles() {
  const market=DATA[state.market];
  const filtered=market.singles.filter(row=>(state.singleClass==="all"||row.candidate_class===state.singleClass)&&String(row.label).toLowerCase().includes(state.search.toLowerCase())).sort((a,b)=>(classOrder[a.lopo_classification]??9)-(classOrder[b.lopo_classification]??9)||(b.train_gate_passes??0)-(a.train_gate_passes??0)||(b.mean_holdout_active_cagr??-99)-(a.mean_holdout_active_cagr??-99));
  $("#single-table").innerHTML=table([
    {key:"label",label:"Raw variable"},
    {key:"candidate_class",label:"Evidence type"},
    {key:"lopo_classification",label:"LOPO class",render:badge},
    {key:"train_gate_passes",label:"Train gate folds",num:true},
    {key:"holdout_joint_positive_rate",label:"Joint positive",num:true,render:pct},
    {key:"mean_holdout_active_cagr",label:"Mean holdout active CAGR",num:true,render:pct},
    {key:"min_holdout_active_cagr",label:"Worst holdout active CAGR",num:true,render:pct},
    {key:"mean_holdout_top_worst_cagr",label:"Mean Top/Worst CAGR",num:true,render:pct},
  ],filtered);
  $("#single-count").textContent=`${filtered.length} variables`;
}
function lineChart(rows, field) {
  if (!rows.length) return `<div class="empty">该变量与 transform 没有 lag 证据</div>`;
  const width=980,height=300,pad={l:62,r:35,t:30,b:45};
  const lags=[1,3,6,12],points=lags.map(lag=>rows.find(row=>Number(row.lag_observations)===lag)).filter(Boolean);
  const values=points.map(row=>Number(row[field])).filter(Number.isFinite);
  if (!values.length) return `<div class="empty">没有数值证据</div>`;
  let min=Math.min(0,...values),max=Math.max(0,...values); if(max===min){max+=.01;min-=.01}
  const x=lag=>pad.l+(lags.indexOf(lag)/(lags.length-1))*(width-pad.l-pad.r);
  const y=value=>pad.t+(max-value)/(max-min)*(height-pad.t-pad.b);
  const ticks=5;
  const grid=Array.from({length:ticks},(_,i)=>{const value=min+(max-min)*i/(ticks-1);return `<line class="chart-grid" x1="${pad.l}" x2="${width-pad.r}" y1="${y(value)}" y2="${y(value)}"/><text class="chart-label" x="${pad.l-9}" y="${y(value)+4}" text-anchor="end">${(value*100).toFixed(1)}%</text>`}).join("");
  const path=points.map((row,i)=>`${i?"L":"M"} ${x(Number(row.lag_observations))} ${y(Number(row[field]))}`).join(" ");
  const marks=points.map(row=>`<circle class="chart-point" cx="${x(Number(row.lag_observations))}" cy="${y(Number(row[field]))}" r="5"/><text class="chart-value" x="${x(Number(row.lag_observations))}" y="${y(Number(row[field]))-12}" text-anchor="middle">${pct(row[field])}</text>`).join("");
  const labels=lags.map(lag=>`<text class="chart-label" x="${x(lag)}" y="${height-14}" text-anchor="middle">lag${lag}</text>`).join("");
  return `<svg class="term-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Lag term structure">${grid}<line class="chart-zero" x1="${pad.l}" x2="${width-pad.r}" y1="${y(0)}" y2="${y(0)}"/><path class="chart-line" d="${path}"/>${marks}${labels}</svg>`;
}
function renderLags() {
  const market=DATA[state.market];
  const variables=[...new Set(market.lags.map(row=>row.raw_column).filter(Boolean))].sort();
  const select=$("#lag-variable");
  const prior=select.value;
  select.innerHTML=variables.map(value=>`<option value="${esc(value)}">${esc(value)}</option>`).join("");
  select.value=variables.includes(prior)?prior:variables[0]??"";
  const rows=market.lags.filter(row=>row.raw_column===select.value&&row.transform===state.lagTransform).sort((a,b)=>a.lag_observations-b.lag_observations);
  $("#term-chart").innerHTML=lineChart(rows,"ratio_cagr");
  $("#lag-table").innerHTML=table([
    {key:"lag_observations",label:"Lag",num:true,render:v=>`lag${esc(v)}`},
    {key:"coverage",label:"Coverage",num:true,render:pct},
    {key:"ratio_cagr",label:"Top/Benchmark ratio CAGR",num:true,render:pct},
    {key:"top_worst_ratio_return",label:"Top/Worst ratio return",num:true,render:pct},
    {key:"robust_score",label:"Robust score",num:true,render:v=>num(v,3)},
    {key:"pass_gate",label:"Official gate",render:v=>badge(bool(v)?"pass":"fail")},
    {key:"fail_reasons",label:"Fail reasons"},
  ],rows);
  $$("#lag-transform button").forEach(button=>button.classList.toggle("active",button.dataset.transform===state.lagTransform));
}
function heatColor(value) {
  if (value===null||value===undefined||Number.isNaN(Number(value))) return "#edf1f2";
  const v=Math.max(-.10,Math.min(.10,Number(value)))/.10;
  if(v>=0){const a=.12+.72*v;return `rgba(22,131,111,${a})`}
  const a=.12+.72*Math.abs(v);return `rgba(184,79,94,${a})`;
}
function renderRegimes() {
  const market=DATA[state.market];
  const topMetrics=market.singles.slice(0,24);
  const periodLabels=[...new Map(market.periods.map(row=>[row.regime_id,row.regime_label_zh])).entries()];
  const cols=periodLabels.length+1;
  let cells=`<div class="heat-cell heat-head">Raw variable</div>${periodLabels.map(([,label])=>`<div class="heat-cell heat-head">${esc(label)}</div>`).join("")}`;
  topMetrics.forEach(metric=>{
    cells+=`<div class="heat-cell heat-label">${esc(metric.label)}</div>`;
    periodLabels.forEach(([id])=>{
      const row=market.periods.find(item=>item.metric===metric.metric&&item.regime_id===id);
      const available=row&&bool(row.signal_validation_available);
      const value=available?row.active_cagr:null;
      cells+=`<div class="heat-cell" style="background:${heatColor(value)};color:${value!==null&&Math.abs(Number(value))>.055?"white":"#173143"}" title="${available?`${metric.label}: ${pct(value)}`:"No signal validation"}">${available?pct(value):"N/A"}</div>`;
    });
  });
  $("#period-heatmap").innerHTML=`<div class="heatmap" style="grid-template-columns:minmax(250px,1.8fr) repeat(${periodLabels.length},minmax(125px,1fr))">${cells}</div>`;
  const winners=[];
  periodLabels.forEach(([id,label])=>{
    market.periods.filter(row=>row.regime_id===id&&bool(row.signal_validation_available)).sort((a,b)=>(b.active_cagr??-99)-(a.active_cagr??-99)).slice(0,5).forEach(row=>winners.push({...row,regime_label_zh:label}));
  });
  $("#winner-table").innerHTML=table([
    {key:"regime_label_zh",label:"Period"},
    {key:"label",label:"Raw variable"},
    {key:"candidate_class",label:"Type"},
    {key:"active_cagr",label:"Active CAGR",num:true,render:pct},
    {key:"top_worst_cagr",label:"Top/Worst CAGR",num:true,render:pct},
    {key:"portfolio_formation_count",label:"Formations",num:true},
  ],winners);
}
function renderSynergy() {
  const market=DATA[state.market];
  const official=market.officialCombinations.slice().sort((a,b)=>(b.robust_uplift_vs_best_component??b.robust_score??-99)-(a.robust_uplift_vs_best_component??a.robust_score??-99));
  $("#official-combo-table").innerHTML=table([
    {key:"label",label:"Architecture / variables"},
    {key:"candidate_type",label:"Test"},
    {key:"classification",label:"Official class",render:badge},
    {key:"ratio_cagr",label:"Ratio CAGR",num:true,render:pct},
    {key:"top_worst_ratio_return",label:"Top/Worst return",num:true,render:pct},
    {key:"robust_score",label:"Robust",num:true,render:v=>num(v,3)},
    {key:"robust_uplift_vs_best_component",label:"Uplift vs best leg",num:true,render:v=>num(v,3)},
  ],official);
  const strict=market.strictSynergy;
  $("#strict-synergy-table").innerHTML=table([
    {key:"label",label:"Variables / architecture"},
    {key:"candidate_type",label:"Test"},
    {key:"classification",label:"LOPO class",render:badge},
    {key:"eligible_lopo_folds",label:"Eligible folds",num:true},
    {key:"confirmed_synergy_folds",label:"Confirmed folds",num:true},
    {key:"confirmed_synergy_rate",label:"Confirmation rate",num:true,render:pct},
    {key:"mean_holdout_active_uplift",label:"Holdout active uplift",num:true,render:pct},
  ],strict);
}
function renderAudit() {
  const market=DATA[state.market];
  $("#audit-table").innerHTML=table([
    {key:"label_zh",label:"Period"},
    {key:"start",label:"Start"},
    {key:"end",label:"End"},
    {key:"market_snapshot_count",label:"Benchmark snapshots",num:true},
    {key:"minimum_snapshots_for_period_validation",label:"Minimum required",num:true},
    {key:"signal_available",label:"Signal validation",render:v=>badge(bool(v)?"available":"blocked")},
  ],market.audit);
  $("#dsr-table").innerHTML=table([
    {key:"label",label:"Candidate"},
    {key:"candidate_class",label:"Class"},
    {key:"annualized_active_sharpe",label:"Active Sharpe",num:true,render:v=>num(v,2)},
    {key:"documented_trial_count",label:"Trial count",num:true},
    {key:"expected_max_null_annualized_sharpe",label:"Expected null max",num:true,render:v=>num(v,2)},
    {key:"dsr_probability",label:"DSR probability",num:true,render:pct},
  ],market.dsr);
}
document.addEventListener("DOMContentLoaded",()=>{
  document.body.classList.add("js-ready");
  $$(".market-tab").forEach(button=>button.addEventListener("click",()=>{state.market=button.dataset.market;renderShell()}));
  $$(".view-tab").forEach(button=>button.addEventListener("click",()=>{state.view=button.dataset.view;renderShell()}));
  $("#single-search").addEventListener("input",event=>{state.search=event.target.value;renderSingles()});
  $("#single-class").addEventListener("change",event=>{state.singleClass=event.target.value;renderSingles()});
  $("#lag-variable").addEventListener("change",renderLags);
  $$("#lag-transform button").forEach(button=>button.addEventListener("click",()=>{state.lagTransform=button.dataset.transform;renderLags()}));
  renderShell();
});
"""


def build_html(data: Mapping[str, object]) -> str:
    tabs = "".join(
        f'<button class="market-tab{" active" if key == "stoxx600" else ""}" '
        f'data-market="{escape(key)}">{escape(config["name"])}</button>'
        for key, config in MARKETS.items()
    )
    embedded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace(
        "</script>",
        "<\\/script>",
    )
    fallback = static_fallback(data["stoxx600"])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TP 四市场因子研究</title>
  <style>{CSS}</style>
</head>
<body>
<div class="app-shell">
  <header class="topbar">
    <div class="topbar-inner">
      <div class="title-row">
        <div>
          <h1>TP Factor Research</h1>
          <p class="subtitle">Raw variables · lag1/3/6/12 · historical out-of-period · pair/subset/leave-one-out</p>
        </div>
        <div class="status">Official evidence loaded</div>
      </div>
      <nav class="market-tabs" aria-label="Market">{tabs}</nav>
    </div>
  </header>
  <main class="workspace">
    <div class="market-heading">
      <h2 id="market-title">STOXX Europe 600</h2>
      <p id="market-meta">STOXX EUROPE 600 · LORO v1 + sparse robustness</p>
    </div>
    <section class="metrics" id="metrics"></section>
    <nav class="view-tabs" aria-label="Evidence view">
      <button class="view-tab active" data-view="singles">Single variables</button>
      <button class="view-tab" data-view="lags">Lag term structure</button>
      <button class="view-tab" data-view="regimes">Regime rotation</button>
      <button class="view-tab" data-view="synergy">Combination &amp; LOO</button>
      <button class="view-tab" data-view="audit">Overfit &amp; audit</button>
    </nav>
    {fallback}
    <section class="panel active" id="panel-singles">
      <div class="section-head">
        <div><h3>Cross-period single-variable evidence</h3><p>Holdout period is excluded from training gate and rank. Original variable names are preserved.</p></div>
        <div class="controls">
          <input id="single-search" type="search" placeholder="Search raw variable" aria-label="Search raw variable">
          <select id="single-class" aria-label="Evidence type"><option value="all">All evidence</option><option value="raw">Raw level</option><option value="relative">Relative variants</option></select>
          <span id="single-count"></span>
        </div>
      </div>
      <div id="single-table"></div>
    </section>
    <section class="panel" id="panel-lags">
      <div class="section-head">
        <div><h3>Same-security lag term structure</h3><p>Every point is an independently tested official Top/Worst raw variable. Different lags are alternatives, not stacked components.</p></div>
        <div class="controls">
          <select id="lag-variable" aria-label="Raw variable"></select>
          <div class="segmented" id="lag-transform">
            <button class="active" data-transform="directional_delta">Directional delta</button>
            <button data-transform="score_delta">Score delta</button>
          </div>
        </div>
      </div>
      <div class="chart-band" id="term-chart"></div>
      <div id="lag-table"></div>
    </section>
    <section class="panel" id="panel-regimes">
      <div class="evidence-note">Period winners are descriptive rotation evidence. They are not selected with information available before that same holdout.</div>
      <div class="section-head"><div><h3>Single-variable period map</h3><p>N/A means there were not enough real benchmark snapshots and portfolio formations to validate the signal.</p></div></div>
      <div class="heatmap-wrap" id="period-heatmap"></div>
      <div class="section-head" style="margin-top:18px"><div><h3>Special period leaders</h3></div></div>
      <div id="winner-table"></div>
    </section>
    <section class="panel" id="panel-synergy">
      <div class="evidence-note">A combination is called synergy only when its official pair/subset evidence beats the stronger leg and leave-one-out or historical holdout evidence confirms the contribution.</div>
      <div class="section-head"><div><h3>Official pair / subset evidence</h3><p>Includes every passed lag6 variable crossed with every non-empty subset of independently passed EPS Revision Ratio, PMOM 12M1M, and EPS Growth FY1 anchors.</p></div></div>
      <div id="official-combo-table"></div>
      <div class="section-head" style="margin-top:18px"><div><h3>Strict historical holdout synergy</h3><p>Weak, additive, redundant, and harmful evidence remains visible.</p></div></div>
      <div id="strict-synergy-table"></div>
    </section>
    <section class="panel" id="panel-audit">
      <div class="audit-grid">
        <div><div class="section-head"><div><h3>Signal-data availability</h3><p>NAV continuity alone is not factor validation.</p></div></div><div id="audit-table"></div></div>
        <div><div class="section-head"><div><h3>Deflated Sharpe</h3><p>Trial-count penalty uses all documented candidates recoverable for the market.</p></div></div><div id="dsr-table"></div></div>
      </div>
    </section>
  </main>
</div>
<noscript><style>.panel,.metrics,.view-tabs{{display:none}}</style></noscript>
<script>const DATA={embedded};</script>
<script>{JS}</script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = {key: market_payload(key, config) for key, config in MARKETS.items()}
    html = build_html(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    manifest = {
        "status": "complete",
        "output": str(args.output.resolve()),
        "markets": list(data),
        "bytes": args.output.stat().st_size,
        "embedded_data": True,
        "external_runtime_dependencies": False,
        "javascript_disabled_fallback": True,
        "variable_name_policy": "original_source_names",
    }
    (args.output.parent / "factor-research-app-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

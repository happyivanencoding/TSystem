"""Build a self-contained HTML report from the latest factor recommendation outputs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
TP_DIR = PROJECT_DIR.parent
OUTPUT_DIR = PROJECT_DIR / "outputs"
RUN_DIR = (
    TP_DIR
    / "artifacts"
    / "research"
    / "runs"
    / "monthly-factor-recommendation-v1"
    / "20260804T141711Z-e7a212e5"
)
RESULTS_DIR = RUN_DIR / "results"
REPORT_PATH = PROJECT_DIR / "factor_recommendation_report.html"


FACTOR_ORDER = [
    "value",
    "quality",
    "growth",
    "momentum",
    "lowvol",
    "size",
    "small_size",
    "dividend",
]
REGION_ORDER = ["US", "EU", "ASIA", "JAPAN", "GLOBAL"]
REGION_LABELS = {
    "US": "美国",
    "EU": "欧洲",
    "ASIA": "亚洲研究组合",
    "JAPAN": "日本",
    "GLOBAL": "全球",
}

FACTOR_DESCRIPTION_ZH = {
    "value": "价值综合因子：衡量股票相对估值与价值暴露；分数越高，代表组合中价值暴露越强。",
    "quality": "质量综合因子：衡量企业质量特征的综合强弱；分数越高，代表质量暴露越强。",
    "growth": "成长综合因子：衡量企业成长特征的综合强弱；分数越高，代表成长暴露越强。",
    "momentum": "动量综合因子：衡量价格/收益动量特征的综合强弱；分数越高，代表动量暴露越强。",
    "lowvol": "低波综合因子：衡量低波动特征的综合强弱；分数越高，代表低波动暴露越强。",
    "size": "大盘规模因子：衡量市值规模暴露；分数越高，代表大盘股暴露越强，不等同于小盘暴露。",
    "small_size": "小盘规模因子：大盘规模因子的显式反向分数；配置中按 score = 10 - large-size score 计算。",
    "dividend": "股息综合因子：衡量股息/分红特征的综合强弱；分数越高，代表股息暴露越强。",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def clean(value: Any) -> Any:
    """Convert pandas/numpy values into strict JSON values."""
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and pd.isna(value):
            return None
        return value
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if hasattr(value, "item"):
        return clean(value.item())
    missing = pd.isna(value)
    if isinstance(missing, bool) and missing:
        return None
    return str(value)


def csv_records(path: Path) -> list[dict[str, Any]]:
    frame = pd.read_csv(path)
    return [{str(key): clean(value) for key, value in row.items()} for row in frame.to_dict("records")]


def round_number(value: Any, digits: int = 2) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def make_latest_rows(panel: pd.DataFrame) -> list[dict[str, Any]]:
    latest_date = pd.to_datetime(panel["Date"]).max()
    latest = panel[pd.to_datetime(panel["Date"]) == latest_date].copy()
    latest["region_sort"] = latest["region"].map({region: index for index, region in enumerate(REGION_ORDER)}).fillna(99)
    latest["factor_sort"] = latest["factor"].map({factor: index for index, factor in enumerate(FACTOR_ORDER)}).fillna(99)
    latest = latest.sort_values(["region_sort", "factor_sort"])

    records: list[dict[str, Any]] = []
    for row in latest.to_dict("records"):
        records.append(
            {
                "region": row["region"],
                "factor": row["factor"],
                "label": row["factor_label"],
                "score": round_number(row["score_0_100"], 2),
                "recommendation": row["recommendation"],
                "covered": clean(row["covered"]),
                "universe": clean(row["universe"]),
                "factor_coverage": round_number(row["factor_coverage"], 4),
                "weight_coverage": round_number(row["weight_coverage"], 4),
                "coverage": round_number(row["coverage"], 4),
                "benchmark": row["benchmark"],
                "currency": row["currency_basis"],
                "production_eligible": bool(row["production_eligible"]),
                "benchmark_approved": bool(row["benchmark_approved"]),
                "approval_status": row["approval_status"],
                "research_only": bool(row["research_only"]),
                "confidence": round_number(row["confidence"], 4),
            }
        )
    return records


def make_history_series(history: pd.DataFrame) -> dict[str, dict[str, Any]]:
    frame = history.copy()
    frame["date_text"] = pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d")
    series: dict[str, dict[str, Any]] = {}
    for (region, factor), group in frame.groupby(["region", "factor"], sort=False):
        group = group.sort_values("Date")
        label = str(group["factor_label"].iloc[-1])
        points = [
            [row["date_text"], round_number(row["score_0_100"], 2)]
            for row in group.to_dict("records")
            if row["score_0_100"] is not None and not pd.isna(row["score_0_100"])
        ]
        series[f"{region}|{factor}"] = {
            "region": region,
            "factor": factor,
            "label": label,
            "points": points,
        }
    return series


def make_region_info(summary: dict[str, Any], latest_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    definitions = summary.get("benchmark_definition", {}).get("regions", {})
    info: dict[str, dict[str, Any]] = {}
    for region in REGION_ORDER:
        row_group = [row for row in latest_rows if row["region"] == region]
        first = row_group[0] if row_group else {}
        definition = definitions.get(region, {})
        info[region] = {
            "label": REGION_LABELS.get(region, region),
            "benchmark": first.get("benchmark") or ", ".join(definition.get("components", [])),
            "currency": first.get("currency") or definition.get("currency_basis"),
            "benchmark_approved": bool(first.get("benchmark_approved", definition.get("approval_status") == "approved")),
            "production_eligible": bool(first.get("production_eligible", definition.get("production_eligible", False))),
            "approval_status": first.get("approval_status") or definition.get("approval_status"),
            "min_coverage": round_number(min((row["coverage"] for row in row_group if row["coverage"] is not None), default=0), 4),
            "mean_coverage": round_number(sum(row["coverage"] or 0 for row in row_group) / len(row_group), 4) if row_group else None,
        }
    return info


def make_payload() -> dict[str, Any]:
    summary = read_json(OUTPUT_DIR / "factor_recommendation_summary.json")
    validation = read_json(OUTPUT_DIR / "factor_recommendation_validation.json")
    manifest = read_json(OUTPUT_DIR / "factor_recommendation_manifest.json")
    run = read_json(RUN_DIR / "run.json")
    component_status = read_json(RESULTS_DIR / "component_status.json")
    factor_config = read_json(PROJECT_DIR / "config" / "factor_definitions_v1.json")

    panel = pd.read_parquet(OUTPUT_DIR / "factor_recommendation_panel.parquet")
    history = pd.read_parquet(OUTPUT_DIR / "factor_recommendation_history.parquet")
    latest_rows = make_latest_rows(panel)
    date_values = pd.to_datetime(history["Date"])
    strategy_metrics = csv_records(RESULTS_DIR / "strategy_metrics.csv")
    cost_sensitivity = csv_records(RESULTS_DIR / "cost_sensitivity.csv")
    promotion_gate = csv_records(RESULTS_DIR / "promotion_gate.csv")
    factor_definitions = csv_records(RESULTS_DIR / "factor_definitions.csv")
    model_candidates = csv_records(RESULTS_DIR / "model_candidate_registry.csv")
    walk_forward_metrics = csv_records(RESULTS_DIR / "walk_forward_metrics.csv")
    lopo_results = csv_records(RESULTS_DIR / "lopo_results.csv")
    loro_results = csv_records(RESULTS_DIR / "loro_results.csv")

    factor_audit_by_name = {row["name"]: row for row in factor_definitions}
    factor_definitions_for_report = []
    for factor in FACTOR_ORDER:
        config_row = factor_config.get("factors", {}).get(factor, {})
        audit_row = factor_audit_by_name.get(factor, {})
        factor_definitions_for_report.append(
            {
                "name": factor,
                "label": config_row.get("label") or audit_row.get("name") or factor,
                "description_zh": FACTOR_DESCRIPTION_ZH.get(factor, "预注册的综合因子。"),
                "description": config_row.get("description", ""),
                "source_columns": config_row.get("source_columns", []),
                "direction": config_row.get("direction", audit_row.get("direction")),
                "transform": config_row.get("transform", "identity"),
                "score_scale": factor_config.get("score_scale"),
                "min_count": config_row.get("min_count", audit_row.get("min_count", 1)),
                "pit_policy": audit_row.get("pit_policy", "available_at_or_before_decision_time"),
            }
        )

    factor_meta = {
        row["name"]: {
            "label": next((item["label"] for item in latest_rows if item["factor"] == row["name"]), row["name"]),
            "direction": row.get("direction"),
        }
        for row in factor_definitions
    }
    gate_passed = sum(bool(row.get("passed")) for row in promotion_gate)
    gate_total = len(promotion_gate)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_date": summary["latest_date"],
        "history_date_min": summary["history_date_min"],
        "history_date_max": summary["history_date_max"],
        "history_months": int(date_values.nunique()),
        "panel_rows": int(summary["panel_rows"]),
        "history_rows": int(summary["history_rows"]),
        "regions": REGION_ORDER,
        "factors": FACTOR_ORDER,
        "factor_meta": factor_meta,
        "region_meta": make_region_info(summary, latest_rows),
        "latest": latest_rows,
        "history_series": make_history_series(history),
        "strategy_metrics": strategy_metrics,
        "cost_sensitivity": cost_sensitivity,
        "promotion_gate": promotion_gate,
        "gate_summary": {"passed": gate_passed, "total": gate_total},
        "factor_definitions": factor_definitions_for_report,
        "model_candidates": model_candidates,
        "walk_forward_metrics": walk_forward_metrics,
        "lopo_summary": {
            "rows": len(lopo_results),
            "periods": sorted({str(row["holdout_period"]) for row in lopo_results}),
            "min_holdout_ic": round_number(min((row["holdout_spearman_ic"] for row in lopo_results), default=0), 4),
            "max_holdout_ic": round_number(max((row["holdout_spearman_ic"] for row in lopo_results), default=0), 4),
        },
        "loro_summary": {
            "rows": len(loro_results),
            "periods": sorted({str(row["holdout_period"]) for row in loro_results}),
        },
        "summary": summary,
        "validation": validation,
        "manifest": {
            "status": manifest.get("status"),
            "model_status": manifest.get("model_status"),
            "gates": manifest.get("gates", {}),
        },
        "run": {
            "run_id": run.get("run", {}).get("run_id"),
            "status": run.get("run", {}).get("status"),
            "started_at": run.get("run", {}).get("started_at"),
            "finished_at": run.get("run", {}).get("finished_at"),
            "commit": run.get("code", {}).get("commit"),
            "branch": run.get("code", {}).get("branch"),
            "dirty": run.get("code", {}).get("dirty"),
            "effective_trial_count": run.get("hypothesis", {}).get("effective_trial_count"),
        },
        "component_status": {
            "asia": component_status.get("asia", {}),
            "synthetic": component_status.get("synthetic", False),
        },
    }
    return clean(payload)


HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>月度因子推荐 · 研究结果看板</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #172033;
      --muted: #657089;
      --faint: #8b95a9;
      --line: #e4e8f0;
      --surface: #ffffff;
      --canvas: #f4f6fa;
      --navy: #17223b;
      --navy-2: #26375b;
      --accent: #4263eb;
      --accent-soft: #edf1ff;
      --positive: #138a66;
      --positive-soft: #e5f7f0;
      --negative: #c44747;
      --negative-soft: #fff0ef;
      --neutral: #9a6b19;
      --neutral-soft: #fff7df;
      --warning: #b45309;
      --warning-soft: #fff4df;
      --shadow: 0 16px 42px rgba(28, 42, 74, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--canvas);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }
    button, select { font: inherit; }
    button { cursor: pointer; }
    .shell { max-width: 1440px; margin: 0 auto; padding: 28px 28px 54px; }
    .hero {
      position: relative;
      overflow: hidden;
      color: #fff;
      background: linear-gradient(135deg, var(--navy), var(--navy-2));
      border-radius: 22px;
      padding: 32px 36px;
      box-shadow: var(--shadow);
    }
    .hero::after {
      content: "";
      position: absolute;
      width: 380px;
      height: 380px;
      right: -110px;
      top: -180px;
      border-radius: 50%;
      background: rgba(102, 126, 234, .18);
    }
    .hero-content { position: relative; z-index: 1; max-width: 860px; }
    .eyebrow { margin: 0 0 8px; color: #aebefc; font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
    h1 { margin: 0; font-size: clamp(26px, 3vw, 42px); letter-spacing: -.04em; line-height: 1.12; }
    .hero-subtitle { margin: 14px 0 0; max-width: 760px; color: #d4dcf3; font-size: 15px; }
    .hero-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 22px; }
    .hero-tag, .status-pill { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 6px 10px; font-size: 12px; font-weight: 700; }
    .hero-tag { color: #e4e9ff; border: 1px solid rgba(225, 232, 255, .2); background: rgba(255,255,255,.08); }
    .status-pill { color: var(--warning); background: var(--warning-soft); }
    .status-pill.ok { color: var(--positive); background: var(--positive-soft); }
    .kpi-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 18px 0; }
    .kpi, .section { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 8px 24px rgba(28,42,74,.04); }
    .kpi { padding: 18px 20px; }
    .kpi-label { color: var(--muted); font-size: 12px; font-weight: 700; letter-spacing: .03em; }
    .kpi-value { margin-top: 7px; font-size: 27px; font-weight: 750; letter-spacing: -.03em; }
    .kpi-note { margin-top: 3px; color: var(--muted); font-size: 12px; }
    .section { margin-top: 18px; padding: 24px; }
    .section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 18px; }
    .section-kicker { margin: 0 0 4px; color: var(--accent); font-size: 11px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
    h2 { margin: 0; font-size: 20px; letter-spacing: -.025em; }
    h3 { margin: 0; font-size: 15px; }
    .section-caption { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
    .alert { display: flex; align-items: flex-start; gap: 12px; padding: 14px 16px; border: 1px solid #f2d7a4; border-radius: 13px; color: #795016; background: var(--warning-soft); }
    .alert strong { display: block; margin-bottom: 2px; color: #6b430c; }
    .alert p { margin: 0; font-size: 13px; }
    .tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }
    .tab { border: 1px solid var(--line); border-radius: 999px; padding: 8px 14px; color: var(--muted); background: var(--surface); font-weight: 700; transition: .16s ease; }
    .tab:hover, .tab.active { color: #fff; border-color: var(--accent); background: var(--accent); }
    .region-context { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px; padding: 12px 14px; margin-bottom: 18px; color: var(--muted); background: #f8f9fc; border: 1px solid var(--line); border-radius: 12px; font-size: 13px; }
    .region-context strong { color: var(--ink); }
    .layout-2 { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, .9fr); gap: 22px; }
    .layout-equal { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 22px; }
    .chart-panel { min-width: 0; }
    .chart-title { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
    .chart-note { color: var(--muted); font-size: 12px; }
    .canvas-wrap { position: relative; width: 100%; min-height: 300px; }
    canvas { display: block; width: 100%; height: 300px; }
    .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
    .table-wrap { width: 100%; overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th { padding: 9px 10px; color: var(--muted); border-bottom: 1px solid var(--line); text-align: left; font-size: 11px; font-weight: 800; letter-spacing: .03em; text-transform: uppercase; white-space: nowrap; }
    td { padding: 11px 10px; border-bottom: 1px solid #edf0f5; vertical-align: middle; }
    tbody tr:last-child td { border-bottom: 0; }
    .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .factor-name { display: flex; align-items: center; gap: 9px; font-weight: 700; white-space: nowrap; }
    .factor-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
    .factor-definition-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .factor-definition { padding: 16px; border: 1px solid var(--line); border-radius: 13px; background: #fbfcff; }
    .factor-definition-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
    .factor-definition-title { font-size: 16px; font-weight: 800; }
    .factor-definition-key { color: var(--faint); font: 11px ui-monospace, SFMono-Regular, Consolas, monospace; }
    .factor-definition-text { margin: 10px 0 6px; font-size: 13px; }
    .factor-definition-source { margin: 0; color: var(--muted); font-size: 12px; }
    .factor-definition-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
    .definition-chip { display: inline-flex; border-radius: 999px; padding: 4px 7px; color: var(--muted); background: #eef1f7; font-size: 11px; }
    .score-cell { min-width: 160px; }
    .score-line { display: flex; align-items: center; gap: 9px; }
    .score-track { flex: 1; height: 7px; overflow: hidden; border-radius: 999px; background: #ebeff7; }
    .score-fill { height: 100%; border-radius: inherit; background: var(--accent); }
    .score-value { width: 42px; text-align: right; font-variant-numeric: tabular-nums; font-weight: 800; }
    .stance { display: inline-flex; border-radius: 999px; padding: 4px 8px; font-size: 11px; font-weight: 800; white-space: nowrap; }
    .stance-positive { color: var(--positive); background: var(--positive-soft); }
    .stance-negative { color: var(--negative); background: var(--negative-soft); }
    .stance-neutral { color: var(--neutral); background: var(--neutral-soft); }
    .select-wrap { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12px; }
    select { min-width: 150px; border: 1px solid var(--line); border-radius: 9px; padding: 8px 10px; color: var(--ink); background: var(--surface); }
    .metric-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 16px 0 4px; }
    .metric { padding: 12px; border-radius: 11px; background: #f8f9fc; }
    .metric-label { color: var(--muted); font-size: 11px; }
    .metric-value { margin-top: 4px; font-size: 17px; font-weight: 800; }
    .bar-list { display: grid; gap: 14px; margin-top: 6px; }
    .bar-row { display: grid; grid-template-columns: 88px minmax(0, 1fr) 60px; align-items: center; gap: 10px; font-size: 13px; }
    .bar-label { color: var(--muted); }
    .bar-track { height: 11px; overflow: hidden; border-radius: 999px; background: #edf0f6; }
    .bar-fill { height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--accent), #6b7ff2); }
    .bar-value { text-align: right; font-weight: 800; font-variant-numeric: tabular-nums; }
    .gate-table td:first-child { font-weight: 700; }
    .gate-pass, .gate-review { display: inline-flex; align-items: center; gap: 5px; border-radius: 999px; padding: 4px 8px; font-size: 11px; font-weight: 800; }
    .gate-pass { color: var(--positive); background: var(--positive-soft); }
    .gate-review { color: var(--warning); background: var(--warning-soft); }
    .note-list { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }
    .note-list li { display: flex; gap: 10px; color: var(--muted); font-size: 13px; }
    .note-list li::before { content: ""; flex: 0 0 6px; width: 6px; height: 6px; margin-top: 7px; border-radius: 50%; background: var(--accent); }
    .asia-box { padding: 16px; border: 1px solid #f2d7a4; border-radius: 13px; background: #fffaf1; }
    .asia-box h3 { color: #7b5011; }
    .component-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
    .component { padding: 12px; border-radius: 10px; background: rgba(255,255,255,.75); border: 1px solid #f4e3bd; }
    .component strong { display: block; }
    .component span { color: var(--muted); font-size: 12px; }
    .details { margin-top: 14px; }
    .details summary { cursor: pointer; color: var(--accent); font-size: 13px; font-weight: 800; }
    .details-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 18px; margin-top: 14px; }
    .detail-item { padding-bottom: 10px; border-bottom: 1px solid var(--line); }
    .detail-label { display: block; color: var(--muted); font-size: 11px; }
    .detail-value { display: block; margin-top: 3px; overflow-wrap: anywhere; font-size: 13px; font-weight: 700; }
    footer { padding: 20px 4px 0; color: var(--faint); font-size: 12px; text-align: center; }
    @media (max-width: 1000px) {
      .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .layout-2, .layout-equal { grid-template-columns: 1fr; }
    }
    @media (max-width: 640px) {
      .shell { padding: 14px 12px 34px; }
      .hero { padding: 24px 22px; border-radius: 17px; }
      .section { padding: 18px 15px; border-radius: 13px; }
      .kpi-grid { gap: 9px; margin: 12px 0; }
      .kpi { padding: 14px; }
      .kpi-value { font-size: 21px; }
      .section-head { display: block; }
      .section-head > :last-child { margin-top: 12px; }
      .metric-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .component-grid, .details-grid, .factor-definition-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div class="hero-content">
        <p class="eyebrow">TP Research / Monthly Factor Recommendation</p>
        <h1>月度因子推荐 · 研究结果看板</h1>
        <p class="hero-subtitle">基于 point-in-time 特征、分组 walk-forward、成本敏感性与独立 promotion gate 的研究审阅视图。</p>
        <div class="hero-tags">
          <span class="hero-tag">截至 <span id="hero-date">—</span></span>
          <span class="hero-tag">Full run</span>
          <span class="hero-tag">research_only</span>
          <span class="status-pill" id="hero-status">—</span>
        </div>
      </div>
    </header>

    <div class="kpi-grid" id="kpis"></div>

    <div class="alert" role="status">
      <div aria-hidden="true">⚠</div>
      <div>
        <strong>当前结论：可审阅，未晋升生产</strong>
        <p>完整研究证据已生成，但 workflow 保留 review_required；ASIA benchmark 尚未获批，forward shadow 仍待完成。</p>
      </div>
    </div>

    <section class="section" aria-labelledby="latest-title">
      <div class="section-head">
        <div>
          <p class="section-kicker">Latest panel</p>
          <h2 id="latest-title">最新月份的区域与因子信号</h2>
          <p class="section-caption">分数是 0–100 的透明 composite score；推荐标签按当前研究规则映射。</p>
        </div>
        <div class="status-pill" id="region-status">—</div>
      </div>
      <div class="tabs" id="region-tabs" role="tablist" aria-label="区域选择"></div>
      <div class="region-context" id="region-context"></div>
      <div class="layout-2">
        <div class="chart-panel">
          <div class="chart-title"><h3>因子分数分布</h3><span class="chart-note">基准线 = 50</span></div>
          <div class="canvas-wrap"><canvas id="score-chart" aria-label="当前区域的因子分数柱状图"></canvas><p class="sr-only" id="score-alt"></p></div>
        </div>
        <div class="chart-panel">
          <div class="chart-title"><h3>最新推荐明细</h3><span class="chart-note" id="latest-count">—</span></div>
          <div class="table-wrap"><table><thead><tr><th>因子</th><th>分数</th><th>推荐</th><th class="num">覆盖率</th><th class="num">覆盖样本</th></tr></thead><tbody id="latest-table"></tbody></table></div>
        </div>
      </div>
    </section>

    <section class="section" aria-labelledby="definitions-title">
      <div class="section-head">
        <div>
          <p class="section-kicker">Factor dictionary</p>
          <h2 id="definitions-title">8 个因子的定义与计算口径</h2>
          <p class="section-caption">以下内容来自 factor_definitions_v1.json；看板把底层配置的 composite score 映射到 0–100 展示尺度，并保留原始字段名与 PIT 约束。</p>
        </div>
      </div>
      <div class="factor-definition-grid" id="factor-definitions"></div>
    </section>

    <section class="section" aria-labelledby="history-title">
      <div class="section-head">
        <div>
          <p class="section-kicker">History</p>
          <h2 id="history-title">历史分数轨迹</h2>
          <p class="section-caption">按区域查看单一因子从 2004-10 到最新月份的变化，历史点来自持久化 history parquet。</p>
        </div>
        <label class="select-wrap" for="factor-select">因子<select id="factor-select"></select></label>
      </div>
      <div class="canvas-wrap"><canvas id="history-chart" aria-label="因子历史分数折线图"></canvas><p class="sr-only" id="history-alt"></p></div>
      <div class="metric-strip" id="history-metrics"></div>
    </section>

    <div class="layout-equal">
      <section class="section" aria-labelledby="cost-title">
        <div class="section-head">
          <div><p class="section-kicker">Robustness</p><h2 id="cost-title">成本敏感性</h2><p class="section-caption">交易成本假设按 bps 展开；净 Sharpe 在 50 bps 下仍为正但下降。</p></div>
        </div>
        <div class="bar-list" id="cost-bars"></div>
        <div class="table-wrap" style="margin-top:18px"><table><thead><tr><th>成本</th><th class="num">年化收益</th><th class="num">波动率</th><th class="num">最大回撤</th></tr></thead><tbody id="cost-table"></tbody></table></div>
      </section>

      <section class="section" aria-labelledby="gate-title">
        <div class="section-head">
          <div><p class="section-kicker">Promotion gate</p><h2 id="gate-title">晋升门禁</h2><p class="section-caption">门禁结果用于人工 review，不会自动 promotion。</p></div>
          <div class="status-pill" id="gate-summary">—</div>
        </div>
        <div class="table-wrap"><table class="gate-table"><thead><tr><th>检查项</th><th>状态</th><th>证据摘要</th></tr></thead><tbody id="gate-table"></tbody></table></div>
      </section>
    </div>

    <div class="layout-equal">
      <section class="section" aria-labelledby="research-title">
        <div class="section-head"><div><p class="section-kicker">Research audit</p><h2 id="research-title">研究方法与稳定性</h2></div></div>
        <ul class="note-list" id="research-notes"></ul>
        <details class="details"><summary>候选模型注册表</summary><div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>候选</th><th>类型</th><th>选择范围</th></tr></thead><tbody id="model-table"></tbody></table></div></details>
      </section>

      <section class="section" aria-labelledby="asia-title">
        <div class="asia-box">
          <h3 id="asia-title">ASIA 特别提示：研究组合，尚未获批</h3>
          <p class="section-caption">ASIA 由 Japan 与 Asia ex Japan 两个组件固定聚合，当前只作为研究结果展示。</p>
          <div class="component-grid" id="asia-components"></div>
        </div>
        <details class="details" open><summary>运行与数据血缘</summary><div class="details-grid" id="provenance"></div></details>
      </section>
    </div>

    <footer>由当前 TP 研究产物生成；本页面仅用于研究审阅，不构成交易建议。</footer>
  </main>

  <script id="report-data" type="application/json">__DATA__</script>
  <script>
    (() => {
      const data = JSON.parse(document.getElementById('report-data').textContent);
      const state = { region: 'US', factor: data.factors[0] };
      const factorLabels = { value: '价值', quality: '质量', growth: '成长', momentum: '动量', lowvol: '低波', size: '大盘', small_size: '小盘', dividend: '股息' };
      const regionLabels = { US: '美国', EU: '欧洲', ASIA: '亚洲研究组合', JAPAN: '日本', GLOBAL: '全球' };
      const $ = (id) => document.getElementById(id);
      const latestByRegion = (region) => data.latest.filter((row) => row.region === region).sort((a, b) => data.factors.indexOf(a.factor) - data.factors.indexOf(b.factor));
      const currentSeries = () => data.history_series[`${state.region}|${state.factor}`] || { points: [], label: factorLabels[state.factor] || state.factor };
      const number = (value, digits = 1) => value === null || value === undefined || Number.isNaN(Number(value)) ? '—' : Number(value).toFixed(digits);
      const percent = (value, digits = 1) => value === null || value === undefined || Number.isNaN(Number(value)) ? '—' : `${(Number(value) * 100).toFixed(digits)}%`;
      const html = (value) => String(value ?? '—').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
      const stanceClass = (value) => value === 'Positive' ? 'stance-positive' : value === 'Negative' ? 'stance-negative' : 'stance-neutral';
      const stanceLabel = (value) => value === 'Positive' ? '正向' : value === 'Negative' ? '负向' : '中性';

      function renderKpis() {
        const net = data.strategy_metrics.find((row) => row.series === 'net') || {};
        const benchmark = data.strategy_metrics.find((row) => row.series === 'benchmark') || {};
        $('hero-date').textContent = data.latest_date;
        $('hero-status').textContent = 'review_required';
        $('kpis').innerHTML = [
          ['最新月份', data.latest_date, '5 个区域 × 8 个因子'],
          ['历史跨度', `${data.history_months} 个月`, `${data.history_date_min} → ${data.history_date_max}`],
          ['净 Sharpe', number(net.sharpe, 3), `基准 ${number(benchmark.sharpe, 3)}`],
          ['晋升门禁', `${data.gate_summary.passed}/${data.gate_summary.total}`, 'promotion_decision = review_required'],
        ].map(([label, value, note]) => `<div class="kpi"><div class="kpi-label">${html(label)}</div><div class="kpi-value">${html(value)}</div><div class="kpi-note">${html(note)}</div></div>`).join('');
      }

      function renderTabs() {
        $('region-tabs').innerHTML = data.regions.map((region) => `<button type="button" class="tab ${region === state.region ? 'active' : ''}" role="tab" aria-selected="${region === state.region}" data-region="${html(region)}">${html(regionLabels[region] || region)}</button>`).join('');
        document.querySelectorAll('[data-region]').forEach((button) => button.addEventListener('click', () => { state.region = button.dataset.region; renderAll(); }));
      }

      function renderRegion() {
        const rows = latestByRegion(state.region);
        const meta = data.region_meta[state.region] || {};
        $('region-status').textContent = meta.benchmark_approved ? 'benchmark approved' : 'benchmark unapproved';
        $('region-status').className = `status-pill${meta.benchmark_approved ? ' ok' : ''}`;
        $('region-context').innerHTML = `<span><strong>${html(regionLabels[state.region] || state.region)}</strong></span><span>Benchmark：<strong>${html(meta.benchmark)}</strong></span><span>币种：<strong>${html(meta.currency)}</strong></span><span>最低覆盖率：<strong>${percent(meta.min_coverage)}</strong></span><span>均值覆盖率：<strong>${percent(meta.mean_coverage)}</strong></span>`;
        $('latest-count').textContent = `${rows.length} 个因子`;
        $('latest-table').innerHTML = rows.map((row) => `<tr><td><div class="factor-name"><span class="factor-dot"></span>${html(factorLabels[row.factor] || row.label)}</div></td><td class="score-cell"><div class="score-line"><span class="score-track"><span class="score-fill" style="width:${Math.max(0, Math.min(100, Number(row.score || 0)))}%"></span></span><span class="score-value">${number(row.score, 1)}</span></div></td><td><span class="stance ${stanceClass(row.recommendation)}">${stanceLabel(row.recommendation)}</span></td><td class="num">${percent(row.coverage)}</td><td class="num">${number(row.covered, 0)} / ${number(row.universe, 0)}</td></tr>`).join('');
        drawScoreChart(rows);
      }

      function fitCanvas(canvas) {
        const rect = canvas.getBoundingClientRect();
        const ratio = window.devicePixelRatio || 1;
        const width = Math.max(320, Math.floor(rect.width));
        const height = Math.max(260, Math.floor(rect.height));
        if (canvas.width !== width * ratio || canvas.height !== height * ratio) { canvas.width = width * ratio; canvas.height = height * ratio; }
        const context = canvas.getContext('2d');
        context.setTransform(ratio, 0, 0, ratio, 0, 0);
        return { context, width, height };
      }

      function drawScoreChart(rows) {
        const canvas = $('score-chart');
        const { context: ctx, width, height } = fitCanvas(canvas);
        ctx.clearRect(0, 0, width, height);
        const pad = { top: 18, right: 18, bottom: 45, left: 40 };
        const plotW = width - pad.left - pad.right;
        const plotH = height - pad.top - pad.bottom;
        ctx.font = '11px Inter, system-ui, sans-serif';
        ctx.strokeStyle = '#e7ebf2'; ctx.lineWidth = 1;
        [0, 25, 50, 75, 100].forEach((tick) => { const y = pad.top + plotH * (1 - tick / 100); ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke(); ctx.fillStyle = '#7a8498'; ctx.textAlign = 'right'; ctx.fillText(String(tick), pad.left - 8, y + 4); });
        const gap = Math.max(8, plotW / (rows.length * 15));
        const barW = Math.max(18, (plotW - gap * (rows.length - 1)) / rows.length);
        rows.forEach((row, index) => { const score = Number(row.score || 0); const x = pad.left + index * (barW + gap); const barH = plotH * score / 100; const y = pad.top + plotH - barH; ctx.fillStyle = row.recommendation === 'Positive' ? '#138a66' : row.recommendation === 'Negative' ? '#c44747' : '#4263eb'; ctx.beginPath(); ctx.roundRect(x, y, barW, barH, 5); ctx.fill(); ctx.fillStyle = '#172033'; ctx.textAlign = 'center'; ctx.font = '700 11px Inter, system-ui, sans-serif'; ctx.fillText(number(score, 0), x + barW / 2, Math.max(13, y - 6)); ctx.fillStyle = '#657089'; ctx.font = '11px Inter, system-ui, sans-serif'; ctx.fillText(factorLabels[row.factor] || row.factor, x + barW / 2, height - 17); });
        const baselineY = pad.top + plotH / 2; ctx.strokeStyle = '#9aa4b8'; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(pad.left, baselineY); ctx.lineTo(width - pad.right, baselineY); ctx.stroke(); ctx.setLineDash([]);
        $('score-alt').textContent = `${regionLabels[state.region]}最新因子分数：${rows.map((row) => `${factorLabels[row.factor] || row.factor} ${number(row.score, 1)}`).join('、')}`;
      }

      function renderFactorSelect() {
        $('factor-select').innerHTML = data.factors.map((factor) => `<option value="${html(factor)}" ${factor === state.factor ? 'selected' : ''}>${html(factorLabels[factor] || factor)}</option>`).join('');
        $('factor-select').onchange = (event) => { state.factor = event.target.value; drawHistoryChart(); };
      }

      function renderFactorDefinitions() {
        const transformLabel = (value) => value === 'reverse_score' ? '反向分数' : '原值 identity';
        const directionLabel = (value) => Number(value) < 0 ? '方向 −1' : '方向 +1';
        $('factor-definitions').innerHTML = data.factor_definitions.map((item) => `<article class="factor-definition"><div class="factor-definition-head"><span class="factor-definition-title">${html(factorLabels[item.name] || item.label)}</span><span class="factor-definition-key">${html(item.name)}</span></div><p class="factor-definition-text">${html(item.description_zh)}</p><p class="factor-definition-source">配置原文：${html(item.description)}</p><div class="factor-definition-meta"><span class="definition-chip">来源：${html((item.source_columns || []).join(' / '))}</span><span class="definition-chip">${directionLabel(item.direction)}</span><span class="definition-chip">${transformLabel(item.transform)}</span><span class="definition-chip">min_count = ${html(item.min_count)}</span><span class="definition-chip">PIT：${html(item.pit_policy)}</span></div></article>`).join('');
      }

      function drawHistoryChart() {
        const series = currentSeries();
        const points = series.points || [];
        const canvas = $('history-chart');
        const { context: ctx, width, height } = fitCanvas(canvas);
        ctx.clearRect(0, 0, width, height);
        const pad = { top: 20, right: 24, bottom: 40, left: 42 };
        const plotW = width - pad.left - pad.right;
        const plotH = height - pad.top - pad.bottom;
        ctx.font = '11px Inter, system-ui, sans-serif';
        [0, 25, 50, 75, 100].forEach((tick) => { const y = pad.top + plotH * (1 - tick / 100); ctx.strokeStyle = '#e7ebf2'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke(); ctx.fillStyle = '#7a8498'; ctx.textAlign = 'right'; ctx.fillText(String(tick), pad.left - 8, y + 4); });
        if (!points.length) { ctx.fillStyle = '#657089'; ctx.textAlign = 'center'; ctx.fillText('暂无历史序列', width / 2, height / 2); return; }
        const stride = Math.max(1, Math.ceil(points.length / 160));
        const sampled = points.filter((_, index) => index % stride === 0 || index === points.length - 1);
        const xOf = (index) => pad.left + (sampled.length === 1 ? plotW / 2 : plotW * index / (sampled.length - 1));
        const yOf = (value) => pad.top + plotH * (1 - Number(value || 0) / 100);
        ctx.strokeStyle = '#4263eb'; ctx.lineWidth = 2.4; ctx.beginPath(); sampled.forEach((point, index) => { const x = xOf(index); const y = yOf(point[1]); if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); }); ctx.stroke();
        const last = sampled[sampled.length - 1]; const lastX = xOf(sampled.length - 1); const lastY = yOf(last[1]); ctx.fillStyle = '#4263eb'; ctx.beginPath(); ctx.arc(lastX, lastY, 4.5, 0, Math.PI * 2); ctx.fill(); ctx.fillStyle = '#172033'; ctx.font = '700 12px Inter, system-ui, sans-serif'; ctx.textAlign = 'right'; ctx.fillText(number(last[1], 1), Math.min(width - pad.right, lastX + 38), Math.max(15, lastY - 10));
        ctx.fillStyle = '#7a8498'; ctx.font = '11px Inter, system-ui, sans-serif'; ctx.textAlign = 'left'; ctx.fillText(sampled[0][0], pad.left, height - 14); ctx.textAlign = 'right'; ctx.fillText(last[0], width - pad.right, height - 14);
        const numeric = points.map((point) => Number(point[1])).filter(Number.isFinite); const min = Math.min(...numeric); const max = Math.max(...numeric); const avg = numeric.reduce((sum, value) => sum + value, 0) / numeric.length;
        $('history-metrics').innerHTML = [['历史点数', points.length, ''], ['最低分', number(min, 1), ''], ['最高分', number(max, 1), ''], ['平均分', number(avg, 1), '']].map(([label, value, note]) => `<div class="metric"><div class="metric-label">${label}</div><div class="metric-value">${value}</div>${note ? `<div class="metric-label">${note}</div>` : ''}</div>`).join('');
        $('history-alt').textContent = `${regionLabels[state.region]}${factorLabels[state.factor] || state.factor}历史序列，共 ${points.length} 个点，最新分数 ${number(last[1], 1)}，区间 ${number(min, 1)}–${number(max, 1)}。`;
      }

      function renderCost() {
        const rows = data.cost_sensitivity;
        const max = Math.max(...rows.map((row) => Number(row.sharpe || 0)), 1);
        $('cost-bars').innerHTML = rows.map((row) => `<div class="bar-row"><span class="bar-label">${number(row.transaction_cost_bps, 0)} bps</span><span class="bar-track"><span class="bar-fill" style="width:${Math.max(4, Number(row.sharpe || 0) / max * 100)}%"></span></span><span class="bar-value">${number(row.sharpe, 3)}</span></div>`).join('');
        $('cost-table').innerHTML = rows.map((row) => `<tr><td>${number(row.transaction_cost_bps, 0)} bps</td><td class="num">${percent(row.annualized_return)}</td><td class="num">${percent(row.annualized_volatility)}</td><td class="num">${percent(row.max_drawdown)}</td></tr>`).join('');
      }

      function renderGates() {
        $('gate-summary').textContent = `${data.gate_summary.passed}/${data.gate_summary.total} checks pass`;
        $('gate-table').innerHTML = data.promotion_gate.map((row) => `<tr><td>${html(row.check)}</td><td>${row.passed ? '<span class="gate-pass">✓ pass</span>' : '<span class="gate-review">! review</span>'}</td><td>${html(row.evidence)}</td></tr>`).join('');
      }

      function renderResearch() {
        const net = data.strategy_metrics.find((row) => row.series === 'net') || {};
        const benchmark = data.strategy_metrics.find((row) => row.series === 'benchmark') || {};
        const wf = data.walk_forward_metrics.find((row) => row.series === 'net') || {};
        $('research-notes').innerHTML = [
          `样本 ${number(net.observations, 0)} 个月；净年化收益 ${percent(net.annualized_return)}，净 Sharpe ${number(net.sharpe, 3)}，基准 Sharpe ${number(benchmark.sharpe, 3)}。`,
          `Walk-forward 净结果与主策略一致：年化波动率 ${percent(wf.annualized_volatility)}，命中率 ${percent(wf.hit_rate)}，最大回撤 ${percent(wf.max_drawdown)}。`,
          `LOPO/LORO 共覆盖 ${data.lopo_summary.periods.length} 个 holdout period；LOPO holdout IC 区间 ${number(data.lopo_summary.min_holdout_ic, 4)}–${number(data.lopo_summary.max_holdout_ic, 4)}。`,
          `研究方法包含 PIT、分组 folds、1 个月 purge、成本、DSR、固定 seed bootstrap；effective trial count = ${data.run.effective_trial_count}。`,
        ].map((item) => `<li>${html(item)}</li>`).join('');
        $('model-table').innerHTML = data.model_candidates.map((row) => `<tr><td>${html(row.name)}</td><td>${html(row.model_type)}</td><td>${row.name === 'M0_equal_factor' ? 'baseline / always available' : 'training-only selection'}</td></tr>`).join('');
      }

      function renderAsia() {
        const asia = data.component_status.asia || {};
        const components = Array.isArray(asia.components) ? asia.components : [];
        $('asia-components').innerHTML = components.map((component) => `<div class="component"><strong>${html(component.name)}</strong><span>${html(component.benchmark)} · 权重 ${component.name === 'JAPAN' ? '50%' : '50%'}</span><span>${component.country_allowlist && component.country_allowlist.length ? `国家白名单：${html(component.country_allowlist.join(', '))}` : '按组件 benchmark 正权重'}</span></div>`).join('');
      }

      function renderProvenance() {
        const items = [
          ['run_id', data.run.run_id], ['运行状态', data.run.status], ['完成时间', data.run.finished_at], ['Git commit', data.run.commit], ['分支', data.run.branch], ['worktree', data.run.dirty ? 'dirty（运行时）' : 'clean'], ['面板行数', data.panel_rows], ['重复 signal key', data.validation.duplicate_signal_keys], ['signal schema', data.validation.signal_schema_valid ? 'valid' : 'invalid'], ['合成数据', data.component_status.synthetic ? 'yes' : 'no'],
        ];
        $('provenance').innerHTML = items.map(([label, value]) => `<div class="detail-item"><span class="detail-label">${html(label)}</span><span class="detail-value">${html(value)}</span></div>`).join('');
      }

      function renderAll() {
        renderKpis(); renderTabs(); renderRegion(); renderFactorDefinitions(); renderFactorSelect(); drawHistoryChart(); renderCost(); renderGates(); renderResearch(); renderAsia(); renderProvenance();
      }
      window.addEventListener('resize', () => { drawScoreChart(latestByRegion(state.region)); drawHistoryChart(); });
      renderAll();
    })();
  </script>
</body>
</html>
'''


def main() -> None:
    payload = make_payload()
    data_blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    data_blob = data_blob.replace("<", "\\u003c").replace(">", "\\u003e")
    REPORT_PATH.write_text(HTML_TEMPLATE.replace("__DATA__", data_blob), encoding="utf-8")
    print(f"wrote {REPORT_PATH}")
    print(f"bytes={REPORT_PATH.stat().st_size}")


if __name__ == "__main__":
    main()

"""Build a self-contained STOXX Europe 600 factor-research explorer."""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "07_backtest_code" / "runs" / "ad_hoc" / "stoxx600_relative_synergy_20260709"
RAW_GATE = ROOT / "07_backtest_code" / "runs" / "ad_hoc" / "stoxx600_raw_gated_20260708_0100" / "raw_validation_gate.csv"
REL_GATE = ROOT / "07_backtest_code" / "runs" / "ad_hoc" / "stoxx600_relative_variables_20260709" / "relative_validation_gate.csv"
OUTPUT = Path(__file__).with_name("stoxx600-factor-explorer.html")

BUCKET_NAMES = {
    "revision": "盈利预期上修",
    "pmom": "价格动量",
    "growth": "前瞻增长",
    "quality_improvement": "质量改善",
    "earnings_yield_improvement": "盈利收益率改善",
    "deleveraging": "去杠杆",
    "value_improvement": "估值改善",
    "risk_decline": "风险下降",
}

SELECTED = [
    ("stoxx600_syn_subset_e5c1a446e9", "盈利预期上修 + 质量改善 + 估值改善", "family_subset", "全样本最强的三桶组合；显示改善信号，而不是静态价值。"),
    ("stoxx600_syn_subset_eba89b8a51", "PMOM + 质量改善 + 去杠杆", "family_subset", "价格确认与经营、资产负债表改善共同出现。"),
    ("stoxx600_syn_subset_b3c0d0fc7d", "盈利预期上修 + 质量改善 + 去杠杆", "family_subset", "盈利可见度与基本面改善的组合。"),
    ("stoxx600_syn_subset_2543debc1d", "PMOM + 质量改善 + 盈利收益率改善", "family_subset", "价格确认、盈利改善与估值重估并行。"),
    ("stoxx600_syn_pair_8dbe63d33df5", "去杠杆 + 利润率改善", "pair", "最强直接 pair 协同：净债务/EBITDA 下降与经营利润率改善。"),
    ("stoxx600_syn_pair_56f732432d80", "利润率改善 + EPS NTM 3M 增长", "pair", "利润率改善被预期上修确认。"),
    ("stoxx600_syn_pair_86df394a53f2", "PMOM + 利润率改善", "pair", "价格趋势与盈利能力改善相互验证。"),
    ("stoxx600_syn_pair_5937db8297d4", "PMOM + ROE 改善", "pair", "价格确认与资本回报率改善相结合。"),
    ("stoxx600_syn_pair_97a8dca0503b", "盈利收益率改善 + 利润率改善", "pair", "估值重估不脱离盈利质量改善。"),
    ("stoxx600_syn_full_bucket_equal", "所有通过桶等权", "full_model", "诊断基准：并非变量越多越好，需由 leave-one-out 约束。"),
]


def records(frame: pd.DataFrame, columns: list[str]) -> list[dict]:
    selected = frame.loc[:, columns].astype(object)
    return selected.where(pd.notna(selected), None).to_dict("records")


def monthly_nav(path: str) -> pd.Series:
    frame = pd.read_parquet(path)
    frame["index"] = pd.to_datetime(frame["index"])
    # Keep the real final trading date instead of relabeling partial July as July 31.
    frame = frame.sort_values("index")
    return frame.groupby(frame["index"].dt.to_period("M"), group_keys=False).tail(1).set_index("index")["nav"]


def selection_data(summary: pd.DataFrame, candidate_map: pd.DataFrame, definitions: dict[str, str], claims: pd.DataFrame) -> list[dict]:
    map_by_metric = candidate_map.set_index("metric")
    claim_by_metric = claims.set_index("metric")
    candidates = []
    for metric, display_name, kind, note in SELECTED:
        rows = summary.loc[summary["metric"].eq(metric)].copy()
        if rows.empty:
            raise ValueError(f"Missing selected metric: {metric}")
        rows["ratio_cagr"] = pd.to_numeric(rows["ratio_cagr"])
        top = rows.loc[rows["ratio_cagr"].idxmax()]
        worst = rows.loc[rows["ratio_cagr"].idxmin()]
        nav = pd.concat(
            [
                monthly_nav(top["perf_ptf"]).rename("top"),
                monthly_nav(worst["perf_ptf"]).rename("worst"),
                monthly_nav(top["perf_bench"]).rename("bench"),
            ],
            axis=1,
        ).dropna()
        row_map = map_by_metric.loc[metric]
        bucket_keys = str(row_map.get("buckets", "")).split("|")
        components = str(row_map.get("components", "")).split("|")
        claim = claim_by_metric.loc[metric] if metric in claim_by_metric.index else None
        candidates.append(
            {
                "metric": metric,
                "name": display_name,
                "officialLabel": top["label"],
                "kind": kind,
                "note": note,
                "buckets": [BUCKET_NAMES.get(key, key) for key in bucket_keys if key],
                "components": [definitions.get(key, key) for key in components if key],
                "claim": None if claim is None else claim["classification"],
                "metrics": {
                    "robust": float(top["robust_score"]),
                    "topCagr": float(top["cagr"]),
                    "activeCagr": float(top["ratio_cagr"]),
                    "topWorst": float(top["top_worst_ratio_return"]),
                    "activeDd": float(top["ratio_max_drawdown"]),
                    "te": float(top["tracking_error"]),
                    "coverage": float(top["coverage"]),
                    "turnover": float(top["avg_turnover"]),
                },
                "series": [[date.strftime("%Y-%m-%d"), round(row.top, 3), round(row.worst, 3), round(row.bench, 3)] for date, row in nav.iterrows()],
            }
        )
    return candidates


def gate_data(raw: pd.DataFrame, rel: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    raw = raw.assign(
        outcome=raw["pass_gate"].map({True: "通过", False: "未通过"}),
        transform="原始变量",
        economic_read=raw["note"].fillna(""),
    ).sort_values(["pass_gate", "robust_score"], ascending=[False, False])
    rel = rel.assign(
        outcome=rel["pass_gate"].map({True: "通过", False: "未通过"}),
        family=rel["base_family"],
    ).sort_values(["pass_gate", "robust_score"], ascending=[False, False])
    raw_columns = ["label", "family", "source", "transform", "outcome", "coverage", "ratio_cagr", "top_worst_ratio_return", "robust_score", "economic_read", "fail_reasons"]
    rel_columns = ["raw_column", "family", "transform", "lag_observations", "outcome", "coverage", "ratio_cagr", "top_worst_ratio_return", "robust_score", "economic_read", "fail_reasons"]
    return records(raw, raw_columns), records(rel, rel_columns)


def build_report() -> dict:
    summary = pd.read_csv(RUN / "performance_summary.csv")
    candidates = pd.read_csv(RUN / "candidate_map.csv")
    definitions = pd.read_json(RUN / "metric_definitions.json")
    definition_labels = dict(zip(definitions["column"], definitions["label"]))
    raw = pd.read_csv(RAW_GATE)
    rel = pd.read_csv(REL_GATE)
    claims = pd.read_csv(RUN / "synergy_claims.csv").sort_values("synergy_score", ascending=False)
    subsets = pd.read_csv(RUN / "family_subset_results.csv").sort_values("robust_score", ascending=False)
    loo = pd.read_csv(RUN / "leave_one_out_results.csv").sort_values("loo_contribution", ascending=False)
    regime = pd.read_csv(RUN / "period_active_cagr_selected.csv").sort_values("post_active_cagr", ascending=False)
    official = pd.read_csv(RUN / "official_run_results.csv")
    manifest = json.loads((RUN / "manifest.json").read_text(encoding="utf-8"))
    raw_rows, relative_rows = gate_data(raw, rel)
    return {
        "title": "STOXX Europe 600 因子研究浏览器",
        "bucketNames": BUCKET_NAMES,
        "asOf": "2026-07-02",
        "runDate": "2026-07-10",
        "universe": "Weight in STOXX EUROPE 600 > 0",
        "benchmark": "STOXX EUROPE 600",
        "evidence": "官方精确 Top/Worst；20% 分位；市值加权；ICB 19 中性；月度信号，信号日后交易",
        "summary": {
            "rawTested": int(len(raw)),
            "rawPassed": int(raw["pass_gate"].sum()),
            "relativeTested": int(len(rel)),
            "relativePassed": int(rel["pass_gate"].sum()),
            "candidateMetrics": int(manifest["candidate_metric_count"]),
            "officialSuccess": int(official["status"].eq("success").sum()),
            "officialExpected": int(manifest["expected_run_count"]),
            "synergyClaims": int(len(claims)),
        },
        "periods": [
            ["all", "全样本", "2009-09-30", "2026-07-02"],
            ["pre", "2010-2019：前 2020 期", "2010-01-01", "2019-12-31"],
            ["covid", "2020-2021：疫情与政策反弹", "2020-01-01", "2021-12-31"],
            ["inflation", "2022-2023：通胀、能源与加息", "2022-01-01", "2023-12-31"],
            ["recent", "2024-2026：正常化与集中度上升", "2024-01-01", "2026-07-02"],
        ],
        "candidates": selection_data(summary, candidates, definition_labels, claims),
        "raw": raw_rows,
        "relative": relative_rows,
        "claims": records(claims.head(12), ["metric", "label", "buckets", "robust_score", "ratio_cagr", "top_worst_ratio_return", "synergy_score", "classification"]),
        "subsets": records(subsets.head(12), ["metric", "label", "buckets", "robust_score", "ratio_cagr", "top_worst_ratio_return", "classification"]),
        "loo": records(loo, ["left_out_bucket", "loo_contribution", "ratio_contribution", "classification"]),
        "regime": records(regime, ["metric", "label", "pre_active_cagr", "post_active_cagr", "all_active_cagr"]),
        "paths": {
            "run": str(RUN),
            "raw": str(RAW_GATE),
            "relative": str(REL_GATE),
            "claims": str(RUN / "synergy_claims.csv"),
            "report": str(RUN / "stoxx600_relative_synergy_report.md"),
            "vault": r"C:\GoogleDrive\笔记\卡片盒子\10_Investment\03_Factor_Research\2026-07-09 STOXX Europe 600 单变量与协同因子研究.md",
        },
    }


HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>STOXX Europe 600 因子研究浏览器</title>
<style>
:root{--bg:#f4f6f3;--paper:#fff;--ink:#17231f;--muted:#62716a;--line:#d6ded6;--green:#16765b;--teal:#137d8a;--amber:#b66a18;--blue:#3c5e89;--red:#a65045;--soft-green:#e9f2eb;--soft-teal:#e8f2f3;--soft-amber:#f7eee0;--shadow:0 10px 28px rgba(26,39,32,.07);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.5}a{color:var(--teal);text-decoration:none}a:hover{text-decoration:underline}.shell{max-width:1540px;margin:0 auto;padding:28px 24px 48px}.masthead{display:flex;align-items:end;justify-content:space-between;gap:24px;padding-bottom:19px;border-bottom:1px solid var(--line)}h1{margin:0;font-size:31px;line-height:1.18;font-weight:720;letter-spacing:0}.subhead{max-width:820px;margin:8px 0 0;color:var(--muted);font-size:15px}.stamp{flex:0 0 auto;padding:10px 12px;border:1px solid var(--line);background:var(--paper);border-radius:8px;box-shadow:var(--shadow);font-size:12px;color:var(--muted);text-align:right}.controls{display:grid;grid-template-columns:minmax(0,1fr) minmax(270px,.4fr);gap:12px;margin:17px 0 12px}.control{display:grid;gap:5px;font-size:12px;font-weight:700;color:var(--muted)}select{width:100%;min-height:42px;padding:9px 11px;border:1px solid var(--line);background:var(--paper);border-radius:7px;color:var(--ink);font:inherit}.metrics{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin:0 0 16px}.metric{padding:11px 12px;border-right:1px solid var(--line);min-height:77px}.metric:last-child{border-right:0}.metric span{display:block;font-size:11px;color:var(--muted)}.metric strong{display:block;margin-top:5px;font-size:19px;line-height:1.08;font-weight:750}.layout{display:grid;grid-template-columns:minmax(250px,.76fr) minmax(510px,1.85fr) minmax(270px,.86fr);gap:14px;align-items:start}.panel{background:var(--paper);border:1px solid var(--line);border-radius:8px;box-shadow:var(--shadow);padding:15px;margin-bottom:14px}.panel h2{margin:0 0 10px;font-size:16px;letter-spacing:0}.panel p{margin:0;color:var(--muted);font-size:13px}.chart-panel{padding:15px 15px 10px}.chart-context{display:flex;justify-content:space-between;gap:16px;margin-bottom:9px}.strategy-name{font-size:18px;font-weight:740;line-height:1.25}.strategy-meta{font-size:12px;color:var(--muted);text-align:right}.chart{height:435px}.chart svg{display:block;width:100%;height:100%}.legend{display:flex;gap:14px;flex-wrap:wrap;margin:8px 0 4px;color:var(--muted);font-size:12px}.legend i{display:inline-block;width:10px;height:10px;margin-right:5px;border-radius:2px}.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}.chip{padding:4px 7px;background:#f6f8f5;border:1px solid var(--line);border-radius:6px;font-size:11px;color:var(--ink)}.period-list{display:grid;gap:0}.period-btn{display:grid;grid-template-columns:1fr auto;gap:8px;width:100%;border:0;border-bottom:1px solid #e6ece6;background:transparent;color:var(--ink);text-align:left;padding:9px 1px;font:inherit;cursor:pointer}.period-btn:last-child{border-bottom:0}.period-btn:hover,.period-btn.active{color:var(--teal)}.period-btn small{color:var(--muted);font-size:11px}.period-btn b{font-size:12px}.narrative{border-left:3px solid var(--green);padding-left:10px;color:var(--muted);font-size:13px}.evidence-list{display:grid;gap:8px}.evidence-row{padding-bottom:8px;border-bottom:1px solid #e6ece6}.evidence-row:last-child{padding-bottom:0;border-bottom:0}.evidence-row b{display:block;font-size:12px}.evidence-row span{font-size:12px;color:var(--muted)}.badge{display:inline-block;padding:3px 6px;border-radius:5px;font-size:11px;font-weight:700}.badge.good{background:var(--soft-green);color:var(--green)}.badge.warn{background:var(--soft-amber);color:var(--amber)}.badge.weak{background:#f6e9e7;color:var(--red)}.section-head{display:flex;justify-content:space-between;align-items:end;gap:12px;margin:24px 0 10px}.section-head h2{margin:0;font-size:20px}.section-head p{margin:0;color:var(--muted);font-size:12px}.evidence-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.wide{grid-column:1/-1}.table-wrap{overflow:auto;max-height:500px}table{border-collapse:collapse;width:100%;min-width:700px}th,td{padding:8px 7px;border-bottom:1px solid #e4eae4;text-align:left;vertical-align:top;font-size:12px;line-height:1.35}th{position:sticky;top:0;background:#f7f9f7;color:var(--muted);font-size:11px;z-index:1}td.num,th.num{text-align:right;white-space:nowrap}.link-button{border:0;background:transparent;padding:0;color:var(--teal);font:inherit;text-align:left;cursor:pointer}.link-button:hover{text-decoration:underline}.gate-toolbar{display:flex;gap:8px;align-items:center;margin:0 0 9px}.gate-toolbar label{font-size:12px;color:var(--muted)}.gate-toolbar select{min-height:34px;width:auto;padding:6px 8px;font-size:12px}.bar-chart{display:grid;gap:8px}.bar-row{display:grid;grid-template-columns:minmax(130px,1fr) minmax(70px,.55fr) 46px;gap:8px;align-items:center}.bar-label{font-size:12px;line-height:1.2;overflow-wrap:anywhere}.bar-track{height:9px;background:#eef2ee;overflow:hidden;border-radius:5px}.bar-fill{height:100%;background:var(--teal);border-radius:5px}.bar-row.negative .bar-fill{background:var(--red)}.bar-value{text-align:right;font-size:12px;font-weight:700}.footnote{margin:10px 0 0;font-size:11px;color:var(--muted)}.provenance{margin-top:18px;border-top:1px solid var(--line);padding-top:13px;font-size:11px;color:var(--muted);overflow-wrap:anywhere}.provenance a{overflow-wrap:anywhere}@media(max-width:1240px){.layout{grid-template-columns:minmax(0,1.45fr) minmax(300px,.8fr)}.chart-panel{grid-column:1;grid-row:1}.period-rail{grid-column:1;grid-row:2}.evidence-rail{grid-column:2;grid-row:1 / span 2}.metrics{grid-template-columns:repeat(4,minmax(0,1fr))}.metric:nth-child(4){border-right:0}.metric:nth-child(-n+4){border-bottom:1px solid var(--line)}}@media(max-width:850px){.masthead,.chart-context{display:block}.stamp,.strategy-meta{text-align:left;margin-top:10px}.controls,.evidence-grid{grid-template-columns:1fr}.layout{display:block}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.metric:nth-child(2n){border-right:0}.metric:nth-child(-n+6){border-bottom:1px solid var(--line)}.chart{height:340px}.wide{grid-column:auto}.shell{padding:20px 12px 36px}}
</style>
</head>
<body>
<main class="shell" id="explorer">
  <header class="masthead">
    <div><h1>STOXX Europe 600 因子研究浏览器</h1><p class="subhead">原始变量、同证券相对变量、组合与 leave-one-out 证据。所有结论均来自已完成的官方精确 Top/Worst 回测。</p></div>
    <div class="stamp" id="stamp"></div>
  </header>
  <section class="controls" aria-label="候选选择器">
    <label class="control">已验证候选<select id="candidate-select"></select></label>
    <label class="control">净值观察窗口<select id="period-select"></select></label>
  </section>
  <section class="metrics" id="metrics" aria-label="全样本官方指标"></section>
  <section class="layout">
    <aside class="period-rail">
      <section class="panel"><h2>时期主动表现</h2><p>点击任意时期，中央图以该期首月归一为 100。数值是 Top / Benchmark 主动 CAGR。</p><div class="period-list" id="period-list"></div></section>
      <section class="panel"><h2>2020 前后：结论</h2><p class="narrative">证据支持“定价机制发生改变”，但不支持“所有旧因子失效”。静态质量、静态杠杆和 EPS revision 仍有正贡献；相对变量最稳定地补强了利润率、ROE 与去杠杆的边际改善。</p></section>
      <section class="panel"><h2>选中策略的组成</h2><div class="chips" id="strategy-chips"></div><p class="footnote" id="strategy-note"></p></section>
    </aside>
    <section class="panel chart-panel">
      <div class="chart-context"><div><div class="strategy-name" id="strategy-name"></div><div class="chips" id="strategy-claim"></div></div><div class="strategy-meta" id="strategy-meta"></div></div>
      <div class="chart" id="chart" aria-label="Top、Worst 与 Benchmark 净值图"></div>
      <div class="legend"><span><i style="background:#16765b"></i>Top</span><span><i style="background:#a65045"></i>Worst</span><span><i style="background:#3c5e89"></i>Benchmark</span></div>
      <p class="footnote">月末净值抽样，仅用于本页交互显示；绩效指标与 gate 判定仍以完整日频官方输出计算。</p>
    </section>
    <aside class="evidence-rail">
      <section class="panel"><h2>研究口径</h2><div class="evidence-list" id="research-facts"></div></section>
      <section class="panel"><h2>完整模型的 leave-one-out</h2><p>正值表示移除后 robust score 下降；这才支持“对完整模型有贡献”的说法。</p><div class="bar-chart" id="loo-chart"></div></section>
      <section class="panel"><h2>解释边界</h2><p>pair、subset 或 leave-one-out 缺一不可。页面不会把经济直觉、core/supplement 标签或单个组合高回报自动写成 synergy。</p></section>
    </aside>
  </section>
  <section class="section-head"><div><h2>单变量 Gate</h2><p>CIQ、FactSet、database 与本地衍生字段使用相同门槛：coverage >= 75%、Top/Benchmark CAGR > 0、Top/Worst > 0、robust score > 0。</p></div><p id="gate-summary"></p></section>
  <section class="evidence-grid">
    <section class="panel"><h2>Raw variables</h2><div class="gate-toolbar"><label>显示 <select id="raw-mode"><option value="pass">通过 gate</option><option value="all">全部</option><option value="fail">未通过</option></select></label></div><div class="table-wrap" id="raw-table"></div></section>
    <section class="panel"><h2>Same-security relative variables</h2><div class="gate-toolbar"><label>显示 <select id="relative-mode"><option value="pass">通过 gate</option><option value="all">全部</option><option value="fail">未通过</option></select></label></div><div class="table-wrap" id="relative-table"></div></section>
  </section>
  <section class="section-head"><div><h2>协同与组合证据</h2><p>直接协同只列入已通过 `synergy_claims.csv` 的结论；family subset 必须单独阅读其分类。</p></div><p id="claim-summary"></p></section>
  <section class="evidence-grid">
    <section class="panel"><h2>直接 pair synergy</h2><div class="table-wrap" id="claims-table"></div></section>
    <section class="panel"><h2>Family subset 结果</h2><div class="table-wrap" id="subsets-table"></div></section>
    <section class="panel wide"><h2>2020 regime break：选定变量/组合的主动 CAGR</h2><p>前期为 2010-2019；后期为 2020-2026-07。该表用于辨别“机制变弱”与“机制换挡”，不是对 2026 年末或 2027 年的预测。</p><div class="table-wrap" id="regime-table"></div></section>
  </section>
  <footer class="provenance" id="provenance"></footer>
</main>
<script id="report-data" type="application/json">__DATA__</script>
<script>
(() => {
  const report = JSON.parse(document.getElementById('report-data').textContent);
  const $ = id => document.getElementById(id);
  const pct = value => `${(value * 100).toFixed(1)}%`;
  const num = value => Number(value).toFixed(2);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const asFile = path => `file:///${path.replace(/\\/g, '/')}`;
  const periodMap = Object.fromEntries(report.periods.map(period => [period[0], period]));
  let currentMetric = report.candidates[0].metric;
  let currentPeriod = 'all';

  $('stamp').innerHTML = `官方完成：<strong>${report.summary.officialSuccess} / ${report.summary.officialExpected}</strong><br>运行完成 ${report.runDate} · 净值截至 ${report.asOf}`;
  $('candidate-select').innerHTML = report.candidates.map(candidate => `<option value="${candidate.metric}">${escape(candidate.name)}</option>`).join('');
  $('period-select').innerHTML = report.periods.map(([id,label]) => `<option value="${id}">${escape(label)}</option>`).join('');
  $('gate-summary').textContent = `raw ${report.summary.rawPassed}/${report.summary.rawTested} 通过 · relative ${report.summary.relativePassed}/${report.summary.relativeTested} 通过`;
  $('claim-summary').textContent = `${report.summary.candidateMetrics} 个候选 · ${report.summary.synergyClaims} 个支持的 synergy claim`;
  $('research-facts').innerHTML = [
    ['Universe', report.universe], ['Benchmark', report.benchmark], ['Evidence', report.evidence], ['Raw gate', `${report.summary.rawPassed} / ${report.summary.rawTested} 通过`], ['Relative gate', `${report.summary.relativePassed} / ${report.summary.relativeTested} 通过`], ['协同矩阵', `${report.summary.officialSuccess} 个官方 Top/Worst side 全部成功`]
  ].map(([label,value]) => `<div class="evidence-row"><b>${escape(label)}</b><span>${escape(value)}</span></div>`).join('');

  function candidate(){ return report.candidates.find(item => item.metric === currentMetric); }
  function periodSlice(series, periodId){
    const [, , start, end] = periodMap[periodId];
    return series.filter(([date]) => date >= start && date <= end);
  }
  function stat(series){
    if(series.length < 2) return null;
    const start = series[0], end = series.at(-1);
    const years = Math.max((Date.parse(end[0]) - Date.parse(start[0])) / 31557600000, 1 / 12);
    return {top: Math.pow(end[1] / start[1], 1 / years) - 1, active: Math.pow((end[1] / end[3]) / (start[1] / start[3]), 1 / years) - 1, spread: Math.pow((end[1] / end[2]) / (start[1] / start[2]), 1 / years) - 1};
  }
  function renderMetrics(item){
    const m = item.metrics;
    const values = [['Robust score', num(m.robust)], ['Top CAGR', pct(m.topCagr)], ['Top / Benchmark CAGR', pct(m.activeCagr)], ['Top / Worst ratio', `${m.topWorst.toFixed(2)}x`], ['Active DD', pct(m.activeDd)], ['Tracking error', pct(m.te)], ['Coverage', pct(m.coverage)], ['Turnover', pct(m.turnover)]];
    $('metrics').innerHTML = values.map(([label,value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join('');
  }
  function svgElement(name, attrs = {}){ const node = document.createElementNS('http://www.w3.org/2000/svg', name); Object.entries(attrs).forEach(([key,value]) => node.setAttribute(key, value)); return node; }
  function renderChart(item){
    const series = periodSlice(item.series, currentPeriod);
    const root = $('chart'); root.replaceChildren();
    if(series.length < 2){ root.textContent = '当前窗口没有足够的净值观测。'; return; }
    const width = 960, height = 435, left = 57, right = 22, top = 18, bottom = 38;
    const normalized = series.map(([date,topValue,worstValue,benchValue]) => [date, topValue / series[0][1] * 100, worstValue / series[0][2] * 100, benchValue / series[0][3] * 100]);
    const values = normalized.flatMap(row => row.slice(1)).filter(Number.isFinite).map(Math.log);
    const low = Math.min(...values), high = Math.max(...values), span = Math.max(high - low, .08);
    const x = index => left + index / (normalized.length - 1) * (width - left - right);
    const y = value => top + (high - Math.log(value)) / span * (height - top - bottom);
    const svg = svgElement('svg', {viewBox:`0 0 ${width} ${height}`, role:'img', 'aria-label':`${item.name} 的 Top、Worst 与 Benchmark 净值`});
    for(let tick = 0; tick <= 4; tick++){
      const logValue = low + span * tick / 4, value = Math.exp(logValue), yy = y(value);
      svg.append(svgElement('line',{x1:left,y1:yy,x2:width-right,y2:yy,stroke:'#e5ebe5','stroke-width':'1'}));
      const text = svgElement('text',{x:left-8,y:yy+4,'text-anchor':'end',fill:'#62716a','font-size':'11'}); text.textContent = value.toFixed(0); svg.append(text);
    }
    [0,.25,.5,.75,1].forEach(fraction => { const index = Math.round((normalized.length - 1) * fraction), point = normalized[index], text = svgElement('text',{x:x(index),y:height-13,'text-anchor':fraction===0?'start':fraction===1?'end':'middle',fill:'#62716a','font-size':'11'}); text.textContent = point[0].slice(0,7); svg.append(text); });
    [['Top',1,'#16765b'],['Worst',2,'#a65045'],['Benchmark',3,'#3c5e89']].forEach(([,key,color]) => { const d = normalized.map((row,index) => `${index ? 'L':'M'}${x(index).toFixed(2)},${y(row[key]).toFixed(2)}`).join(' '); svg.append(svgElement('path',{d,fill:'none',stroke:color,'stroke-width':'2.2','stroke-linejoin':'round','stroke-linecap':'round'})); });
    root.append(svg);
  }
  function renderPeriods(item){
    $('period-list').innerHTML = report.periods.map(([id,label]) => { const stats = stat(periodSlice(item.series,id)); return `<button class="period-btn ${id === currentPeriod ? 'active' : ''}" data-period="${id}"><span>${escape(label)}<small>${stats ? ` · Top/Worst ${pct(stats.spread)}` : ''}</small></span><b>${stats ? pct(stats.active) : 'n/a'}</b></button>`; }).join('');
    document.querySelectorAll('[data-period]').forEach(button => button.addEventListener('click', () => { currentPeriod = button.dataset.period; $('period-select').value = currentPeriod; render(); }));
  }
  function claimBadge(item){
    if(item.claim === 'synergistic') return '<span class="badge good">已支持 synergistic</span>';
    if(item.kind === 'full_model') return '<span class="badge warn">诊断基准，不作 synergy claim</span>';
    return '<span class="badge warn">组合验证，需以 claims 表分类为准</span>';
  }
  function renderStrategy(item){
    $('strategy-name').textContent = item.name;
    $('strategy-meta').innerHTML = `${escape(item.officialLabel)}<br>全样本 official exact`;
    $('strategy-chips').innerHTML = item.buckets.map(value => `<span class="chip">${escape(value)}</span>`).join('') + item.components.map(value => `<span class="chip">${escape(value)}</span>`).join('');
    $('strategy-note').textContent = item.note;
    $('strategy-claim').innerHTML = claimBadge(item);
  }
  function gateTable(kind){
    const mode = $(kind + '-mode').value, rows = report[kind].filter(row => mode === 'all' || (mode === 'pass' && row.outcome === '通过') || (mode === 'fail' && row.outcome === '未通过'));
    const isRaw = kind === 'raw';
    const first = isRaw ? '变量' : '变量';
    const name = row => isRaw ? row.label : `${row.raw_column} · ${row.transform} lag${row.lag_observations}`;
    const source = row => isRaw ? row.source : row.economic_read;
    $(kind + '-table').innerHTML = `<table><thead><tr><th>${first}</th><th>Family / 解释</th><th>结果</th><th class="num">Coverage</th><th class="num">主动 CAGR</th><th class="num">Top/Worst</th><th class="num">Robust</th></tr></thead><tbody>${rows.map(row => `<tr><td>${escape(name(row))}</td><td>${escape(isRaw ? `${row.family} · ${source(row)}` : `${row.family} · ${source(row)}`)}</td><td><span class="badge ${row.outcome === '通过' ? 'good' : 'weak'}">${row.outcome}</span></td><td class="num">${pct(row.coverage)}</td><td class="num">${pct(row.ratio_cagr)}</td><td class="num">${Number(row.top_worst_ratio_return).toFixed(2)}x</td><td class="num">${num(row.robust_score)}</td></tr>`).join('')}</tbody></table>`;
  }
  function compactTable(id, rows, headers, build){
    $(id).innerHTML = `<table><thead><tr>${headers.map(([label,num]) => `<th class="${num ? 'num' : ''}">${label}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${build(row).map(([value,num]) => `<td class="${num ? 'num' : ''}">${value}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  }
  function renderEvidence(){
    compactTable('claims-table',report.claims,[['Pair',false],['Buckets',false],['Robust',true],['主动 CAGR',true],['Top/Worst',true],['Synergy score',true]],row => [[escape(row.label),false],[escape(row.buckets.replaceAll('|',' + ')),false],[num(row.robust_score),true],[pct(row.ratio_cagr),true],[`${Number(row.top_worst_ratio_return).toFixed(2)}x`,true],[num(row.synergy_score),true]]);
    compactTable('subsets-table',report.subsets,[['Subset',false],['Buckets',false],['分类',false],['Robust',true],['主动 CAGR',true],['Top/Worst',true]],row => [[escape(row.label),false],[escape(row.buckets.replaceAll('|',' + ')),false],[`<span class="badge ${row.classification === 'synergistic' ? 'good' : 'warn'}">${escape(row.classification)}</span>`,false],[num(row.robust_score),true],[pct(row.ratio_cagr),true],[`${Number(row.top_worst_ratio_return).toFixed(2)}x`,true]]);
    compactTable('regime-table',report.regime,[['变量 / 组合',false],['2010-2019',true],['2020-2026',true],['全样本',true],['变化',true]],row => { const delta = Number(row.post_active_cagr) - Number(row.pre_active_cagr); return [[escape(row.label),false],[pct(row.pre_active_cagr),true],[pct(row.post_active_cagr),true],[pct(row.all_active_cagr),true],[`<span class="badge ${delta >= 0 ? 'good' : 'weak'}">${delta >= 0 ? '+' : ''}${pct(delta)}</span>`,true]]; });
    const loo = report.loo, max = Math.max(...loo.map(row => Math.abs(Number(row.loo_contribution))), .01);
    $('loo-chart').innerHTML = loo.map(row => { const value = Number(row.loo_contribution), width = Math.abs(value) / max * 100; return `<div class="bar-row ${value < 0 ? 'negative' : ''}"><span class="bar-label">${escape(report.bucketNames[row.left_out_bucket] || row.left_out_bucket)}</span><span class="bar-track"><span class="bar-fill" style="width:${width}%"></span></span><span class="bar-value">${value >= 0 ? '+' : ''}${num(value)}</span></div>`; }).join('');
  }
  function render(){ const item = candidate(); renderMetrics(item); renderStrategy(item); renderPeriods(item); renderChart(item); }
  $('candidate-select').addEventListener('change', event => { currentMetric = event.target.value; render(); });
  $('period-select').addEventListener('change', event => { currentPeriod = event.target.value; render(); });
  $('raw-mode').addEventListener('change', () => gateTable('raw'));
  $('relative-mode').addEventListener('change', () => gateTable('relative'));
  gateTable('raw'); gateTable('relative'); renderEvidence(); render();
  $('provenance').innerHTML = `数据来源：<a href="${asFile(report.paths.run)}">最终官方运行目录</a> · <a href="${asFile(report.paths.raw)}">raw gate</a> · <a href="${asFile(report.paths.relative)}">relative gate</a> · <a href="${asFile(report.paths.claims)}">synergy claims</a> · <a href="${asFile(report.paths.report)}">研究报告</a> · <a href="${asFile(report.paths.vault)}">卡片盒子解释报告</a><br>本页为研究展示，不构成投资建议。`;
})();
</script>
</body>
</html>
'''


def main() -> None:
    report = build_report()
    payload = json.dumps(report, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    OUTPUT.write_text(HTML.replace("__DATA__", payload), encoding="utf-8")
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()

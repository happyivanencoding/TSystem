"""Build a standalone interactive explorer from official MSCI EUR SMALL runs."""

from __future__ import annotations

import json
import importlib.util
from collections import defaultdict
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "07_backtest_code" / "runs" / "ad_hoc"
SYNERGY_DIR = RUNS / "eu_small_relative_synergy_20260709"
RELATIVE_DIR = RUNS / "eu_small_relative_variables_20260709"
RAW_DIR = RUNS / "eu_small_multifactor_20260707_085611"
VALIDATED_DIR = RUNS / "eu_small_validated_gate_20260708_official"
QVM_CONFIG = ROOT / "15_small_cap_model" / "config" / "eu_small_validated_qvm.json"
FRAGMENT = (
    ROOT
    / ".codex"
    / "visualizations"
    / "2026"
    / "07"
    / "10"
    / "eu-small-factor-explorer"
    / "eu-small-factor-explorer.html"
)
STANDALONE = ROOT / "09_reports" / "eu-small-factor-explorer.html"
VISUALIZE_RENDERER = Path(
    r"C:\Users\jingx\.codex\plugins\cache\openai-bundled\visualize\1.0.11\skills\visualize\scripts\render.py"
)

PERIODS = [
    ("all", "全样本", "2005-03-31", "2026-06-30"),
    ("2005-2007", "Pre-GFC 信贷扩张", "2005-03-31", "2007-12-31"),
    ("2008-2012", "GFC 与欧债危机", "2008-01-01", "2012-12-31"),
    ("2013-2016", "ECB 低利率 / QE", "2013-01-01", "2016-12-31"),
    ("2017-2019", "后周期低利率扩张", "2017-01-01", "2019-12-31"),
    ("2020-2021", "疫情冲击与政策反弹", "2020-01-01", "2021-12-31"),
    ("2022-2023", "通胀、能源与加息冲击", "2022-01-01", "2023-12-31"),
    ("2024-2026", "通胀回落与政策正常化", "2024-01-01", "2026-06-30"),
]


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def score_rows(path: Path) -> pd.DataFrame:
    frame = read_csv(path)
    return frame[frame["status"].eq("success") & frame["valid"].astype(str).eq("True")].copy()


def metric_index(frame: pd.DataFrame) -> dict[tuple[str, str], pd.Series]:
    return {
        (str(row.metric), str(row.side)): row
        for row in frame.itertuples(index=False)
    }


def num(value: object, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if pd.notna(parsed) else default


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def number(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


NAV_CACHE: dict[str, pd.DataFrame] = {}


def nav_frame(parquet_path: str) -> pd.DataFrame:
    csv_path = str(parquet_path).replace(".parquet", ".csv")
    if csv_path not in NAV_CACHE:
        raw = pd.read_csv(csv_path)
        raw = raw.iloc[:, :2].copy()
        raw.columns = ["date", "nav"]
        raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
        raw["nav"] = pd.to_numeric(raw["nav"], errors="coerce")
        NAV_CACHE[csv_path] = raw.dropna().sort_values("date")
    return NAV_CACHE[csv_path].copy()


def joined_nav(top: pd.Series, worst: pd.Series) -> pd.DataFrame:
    top_nav = nav_frame(str(top.perf_ptf)).rename(columns={"nav": "top"})
    worst_nav = nav_frame(str(worst.perf_ptf)).rename(columns={"nav": "worst"})
    bench_nav = nav_frame(str(top.perf_bench)).rename(columns={"nav": "bench"})
    merged = top_nav.merge(worst_nav, on="date", how="inner").merge(bench_nav, on="date", how="inner")
    return merged.sort_values("date").dropna()


def period_stats(frame: pd.DataFrame) -> dict[str, dict[str, float | str | None]]:
    result: dict[str, dict[str, float | str | None]] = {}
    for period_id, _, start, end in PERIODS:
        subset = frame[(frame["date"] >= start) & (frame["date"] <= end)].copy()
        if len(subset) < 2:
            continue
        first, last = subset.iloc[0], subset.iloc[-1]
        days = max((last.date - first.date).days, 1)
        active = subset["top"] / subset["bench"]
        top_worst = subset["top"] / subset["worst"]
        active_cagr = (active.iloc[-1] / active.iloc[0]) ** (365.25 / days) - 1
        top_cagr = (last.top / first.top) ** (365.25 / days) - 1
        tw_cagr = (top_worst.iloc[-1] / top_worst.iloc[0]) ** (365.25 / days) - 1
        drawdown = (active / active.cummax() - 1).min()
        result[period_id] = {
            "start": first.date.strftime("%Y-%m-%d"),
            "end": last.date.strftime("%Y-%m-%d"),
            "activeCagr": round(active_cagr, 6),
            "topCagr": round(top_cagr, 6),
            "topWorstCagr": round(tw_cagr, 6),
            "activeDrawdown": round(float(drawdown), 6),
        }
    return result


def monthly_series(frame: pd.DataFrame) -> list[dict[str, float | str]]:
    monthly = frame.set_index("date").resample("ME").last().dropna().reset_index()
    base = monthly.iloc[0]
    return [
        {
            "d": row.date.strftime("%Y-%m-%d"),
            "t": round(float(row.top / base.top * 100), 3),
            "w": round(float(row.worst / base.worst * 100), 3),
            "b": round(float(row.bench / base.bench * 100), 3),
        }
        for row in monthly.itertuples(index=False)
    ]


def load_definitions(path: Path) -> dict[str, dict]:
    definitions = {}
    for item in json.loads(path.read_text(encoding="utf-8")):
        definitions[str(item["column"])] = item.get("components", {})
    return definitions


def enrich_raw_labels() -> tuple[dict[str, dict], dict[str, str]]:
    selected = read_csv(SYNERGY_DIR / "selected_legs.csv")
    raw_meta = {}
    labels = {}
    for row in selected.itertuples(index=False):
        metric = str(row.metric)
        raw_meta[metric] = {
            "label": str(row.label),
            "bucket": str(row.bucket),
            "economic": str(row.economic_role),
            "source": str(row.source_type),
        }
        labels[metric] = str(row.label)
    raw_gate = read_csv(VALIDATED_DIR / "raw_validation_gate.csv")
    for row in raw_gate.itertuples(index=False):
        metric = str(row.metric)
        labels.setdefault(metric, str(row.label))
    return raw_meta, labels


def add_qvm_definition(definitions: dict[str, dict], labels: dict[str, str]) -> None:
    config = json.loads(QVM_CONFIG.read_text(encoding="utf-8"))
    components = {}
    for family, family_weight in config["final_weights"].items():
        variables = config["subfactors"][family]["variables"]
        family_key = f"qvm::{family}"
        family_components = {}
        for variable in variables:
            raw_key = f"raw::{variable['column']}"
            family_components[raw_key] = 1 / len(variables)
            direction = "高为好" if variable["direction"] > 0 else "低为好"
            labels[raw_key] = f"{variable['column']}（{direction}）"
        definitions[family_key] = family_components
        labels[family_key] = f"{family}"
        components[family_key] = family_weight
    definitions["eu_small_validated_qvm"] = components


def expand_weights(
    metric: str,
    definitions: dict[str, dict],
    labels: dict[str, str],
    weight: float = 1.0,
    trail: tuple[str, ...] = (),
) -> list[dict[str, object]]:
    components = definitions.get(metric)
    if not components:
        return [{"metric": metric, "label": labels.get(metric, metric), "weight": weight, "path": " > ".join(trail)}]
    expanded: list[dict[str, object]] = []
    for child, child_weight in components.items():
        child_label = labels.get(child, child.replace("eu_small_syn_bucket_", ""))
        expanded.extend(
            expand_weights(
                str(child), definitions, labels, weight * float(child_weight), trail + (child_label,)
            )
        )
    return expanded


def direct_components(metric: str, definitions: dict[str, dict], labels: dict[str, str]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], float] = defaultdict(float)
    for item in expand_weights(metric, definitions, labels):
        grouped[(str(item["metric"]), str(item["path"]))] += float(item["weight"])
    rows = [
        {"metric": key[0], "label": labels.get(key[0], key[0]), "path": key[1], "weight": round(value, 6)}
        for key, value in grouped.items()
    ]
    return sorted(rows, key=lambda row: (-float(row["weight"]), str(row["label"])))


def root_components(metric: str, definitions: dict[str, dict], labels: dict[str, str]) -> list[dict[str, object]]:
    components = definitions.get(metric, {})
    return [
        {"label": labels.get(child, str(child).replace("eu_small_syn_bucket_", "")), "weight": round(float(weight), 6)}
        for child, weight in components.items()
    ]


def main() -> None:
    raw_meta, labels = enrich_raw_labels()
    definitions = load_definitions(SYNERGY_DIR / "metric_definitions.json")
    definitions.update(load_definitions(VALIDATED_DIR / "metric_definitions.json"))
    add_qvm_definition(definitions, labels)

    sources = {
        "latest": metric_index(score_rows(SYNERGY_DIR / "performance_summary.csv")),
        "relative": metric_index(score_rows(RELATIVE_DIR / "performance_summary.csv")),
        "raw": metric_index(score_rows(RAW_DIR / "performance_summary.csv")),
        "validated": metric_index(score_rows(VALIDATED_DIR / "performance_summary.csv")),
    }
    candidate_map = read_csv(SYNERGY_DIR / "candidate_map.csv").set_index("metric")
    synergy = read_csv(SYNERGY_DIR / "synergy_claims.csv")
    subsets = read_csv(SYNERGY_DIR / "family_subset_results.csv").sort_values("robust_score", ascending=False)
    leave_one_out = read_csv(SYNERGY_DIR / "leave_one_out_results.csv")

    chosen: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()

    def choose(metric: str, group: str, source: str, evidence: str) -> None:
        if metric not in seen:
            chosen.append((metric, group, source, evidence))
            seen.add(metric)

    for metric in [
        "eu_small_syn_subset_ee96431827",
        "eu_small_syn_subset_08e95a53d5",
        "eu_small_syn_full_bucket_equal",
    ]:
        choose(metric, "最新核心组合", "latest", "family subset / full model official evidence")
    for metric in synergy.loc[synergy["classification"].eq("synergistic"), "metric"]:
        choose(str(metric), "已证实协同 pair", "latest", "pair synergy official evidence")
    for metric in subsets.head(20)["metric"]:
        choose(str(metric), "领先 family subset", "latest", "family subset official evidence")
    for metric in leave_one_out["metric"]:
        choose(str(metric), "最新 leave-one-out", "latest", "leave-one-out official evidence")
    for metric in raw_meta:
        source = "relative" if (metric, "Top") in sources["relative"] else "raw"
        choose(metric, "通过 gate 的单变量", source, "raw / relative raw official evidence")
    for metric in [
        "eu_small_validated_qvm",
        "eu_small_validated_quality_momentum",
        "eu_small_validated_quality_value",
        "eu_small_validated_value_momentum",
        "eu_small_validated_all_equal",
        "eu_small_validated_loo_growth",
    ]:
        choose(metric, "历史生产候选", "validated", "validated-family official evidence")

    candidates = []
    missing = []
    for metric, group, source_name, evidence in chosen:
        index = sources[source_name]
        top = index.get((metric, "Top"))
        worst = index.get((metric, "Worst"))
        if top is None or worst is None:
            missing.append(metric)
            continue
        try:
            nav = joined_nav(top, worst)
        except FileNotFoundError:
            missing.append(metric)
            continue
        label = labels.get(metric)
        if not label and metric in candidate_map.index:
            label = str(candidate_map.loc[metric, "label"])
        label = label or str(top.label)
        labels[metric] = label
        top_metrics = {
            "robust": num(top.robust_score),
            "coverage": num(top.coverage),
            "topCagr": num(top.cagr),
            "activeCagr": num(top.ratio_cagr),
            "activeDrawdown": num(top.ratio_max_drawdown),
            "trackingError": num(top.tracking_error),
            "topWorstReturn": num(top.top_worst_ratio_return),
            "turnover": num(top.avg_turnover),
            "hitRate": num(top.annual_active_hit_rate),
            "rolling3y": num(top.rolling_3y_min_ratio_cagr),
        }
        raw_weight_rows = direct_components(metric, definitions, labels)
        if metric in raw_meta and not raw_weight_rows:
            raw_weight_rows = [{"metric": metric, "label": label, "path": raw_meta[metric]["bucket"], "weight": 1.0}]
        candidates.append(
            {
                "metric": metric,
                "label": label,
                "group": group,
                "evidence": evidence,
                "type": str(getattr(top, "role", "official candidate")),
                "note": str(getattr(top, "note", "")),
                "source": source_name,
                "rawMeta": raw_meta.get(metric, {}),
                "metrics": top_metrics,
                "series": monthly_series(nav),
                "periods": period_stats(nav),
                "rootWeights": root_components(metric, definitions, labels),
                "rawWeights": raw_weight_rows,
            }
        )

    candidates.sort(key=lambda candidate: (candidate["group"] != "最新核心组合", -float(candidate["metrics"]["robust"] or -999)))
    data = {
        "title": "MSCI Europe Small 因子研究浏览器",
        "asOf": "2026-06-30",
        "universe": "Weight in MSCI EUR SMALL > 0",
        "benchmark": "MSCI EUR SMALL",
        "evidence": "official exact Top/Worst; 20% Top/Worst; ICB 19 中性；monthly signal",
        "periods": [
            {"id": period_id, "label": label, "start": start, "end": end}
            for period_id, label, start, end in PERIODS
        ],
        "defaultMetric": "eu_small_syn_subset_ee96431827",
        "candidateCount": len(candidates),
        "missing": missing,
        "candidates": candidates,
        "provenance": {
            "latestSynergy": str(SYNERGY_DIR),
            "relativeRaw": str(RELATIVE_DIR),
            "rawGate": str(RAW_DIR),
            "validatedQvm": str(VALIDATED_DIR),
        },
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    fragment = html_fragment(payload)
    FRAGMENT.parent.mkdir(parents=True, exist_ok=True)
    FRAGMENT.write_text(fragment, encoding="utf-8")
    write_standalone()
    print(f"Wrote {FRAGMENT}")
    print(f"Wrote {STANDALONE}")
    print(f"Candidates: {len(candidates)}; missing: {len(missing)}; bytes: {FRAGMENT.stat().st_size}")


def write_standalone() -> None:
    spec = importlib.util.spec_from_file_location("tp_visualize_renderer", VISUALIZE_RENDERER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load visualization renderer: {VISUALIZE_RENDERER}")
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    document = renderer.render(FRAGMENT, "MSCI Europe Small Factor Explorer")
    shell_style = "body{box-sizing:border-box;padding:1rem;background:inherit}iframe{display:block;width:100%;max-width:736px;height:calc(100vh - 2rem);margin:0 auto;border:0}"
    full_width_style = "body{box-sizing:border-box;padding:0;background:inherit}iframe{display:block;width:100%;max-width:none;height:100vh;margin:0;border:0}"
    if shell_style not in document:
        raise RuntimeError("Visualization shell style changed; full-width override needs review")
    STANDALONE.write_text(document.replace(shell_style, full_width_style), encoding="utf-8")


def html_fragment(payload: str) -> str:
    return f'''<div id="eu-small-factor-explorer" class="research-explorer">
  <style>
    #eu-small-factor-explorer {{
      --bg: #f6f7f4; --surface: #ffffff; --ink: #17312d; --muted: #60716d; --line: #d9e0da;
      --green: #237657; --teal: #087f86; --amber: #b87518; --red: #a84e43; --blue: #516a9b;
      color: var(--ink); background: var(--bg); font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    }}
    #eu-small-factor-explorer * {{ box-sizing: border-box; }}
    #eu-small-factor-explorer .shell {{ max-width: 1440px; margin: 0 auto; padding: 28px 24px 44px; }}
    #eu-small-factor-explorer .masthead {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-end; padding-bottom:18px; border-bottom:1px solid var(--line); }}
    #eu-small-factor-explorer h1 {{ margin:0; font-size:30px; letter-spacing:0; }}
    #eu-small-factor-explorer .subhead {{ color:var(--muted); margin:8px 0 0; line-height:1.55; }}
    #eu-small-factor-explorer .stamp {{ color:var(--muted); font-size:12px; line-height:1.55; text-align:right; white-space:nowrap; }}
    #eu-small-factor-explorer .controls {{ display:grid; grid-template-columns:minmax(0, 1fr) minmax(230px, .42fr); gap:12px; margin:18px 0; }}
    #eu-small-factor-explorer label {{ display:grid; gap:5px; color:var(--muted); font-size:12px; font-weight:700; }}
    #eu-small-factor-explorer select {{ width:100%; border:1px solid var(--line); border-radius:6px; background:var(--surface); color:var(--ink); padding:10px 12px; font:inherit; }}
    #eu-small-factor-explorer .metric-grid {{ display:grid; grid-template-columns:repeat(6, minmax(0, 1fr)); gap:10px; margin:12px 0 16px; }}
    #eu-small-factor-explorer .metric {{ padding:11px 12px; background:var(--surface); border:1px solid var(--line); border-radius:6px; min-height:76px; }}
    #eu-small-factor-explorer .metric span {{ display:block; color:var(--muted); font-size:11px; line-height:1.35; }}
    #eu-small-factor-explorer .metric strong {{ display:block; font-size:20px; margin-top:4px; }}
    #eu-small-factor-explorer .layout {{ display:grid; grid-template-columns:minmax(250px, .72fr) minmax(560px, 1.75fr) minmax(285px, .88fr); gap:14px; align-items:start; }}
    #eu-small-factor-explorer .left-rail, #eu-small-factor-explorer .right-rail, #eu-small-factor-explorer .chart-column {{ min-width:0; }}
    #eu-small-factor-explorer .block {{ background:var(--surface); border:1px solid var(--line); border-radius:6px; padding:15px; margin-bottom:14px; }}
    #eu-small-factor-explorer h2 {{ margin:0 0 11px; font-size:17px; letter-spacing:0; }}
    #eu-small-factor-explorer h3 {{ margin:15px 0 8px; font-size:14px; }}
    #eu-small-factor-explorer .chart {{ width:100%; min-height:450px; }}
    #eu-small-factor-explorer .legend {{ display:flex; flex-wrap:wrap; gap:12px; color:var(--muted); font-size:12px; margin:8px 0 0; }}
    #eu-small-factor-explorer .legend i {{ display:inline-block; width:9px; height:9px; margin-right:5px; border-radius:2px; }}
    #eu-small-factor-explorer .context {{ display:flex; justify-content:space-between; gap:16px; margin-bottom:10px; }}
    #eu-small-factor-explorer .context .name {{ font-weight:800; font-size:18px; line-height:1.35; }}
    #eu-small-factor-explorer .context .meta {{ color:var(--muted); font-size:12px; line-height:1.5; text-align:right; }}
    #eu-small-factor-explorer .weights {{ display:flex; flex-wrap:wrap; gap:7px; }}
    #eu-small-factor-explorer .weight-chip {{ border:1px solid var(--line); background:#f7faf7; border-radius:999px; padding:5px 8px; font-size:11px; line-height:1.25; }}
    #eu-small-factor-explorer .weight-chip b {{ display:block; font-size:12px; }}
    #eu-small-factor-explorer table {{ width:100%; border-collapse:collapse; }}
    #eu-small-factor-explorer th, #eu-small-factor-explorer td {{ padding:8px 6px; border-bottom:1px solid #e8ece7; text-align:left; vertical-align:top; font-size:12px; line-height:1.4; }}
    #eu-small-factor-explorer th {{ color:var(--muted); font-size:11px; font-weight:700; }}
    #eu-small-factor-explorer td.num, #eu-small-factor-explorer th.num {{ text-align:right; white-space:nowrap; }}
    #eu-small-factor-explorer .table-scroll {{ overflow:auto; max-height:470px; }}
    #eu-small-factor-explorer .select-row {{ cursor:pointer; background:transparent; color:var(--ink); border:0; width:100%; text-align:left; padding:0; font:inherit; }}
    #eu-small-factor-explorer .select-row:hover {{ color:var(--teal); text-decoration:underline; }}
    #eu-small-factor-explorer .muted {{ color:var(--muted); }}
    #eu-small-factor-explorer .path {{ color:var(--muted); font-size:11px; }}
    #eu-small-factor-explorer .footer {{ color:var(--muted); font-size:11px; line-height:1.55; margin-top:8px; overflow-wrap:anywhere; }}
    #eu-small-factor-explorer .empty {{ color:var(--muted); padding:18px 0; }}
    @media (max-width: 1240px) {{ #eu-small-factor-explorer .layout {{ grid-template-columns:minmax(0, 1.45fr) minmax(300px, .8fr); }} #eu-small-factor-explorer .left-rail {{ grid-column:1 / -1; display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:14px; }} #eu-small-factor-explorer .left-rail .block {{ margin-bottom:0; }} #eu-small-factor-explorer .metric-grid {{ grid-template-columns:repeat(3, minmax(0, 1fr)); }} }}
    @media (max-width: 900px) {{ #eu-small-factor-explorer .layout, #eu-small-factor-explorer .left-rail {{ display:block; }} #eu-small-factor-explorer .left-rail .block {{ margin-bottom:14px; }} }}
    @media (max-width: 640px) {{ #eu-small-factor-explorer .shell {{ padding:18px 12px 30px; }} #eu-small-factor-explorer .masthead, #eu-small-factor-explorer .context {{ display:block; }} #eu-small-factor-explorer .stamp, #eu-small-factor-explorer .context .meta {{ text-align:left; margin-top:9px; white-space:normal; }} #eu-small-factor-explorer .controls, #eu-small-factor-explorer .metric-grid {{ grid-template-columns:1fr; }} #eu-small-factor-explorer .chart {{ min-height:360px; }} }}
  </style>
  <div class="shell">
    <header class="masthead">
      <div><h1>MSCI Europe Small 因子研究浏览器</h1><p class="subhead">全样本、时期轮动、官方 Top/Worst 与 raw variable 权重结构</p></div>
      <div class="stamp" id="stamp"></div>
    </header>
    <div class="controls">
      <label>变量 / 组合<select id="candidate-select" aria-label="选择变量或组合"></select></label>
      <label>观察区间<select id="period-select" aria-label="选择观察区间"></select></label>
    </div>
    <section class="metric-grid" id="metrics" aria-label="选中候选的指标"></section>
    <main class="layout">
      <aside class="left-rail">
        <section class="block"><h2>选中候选的时期表现</h2><div class="table-scroll" id="period-table"></div></section>
        <section class="block"><h2>证据与口径</h2><div id="evidence"></div></section>
      </aside>
      <div class="chart-column">
        <section class="block">
          <div class="context"><div class="name" id="selected-name"></div><div class="meta" id="selected-meta"></div></div>
          <div class="chart" id="chart" role="img" aria-label="Top Worst Benchmark NAV and ratio chart"></div>
          <div class="legend"><span><i style="background:var(--teal)"></i>Top</span><span><i style="background:var(--red)"></i>Worst</span><span><i style="background:var(--amber)"></i>Benchmark</span><span><i style="background:var(--green)"></i>Top / Benchmark</span><span><i style="background:var(--blue)"></i>Top / Worst</span></div>
        </section>
      </div>
      <aside class="right-rail">
        <section class="block"><h2>入选构成与 nominal 权重</h2><div class="weights" id="root-weights"></div><div class="table-scroll" id="raw-weights"></div></section>
        <section class="block"><h2>该时期的领先候选</h2><div class="table-scroll" id="leaderboard"></div></section>
      </aside>
    </main>
    <div class="footer" id="provenance"></div>
  </div>
  <script id="report-data" type="application/json">{payload}</script>
  <script>
  (() => {{
    const DATA = JSON.parse(document.getElementById('report-data').textContent);
    const byMetric = new Map(DATA.candidates.map(item => [item.metric, item]));
    const candidateSelect = document.getElementById('candidate-select');
    const periodSelect = document.getElementById('period-select');
    const fmtPct = value => Number.isFinite(value) ? `${{(value * 100).toFixed(1)}}%` : '-';
    const fmtNum = value => Number.isFinite(value) ? value.toFixed(2) : '-';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[char]));
    const period = () => DATA.periods.find(item => item.id === periodSelect.value);
    const selected = () => byMetric.get(candidateSelect.value);
    const seriesFor = (candidate, scope) => candidate.series.filter(point => point.d >= scope.start && point.d <= scope.end);
    const periodMetric = (candidate, scope) => candidate.periods[scope.id] || null;
    function options() {{
      const groups = new Map();
      DATA.candidates.forEach(item => {{ if (!groups.has(item.group)) groups.set(item.group, []); groups.get(item.group).push(item); }});
      candidateSelect.innerHTML = [...groups].map(([group, items]) => `<optgroup label="${{esc(group)}}">${{items.map(item => `<option value="${{esc(item.metric)}}">${{esc(item.label)}}</option>`).join('')}}</optgroup>`).join('');
      periodSelect.innerHTML = DATA.periods.map(item => `<option value="${{item.id}}">${{esc(item.label)}} (${{item.start}} 至 ${{item.end}})</option>`).join('');
      candidateSelect.value = DATA.defaultMetric;
      periodSelect.value = 'all';
    }}
    function linePath(points, key, x, y) {{ return points.map((point, index) => `${{index ? 'L' : 'M'}}${{x(index).toFixed(2)}},${{y(point[key]).toFixed(2)}}`).join(' '); }}
    function chart(candidate, scope) {{
      const rawPoints = seriesFor(candidate, scope);
      const root = document.getElementById('chart');
      if (rawPoints.length < 2) {{ root.innerHTML = '<div class="empty">该候选在此区间没有足够的 NAV 点。</div>'; return; }}
      const base = rawPoints[0];
      const points = rawPoints.map(point => ({{ ...point, t: point.t / base.t * 100, w: point.w / base.w * 100, b: point.b / base.b * 100 }}));
      const ratioPoints = points.map(point => ({{ ...point, active: point.t / point.b * 100, tw: point.t / point.w * 100 }}));
      const width = 980, height = 470, left = 48, right = 18, top = 18, split = 232, bottom = 34, gap = 34;
      const x = index => left + index / Math.max(points.length - 1, 1) * (width - left - right);
      const bounds = keys => {{ const values = points.flatMap(point => keys.map(key => key === 'active' || key === 'tw' ? ratioPoints[points.indexOf(point)][key] : point[key])); const lo = Math.min(...values), hi = Math.max(...values), pad = Math.max((hi - lo) * .08, 1); return [lo - pad, hi + pad]; }};
      const navBounds = bounds(['t','w','b']);
      const ratioBounds = (() => {{ const values = ratioPoints.flatMap(point => [point.active, point.tw]); const lo = Math.min(...values), hi = Math.max(...values), pad = Math.max((hi - lo) * .08, 1); return [lo-pad, hi+pad]; }})();
      const yTop = value => top + (navBounds[1] - value) / (navBounds[1] - navBounds[0]) * (split - top);
      const yBottom = value => split + gap + (ratioBounds[1] - value) / (ratioBounds[1] - ratioBounds[0]) * (height - bottom - split - gap);
      const grid = (bounds, y) => [bounds[0], (bounds[0]+bounds[1])/2, bounds[1]].map(value => `<g><line x1="${{left}}" y1="${{y(value)}}" x2="${{width-right}}" y2="${{y(value)}}" stroke="#d9e0da" stroke-width="1"/><text x="5" y="${{y(value)+4}}" fill="#60716d" font-size="11">${{Math.round(value)}}</text></g>`).join('');
      root.innerHTML = `<svg viewBox="0 0 ${{width}} ${{height}}" width="100%" height="100%" aria-label="${{esc(candidate.label)}} NAV and ratios"><title>${{esc(candidate.label)}}：Top、Worst、Benchmark 与相对净值</title>${{grid(navBounds,yTop)}}<path d="${{linePath(points,'b',x,yTop)}}" fill="none" stroke="#b87518" stroke-width="2"/><path d="${{linePath(points,'w',x,yTop)}}" fill="none" stroke="#a84e43" stroke-width="2"/><path d="${{linePath(points,'t',x,yTop)}}" fill="none" stroke="#087f86" stroke-width="2.5"/><text x="${{left}}" y="${{split+21}}" fill="#60716d" font-size="11">相对净值（起点 = 100）</text>${{grid(ratioBounds,yBottom)}}<path d="${{ratioPoints.map((point,index)=>`${{index?'L':'M'}}${{x(index).toFixed(2)}},${{yBottom(point.active).toFixed(2)}}`).join(' ')}}" fill="none" stroke="#237657" stroke-width="2.3"/><path d="${{ratioPoints.map((point,index)=>`${{index?'L':'M'}}${{x(index).toFixed(2)}},${{yBottom(point.tw).toFixed(2)}}`).join(' ')}}" fill="none" stroke="#516a9b" stroke-width="2.1"/><text x="${{left}}" y="${{height-7}}" fill="#60716d" font-size="11">${{points[0].d}}</text><text x="${{width-right}}" y="${{height-7}}" text-anchor="end" fill="#60716d" font-size="11">${{points[points.length-1].d}}</text></svg>`;
    }}
    function renderMetrics(candidate, scope) {{
      const stat = periodMetric(candidate, scope);
      const whole = scope.id === 'all';
      const cards = whole ? [
        ['Robust score', fmtNum(candidate.metrics.robust)], ['Top / Bench CAGR', fmtPct(candidate.metrics.activeCagr)], ['Ratio max DD', fmtPct(candidate.metrics.activeDrawdown)], ['Top / Worst return', fmtNum(candidate.metrics.topWorstReturn)], ['3Y 最差 relative CAGR', fmtPct(candidate.metrics.rolling3y)], ['年化命中率', fmtPct(candidate.metrics.hitRate)]
      ] : [
        ['Top / Bench CAGR', fmtPct(stat?.activeCagr)], ['Top CAGR', fmtPct(stat?.topCagr)], ['Top / Worst CAGR', fmtPct(stat?.topWorstCagr)], ['Active max DD', fmtPct(stat?.activeDrawdown)], ['有效起点', stat?.start || '-'], ['有效终点', stat?.end || '-']
      ];
      document.getElementById('metrics').innerHTML = cards.map(([label,value]) => `<div class="metric"><span>${{esc(label)}}</span><strong>${{esc(value)}}</strong></div>`).join('');
    }}
    function renderWeights(candidate) {{
      const root = document.getElementById('root-weights');
      root.innerHTML = candidate.rootWeights.length ? candidate.rootWeights.map(item => `<div class="weight-chip"><b>${{esc(item.label)}}</b>${{fmtPct(item.weight)}}</div>`).join('') : '<span class="muted">单一 raw variable：100%</span>';
      const rows = candidate.rawWeights.length ? candidate.rawWeights.map(item => `<tr><td>${{esc(item.label)}}</td><td class="path">${{esc(item.path || 'raw variable')}}</td><td class="num"><b>${{fmtPct(item.weight)}}</b></td></tr>`).join('') : '<tr><td colspan="3" class="muted">没有可展开的 raw variable 定义。</td></tr>';
      document.getElementById('raw-weights').innerHTML = `<table><thead><tr><th>Raw variable</th><th>归属路径</th><th class="num">总 nominal 权重</th></tr></thead><tbody>${{rows}}</tbody></table>`;
    }}
    function renderPeriods(candidate) {{
      const rows = DATA.periods.filter(item => item.id !== 'all').map(item => {{ const stat = candidate.periods[item.id]; return `<tr><td>${{esc(item.label)}}</td><td class="num">${{fmtPct(stat?.activeCagr)}}</td><td class="num">${{fmtPct(stat?.topWorstCagr)}}</td><td class="num">${{fmtPct(stat?.activeDrawdown)}}</td><td class="num">${{esc(stat?.start || '-')}}<br>${{esc(stat?.end || '')}}</td></tr>`; }}).join('');
      document.getElementById('period-table').innerHTML = `<table><thead><tr><th>时期</th><th class="num">Top / Bench CAGR</th><th class="num">Top / Worst CAGR</th><th class="num">Active max DD</th><th class="num">有效窗口</th></tr></thead><tbody>${{rows}}</tbody></table>`;
    }}
    function renderLeaderboard(scope) {{
      const rows = DATA.candidates.map(candidate => ({{ candidate, stat: periodMetric(candidate, scope) }})).filter(item => item.stat).sort((a,b) => b.stat.activeCagr - a.stat.activeCagr).slice(0, 10).map((item,index) => `<tr><td class="num">${{index+1}}</td><td><button class="select-row" data-metric="${{esc(item.candidate.metric)}}">${{esc(item.candidate.label)}}</button><div class="path">${{esc(item.candidate.group)}}</div></td><td class="num"><b>${{fmtPct(item.stat.activeCagr)}}</b></td><td class="num">${{fmtPct(item.stat.topWorstCagr)}}</td><td class="num">${{fmtPct(item.stat.activeDrawdown)}}</td></tr>`).join('');
      document.getElementById('leaderboard').innerHTML = `<table><thead><tr><th class="num">#</th><th>变量 / 组合</th><th class="num">Relative CAGR</th><th class="num">Top/Worst CAGR</th><th class="num">DD</th></tr></thead><tbody>${{rows}}</tbody></table>`;
      document.querySelectorAll('[data-metric]').forEach(button => button.addEventListener('click', () => {{ candidateSelect.value = button.dataset.metric; render(); }}));
    }}
    function renderEvidence(candidate) {{
      const economic = candidate.rawMeta?.economic ? `<p class="muted">经济角色：${{esc(candidate.rawMeta.economic)}}</p>` : '';
      document.getElementById('evidence').innerHTML = `<table><tbody><tr><th>候选类型</th><td>${{esc(candidate.group)}}</td></tr><tr><th>Official evidence</th><td>${{esc(candidate.evidence)}}</td></tr><tr><th>Coverage</th><td>${{fmtPct(candidate.metrics.coverage)}}</td></tr><tr><th>Tracking error</th><td>${{fmtPct(candidate.metrics.trackingError)}}</td></tr><tr><th>Turnover</th><td>${{fmtPct(candidate.metrics.turnover)}}</td></tr></tbody></table>${{economic}}<p class="footer">Raw 权重为信号定义中的 nominal 权重；月度最少可用变量规则会在实际计算时对可用项重新归一。</p>`;
    }}
    function render() {{
      const candidate = selected(), scope = period();
      document.getElementById('selected-name').textContent = candidate.label;
      document.getElementById('selected-meta').innerHTML = `${{esc(candidate.group)}}<br>${{esc(candidate.metric)}}<br>${{esc(scope.label)}}`;
      renderMetrics(candidate, scope); chart(candidate, scope); renderPeriods(candidate); renderWeights(candidate); renderLeaderboard(scope); renderEvidence(candidate);
    }}
    options();
    document.getElementById('stamp').innerHTML = `截至 ${{DATA.asOf}}<br>${{DATA.candidateCount}} 个可交互候选<br>${{esc(DATA.benchmark)}}`;
    document.getElementById('provenance').innerHTML = `Universe: ${{esc(DATA.universe)}} · ${{esc(DATA.evidence)}}<br>最新协同：${{esc(DATA.provenance.latestSynergy)}}<br>Relative raw：${{esc(DATA.provenance.relativeRaw)}}<br>Raw gate：${{esc(DATA.provenance.rawGate)}}<br>历史 QVM：${{esc(DATA.provenance.validatedQvm)}}`;
    candidateSelect.addEventListener('change', render); periodSelect.addEventListener('change', render); render();
  }})();
  </script>
</div>
'''


if __name__ == "__main__":
    main()

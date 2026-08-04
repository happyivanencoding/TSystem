"""Build a self-contained HTML review page from a v2 research result directory."""

from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path

import pandas as pd


def _table(frame: pd.DataFrame, columns: list[str] | None = None, limit: int = 200) -> str:
    if frame is None or frame.empty:
        return '<p class="empty">暂无数据</p>'
    selected = frame.loc[:, [column for column in (columns or list(frame.columns)) if column in frame.columns]].head(limit)
    return selected.to_html(index=False, classes="data", border=0, na_rep="—", escape=True)


def build_report(results_dir: str | Path, output: str | Path) -> Path:
    results = Path(results_dir)
    target = Path(output)
    manifest = json.loads((results / "manifest.json").read_text(encoding="utf-8")) if (results / "manifest.json").exists() else {}
    factors = pd.read_csv(results / "factor_definitions.csv") if (results / "factor_definitions.csv").exists() else pd.DataFrame()
    panel = pd.read_parquet(results / "factor_panel.parquet") if (results / "factor_panel.parquet").exists() else pd.DataFrame()
    gates = pd.read_csv(results / "promotion_gate.csv") if (results / "promotion_gate.csv").exists() else pd.DataFrame()
    metrics = pd.read_csv(results / "strategy_metrics.csv") if (results / "strategy_metrics.csv").exists() else pd.DataFrame()
    latest = panel.copy()
    if not latest.empty and "Date" in latest.columns:
        latest["Date"] = pd.to_datetime(latest["Date"], errors="coerce")
        latest = latest.loc[latest["Date"].eq(latest["Date"].max())].copy()
    gate_passed = int(gates["passed"].sum()) if not gates.empty and "passed" in gates.columns else 0
    gate_count = int(len(gates))
    rows = []
    for _, row in factors.iterrows():
        rows.append(
            "<tr>"
            f"<td><code>{escape(str(row.get('factor', '')))}</code></td>"
            f"<td>{escape(str(row.get('label', '')))}</td>"
            f"<td><code>{escape(str(row.get('source_columns', '')))}</code></td>"
            f"<td>{escape(str(row.get('definition', '')))}</td>"
            "</tr>"
        )
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>月度因子推荐 v2 | Research Review</title>
<style>
:root{{--bg:#f4f7fb;--ink:#172033;--muted:#61708a;--line:#dce4f0;--card:#fff;--blue:#315bd7;--warn:#a45b13;--bad:#ad2e34;--good:#1e7a4e}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 Inter,Segoe UI,Arial,sans-serif}}main{{max-width:1440px;margin:auto;padding:34px 26px 64px}}h1,h2,h3{{margin:0 0 12px}}h1{{font-size:32px;letter-spacing:-.03em}}h2{{font-size:20px;margin-top:30px}}p{{color:var(--muted)}}.hero{{background:linear-gradient(135deg,#152a60,#315bd7);color:white;border-radius:20px;padding:28px 32px;box-shadow:0 14px 36px #203b7d26}}.hero p{{color:#dbe5ff;max-width:900px}}.chips{{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}}.chip{{padding:7px 11px;border:1px solid #ffffff42;border-radius:99px;color:#fff;background:#ffffff14}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-top:18px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:17px;box-shadow:0 6px 18px #203b7d0d}}.metric{{font-size:24px;font-weight:700}}.label{{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em}}.section{{margin-top:25px}}.table-wrap{{overflow:auto;background:var(--card);border:1px solid var(--line);border-radius:14px}}table.data{{border-collapse:collapse;width:100%;min-width:760px}}table.data th{{position:sticky;top:0;background:#edf2fb;color:#43506b;text-align:left;font-size:12px;letter-spacing:.04em}}table.data td,table.data th{{border-bottom:1px solid var(--line);padding:10px 12px;vertical-align:top}}table.data tr:last-child td{{border-bottom:0}}code{{color:#324d99}}.note{{border-left:4px solid var(--warn);background:#fff8ed;padding:13px 16px;border-radius:8px;color:#78440e}}.empty{{padding:18px}}.small{{font-size:12px;color:var(--muted)}}.pass{{color:var(--good);font-weight:700}}.fail{{color:var(--bad);font-weight:700}}
</style></head><body><main>
<section class="hero"><div class="small">TP Research / Factor Recommendation</div><h1>月度因子推荐 v2</h1>
<p>官方因子 sleeve 研究复核页。研究单位为 Date × Region × RegionComponent × Factor × SleeveSide；主目标为 next_month_top_sleeve_net_active_return。</p>
<div class="chips"><span class="chip">{escape(str(manifest.get('promotion_decision', 'RESEARCH_ONLY')))}</span><span class="chip">OfficialPortfolioBacktest</span><span class="chip">PIT / drift / close-weight execution</span><span class="chip">v1 invalidated</span></div></section>
<div class="grid"><div class="card"><div class="label">样本</div><div class="metric">{escape(str(manifest.get('sample_start', '—')))} → {escape(str(manifest.get('sample_end', '—')))}</div></div><div class="card"><div class="label">Panel rows</div><div class="metric">{len(panel):,}</div></div><div class="card"><div class="label">Latest factors</div><div class="metric">{len(latest):,}</div></div><div class="card"><div class="label">Gates</div><div class="metric">{gate_passed}/{gate_count}</div></div></div>
<div class="section note"><strong>展示语义：</strong>Exposure snapshot / Not a forecast / Research v1 invalidated。没有冻结 v2 champion 时，forecast 必须是 model_unavailable / NO_VIEW；本页不把暴露分数命名为预测收益。</div>
<section class="section"><h2>每个因子的定义</h2><div class="table-wrap"><table class="data"><thead><tr><th>因子</th><th>标签</th><th>源字段</th><th>定义</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
<section class="section"><h2>最新因子面板</h2><div class="table-wrap">{_table(latest, ['Date','region','factor','rank_persistence_12m','trailing_12m_active_return','coverage','weight_coverage','next_month_top_sleeve_net_active_return'])}</div></section>
<section class="section"><h2>Allocator / economic metrics</h2><div class="table-wrap">{_table(metrics, ['region','cost_bps','observations','mean_active_return','net_ir','hit_rate','max_drawdown','max_concentration'])}</div></section>
<section class="section"><h2>Promotion gates</h2><div class="table-wrap">{_table(gates, ['gate_name','threshold','actual','operator','passed','region','evidence_path','failure_reason'])}</div></section>
<p class="small">Generated from: {escape(str(results))}<br>Code: {escape(str(manifest.get('code', {})))}<br>ASIA status: {escape(str(manifest.get('asia_status', 'NO_AGGREGATE_PERFORMANCE_CURRENCY_UNRESOLVED')))}</p>
</main></body></html>"""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(build_report(args.results, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

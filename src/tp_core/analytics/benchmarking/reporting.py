"""Raw measurement exports and a compact HTML performance report."""

from __future__ import annotations

import html
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from .statistics import geometric_mean


def _table(rows: Iterable[Mapping[str, Any]], *, limit: int = 200) -> str:
    frame = pd.DataFrame(list(rows))
    if frame.empty:
        return "<p>无数据</p>"
    frame = frame.head(limit).copy()
    return frame.to_html(index=False, border=0, classes="evidence-table", na_rep="")


def _category_summary(attribution: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frame = pd.DataFrame(attribution)
    if frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for category, group in frame.groupby("category", sort=True):
        rows.append(
            {
                "category": category,
                "workload_count": int(group["workload_id"].nunique()),
                "geometric_mean_speedup_x": geometric_mean(group["speedup_x"]),
                "median_time_saved_pct": float(group["time_saved_pct"].median()),
                "regression_count": int((group["speedup_x"] < 1.0).sum()),
            }
        )
    return rows


def _format_headline(attribution: list[dict[str, Any]], workload_id: str) -> str:
    matches = [
        row
        for row in attribution
        if row.get("workload_id") == workload_id and row.get("storage") == "google_drive"
    ]
    if not matches:
        return "N/A"
    value = matches[0].get("speedup_x")
    return f"{float(value):.2f}x" if value is not None else "N/A"


def build_markdown_report(
    *,
    run_id: str,
    environment: Mapping[str, Any],
    summary: list[dict[str, Any]],
    attribution: list[dict[str, Any]],
    storage_comparison: list[dict[str, Any]],
    pipeline: Mapping[str, Any],
    deployment: Mapping[str, Any],
    rollback: Mapping[str, Any],
    monthly: list[Mapping[str, Any]],
    readiness: Mapping[str, Any],
) -> str:
    regressions = [
        row
        for row in attribution
        if row.get("speedup_x") is not None and float(row["speedup_x"]) < 1.0
    ]
    categories = _category_summary(attribution)
    lines = [
        f"# DuckDB Authority 激活前性能报告（{run_id}）",
        "",
        "## 结论",
        "",
        f"- Current Legacy -> DuckDB：S03 {_format_headline(attribution, 'S03')}；R02 {_format_headline(attribution, 'R02')}；Dashboard hot paths 以 M01-M12 的类别 geometric mean 见下表。",
        f"- A/B/C commit：{environment.get('commit') or 'unknown'}；release：{environment.get('release_id') or 'unknown'}。",
        "- 本报告使用 median 作为主结论；process-cold 与 warm 分开，不声称清空了系统磁盘缓存。",
        "",
        "## A/B/C 定义",
        "",
        "| 组 | 代码 | 数据引擎 |",
        "| --- | --- | --- |",
        "| A | pre-DuckDB commit 的 detached worktree | Legacy Parquet |",
        "| B | 当前 commit | legacy_parquet |",
        "| C | 当前 commit | duckdb immutable release |",
        "",
        "## Category attribution",
        "",
        _table(categories),
        "",
        "## Workload summary（p50/p90）",
        "",
        _table(summary),
        "",
        "## 三方比较与 storage comparison",
        "",
        _table(attribution),
        "",
        _table(storage_comparison),
        "",
        "## Regressions",
        "",
        _table(regressions)
        if regressions
        else "<p>未发现 process-cold Google Drive workload 回归。</p>",
        "",
        "## Production-chain parity",
        "",
        _table(pipeline.get("parity", [])),
        "",
        "## Deployment smoke / rollback / monthly replay",
        "",
        _table([deployment]),
        "",
        _table([rollback]),
        "",
        _table(monthly),
        "",
        "## Readiness",
        "",
        _table([readiness]),
        "",
        "Remaining blocker：external approval 仍为 blocked；本任务不执行 Authority activation，不关闭 compatibility exports。",
        "",
    ]
    return "\n".join(lines)


def build_html_report(markdown: str, *, run_id: str, readiness: Mapping[str, Any]) -> str:
    body = markdown.replace("\n", "<br>\n")
    decision = html.escape(str(readiness.get("decision", "EVIDENCE_CLOSURE_BLOCKED")))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>DuckDB performance {html.escape(run_id)}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;line-height:1.45;color:#17202a;background:#f6f8fa}}
main{{max-width:1440px;margin:auto;background:white;padding:24px;border:1px solid #d0d7de;border-radius:8px}}
h1,h2{{color:#0b3954}} .evidence-table{{border-collapse:collapse;font-size:12px;width:100%;margin:8px 0 20px}}
.evidence-table th,.evidence-table td{{border:1px solid #d8dee4;padding:5px;text-align:left;vertical-align:top}}
.evidence-table th{{background:#eef2f6}} .decision{{font-weight:700;color:#8a2c0d}}
</style></head><body><main>
<div class="decision">Decision: {decision}</div>
<h1>DuckDB Authority 激活前性能报告</h1>
<div>{body}</div>
</main></body></html>"""


def write_reports(
    *,
    run_dir: str | Path,
    run_id: str,
    measurements: list[dict[str, Any]],
    summary: list[dict[str, Any]],
    attribution: list[dict[str, Any]],
    storage_comparison: list[dict[str, Any]],
    pipeline: Mapping[str, Any],
    deployment: Mapping[str, Any],
    rollback: Mapping[str, Any],
    monthly: list[Mapping[str, Any]],
    readiness: Mapping[str, Any],
    environment: Mapping[str, Any],
    stable_html: str | Path,
) -> dict[str, str]:
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    raw = pd.DataFrame(measurements)
    raw.to_parquet(root / "raw_measurements.parquet", index=False)
    raw.to_csv(root / "raw_measurements.csv", index=False)
    pd.DataFrame(summary).to_csv(root / "workload_summary.csv", index=False)
    pd.DataFrame(attribution).to_csv(root / "engine_comparison.csv", index=False)
    pd.DataFrame(storage_comparison).to_csv(root / "storage_comparison.csv", index=False)
    pd.DataFrame(_category_summary(attribution)).to_csv(root / "category_summary.csv", index=False)
    markdown = build_markdown_report(
        run_id=run_id,
        environment=environment,
        summary=summary,
        attribution=attribution,
        storage_comparison=storage_comparison,
        pipeline=pipeline,
        deployment=deployment,
        rollback=rollback,
        monthly=monthly,
        readiness=readiness,
    )
    html_report = build_html_report(markdown, run_id=run_id, readiness=readiness)
    (root / "final_report.md").write_text(markdown, encoding="utf-8")
    (root / "final_report.html").write_text(html_report, encoding="utf-8")
    stable = Path(stable_html)
    stable.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "final_report.html", stable)
    return {
        "markdown": str(root / "final_report.md"),
        "html": str(root / "final_report.html"),
        "stable_html": str(stable),
    }


__all__ = ["build_html_report", "build_markdown_report", "write_reports"]

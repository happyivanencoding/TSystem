"""Generate Chinese qualitative sector-view reports from latest sector scores."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

import pandas as pd


from tp_core.data_sources import TP_ROOT
from tp_core.research_context import (
    EvidenceItem,
    EvidencePack,
    LatestCsvModelAdapter,
    LatestCsvSpec,
    ObsidianBridge,
    SourceManifest,
    collect_public_pages,
    collect_recent_rss_items_with_issues,
    load_public_page_sources_from_yaml,
    load_rss_sources_from_yaml,
    write_jsonl,
)
from tp_core.research_context.evidence import write_json


PROJECT_DIR = TP_ROOT / "13_sector_score_model"
DEFAULT_VAULT_ROOT = Path(r"C:\GoogleDrive\笔记\卡片盒子")
DEFAULT_SOURCE_CONFIG = PROJECT_DIR / "config" / "qualitative_sources.yaml"
FACTOR_COLUMNS = ["momentum", "growth", "margin", "lowvol", "valuation"]
FACTOR_LABELS = {
    "momentum": "Trend",
    "growth": "Growth",
    "margin": "Margin",
    "lowvol": "LowVol",
    "valuation": "Value",
}
REGION_LABELS = {"US": "美国", "EU": "欧洲"}
SECTOR_THEMES = {
    "Technology": ["AI", "AI Capex", "Cloud Infrastructure", "Semiconductors", "Sovereign AI"],
    "Basic Resources": ["Commodities", "Mining", "Copper", "Steel"],
    "Energy": ["Oil", "Gas", "LNG", "OPEC", "Renewables"],
    "Banks": ["Interest Rates", "Credit Cycle", "Net Interest Margin"],
    "Financial Services": ["Capital Markets", "Asset Management", "Trading Revenue"],
    "Insurance": ["Reinsurance", "Float", "Interest Rates"],
    "Health Care": ["Pharma", "Biotech", "Pricing Power", "Drug Pipeline"],
    "Utilities": ["Grid Capex", "Power Demand", "Regulated Earnings"],
    "Automobiles and Parts": ["EV", "Hybrid Pivot", "Tariffs", "China Competition"],
    "Personal & Household Goods": ["Luxury", "China Demand", "Consumer Confidence"],
    "Food, Beverage and Tobacco": ["Consumer Staples", "GLP-1", "Pricing Power"],
    "Telecommunications": ["5G", "Capex", "Competition"],
    "Media": ["Advertising", "Streaming", "Platform Media"],
    "Travel and Leisure": ["Travel Demand", "Consumer Discretionary"],
    "Industrial Goods and Services": ["Capex", "Defense", "Automation"],
    "Chemicals": ["Materials", "Input Costs", "Industrial Demand"],
}


def main() -> None:
    args = parse_args()
    vault_root = Path(args.vault_root)
    explicit_output_dir = Path(args.output_dir) if args.output_dir else None
    output_dir = explicit_output_dir or PROJECT_DIR / "outputs_qualitative" / args.month
    output_dir.mkdir(parents=True, exist_ok=True)

    bridge = ObsidianBridge(vault_root)
    manual_evidence = load_evidence_jsonl(Path(args.evidence_jsonl)) if args.evidence_jsonl else []
    rss_evidence = []
    web_collection_issues = []
    if args.collect_rss:
        rss_sources = load_rss_sources_from_yaml(Path(args.source_config))
        rss_result = collect_recent_rss_items_with_issues(rss_sources, window_days=args.window_days)
        rss_evidence = rss_result.items
        web_collection_issues.extend(issue.to_dict() for issue in rss_result.issues)
    public_page_evidence = []
    if args.collect_public_pages:
        page_sources = load_public_page_sources_from_yaml(Path(args.source_config))
        page_result = collect_public_pages(page_sources)
        public_page_evidence = page_result.items
        web_collection_issues.extend(issue.to_dict() for issue in page_result.issues)

    rows = load_latest_sector_rows(args.us_latest, args.eu_latest)
    if args.month == "auto":
        args.month = infer_month(rows)
        output_dir = explicit_output_dir or PROJECT_DIR / "outputs_qualitative" / args.month
        output_dir.mkdir(parents=True, exist_ok=True)

    selected = [
        row
        for row in rows
        if (not args.active_only or str(row["recommendation"]) in {"Positive", "Negative"})
        and (not args.markets or row["market"] in args.markets)
    ]
    packs = [
        build_pack(
            row,
            bridge=bridge,
            manual_evidence=manual_evidence,
            rss_evidence=[*rss_evidence, *public_page_evidence],
        )
        for row in selected
    ]

    report = render_monthly_report(args.month, packs)
    commentary = render_commentary_only(packs)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    (output_dir / "final_commentary_no_citations.md").write_text(commentary, encoding="utf-8")
    write_jsonl(output_dir / "evidence.jsonl", [item for pack in packs for item in pack.items])
    write_json(output_dir / "evidence_packs.json", [pack.to_dict() for pack in packs])
    write_query_topics(output_dir / "query_topics.csv", selected)
    write_sources_csv(output_dir / "sources.csv", [item for pack in packs for item in pack.items])

    notes_written: list[str] = []
    if args.write_vault:
        notes_written = write_obsidian_outputs(
            bridge=bridge,
            month=args.month,
            packs=packs,
            report=report,
            overwrite=args.overwrite_vault,
        )

    manifest = SourceManifest.new(
        run_id=f"sector-qual-{args.month}",
        model="sector_score_model",
        window_days=args.window_days,
        output_language="中文",
        vault_root=vault_root,
        sources=[item.to_dict() for pack in packs for item in pack.items if item.kind in {"web", "manual"}],
        notes_written=notes_written,
    )
    write_json(output_dir / "run_manifest.json", manifest.to_dict() | {"web_collection_issues": web_collection_issues})
    print(f"wrote {len(packs)} sector packs to {output_dir}")
    if notes_written:
        print(f"updated {len(notes_written)} Obsidian notes")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", default="auto", help="YYYY-MM, or auto from latest sector rows")
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--markets", nargs="*", choices=["US", "EU"], default=["US", "EU"])
    parser.add_argument("--vault-root", default=str(DEFAULT_VAULT_ROOT))
    parser.add_argument("--output-dir")
    parser.add_argument("--us-latest", default=str(PROJECT_DIR / "outputs" / "sector_scores_latest.csv"))
    parser.add_argument("--eu-latest", default=str(PROJECT_DIR / "outputs_eu" / "sector_scores_latest.csv"))
    parser.add_argument("--evidence-jsonl", help="Codex/manual web evidence JSONL")
    parser.add_argument("--source-config", default=str(DEFAULT_SOURCE_CONFIG))
    parser.add_argument("--collect-rss", action="store_true", help="collect no-key RSS items from config")
    parser.add_argument("--collect-public-pages", action="store_true", help="collect configured public pages")
    parser.add_argument("--active-only", action="store_true", help="only write Positive/Negative sectors")
    parser.add_argument("--write-vault", action="store_true", help="write formal Obsidian notes")
    parser.add_argument("--overwrite-vault", action="store_true")
    return parser.parse_args()


def load_latest_sector_rows(us_path: str, eu_path: str) -> list[dict[str, object]]:
    adapter = LatestCsvModelAdapter(
        (
            LatestCsvSpec("US", Path(us_path)),
            LatestCsvSpec("EU", Path(eu_path)),
        )
    )
    return adapter.load_rows()


def infer_month(rows: list[dict[str, object]]) -> str:
    dates = [pd.Timestamp(row["Date"]) for row in rows if pd.notna(row.get("Date"))]
    if not dates:
        return date.today().strftime("%Y-%m")
    return max(dates).strftime("%Y-%m")


def build_pack(
    row: dict[str, object],
    *,
    bridge: ObsidianBridge,
    manual_evidence: list[EvidenceItem],
    rss_evidence: list[EvidenceItem],
) -> EvidencePack:
    region = str(row["market"])
    sector = str(row["sector_name"])
    view = str(row["recommendation"])
    terms = obsidian_terms(sector)
    hits = bridge.search(terms, limit=6)
    items: list[EvidenceItem] = [model_item(row)]
    items.extend(obsidian_item(row, hit) for hit in hits)
    items.extend(match_external_evidence(region, sector, view, manual_evidence))
    items.extend(match_external_evidence(region, sector, view, rss_evidence))
    web_count = sum(1 for item in items if item.kind in {"web", "manual"} and item.stance != "缺口")
    if not hits:
        items.append(gap_item(region, sector, view, "缺少已有 Obsidian 佐证"))
    if web_count < 2:
        items.append(gap_item(region, sector, view, f"最近30天 web evidence 只有 {web_count} 条，需要补足到 2 条"))
    return EvidencePack(
        region=region,
        subject=sector,
        view=view,
        model_scores=model_scores(row),
        items=items,
        missing_obsidian=not hits,
        missing_web_count=max(0, 2 - web_count),
    )


def model_item(row: dict[str, object]) -> EvidenceItem:
    region = str(row["market"])
    sector = str(row["sector_name"])
    view = str(row["recommendation"])
    scores = ", ".join(f"{FACTOR_LABELS[col]} {float(row[col]):.2f}" for col in FACTOR_COLUMNS if pd.notna(row.get(col)))
    return EvidenceItem(
        id=stable_id("model", region, sector, view),
        kind="model",
        region=region,
        subject=sector,
        view=view,
        stance="支持",
        title=f"{region} {sector} 模型分数",
        summary=f"模型给出 {view}，核心因子为：{scores}；综合分 {float(row['score_final']):.2f}，排名 {float(row['rank']):.0f}。",
        source="sector_scores_latest.csv",
        source_date=pd.Timestamp(row["Date"]).date().isoformat(),
        captured_at=datetime.now().isoformat(timespec="seconds"),
        related_notes=[f"[[{region} {sector}]]"],
        tags=["model", "sector_score_model"],
    )


def obsidian_item(row: dict[str, object], hit) -> EvidenceItem:
    region = str(row["market"])
    sector = str(row["sector_name"])
    view = str(row["recommendation"])
    return EvidenceItem(
        id=stable_id("obsidian", region, sector, hit.title),
        kind="obsidian",
        region=region,
        subject=sector,
        view=view,
        stance="中性",
        title=hit.title,
        summary=hit.excerpt[:500],
        source=str(hit.path),
        captured_at=datetime.now().isoformat(timespec="seconds"),
        related_notes=[hit.wikilink, f"[[{region} {sector}]]"],
        tags=["obsidian"],
    )


def gap_item(region: str, sector: str, view: str, summary: str) -> EvidenceItem:
    return EvidenceItem(
        id=stable_id("gap", region, sector, summary),
        kind="gap",
        region=region,
        subject=sector,
        view=view,
        stance="缺口",
        title=f"{region} {sector} evidence 缺口",
        summary=summary,
        captured_at=datetime.now().isoformat(timespec="seconds"),
        related_notes=[f"[[{region} {sector}]]"],
        tags=["quality_control"],
    )


def load_evidence_jsonl(path: Path) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            items.append(EvidenceItem(**payload))
    return items


def match_external_evidence(
    region: str,
    sector: str,
    view: str,
    items: Iterable[EvidenceItem],
) -> list[EvidenceItem]:
    sector_key = sector.lower()
    themes = [theme.lower() for theme in SECTOR_THEMES.get(sector, [])]
    matched: list[EvidenceItem] = []
    for item in items:
        if item.region and item.region not in {region, REGION_LABELS.get(region, "")}:
            continue
        if item.subject and not _matches_explicit_subject(item.subject, sector):
            continue
        text = " ".join([item.title, item.summary, *item.tags]).lower()
        if item.subject or _matches_sector_text(text, sector_key, themes):
            matched.append(
                EvidenceItem(
                    **(
                        item.to_dict()
                        | {
                            "region": region,
                            "subject": sector,
                            "view": view,
                            "related_notes": _unique([*item.related_notes, f"[[{region} {sector}]]"]),
                        }
                    )
                )
            )
    return matched[:4]


def _matches_explicit_subject(item_subject: str, sector: str) -> bool:
    subject_key = item_subject.strip().lower()
    sector_key = sector.lower()
    if subject_key == sector_key:
        return True
    parts = [part.strip().lower() for part in re.split(r"[;/|]", item_subject) if part.strip()]
    return sector_key in parts


def _matches_sector_text(text: str, sector_key: str, themes: list[str]) -> bool:
    if sector_key in text:
        return True
    for theme in themes:
        escaped = re.escape(theme)
        if len(theme) <= 3:
            if re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text):
                return True
        elif theme in text:
            return True
    return False


def model_scores(row: dict[str, object]) -> dict[str, float | str | None]:
    scores: dict[str, float | str | None] = {
        "date": pd.Timestamp(row["Date"]).date().isoformat(),
        "recommendation": str(row["recommendation"]),
        "score_final": _float_or_none(row.get("score_final")),
        "rank": _float_or_none(row.get("rank")),
    }
    for column in FACTOR_COLUMNS:
        scores[FACTOR_LABELS[column]] = _float_or_none(row.get(column))
    return scores


def query_terms(region: str, sector: str, row: dict[str, object]) -> list[str]:
    strong_factors = [
        FACTOR_LABELS[column]
        for column in FACTOR_COLUMNS
        if pd.notna(row.get(column)) and float(row[column]) >= 7
    ]
    weak_factors = [
        FACTOR_LABELS[column]
        for column in FACTOR_COLUMNS
        if pd.notna(row.get(column)) and float(row[column]) <= 3
    ]
    return _unique([region, REGION_LABELS.get(region, ""), sector, *SECTOR_THEMES.get(sector, []), *strong_factors, *weak_factors])


def obsidian_terms(sector: str) -> list[str]:
    return _unique([sector, *SECTOR_THEMES.get(sector, [])])


def render_monthly_report(month: str, packs: list[EvidencePack]) -> str:
    lines = [
        "---",
        f"title: {month} TP 行业观点",
        "tags:",
        "  - Type/SectorView",
        "  - Source/TP",
        "---",
        "",
        f"# {month} TP 行业观点",
        "",
        "本报告覆盖 TP sector model 的全部行业；正面、负面和中性行业均生成 commentary。",
        "",
    ]
    for region in ["US", "EU"]:
        region_packs = sort_packs([pack for pack in packs if pack.region == region])
        if not region_packs:
            continue
        lines.extend([f"## {REGION_LABELS.get(region, region)}", "", *render_overview_table(region_packs), ""])
        for view in ["Positive", "Neutral", "Negative"]:
            view_packs = sort_packs([pack for pack in region_packs if pack.view == view])
            if not view_packs:
                continue
            lines.extend([f"### {view_to_cn(view)}", ""])
            for pack in view_packs:
                lines.extend(render_pack_block(pack))
    return "\n".join(lines).rstrip() + "\n"


def render_pack_block(pack: EvidencePack) -> list[str]:
    paragraph = commentary_for_pack(pack)
    evidence_lines = []
    for item in pack.items:
        if item.kind == "model":
            continue
        link = item.related_notes[0] if item.related_notes else item.title
        evidence_lines.append(f"- {item.stance}：{link} - {item.summary[:180]}")
    if not evidence_lines:
        evidence_lines.append("- 缺口：尚未写入外部证据。")
    score_text = "，".join(
        f"{key} {value:.2f}" for key, value in pack.model_scores.items() if isinstance(value, float) and key not in {"rank"}
    )
    return [
        f"#### [[{pack.region} {pack.subject}]] - {view_to_cn(pack.view)}",
        "",
        paragraph,
        "",
        "##### Evidence block",
        f"- 模型依据：{score_text}",
        f"- 质量状态：{pack.quality_status()}",
        *evidence_lines,
        "",
    ]


def commentary_for_pack(pack: EvidencePack) -> str:
    model = next((item for item in pack.items if item.kind == "model"), None)
    obsidian = [item for item in pack.items if item.kind == "obsidian"]
    web = [item for item in pack.items if item.kind in {"web", "manual"}]
    supporting_web = [item for item in web if item.stance == "支持"]
    opposing_web = [item for item in web if item.stance == "反驳"]
    direction = view_to_cn(pack.view)
    base = model.summary if model else f"模型给出{direction}观点。"
    old = f"已有知识库中，{obsidian[0].title} 等笔记提供了相关背景。" if obsidian else "已有 Obsidian 知识暂未找到直接佐证。"
    if supporting_web:
        fresh = f"最近30天支持该观点的证据是：{supporting_web[0].summary}"
    elif web:
        fresh = f"最近30天新增证据主要是反向提示：{web[0].summary}"
    else:
        fresh = "最近30天的网络证据仍需补充，因此本段应先作为待复核观点。"
    risk = f"同时需要注意：{opposing_web[0].summary}" if opposing_web else ""
    return f"{pack.subject} 被模型归为{direction}行业。{base}{old}{fresh}{risk}"


def render_commentary_only(packs: list[EvidencePack]) -> str:
    lines: list[str] = []
    for region in ["US", "EU"]:
        region_packs = sort_packs([pack for pack in packs if pack.region == region])
        if not region_packs:
            continue
        lines.extend([f"## {REGION_LABELS.get(region, region)}", ""])
        for pack in region_packs:
            lines.extend([f"### {pack.subject} - {view_to_cn(pack.view)}", commentary_for_pack(pack), ""])
    return "\n".join(lines).rstrip() + "\n"


def render_overview_table(packs: list[EvidencePack]) -> list[str]:
    lines = [
        "### 行业总览",
        "",
        "| 排名 | 行业 | View | Score | Trend | Growth | Margin | LowVol | Value | 状态 |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for pack in sort_packs(packs):
        scores = pack.model_scores
        lines.append(
            "| {rank:.0f} | [[{region} {subject}]] | {view} | {score:.2f} | {trend:.2f} | {growth:.2f} | {margin:.2f} | {lowvol:.2f} | {value:.2f} | {status} |".format(
                rank=float(scores.get("rank") or 0),
                region=pack.region,
                subject=pack.subject,
                view=view_to_cn(pack.view),
                score=float(scores.get("score_final") or 0),
                trend=float(scores.get("Trend") or 0),
                growth=float(scores.get("Growth") or 0),
                margin=float(scores.get("Margin") or 0),
                lowvol=float(scores.get("LowVol") or 0),
                value=float(scores.get("Value") or 0),
                status=pack.quality_status(),
            )
        )
    return lines


def sort_packs(packs: list[EvidencePack]) -> list[EvidencePack]:
    return sorted(packs, key=lambda pack: float(pack.model_scores.get("rank") or 999))


def write_obsidian_outputs(
    *,
    bridge: ObsidianBridge,
    month: str,
    packs: list[EvidencePack],
    report: str,
    overwrite: bool,
) -> list[str]:
    title = f"{month} TP 行业观点"
    written: list[Path] = [bridge.write_monthly_view(month=month, title=title, body=report, overwrite=overwrite)]
    today = date.today()
    for pack in packs:
        evidence_links: list[str] = []
        for item in pack.items:
            if item.kind not in {"web", "manual"}:
                continue
            clipping = bridge.write_clipping(item, monthly_view_title=title, captured=today, overwrite=overwrite)
            written.append(clipping)
            evidence_links.append(f"[[{clipping.stem}]]")
        hub = bridge.update_sector_hub(
            region=pack.region,
            sector=pack.subject,
            month=month,
            monthly_view_title=title,
            evidence_links=evidence_links,
        )
        written.append(hub)
    return [str(path) for path in _unique_paths(written)]


def write_query_topics(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["market", "sector_name", "recommendation", "query_terms"])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "market": row["market"],
                    "sector_name": row["sector_name"],
                    "recommendation": row["recommendation"],
                    "query_terms": "; ".join(query_terms(str(row["market"]), str(row["sector_name"]), row)),
                }
            )


def write_sources_csv(path: Path, items: list[EvidenceItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "kind", "region", "subject", "view", "stance", "title", "source_date", "source"],
        )
        writer.writeheader()
        for item in items:
            writer.writerow({field: getattr(item, field) for field in writer.fieldnames})


def view_to_cn(view: str) -> str:
    return {"Positive": "正面", "Negative": "负面", "Neutral": "中性"}.get(view, view)


def stable_id(*parts: object) -> str:
    return hashlib.sha1("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:12]


def _float_or_none(value: object) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _unique_paths(values: Iterable[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


if __name__ == "__main__":
    main()

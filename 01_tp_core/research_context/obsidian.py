"""Obsidian vault search and writing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import re
from typing import Iterable

from .evidence import EvidenceItem


@dataclass(frozen=True)
class ObsidianSearchHit:
    title: str
    path: Path
    score: int
    excerpt: str

    @property
    def wikilink(self) -> str:
        return f"[[{self.title}]]"


class ObsidianBridge:
    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root

    def search(self, terms: Iterable[str], *, limit: int = 8) -> list[ObsidianSearchHit]:
        normalized_terms = [term.lower() for term in terms if term and len(term.strip()) >= 2]
        if not normalized_terms:
            return []
        hits: list[ObsidianSearchHit] = []
        for path in self.vault_root.rglob("*.md"):
            if _is_generated_report_path(path):
                continue
            text = _read_text(path)
            lower = text.lower()
            title = path.stem
            title_lower = title.lower()
            score = sum(4 for term in normalized_terms if term in title_lower)
            score += sum(1 for term in normalized_terms if term in lower)
            if score <= 0:
                continue
            hits.append(
                ObsidianSearchHit(
                    title=title,
                    path=path,
                    score=score,
                    excerpt=_excerpt(text, normalized_terms),
                )
            )
        return sorted(hits, key=lambda hit: (-hit.score, len(str(hit.path))))[:limit]

    def monthly_view_path(self, month: str) -> Path:
        return (
            self.vault_root
            / "10_Investment"
            / "02_Sectors"
            / "Monthly_Sector_Views"
            / f"{month} TP 行业观点.md"
        )

    def sector_hub_path(self, region: str, sector: str) -> Path:
        safe_sector = _safe_filename(f"{region} {sector}")
        return self.vault_root / "10_Investment" / "02_Sectors" / "Sector_Hubs" / f"{safe_sector}.md"

    def clipping_path(self, captured: date, title: str) -> Path:
        quarter = (captured.month - 1) // 3 + 1
        safe_title = _safe_filename(title)[:90]
        return (
            self.vault_root
            / "40_News_Room"
            / f"{captured.year}_Q{quarter}_Clippings"
            / f"{captured.isoformat()} {safe_title}.md"
        )

    def write_clipping(
        self,
        item: EvidenceItem,
        *,
        monthly_view_title: str,
        captured: date,
        overwrite: bool = False,
    ) -> Path:
        path = self.clipping_path(captured, item.title)
        if path.exists() and not overwrite:
            return path
        links = "\n".join(f"- {link}" for link in _unique([*item.related_notes, f"[[{monthly_view_title}]]"]))
        source_line = f"- {item.source}" if item.source else "- "
        body = f"""---
type: clipping
captured: {captured.isoformat()}
region: {item.region}
subject: {item.subject}
view: {item.view}
stance: {item.stance}
source_date: {item.source_date}
---

# {item.title}

## 摘要
{item.summary}

## 对模型观点的影响
{item.stance} [[{item.region} {item.subject}]] 的{_view_to_cn(item.view)}观点。

## 来源
{source_line}

## Links
{links}
"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def write_monthly_view(
        self,
        *,
        month: str,
        title: str,
        body: str,
        overwrite: bool = True,
    ) -> Path:
        path = self.monthly_view_path(month)
        if path.exists() and not overwrite:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def update_sector_hub(
        self,
        *,
        region: str,
        sector: str,
        month: str,
        monthly_view_title: str,
        evidence_links: list[str],
    ) -> Path:
        path = self.sector_hub_path(region, sector)
        title = f"{region} {sector}"
        if path.exists():
            text = _read_text(path)
        else:
            text = f"# {title}\n\n## Related Monthly Views\n\n## Recent Evidence\n"
        monthly_line = f"- [[{monthly_view_title}]]"
        evidence_lines = [f"- {link}" for link in evidence_links]
        text = _ensure_section_line(text, "## Related Monthly Views", monthly_line)
        for line in evidence_lines:
            text = _ensure_section_line(text, "## Recent Evidence", line)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig", errors="ignore")


def _is_generated_report_path(path: Path) -> bool:
    return "Monthly_Sector_Views" in path.parts


def _excerpt(text: str, terms: list[str]) -> str:
    lower = text.lower()
    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
    if not positions:
        return text[:220].replace("\n", " ")
    start = max(0, min(positions) - 80)
    return text[start : start + 260].replace("\n", " ")


def _safe_filename(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', " ", value).strip()


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _ensure_section_line(text: str, section: str, line: str) -> str:
    if line in text:
        return text
    marker = section.strip()
    if marker not in text:
        text = text.rstrip() + f"\n\n{marker}\n"
    pattern = re.compile(rf"({re.escape(marker)}\n)(.*?)(\n## |\Z)", re.S)
    match = pattern.search(text)
    if not match:
        return text.rstrip() + f"\n\n{marker}\n{line}\n"
    block = match.group(2).rstrip()
    replacement = f"{match.group(1)}{block}\n{line}\n"
    if match.group(3) == "\n## ":
        replacement += "\n## "
    return text[: match.start()] + replacement + text[match.end() :]


def _view_to_cn(view: str) -> str:
    return {"Positive": "正面", "Negative": "负面", "Neutral": "中性"}.get(view, view)

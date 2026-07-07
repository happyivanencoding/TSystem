"""No-key web collection helpers for RSS and public pages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import html
import hashlib
from pathlib import Path
import re
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .evidence import EvidenceItem


@dataclass(frozen=True)
class RssSource:
    name: str
    url: str
    region: str = ""
    subjects: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublicPageSource:
    name: str
    url: str
    region: str = ""
    subjects: tuple[str, ...] = ()


@dataclass(frozen=True)
class WebCollectionIssue:
    source_name: str
    url: str
    reason: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "source_name": self.source_name,
            "url": self.url,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class WebCollectionResult:
    items: list[EvidenceItem]
    issues: list[WebCollectionIssue]


def collect_recent_rss_items(
    sources: Iterable[RssSource],
    *,
    window_days: int,
    now: datetime | None = None,
) -> list[EvidenceItem]:
    return collect_recent_rss_items_with_issues(sources, window_days=window_days, now=now).items


def collect_recent_rss_items_with_issues(
    sources: Iterable[RssSource],
    *,
    window_days: int,
    now: datetime | None = None,
) -> WebCollectionResult:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    items: list[EvidenceItem] = []
    issues: list[WebCollectionIssue] = []
    for source in sources:
        try:
            raw = _fetch(source.url)
        except (HTTPError, URLError, TimeoutError) as exc:
            issues.append(WebCollectionIssue(source.name, source.url, "fetch_failed", str(exc)))
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            issues.append(WebCollectionIssue(source.name, source.url, "parse_failed", "not valid RSS/Atom XML"))
            continue
        for node in root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = _child_text(node, "title")
            link = _child_text(node, "link")
            published = _child_text(node, "pubDate") or _child_text(node, "published") or _child_text(node, "updated")
            published_dt = _parse_date(published)
            if published_dt and published_dt < cutoff:
                continue
            summary = _clean(_child_text(node, "description") or _child_text(node, "summary"))
            item_id = hashlib.sha1(f"{source.name}|{title}|{link}".encode("utf-8")).hexdigest()[:12]
            items.append(
                EvidenceItem(
                    id=f"rss-{item_id}",
                    kind="web",
                    region=source.region,
                    subject=", ".join(source.subjects),
                    view="",
                    stance="中性",
                    title=title or source.name,
                    summary=summary[:700],
                    source=link or source.url,
                    source_date=published_dt.date().isoformat() if published_dt else "",
                    captured_at=now.isoformat(timespec="seconds"),
                    tags=["rss", source.name],
                )
            )
    return WebCollectionResult(items=_dedupe(items), issues=issues)


def collect_public_pages(sources: Iterable[PublicPageSource]) -> WebCollectionResult:
    items: list[EvidenceItem] = []
    issues: list[WebCollectionIssue] = []
    now = datetime.now(timezone.utc)
    for source in sources:
        try:
            raw = _fetch(source.url)
        except (HTTPError, URLError, TimeoutError) as exc:
            issues.append(WebCollectionIssue(source.name, source.url, "fetch_failed", str(exc)))
            continue
        text = raw.decode("utf-8", errors="ignore")
        title = _html_title(text) or source.name
        body = _clean(text)
        if _looks_paywalled(body):
            issues.append(WebCollectionIssue(source.name, source.url, "paywall_or_blocked", title))
            continue
        if len(body) < 300:
            issues.append(WebCollectionIssue(source.name, source.url, "insufficient_content", title))
            continue
        item_id = hashlib.sha1(f"{source.name}|{source.url}".encode("utf-8")).hexdigest()[:12]
        items.append(
            EvidenceItem(
                id=f"page-{item_id}",
                kind="web",
                region=source.region,
                subject=", ".join(source.subjects),
                view="",
                stance="中性",
                title=title,
                summary=body[:900],
                source=source.url,
                captured_at=now.isoformat(timespec="seconds"),
                tags=["public_page", source.name],
            )
        )
    return WebCollectionResult(items=_dedupe(items), issues=issues)


def load_rss_sources_from_yaml(path: Path) -> list[RssSource]:
    if not path.exists():
        return []
    sources: list[RssSource] = []
    current: dict[str, str] = {}
    section = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line in {"sources:", "public_pages:"}:
            if current and section == "sources":
                sources.append(_source_from_dict(current))
            current = {}
            section = line.rstrip(":")
            continue
        if section != "sources":
            continue
        if line.startswith("- "):
            if current:
                sources.append(_source_from_dict(current))
            current = {}
            line = line[2:].strip()
        if ":" in line:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip().strip('"')
    if current:
        sources.append(_source_from_dict(current))
    return sources


def load_public_page_sources_from_yaml(path: Path) -> list[PublicPageSource]:
    if not path.exists():
        return []
    sources: list[PublicPageSource] = []
    current: dict[str, str] = {}
    section = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line in {"sources:", "public_pages:"}:
            section = line.rstrip(":")
            continue
        if section != "public_pages":
            continue
        if line.startswith("- "):
            if current:
                sources.append(_page_source_from_dict(current))
            current = {}
            line = line[2:].strip()
        if ":" in line:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip().strip('"')
    if current:
        sources.append(_page_source_from_dict(current))
    return sources


def _source_from_dict(values: dict[str, str]) -> RssSource:
    subjects = tuple(part.strip() for part in values.get("subjects", "").strip("[]").split(",") if part.strip())
    return RssSource(
        name=values.get("name", ""),
        url=values.get("url", ""),
        region=values.get("region", ""),
        subjects=subjects,
    )


def _page_source_from_dict(values: dict[str, str]) -> PublicPageSource:
    subjects = tuple(part.strip() for part in values.get("subjects", "").strip("[]").split(",") if part.strip())
    return PublicPageSource(
        name=values.get("name", ""),
        url=values.get("url", ""),
        region=values.get("region", ""),
        subjects=subjects,
    )


def _fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "TP research context/0.1"})
    with urlopen(request, timeout=20) as response:
        return response.read()


def _child_text(node: ET.Element, name: str) -> str:
    child = node.find(name)
    if child is None:
        child = node.find(f"{{http://www.w3.org/2005/Atom}}{name}")
    if child is None:
        return ""
    if name == "link" and child.text is None:
        return child.attrib.get("href", "")
    return "".join(child.itertext()).strip()


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean(value: str) -> str:
    value = re.sub(r"<script[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _html_title(value: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", value, re.I | re.S)
    if not match:
        return ""
    return _clean(match.group(1))


def _looks_paywalled(value: str) -> bool:
    lower = value.lower()
    signals = ["subscribe to continue", "sign in to continue", "enable javascript", "access denied"]
    return any(signal in lower for signal in signals)


def _dedupe(items: list[EvidenceItem]) -> list[EvidenceItem]:
    seen: set[str] = set()
    result: list[EvidenceItem] = []
    for item in items:
        key = item.source or item.title
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result

"""Read-only OKF/card-box news provider with explicit PIT lineage."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

from .models import NewsStandardModel
from .protocol import ProviderContext, ProviderQuery, ProviderResult

NEWS_PREFIX = "卡片盒子/40_News_Room/"
NEWS_TYPES = {"NewsClip", "MarketBriefing", "MarketBrief", "clipping"}
TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def _sha256(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _canonical_url(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text.startswith(("http://", "https://")):
        return None
    split = urlsplit(text)
    query = [
        (key, item)
        for key, item in parse_qsl(split.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    ]
    return urlunsplit(
        (split.scheme.lower(), split.netloc.lower(), split.path.rstrip("/"), urlencode(query), "")
    )


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


def _frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---"):
        return {}, raw
    match = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", raw, re.DOTALL)
    if match is None:
        return {}, raw
    loaded = yaml.safe_load(match.group(1)) or {}
    return (dict(loaded) if isinstance(loaded, dict) else {}), raw[match.end() :]


def _body_without_local_relations(body: str) -> str:
    body = re.split(r"\n##\s+相关笔记\b", body, maxsplit=1)[0]
    body = re.sub(r"\[\[([^]|]+)\|([^]]+)\]\]", r"\2", body)
    body = re.sub(r"\[\[([^]]+)\]\]", r"\1", body)
    body = re.sub(r"chrome-extension://\S+", "", body)
    return body.strip()


class OkfNewsProvider:
    provider_id = "okf_news"
    standard_model = NewsStandardModel

    def fetch(self, query: ProviderQuery, context: ProviderContext) -> ProviderResult:
        manifest_path = Path(str(query.job["manifest_path"])).resolve()
        notes_root = Path(str(query.job["notes_root"])).resolve()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records: list[NewsStandardModel] = []
        skipped = {"not_news": 0, "privacy": 0, "missing_pit": 0, "missing_file": 0, "duplicate": 0}
        seen: set[str] = set()
        for item in sorted(manifest, key=lambda value: str(value.get("source_path") or "")):
            source_path = str(item.get("source_path") or "").replace("\\", "/")
            if not source_path.startswith(NEWS_PREFIX) or item.get("type") not in NEWS_TYPES:
                skipped["not_news"] += 1
                continue
            if item.get("privacy_level") != "public_internal":
                skipped["privacy"] += 1
                continue
            note_path = (notes_root / Path(source_path)).resolve()
            if not note_path.is_relative_to(notes_root):
                raise ValueError(f"OKF source_path 越界：{source_path}")
            if not note_path.is_file():
                skipped["missing_file"] += 1
                continue
            raw = note_path.read_text(encoding="utf-8", errors="replace")
            metadata, body = _frontmatter(raw)
            observed = _parse_datetime(
                metadata.get("source_date")
                or metadata.get("published")
                or metadata.get("date")
                or Path(source_path).name[:10]
            )
            captured = _parse_datetime(metadata.get("captured") or metadata.get("created"))
            if observed is None or captured is None:
                skipped["missing_pit"] += 1
                continue
            source_url = _canonical_url(
                metadata.get("source")
                or metadata.get("source_url")
                or metadata.get("original_source")
            )
            title = str(metadata.get("title") or item.get("title") or note_path.stem).strip()
            text = _body_without_local_relations(body)
            content_hash = _sha256(raw)
            dedup_key = (
                f"url:{source_url}"
                if source_url
                else f"title:{title.casefold()}|date:{observed.date()}|content:{_sha256(text)}"
            )
            if dedup_key in seen:
                skipped["duplicate"] += 1
                continue
            seen.add(dedup_key)
            records.append(
                NewsStandardModel(
                    source="okf_card_box",
                    field="news_text",
                    value=title,
                    available_at=captured,
                    retrieved_at=context.retrieved_at,
                    unit="text",
                    record_id=_sha256(source_path),
                    title=title,
                    text=text,
                    source_url=source_url,
                    observation_date=observed,
                    captured_at=captured,
                    region=metadata.get("region"),
                    subject=metadata.get("subject"),
                    view=metadata.get("view"),
                    stance=metadata.get("stance"),
                    privacy_level="public_internal",
                    content_sha256=content_hash,
                    metadata={
                        "source_path": source_path,
                        "okf_path": item.get("okf_path"),
                        "record_type": item.get("type"),
                        "selection_bias": "curated_news_room",
                        "predictor_default": False,
                    },
                )
            )
        return ProviderResult(
            family="news",
            source="okf_card_box",
            job_key=_sha256(str(manifest_path)),
            records=tuple(records),
            raw_payload={
                "manifest_sha256": _sha256(manifest_path.read_bytes()),
                "record_count": len(records),
                "skipped": skipped,
            },
        )


__all__ = ["OkfNewsProvider"]

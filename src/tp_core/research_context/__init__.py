"""Reusable research context helpers for TP qualitative reports."""

from .evidence import EvidenceItem, EvidencePack, SourceManifest, write_jsonl
from .model_adapter import (
    CompanyAnalysisCsvAdapter,
    CountryModelAdapter,
    LatestCsvModelAdapter,
    LatestCsvSpec,
    ModelAdapter,
)
from .obsidian import ObsidianBridge, ObsidianSearchHit
from .web_sources import (
    PublicPageSource,
    RssSource,
    WebCollectionIssue,
    WebCollectionResult,
    collect_public_pages,
    collect_recent_rss_items,
    collect_recent_rss_items_with_issues,
    load_public_page_sources_from_yaml,
    load_rss_sources_from_yaml,
)

__all__ = [
    "EvidenceItem",
    "EvidencePack",
    "SourceManifest",
    "write_jsonl",
    "ModelAdapter",
    "LatestCsvSpec",
    "LatestCsvModelAdapter",
    "CountryModelAdapter",
    "CompanyAnalysisCsvAdapter",
    "ObsidianBridge",
    "ObsidianSearchHit",
    "RssSource",
    "PublicPageSource",
    "WebCollectionIssue",
    "WebCollectionResult",
    "collect_recent_rss_items",
    "collect_recent_rss_items_with_issues",
    "collect_public_pages",
    "load_rss_sources_from_yaml",
    "load_public_page_sources_from_yaml",
]

"""Deterministic company reports with optional grounded, read-only narrative."""

from .deterministic import render_markdown
from .models import (
    CompanyEvidenceItem,
    CompanyResearchSnapshot,
    NarrativeDocument,
    NarrativeResponse,
    NumericFact,
)
from .narrative import NarrativeRouter, build_default_router, validate_narrative
from .snapshot import build_snapshot

__all__ = [
    "CompanyEvidenceItem",
    "CompanyResearchSnapshot",
    "NarrativeDocument",
    "NarrativeResponse",
    "NarrativeRouter",
    "NumericFact",
    "build_default_router",
    "build_snapshot",
    "render_markdown",
    "validate_narrative",
]

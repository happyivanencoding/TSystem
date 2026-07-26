"""Strict contracts for deterministic company facts and grounded narrative."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NumericFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str
    label: str
    value: float
    unit: str
    as_of: str
    source: str
    source_column: str
    formula: str = "reported_value"
    input_fingerprint: str


class CompanyEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    title: str
    summary: str
    source: str
    source_date: str
    captured_at: str
    source_url: str | None = None
    stance: str = "neutral"


class CompanyResearchSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    isin: str
    name: str
    symbol: str | None = None
    as_of: str
    region: str | None = None
    sector: str | None = None
    facts: list[NumericFact] = Field(default_factory=list)
    evidence: list[CompanyEvidenceItem] = Field(default_factory=list)
    snapshot_fingerprint: str

    def public_payload(self) -> dict[str, Any]:
        """Payload safe for narrative models: no paths, user data, or raw files."""

        return self.model_dump()


class NarrativeClaim(BaseModel):
    claim: str
    evidence_ids: list[str] = Field(min_length=1)


class NarrativeSection(BaseModel):
    heading: str
    text: str
    claims: list[NarrativeClaim] = Field(default_factory=list)


class NarrativeDocument(BaseModel):
    title: str
    sections: list[NarrativeSection] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)


class NarrativeResponse(BaseModel):
    provider: str
    requested_model: str
    actual_model: str
    document: NarrativeDocument
    audit: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "CompanyEvidenceItem",
    "CompanyResearchSnapshot",
    "NarrativeClaim",
    "NarrativeDocument",
    "NarrativeResponse",
    "NarrativeSection",
    "NumericFact",
]

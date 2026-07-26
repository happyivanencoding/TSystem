"""OpenBB-inspired standard data models for TP provider outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StandardModel(BaseModel):
    """Common validated envelope; provider-specific extras remain auditable."""

    model_config = ConfigDict(extra="allow")

    source: str
    field: str
    value: Any
    available_at: datetime
    retrieved_at: datetime
    unit: str
    currency: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MacroStandardModel(StandardModel):
    series_id: str
    observation_date: datetime
    vintage_at: datetime
    value: float
    availability_method: str = "source"


class FundamentalStandardModel(StandardModel):
    ISIN: str
    period_end: datetime
    value: float
    fiscal_period: str | None = None
    provider_field: str | None = None
    availability_method: str = "source"


class EstimateStandardModel(StandardModel):
    ISIN: str
    estimate_as_of: datetime
    fiscal_period_end: datetime
    horizon: str
    value: float
    analyst_count: float | None = None
    provider_field: str | None = None
    availability_method: str = "source"


class NewsStandardModel(StandardModel):
    record_id: str
    title: str
    text: str
    source_url: str | None = None
    observation_date: datetime
    captured_at: datetime
    region: str | None = None
    subject: str | None = None
    view: str | None = None
    stance: str | None = None
    privacy_level: str = "public_internal"
    content_sha256: str


__all__ = [
    "EstimateStandardModel",
    "FundamentalStandardModel",
    "MacroStandardModel",
    "NewsStandardModel",
    "StandardModel",
]

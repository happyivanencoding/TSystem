"""Read-only company research routes; no job, write, portfolio, or trade tools."""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from presentation_layer import company_analysis as analysis
from tp_reporting.company_research import (
    NarrativeRouter,
    build_default_router,
    build_snapshot,
    render_markdown,
)


class CopilotRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


def _snapshot(isin: str):
    from fastapi import HTTPException

    data = analysis.get_data()
    selected = data[data["ISIN"] == isin]
    if selected.empty:
        raise HTTPException(status_code=404, detail="Company not found")
    row = selected.iloc[0]
    region = row.get("Exchange Country Region")
    sector = row.get("Supersector")
    medians: dict[str, Any] = {}
    if pd.notna(region) and pd.notna(sector):
        medians = analysis.get_medians_data().get((region, sector), {})
    return build_snapshot(row.to_dict(), medians)


def register_routes(
    api,
    router: NarrativeRouter | None = None,
    *,
    prefix: str = "/api/company",
) -> None:
    from fastapi import HTTPException

    narrative_router = router or build_default_router()

    @api.get(f"{prefix}/{{isin}}/research-snapshot")
    def research_snapshot(isin: str):
        return _snapshot(isin).model_dump(mode="json")

    @api.get(f"{prefix}/{{isin}}/research-report")
    def research_report(isin: str, include_narrative: bool = False):
        snapshot = _snapshot(isin)
        narrative = (
            narrative_router.generate(snapshot)
            if include_narrative
            else None
        )
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "narrative": narrative.model_dump(mode="json") if narrative else None,
            "markdown": render_markdown(snapshot, narrative),
            "mode": "grounded_narrative" if narrative else "deterministic_only",
            "read_only": True,
        }

    @api.post(f"{prefix}/{{isin}}/copilot")
    def read_only_copilot(isin: str, request: CopilotRequest):
        if not narrative_router.enabled:
            raise HTTPException(
                status_code=403,
                detail="Read-only Copilot is disabled; set TP_NARRATIVE_ENABLED=1.",
            )
        snapshot = _snapshot(isin)
        narrative = narrative_router.generate(snapshot, question=request.question)
        if narrative is None:
            raise HTTPException(
                status_code=503,
                detail="No grounded narrative provider is currently available.",
            )
        return {
            "snapshot_fingerprint": snapshot.snapshot_fingerprint,
            "response": narrative.model_dump(mode="json"),
            "read_only": True,
        }


def create_router(router: NarrativeRouter | None = None):
    from fastapi import APIRouter

    api = APIRouter(tags=["company-research-read-only"])
    register_routes(api, router)
    return api


__all__ = ["CopilotRequest", "create_router", "register_routes"]

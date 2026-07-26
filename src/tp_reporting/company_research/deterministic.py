"""Deterministic company report renderer; always available without an LLM."""

from __future__ import annotations

from .models import CompanyResearchSnapshot, NarrativeResponse


def render_markdown(
    snapshot: CompanyResearchSnapshot,
    narrative: NarrativeResponse | None = None,
) -> str:
    lines = [
        f"# {snapshot.name or snapshot.isin} research report",
        "",
        f"- ISIN: `{snapshot.isin}`",
        f"- Symbol: `{snapshot.symbol or 'unknown'}`",
        f"- As of: `{snapshot.as_of}`",
        f"- Snapshot: `{snapshot.snapshot_fingerprint}`",
        "",
        "## Deterministic facts",
        "",
        "| Fact ID | Metric | Value | Unit | Source | Formula |",
        "|---|---|---:|---|---|---|",
    ]
    for fact in snapshot.facts:
        lines.append(
            f"| `{fact.fact_id}` | {fact.label} | {fact.value:.8g} | "
            f"{fact.unit} | {fact.source} | `{fact.formula}` |"
        )
    if narrative is not None:
        lines.extend(["", "## Grounded narrative", ""])
        for section in narrative.document.sections:
            lines.extend([f"### {section.heading}", "", section.text, ""])
            for claim in section.claims:
                identifiers = ", ".join(f"`{item}`" for item in claim.evidence_ids)
                lines.append(f"- {claim.claim} ({identifiers})")
            lines.append("")
        if narrative.document.limitations:
            lines.extend(["### Limitations", ""])
            lines.extend(f"- {item}" for item in narrative.document.limitations)
    else:
        lines.extend(
            [
                "",
                "## Narrative status",
                "",
                "Deterministic-only report. Narrative generation is disabled or unavailable.",
            ]
        )
    lines.extend(
        [
            "",
            "## Governance",
            "",
            "The narrative is read-only and may only cite the deterministic fact/evidence IDs above. "
            "It cannot update data, launch jobs, change portfolios, or place trades.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = ["render_markdown"]

"""Deterministic construction of company research snapshots."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Mapping

import pandas as pd

from .models import CompanyResearchSnapshot, NumericFact

IDENTITY_COLUMNS = {
    "ISIN",
    "Name",
    "Symbol",
    "Date",
    "Exchange Country Region",
    "Supersector",
}
MAX_FACTS = 80


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _fact_id(prefix: str, column: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", column.casefold()).strip("-")[:60]
    return f"{prefix}-{slug}"


def _unit(column: str) -> str:
    lowered = column.casefold()
    if "weight in " in lowered:
        return "fraction"
    if "percentile" in lowered or "score" in lowered or "rank" in lowered:
        return "score"
    if "%" in column or "margin" in lowered or "yield" in lowered or "roe" in lowered:
        return "percent_or_ratio_as_reported"
    if "market value" in lowered:
        return "EUR_millions"
    return "as_reported"


def build_snapshot(
    row: Mapping[str, Any],
    medians: Mapping[str, Any] | None = None,
) -> CompanyResearchSnapshot:
    """Create facts, peer medians and deterministic deltas from one data row."""

    as_of_value = pd.to_datetime(row.get("Date"), errors="coerce")
    as_of = as_of_value.date().isoformat() if pd.notna(as_of_value) else "unknown"
    clean_row = {
        str(key): value
        for key, value in row.items()
        if value is not None and not (isinstance(value, float) and math.isnan(value))
    }
    row_fingerprint = _digest(clean_row)
    facts: list[NumericFact] = []
    medians = medians or {}
    for column in sorted(clean_row):
        if column in IDENTITY_COLUMNS:
            continue
        value = pd.to_numeric(pd.Series([clean_row[column]]), errors="coerce").iloc[0]
        if pd.isna(value) or not math.isfinite(float(value)):
            continue
        company_fact_id = _fact_id("company", column)
        facts.append(
            NumericFact(
                fact_id=company_fact_id,
                label=column.strip(),
                value=float(value),
                unit=_unit(column),
                as_of=as_of,
                source="TP canonical last_screen",
                source_column=column,
                input_fingerprint=row_fingerprint,
            )
        )
        median = pd.to_numeric(pd.Series([medians.get(column)]), errors="coerce").iloc[0]
        if pd.isna(median) or not math.isfinite(float(median)):
            if len(facts) >= MAX_FACTS:
                break
            continue
        median_fact_id = _fact_id("peer-median", column)
        facts.extend(
            [
                NumericFact(
                    fact_id=median_fact_id,
                    label=f"Peer median: {column.strip()}",
                    value=float(median),
                    unit=_unit(column),
                    as_of=as_of,
                    source="TP deterministic region-sector median",
                    source_column=column,
                    formula="median(region, sector)",
                    input_fingerprint=row_fingerprint,
                ),
                NumericFact(
                    fact_id=_fact_id("delta-vs-peer", column),
                    label=f"Delta vs peer: {column.strip()}",
                    value=float(value) - float(median),
                    unit=_unit(column),
                    as_of=as_of,
                    source="TP deterministic calculation",
                    source_column=column,
                    formula=f"{company_fact_id} - {median_fact_id}",
                    input_fingerprint=row_fingerprint,
                ),
            ]
        )
        if len(facts) >= MAX_FACTS:
            break
    facts = facts[:MAX_FACTS]
    content = {
        "isin": str(clean_row.get("ISIN") or ""),
        "name": str(clean_row.get("Name") or ""),
        "symbol": clean_row.get("Symbol"),
        "as_of": as_of,
        "facts": [fact.model_dump() for fact in facts],
    }
    return CompanyResearchSnapshot(
        isin=content["isin"],
        name=content["name"],
        symbol=str(content["symbol"]) if content["symbol"] is not None else None,
        as_of=as_of,
        region=clean_row.get("Exchange Country Region"),
        sector=clean_row.get("Supersector"),
        facts=facts,
        snapshot_fingerprint=_digest(content),
    )


__all__ = ["build_snapshot"]

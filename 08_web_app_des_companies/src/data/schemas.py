"""Column name constants and shared dataset schema.

Using constants instead of string literals prevents typos across the codebase
and makes future schema migrations trivial (single source of truth).
"""
from __future__ import annotations

# --- Shared columns between DES and NEWS datasets ---
COL_DATE: str = "Date"
COL_TITLE: str = "Title"
COL_BODY: str = "HTMLbody"  # Actually Markdown content despite the name
COL_COMPANY_RAW: str = "Company"
COL_ISIN: str = "ISIN"
COL_NAME: str = "NAME"
COL_SECTOR: str = "SECTOR"
COL_COUNTRY: str = "COUNTRY"
COL_COMPANY: str = "COMPANY"

# Ordered list used when standardizing loaded DataFrames
EXPECTED_COLUMNS: tuple[str, ...] = (
    COL_DATE,
    COL_TITLE,
    COL_BODY,
    COL_COMPANY_RAW,
    COL_ISIN,
    COL_NAME,
    COL_SECTOR,
    COL_COUNTRY,
    COL_COMPANY,
)

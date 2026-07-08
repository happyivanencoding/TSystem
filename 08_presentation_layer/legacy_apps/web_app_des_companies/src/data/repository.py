"""CompanyRepository — semantic access layer over raw datasets.

This is the ONLY data entry point used by services / UI layers.
Adding new datasets (e.g. fundamentals) is done here by exposing new
high-level methods, keeping UI callers stable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from src.data import loaders
from src.data.schemas import (
    COL_BODY,
    COL_COUNTRY,
    COL_DATE,
    COL_ISIN,
    COL_NAME,
    COL_SECTOR,
)
from src.data.schemas_ciq import (
    CIQ_COL_DATE,
    CIQ_COL_ICB_SUPERSECTOR,
    CIQ_COL_ISIN as CIQ_ISIN,
)


def _latest_ciq_supersector_by_isin() -> dict[str, str]:
    """Dernière ligne CIQ par ISIN : secteur déjà mappé Benchmark → libellé ICB."""
    try:
        ciq = loaders.load_screen_aggregate_ciq()
    except (FileNotFoundError, ValueError):
        return {}
    sub = ciq[[CIQ_ISIN, CIQ_COL_DATE, CIQ_COL_ICB_SUPERSECTOR]].copy()
    sub[CIQ_COL_DATE] = pd.to_datetime(sub[CIQ_COL_DATE], errors="coerce")
    sub = sub.sort_values(CIQ_COL_DATE, ascending=False)
    sub = sub.drop_duplicates(subset=[CIQ_ISIN], keep="first")
    out: dict[str, str] = {}
    for _, row in sub.iterrows():
        isin = str(row[CIQ_ISIN]).strip()
        v = row[CIQ_COL_ICB_SUPERSECTOR]
        if pd.notna(v) and str(v).strip():
            out[isin] = str(v).strip()
    return out


@dataclass(frozen=True)
class CompanyIdentity:
    """Minimal company identity used by list views."""

    isin: str
    name: str
    country: str
    sector: str


class CompanyRepository:
    """High-level data API used by services and UI callbacks."""

    def __init__(self) -> None:
        # Eager load: ~8 MB total, trivial for in-memory filtering speed
        self._des: pd.DataFrame = loaders.load_des()
        self._news: pd.DataFrame = loaders.load_news()
        self._ciq_sector_by_isin: dict[str, str] = _latest_ciq_supersector_by_isin()
        # Aperçu carte accueil : une fois par processus (évite tri/dedup à chaque pagination)
        self._latest_des_preview: pd.DataFrame = (
            self._des.sort_values(COL_DATE, ascending=False)
            .drop_duplicates(subset=[COL_ISIN], keep="first")[[COL_ISIN, COL_BODY]]
            .reset_index(drop=True)
        )

    # --- Reference data (for filter dropdowns) ---
    def list_countries(self) -> list[str]:
        return sorted(self._des[COL_COUNTRY].dropna().unique().tolist())

    def list_sectors(self) -> list[str]:
        return sorted(self.companies_df()[COL_SECTOR].dropna().unique().tolist())

    # --- Company catalog (one row per ISIN, built from DES) ---
    def latest_des_preview(self) -> pd.DataFrame:
        """ISIN + dernier corps DES (markdown) pour fusion catalogue / cartes."""
        return self._latest_des_preview

    def companies_df(self) -> pd.DataFrame:
        """Return one canonical row per company with identity columns only."""
        cols = [COL_ISIN, COL_NAME, COL_COUNTRY, COL_SECTOR]
        # Keep first occurrence to preserve most recent DES (parquet is sorted by date desc upstream)
        out = (
            self._des[cols]
            .dropna(subset=[COL_ISIN])
            .drop_duplicates(subset=[COL_ISIN], keep="first")
            .reset_index(drop=True)
        )
        if self._ciq_sector_by_isin:
            mapped = out[COL_ISIN].map(self._ciq_sector_by_isin)
            out[COL_SECTOR] = mapped.fillna(out[COL_SECTOR])
        return out

    # --- Single-company access ---
    def get_description(self, isin: str) -> Optional[pd.Series]:
        """Return the most recent DES row for the given ISIN, or None."""
        rows = self._des[self._des[COL_ISIN] == isin]
        if rows.empty:
            return None
        return rows.sort_values(COL_DATE, ascending=False).iloc[0]

    def get_news(self, isin: str) -> pd.DataFrame:
        """Return all news rows for a given ISIN, sorted by date desc."""
        rows = self._news[self._news[COL_ISIN] == isin]
        return rows.sort_values(COL_DATE, ascending=False).reset_index(drop=True)

    def get_identity(self, isin: str) -> Optional[CompanyIdentity]:
        row = self.get_description(isin)
        if row is None:
            return None
        isin_s = str(row[COL_ISIN]).strip()
        sector = row[COL_SECTOR]
        if self._ciq_sector_by_isin and isin_s in self._ciq_sector_by_isin:
            sector = self._ciq_sector_by_isin[isin_s]
        return CompanyIdentity(
            isin=row[COL_ISIN],
            name=row[COL_NAME],
            country=row[COL_COUNTRY],
            sector=sector,
        )


# --- Module-level singleton ---
# The repository is intentionally a shared instance: its data is immutable
# during app lifetime and loaders are already cached.
_repo_instance: Optional[CompanyRepository] = None


def get_repository() -> CompanyRepository:
    """Return the process-wide CompanyRepository singleton."""
    global _repo_instance
    if _repo_instance is None:
        _repo_instance = CompanyRepository()
    return _repo_instance

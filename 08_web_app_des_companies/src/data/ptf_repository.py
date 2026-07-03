"""Portefeuilles (PTF) issus de ``PTF_IA_WORLD.xlsx`` — accès haut niveau."""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.data import loaders
from src.data.schemas_ptf import PTF_COL_DATE, PTF_COL_ISIN, PTF_COL_PTF, PTF_COL_WEIGHT


class PtfRepository:
    """API sur le fichier PTF (plusieurs dates par ISIN possibles)."""

    @property
    def df(self) -> pd.DataFrame:
        # Toujours via ``load_ptf`` : mtime dans loaders invalide le cache disque
        return loaders.load_ptf()

    def list_ptf_names(self) -> list[str]:
        col = PTF_COL_PTF
        d = self.df
        if col not in d.columns:
            return []
        s = d[col].dropna().astype(str).str.strip()
        return sorted(s.unique().tolist(), key=str.lower)

    def holdings_asof(self, ptf: str, asof: pd.Timestamp) -> pd.DataFrame:
        """Lignes du PTF à la date ``asof`` (égalité stricte), une ligne par ISIN.

        Sinon : un seul snapshot du portefeuille = dernière ``Date`` ≤ ``asof``
        (même date pour tous les titres), pas une date max par ISIN.
        """
        d = self.df
        ptf_s = str(ptf).strip()
        m = d[PTF_COL_PTF].astype(str).str.strip() == ptf_s
        sub = d.loc[m].copy()
        if sub.empty:
            return pd.DataFrame(
                {PTF_COL_ISIN: pd.Series([], dtype=object), PTF_COL_WEIGHT: []}
            )
        if PTF_COL_DATE not in sub.columns:
            return sub[[PTF_COL_ISIN, PTF_COL_WEIGHT]].drop_duplicates(
                subset=[PTF_COL_ISIN]
            )
        asof = pd.Timestamp(asof)
        sub[PTF_COL_DATE] = pd.to_datetime(sub[PTF_COL_DATE], errors="coerce")
        exact = sub[sub[PTF_COL_DATE] == asof]
        if not exact.empty:
            return exact[[PTF_COL_ISIN, PTF_COL_WEIGHT]].drop_duplicates(
                subset=[PTF_COL_ISIN]
            )
        sub = sub[sub[PTF_COL_DATE] <= asof]
        if sub.empty:
            return pd.DataFrame(
                {PTF_COL_ISIN: pd.Series([], dtype=object), PTF_COL_WEIGHT: []}
            )
        d_max = sub[PTF_COL_DATE].max()
        last = sub[sub[PTF_COL_DATE] == d_max]
        return last[[PTF_COL_ISIN, PTF_COL_WEIGHT]].drop_duplicates(
            subset=[PTF_COL_ISIN]
        )


_ptf: Optional["PtfRepository"] = None


def get_ptf_repository() -> PtfRepository:
    global _ptf
    if _ptf is None:
        _ptf = PtfRepository()
    return _ptf

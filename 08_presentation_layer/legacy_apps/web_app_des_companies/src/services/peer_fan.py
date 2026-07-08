"""Séries temporelles « fan » : ancre + pairs (même secteur, même seau régional, bench)."""
from __future__ import annotations

import random
from typing import Optional

import pandas as pd

from src.data.schemas_ciq import (
    CIQ_COL_DATE,
    CIQ_COL_ISIN,
    CIQ_COL_REGION,
    PEER_INDUSTRY_COLS_ORDER,
)
from src.services.region_bucket import region_bucket_value

MAX_PEER_TRACES: int = 80


def _anchor_industry_key(r: pd.Series) -> Optional[tuple[str, str]]:
    """Premier champ secteur non vide, dans l'ordre ICB19 → FactSet Ind → FactSet Economy.

    Retour (nom_colonne, valeur_normalisée_en_minuscule) pour comparaison stricte.
    """
    for col in PEER_INDUSTRY_COLS_ORDER:
        if col not in r.index:
            continue
        v = r.get(col)
        if v is not None and pd.notna(v) and str(v).strip():
            return (col, str(v).strip().lower())
    return None


def _peer_row_mask(
    sub: pd.DataFrame, anchor_isin: str
) -> tuple[Optional[tuple[str, str]], Optional[str], pd.Series]:
    """Masque booléen (index ``sub``) : lignes pairs même industrie (col. ancre) + même seau région."""
    empty = pd.Series(False, index=sub.index, dtype=bool)
    arow = sub[sub[CIQ_COL_ISIN] == anchor_isin]
    if arow.empty:
        return None, None, empty
    r0 = arow.iloc[0]
    ind_key = _anchor_industry_key(r0)
    if ind_key is None:
        return None, None, empty
    col, val = ind_key
    if col not in sub.columns:
        return ind_key, None, empty
    buck = region_bucket_value(r0.get(CIQ_COL_REGION))
    colv = sub[col]
    m_ind = colv.notna() & (colv.astype(str).str.strip().str.lower() == val)
    reg_buckets = sub[CIQ_COL_REGION].map(region_bucket_value)
    m_reg = reg_buckets == buck
    ais = str(anchor_isin).strip()
    m_not_anchor = sub[CIQ_COL_ISIN].astype(str).str.strip() != ais
    peer_mask = m_ind & m_reg & m_not_anchor
    return ind_key, buck, peer_mask


def peer_fan_timeseries(
    index_history: pd.DataFrame,
    anchor_isin: str,
    metric_col: str,
    *,
    seed: int = 42,
) -> tuple[Optional[pd.Series], dict[str, pd.Series], Optional[str]]:
    """Ancre : série complète dans l'historique bench. Pairs : points (date, valeur) si pair ce jour-là."""
    if index_history is None or index_history.empty:
        return None, {}, "Aucun historique bench"
    need = {CIQ_COL_DATE, CIQ_COL_ISIN, metric_col, CIQ_COL_REGION}
    if not need.issubset(index_history.columns):
        return None, {}, "Colonnes requises manquantes"
    if not any(c in index_history.columns for c in PEER_INDUSTRY_COLS_ORDER):
        return None, {}, "Aucune colonne secteur (ICB / FactSet)"

    H = index_history.copy()
    H[CIQ_COL_DATE] = pd.to_datetime(H[CIQ_COL_DATE], errors="coerce")
    H = H.dropna(subset=[CIQ_COL_DATE])

    dates = sorted(H[CIQ_COL_DATE].unique())
    chunks: list[pd.DataFrame] = []

    for d in dates:
        sub = H[H[CIQ_COL_DATE] == d]
        _i, _b, peer_mask = _peer_row_mask(sub, anchor_isin)
        if not peer_mask.any():
            continue
        pr = sub.loc[peer_mask, [CIQ_COL_ISIN, metric_col]].copy()
        pr = pr.dropna(subset=[metric_col])
        if pr.empty:
            continue
        pr[CIQ_COL_ISIN] = pr[CIQ_COL_ISIN].astype(str).str.strip()
        pr["_dt"] = pd.Timestamp(d)
        pr["_v"] = pd.to_numeric(pr[metric_col], errors="coerce")
        pr = pr.dropna(subset=["_v"])
        if pr.empty:
            continue
        chunks.append(pr[[CIQ_COL_ISIN, "_dt", "_v"]])

    out_peers: dict[str, pd.Series] = {}
    if chunks:
        big = pd.concat(chunks, ignore_index=True)
        u = big[CIQ_COL_ISIN].unique().tolist()
        if len(u) > MAX_PEER_TRACES:
            rng = random.Random(seed)
            keep = set(rng.sample(sorted(u), MAX_PEER_TRACES))
            big = big[big[CIQ_COL_ISIN].isin(keep)]
        for pid, g in big.groupby(CIQ_COL_ISIN, sort=False):
            g = g.sort_values("_dt")
            out_peers[str(pid)] = pd.Series(
                g["_v"].to_numpy(dtype=float, copy=False),
                index=pd.DatetimeIndex(g["_dt"]),
            )

    arows = H[H[CIQ_COL_ISIN] == anchor_isin][[CIQ_COL_DATE, metric_col]].dropna(
        subset=[metric_col]
    )
    if arows.empty:
        anc_s: Optional[pd.Series] = None
    else:
        anc_s = arows.set_index(CIQ_COL_DATE)[metric_col].sort_index()
        anc_s = anc_s[~anc_s.index.duplicated(keep="last")]

    return anc_s, out_peers, None

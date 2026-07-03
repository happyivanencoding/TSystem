"""Groupes d'affichage PTF : libellé UI -> nom de colonne CIQ (screen_aggregateCIQ)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from config.settings import FACTOR_SCORE_COLUMNS_CONFIG, PTF_METRIC_GROUPS

# Les 7 « facteurs » (Scores) : sous-graphiques / exclus du clic « autre metric » (voir FACTOR_SCORE_COLUMNS_CONFIG)
FACTOR_SCORE_COLUMNS: frozenset[str] = frozenset(FACTOR_SCORE_COLUMNS_CONFIG)

# Colonnes jamais interprétées comme métrique cliquable
METADATA_DATA_TABLE_IDS: frozenset[str] = frozenset(
    {"ptf_w", "isin", "name", "n"}
)


@dataclass(frozen=True)
class ColumnGroup:
    """Un groupe d'en-têtes (Summary, Market, …)."""

    id: str
    label: str
    # (libellé affiché, nom colonne CIQ) — exclut le poids bench, injecté à part
    entries: tuple[tuple[str, str], ...]


def _build_raw_groups() -> tuple[ColumnGroup, ...]:
    out: list[ColumnGroup] = []
    for g in PTF_METRIC_GROUPS:
        ent = tuple(tuple(p) for p in g["entries"])
        out.append(
            ColumnGroup(
                id=str(g["id"]),
                label=str(g["label"]),
                entries=ent,
            )
        )
    return tuple(out)


# Valeurs cibles (depuis config.settings.PTF_METRIC_GROUPS ; filtrage à l’exécution selon les colonnes CIQ)
_RAW_GROUPS: tuple[ColumnGroup, ...] = _build_raw_groups()


def filter_groups_for_ciq(available: Iterable[str]) -> list[ColumnGroup]:
    """Ne garde que les entrées dont la colonne CIQ existe."""
    have = set(available)
    out: list[ColumnGroup] = []
    for g in _RAW_GROUPS:
        ent = tuple((lab, c) for lab, c in g.entries if c in have)
        if ent:
            out.append(
                ColumnGroup(
                    id=g.id,
                    label=g.label,
                    entries=ent,
                )
            )
    return out


def default_summary_column_names(available: set[str], bench_col: str) -> list[str]:
    """Colonnes par défaut : poids bench + colonnes du groupe Summary présentes dans ``available``."""
    cols: list[str] = []
    if bench_col in available:
        cols.append(bench_col)
    g = next((x for x in _RAW_GROUPS if x.id == "summary"), None)
    if g:
        for _lab, c in g.entries:
            if c in available and c not in cols:
                cols.append(c)
    return cols


def ciq_name_for_display_label(available: set[str], display: str) -> Optional[str]:
    for g in _RAW_GROUPS:
        for lab, c in g.entries:
            if lab == display and c in available:
                return c
    return None

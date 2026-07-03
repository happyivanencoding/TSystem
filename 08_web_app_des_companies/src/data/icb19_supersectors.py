"""Liste ordonnée des 19 ICB19 Supersectors (fichier ``ICB_mapping.csv``)."""
from __future__ import annotations

import pandas as pd

from config.settings import ICB_MAPPING_CSV

# Libellés courts pour les onglets (value callback = libellé DATA complet)
_ICB_TAB_LABEL_SHORT: dict[str, str] = {
    "Telecommunications": "Télécoms",
    "Industrial Goods & Services": "Industriel",
    "Food, Beverage & Tobacco": "Alimentation",
    "Personal & Household Goods": "Perso & ménage",
    "Financial Services": "Fin. services",
    "Basic Resources": "Ressources",
    "Travel & Leisure": "Loisirs",
    "Auto & Parts": "Auto",
}


def icb_supersector_tab_label(full: str) -> str:
    """Libellé affiché sur l’onglet ; ``full`` reste la valeur métier (filtrage CIQ)."""
    t = str(full).strip()
    return _ICB_TAB_LABEL_SHORT.get(t, t)


def load_icb19_supersector_labels() -> list[str]:
    """Retourne les 19 libellés dans l'ordre des codes 1..19."""
    mdf = pd.read_csv(ICB_MAPPING_CSV)
    if "code" in mdf.columns and "icb19_supersector" in mdf.columns:
        mdf = mdf.sort_values("code", ascending=True)
    col = "icb19_supersector"
    out: list[str] = []
    for x in mdf[col].tolist():
        if x is not None and not (isinstance(x, float) and pd.isna(x)):
            t = str(x).strip()
            if t:
                out.append(t)
    return out

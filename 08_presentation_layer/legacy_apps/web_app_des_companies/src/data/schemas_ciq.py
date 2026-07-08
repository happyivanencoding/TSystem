"""Column name constants for the ``screen_aggregateCIQ`` parquet.

Kept separate from DES/NEWS schema: this dataset has ~276 columns and a very
different shape (panel: Date x ISIN with many numeric metrics + per-index
weight columns ``Weight in XXX``).
"""
from __future__ import annotations

CIQ_COL_DATE: str = "Date"
CIQ_COL_SYMBOL: str = "Symbol"
CIQ_COL_NAME: str = "Name"
CIQ_COL_ISIN: str = "ISIN"  # Present as DataFrame index in the raw parquet

# Industry / region (string columns, not the leading-space float codes)
CIQ_COL_ICB_INDUSTRY: str = "ICB11 Industry"
# Libellé secteur canonique : rempli au chargement depuis le code « Benchmark ICB Supersector »
# via ``ICB_mapping.csv`` ; si code absent / non mappé, conserve la valeur parquet ICB19.
CIQ_COL_ICB_SUPERSECTOR: str = "ICB19 Supersector"
# Nom logique FactSet (colonne réelle peut avoir un espace en tête dans le parquet)
CIQ_COL_BENCHMARK_ICB_SUPERSECTOR: str = "Benchmark ICB Supersector"
# Secours quand ICB est vide (souvent ~98 % NaN dans le panel historique) :
CIQ_COL_FACTSET_IND: str = "FactSet Ind"
CIQ_COL_FACTSET_ECONOMY: str = "FactSet Economy"
CIQ_COL_REGION: str = "Exchange Country Region"
CIQ_COL_COUNTRY: str = "Benchmark Country English"

# Ordre de priorité pour « même secteur » (pairs / bench)
PEER_INDUSTRY_COLS_ORDER: tuple[str, ...] = (
    CIQ_COL_ICB_SUPERSECTOR,
    CIQ_COL_FACTSET_IND,
    CIQ_COL_FACTSET_ECONOMY,
)

# Prefix for per-index constituent weight columns (e.g. ``Weight in MSCI WORLD``)
WEIGHT_IN_PREFIX: str = "Weight in "

# Columns that must never appear in the numeric-metric picker
CIQ_NON_METRIC_COLS: frozenset[str] = frozenset(
    {
        CIQ_COL_DATE,
        CIQ_COL_SYMBOL,
        CIQ_COL_NAME,
        CIQ_COL_ISIN,
        CIQ_COL_ICB_INDUSTRY,
        CIQ_COL_ICB_SUPERSECTOR,
        CIQ_COL_BENCHMARK_ICB_SUPERSECTOR,
        CIQ_COL_REGION,
        CIQ_COL_COUNTRY,
        "Exchange Country Name",
        "Exchange Country Iso2",
        "Company Main Exchange",
        "Company SEDOL",
        "Curncy Iso",
        "FactSet Economy",
        "FactSet Ind",
        "Benchmark Identifier -  SEDOLCHK",
    }
)

# Minimal columns required for the page to render at all
CIQ_MIN_REQUIRED: tuple[str, ...] = (
    CIQ_COL_DATE,
    CIQ_COL_NAME,
    CIQ_COL_ICB_SUPERSECTOR,
)

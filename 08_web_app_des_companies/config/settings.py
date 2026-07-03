"""Global application settings.

Centralized configuration: data paths, pagination, UI defaults.
Change values here to tune the app without touching UI or data code.
"""
from __future__ import annotations

from pathlib import Path
import sys

_TP_ROOT = Path(__file__).resolve().parents[2]
if str(_TP_ROOT) not in sys.path:
    sys.path.insert(0, str(_TP_ROOT))

from tp_core.data_sources import SCREEN_AGGREGATE_PATH

# --- Paths ---
ROOT_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = ROOT_DIR / "data"

DES_PARQUET: Path = DATA_DIR / "last_DES.parquet"
NEWS_PARQUET: Path = DATA_DIR / "Last_NEWS_3months.parquet"
SCREEN_AGGREGATE_PARQUET: Path = SCREEN_AGGREGATE_PATH
# Historical name kept for app compatibility; the canonical screen aggregate now
# contains the CIQ columns and must be the only source used by the app.
SCREEN_AGG_CIQ_PARQUET: Path = SCREEN_AGGREGATE_PARQUET
ICB_MAPPING_CSV: Path = DATA_DIR / "ICB_mapping.csv"
# Feuille : colonnes PTF, Date, Weight, ISIN
PTF_XLSX: Path = DATA_DIR / "PTF_IA_WORLD.xlsx"

# --- UI ---
APP_TITLE: str = "Panorama des Entreprises"
APP_SUBTITLE: str = "Descriptions & Actualités financières"

# Card grid pagination on the home page
CARDS_PER_PAGE: int = 24

# Max characters displayed in the card summary snippet
CARD_SUMMARY_CHARS: int = 180

# --- Server ---
HOST: str = "127.0.0.1"
PORT: int = 8050
DEBUG: bool = True

# --- Page PTF / indice (principalement modifiée par le métier ; noms de colonnes = screen_aggregateCIQ) ---

# Valeur par défaut du sélecteur de benchmark ; si None, premier élément de list_indices
DEFAULT_BENCHMARK: str | None = "Weight in MSCI WORLD"

# Date par défaut : dernière ou première dans la liste des dates pour ce bench
PTF_DEFAULT_DATE_MODE: str = "latest"  # "latest" | "first"

# Lignes par page du DataTable principal
PTF_TABLE_PAGE_SIZE: int = 25

# Graphique d’historique des facteurs : chaque tuple (libellé affiché, colonne CIQ) ; ordre = ordre des traces
FACTOR_TRACES: tuple[tuple[str, str], ...] = (
    ("Quality", "Quality Avg Percentile"),
    ("Growth", "Growth Avg Percentile"),
    ("Lowvol", "LowVol Avg Percentile"),
    ("Momentum", "MOM Score"),
    ("Value", "Dividend Avg Percentile"),
    ("ML", "Score ML"),
)

# Colonnes entrant dans la moyenne du score MultiFactor (ajouter/retirer « Score ML » ici, indépendamment du switch ML dans FACTOR_TRACES)
MULTIFACTOR_BASE_COLUMNS: tuple[str, ...] = (
    "Quality Avg Percentile",
    "Growth Avg Percentile",
    "LowVol Avg Percentile",
    "MOM Score",
    "Dividend Avg Percentile",
)

# Colonnes « facteur » sur tout le site (clic / exclusion) ; retirer « Score ML » ici si ML retiré du graphique
FACTOR_SCORE_COLUMNS_CONFIG: tuple[str, ...] = (
    "Multi Avg Percentile",
    "Score ML",
    "MOM Score",
    "LowVol Avg Percentile",
    "Growth Avg Percentile",
    "Dividend Avg Percentile",
    "Quality Avg Percentile",
)

# Colonnes d’indicateurs visibles par défaut dans ptf-cols (noms CIQ) ; tuple vide = groupe summary tout coché + bench
PTF_DEFAULT_VISIBLE_COLUMNS: tuple[str, ...] = ()

# Groupes d’indicateurs pairs : id / label / entries ((libellé affiché, nom de colonne))
PTF_METRIC_GROUPS: tuple[dict, ...] = (
    {
        "id": "summary",
        "label": "Summary",
        "entries": (
            ("ESG E", "ESG_E"),
            ("ESG S", "ESG_S"),
            ("ESG G", "ESG_G"),
            ("ESG analyst", "ESG_ANALYST_SCORE"),
            ("Carbon intensity (sales)", "CarbonIntensity_Sales"),
            ("MarketV EUR", "Benchmark Market Value Millions in EUR"),
            ("Multi score", "Multi Avg Percentile"),
            ("Score ML", "Score ML"),
        ),
    },
    {
        "id": "market",
        "label": "Market",
        "entries": (
            ("Mom score", "MOM Score"),
            ("LowVol score", "LowVol Avg Percentile"),
            ("Perf5D", "Perf5D"),
            ("Perf1M", "Perf1M"),
            ("Perf3M", "Perf3M"),
            ("Perf6M", "Perf6M"),
            ("Daily Vol 60J", "Daily Vol 60J"),
            ("PMOM 12M1M", "PMOM 12M1M"),
            ("EPS NTM 3M Growth", "EPS NTM 3M Growth"),
            ("EPS Revision Ratio", "EPS Revision Ratio"),
            ("SP Price Target CIQ", "SP Price Target CIQ"),
            ("SP Price Close CIQ", "SP Price Close CIQ"),
            ("Pct_Short_Interest", "Pct_Short_Interest"),
        ),
    },
    {
        "id": "growth",
        "label": "Growth",
        "entries": (
            ("Growth score", "Growth Avg Percentile"),
            ("Sales Growth FY1", "Sales Growth FY1"),
            ("Gross Income Growth FY1", "Gross Income Growth FY1"),
            ("EPS Growth FY1", "EPS Growth FY1"),
            ("SP Est 5Y EPS Gr CIQ", "SP Est 5Y EPS Gr CIQ"),
            ("Revenue 5Y CAGR", "Revenue 5Y CAGR"),
            ("Gross Profit 5Y CAGR", "Gross Profit 5Y CAGR"),
            ("Ebitda 5Y CAGR", "Ebitda 5Y CAGR"),
            ("Ebit 5Y CAGR", "Ebit 5Y CAGR"),
            ("CFO 5Y CAGR", "CFO 5Y CAGR"),
            ("Const Earning 5Y CAGR", "Const Earning 5Y CAGR"),
        ),
    },
    {
        "id": "valorisation",
        "label": "Valorisation",
        "entries": (
            ("Value score", "Value Avg Percentile"),
            ("PE LTM", "PE LTM"),
            ("PE FY1", "PE FY1"),
            ("PB LTM", "PB LTM"),
            ("Price to Book FY1", "Price to Book FY1"),
            ("PFCF LTM", "PFCF LTM"),
            ("Price to FreeCF FY1", "Price to FreeCF FY1"),
            ("EV To EBITDA LTM", "EV To EBITDA LTM"),
            ("EV To EBITDA FY1", "EV To EBITDA FY1"),
            ("EV to Ebit FY1", "EV to Ebit FY1"),
            ("EV to Sales FY1", "EV to Sales FY1"),
            ("Price Cont Op Earning", "Price Cont Op Earning"),
            ("P to CFO", "P to CFO"),
        ),
    },
    {
        "id": "quali",
        "label": "Quali",
        "entries": (
            ("Dividend score", "Dividend Avg Percentile"),
            ("Quality score", "Quality Avg Percentile"),
            ("Gross Margin", "Gross Margin"),
            ("Ebitda Margin", "Ebitda Margin"),
            ("EBITDAm FY1", "EBITDAm FY1"),
            ("Cont Op Earning Margin", "Cont Op Earning Margin"),
            ("Oper Margin", "Oper Margin"),
            ("ROE avg FY0", "ROE avg FY0"),
            ("Asset TO exFIN", "Asset TO exFIN"),
            ("FCF Conversion", "FCF Conversion"),
            ("NetDebt to EBITDA exFIN", "NetDebt to EBITDA exFIN"),
            ("netD to EBITDA FY1", "netD to EBITDA FY1"),
            ("Net Debt to Ebit", "Net Debt to Ebit"),
            ("Net Debt to Tot Equity", "Net Debt to Tot Equity"),
            ("Net Debt to Market Cap", "Net Debt to Market Cap"),
            ("Current Ratio", "Current Ratio"),
        ),
    },
)


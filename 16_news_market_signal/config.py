"""Four-market definitions and stable paths for the news-signal research system."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
TP_ROOT = PROJECT_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
OUTPUT_DIR = PROJECT_DIR / "outputs"
RUNS_DIR = PROJECT_DIR / "runs"
GENERATED_QUERY_DIR = PROJECT_DIR / "queries" / "generated"
ENTITY_HISTORY_PATH = OUTPUT_DIR / "entity_sector_history.parquet"

START_DATE = "2007-01-01"
MARKETS = ("US", "EU", "JP", "CN_HK")


@dataclass(frozen=True)
class MarketSpec:
    code: str
    timezone: str
    close_time: time
    benchmark: str
    weight_columns: tuple[str, ...]
    gdelt_country_codes: tuple[str, ...]
    proxy_region: str | None = None
    proxy_country: str | None = None
    proxy_n: int | None = None

    @property
    def signal_cutoff(self) -> time:
        minutes = self.close_time.hour * 60 + self.close_time.minute - 30
        return time(minutes // 60, minutes % 60)


# GDELT uses FIPS-style country codes in event geography fields.
EU_GDELT_CODES = (
    "AL", "AU", "BE", "BK", "BU", "HR", "CY", "EZ", "DA", "EN", "FI",
    "FR", "GM", "GR", "HU", "IC", "EI", "IT", "LG", "LH", "LU", "MK",
    "MT", "NL", "NO", "PL", "PO", "RO", "RI", "LO", "SI", "SP", "SW",
    "SZ", "UK",
)

MARKET_SPECS = {
    "US": MarketSpec(
        code="US",
        timezone="America/New_York",
        close_time=time(16, 0),
        benchmark="SP500",
        weight_columns=("Weight in SP500",),
        gdelt_country_codes=("US",),
        proxy_region="North America",
        proxy_n=500,
    ),
    "EU": MarketSpec(
        code="EU",
        timezone="Europe/Paris",
        close_time=time(17, 30),
        benchmark="STOXX EUROPE 600",
        weight_columns=("Weight in STOXX EUROPE 600",),
        gdelt_country_codes=EU_GDELT_CODES,
        proxy_region="West Europe",
        proxy_n=600,
    ),
    "JP": MarketSpec(
        code="JP",
        timezone="Asia/Tokyo",
        close_time=time(15, 0),
        benchmark="NIKKEI",
        weight_columns=("Weight in NIKKEI",),
        gdelt_country_codes=("JA",),
        proxy_country="JAPAN",
        proxy_n=400,
    ),
    "CN_HK": MarketSpec(
        code="CN_HK",
        timezone="Asia/Hong_Kong",
        close_time=time(16, 0),
        benchmark="MSCI EM/WORLD CHINA-HONG KONG",
        weight_columns=("Weight in MSCI EM", "Weight in MSCI WORLD"),
        gdelt_country_codes=("CH", "HK"),
    ),
}

TOPIC_KEYWORDS = {
    "monetary_policy": ("CENTRAL_BANK", "INTEREST_RATE", "MONETARY_POLICY", "FEDERAL_RESERVE"),
    "inflation": ("INFLATION", "CONSUMER_PRICE", "PRODUCER_PRICE"),
    "growth": ("ECON_GROWTH", "GDP", "RECESSION", "UNEMPLOYMENT", "MANUFACTURING"),
    "credit_liquidity": ("BANK", "CREDIT", "LIQUIDITY", "DEFAULT", "DEBT"),
    "earnings": ("EARNINGS", "PROFIT", "REVENUE", "CORPORATE_RESULTS"),
    "energy_commodities": ("ENERGY", "OIL", "GAS", "COMMODITY", "MINING"),
    "geopolitics_trade": ("SANCTION", "TRADE", "TARIFF", "WAR", "CONFLICT", "DIPLOMACY"),
    "technology": ("TECHNOLOGY", "SEMICONDUCTOR", "ARTIFICIAL_INTELLIGENCE", "CYBER"),
    "regulation": ("REGULATION", "ANTITRUST", "LAW", "TAX"),
}

FINANCE_THEME_REGEX = "|".join(
    sorted({token for tokens in TOPIC_KEYWORDS.values() for token in tokens})
)

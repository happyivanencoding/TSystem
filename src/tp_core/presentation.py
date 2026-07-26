"""展示/报告层可复用的纯函数。

这里不依赖 Dash、Streamlit 或任何前端框架；应用层只负责把自己的列名和
组件状态传进来。这样公司分析、报告生成和未来 dashboard 可以共享同一套
筛选、分页与行业标签规则。
"""

from __future__ import annotations

from collections.abc import Iterable
import math

import pandas as pd


WEST_EUROPE = "west_europe"
NORTH_AMERICA = "north_america"
OTHERS = "others"


ICB_SUPERSECTOR_BY_CODE: dict[int, str] = {
    1: "Auto & Parts",
    2: "Banks",
    3: "Basic Resources",
    4: "Chemicals",
    5: "Construction",
    6: "Financial Services",
    7: "Food, Beverage & Tobacco",
    8: "Health Care",
    9: "Industrial Goods & Services",
    10: "Insurance",
    11: "Media",
    12: "Energy",
    13: "Personal & Household Goods",
    14: "Real Estate",
    15: "Retail",
    16: "Technology",
    17: "Telecommunications",
    18: "Travel & Leisure",
    19: "Utilities",
}


def region_bucket_value(region) -> str:
    """Map exchange-region labels to the three presentation buckets."""

    if region is None or (isinstance(region, float) and math.isnan(region)):
        return OTHERS
    value = str(region).strip().lower()
    if value == "west europe":
        return WEST_EUROPE
    if value == "north america":
        return NORTH_AMERICA
    return OTHERS


def add_icb_supersector_names(
    dataframe: pd.DataFrame,
    icb_code_column: str = " Benchmark ICB Supersector ",
    output_column: str = "Supersector",
) -> pd.DataFrame:
    """Add ICB supersector names from numeric ICB19 codes."""

    out = dataframe.copy()
    out[output_column] = pd.to_numeric(out[icb_code_column], errors="coerce").map(ICB_SUPERSECTOR_BY_CODE)
    return out


def apply_filters(
    df: pd.DataFrame,
    countries: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    query: str | None = None,
    *,
    country_col: str,
    sector_col: str,
    name_col: str,
    isin_col: str,
) -> pd.DataFrame:
    """Filter a company-like DataFrame by country, sector and text query."""

    result = df

    if countries:
        result = result[result[country_col].isin(set(countries))]

    if sectors:
        result = result[result[sector_col].isin(set(sectors))]

    if query:
        q = query.strip().lower()
        if q:
            name_hit = result[name_col].astype(str).str.lower().str.contains(q, na=False)
            isin_hit = result[isin_col].astype(str).str.lower().str.contains(q, na=False)
            result = result[name_hit | isin_hit]

    return result.reset_index(drop=True)


def paginate(df: pd.DataFrame, page: int, page_size: int) -> pd.DataFrame:
    """Return a single page slice using 1-indexed page numbers."""

    if page < 1:
        page = 1
    start = (page - 1) * page_size
    end = start + page_size
    return df.iloc[start:end].reset_index(drop=True)


def total_pages(n_items: int, page_size: int) -> int:
    """Compute total pages for a positive page size."""

    if page_size <= 0 or n_items <= 0:
        return 1
    return (n_items + page_size - 1) // page_size


__all__ = [
    "ICB_SUPERSECTOR_BY_CODE",
    "NORTH_AMERICA",
    "OTHERS",
    "WEST_EUROPE",
    "add_icb_supersector_names",
    "apply_filters",
    "paginate",
    "region_bucket_value",
    "total_pages",
]

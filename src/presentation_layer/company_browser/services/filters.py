"""兼容入口：公司筛选/分页纯函数已迁入 tp_core.presentation。"""
from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd

from tp_core.presentation import apply_filters as _apply_filters
from tp_core.presentation import paginate, total_pages

from presentation_layer.company_browser.data.schemas import COL_COUNTRY, COL_ISIN, COL_NAME, COL_SECTOR


def apply_filters(
    df: pd.DataFrame,
    countries: Optional[Iterable[str]] = None,
    sectors: Optional[Iterable[str]] = None,
    query: Optional[str] = None,
) -> pd.DataFrame:
    return _apply_filters(
        df,
        countries=countries,
        sectors=sectors,
        query=query,
        country_col=COL_COUNTRY,
        sector_col=COL_SECTOR,
        name_col=COL_NAME,
        isin_col=COL_ISIN,
    )


__all__ = ["apply_filters", "paginate", "total_pages"]

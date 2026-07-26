from __future__ import annotations

import logging
from typing import List

import pandas as pd

from tp_backtest.utils.constants import COL_SECTOR_ICB11, COL_SECTOR_ICB19

logger = logging.getLogger(__name__)

class ScoreNeutralizationMixin:
    def neutralise_score_by_secteur(self, df: pd.DataFrame, list_score_col: List[str]) -> pd.DataFrame:
        """
        Neutralize scores by sector using rank percentile.
        """
        df = df.copy()
        scores = df[list_score_col].astype(float).rank(pct=True)
        scores = (scores - scores.min()) / (scores.max() - scores.min())
        
        if self.score_neutral == "ICB 11":
            sector_col = COL_SECTOR_ICB11
        elif self.score_neutral == "ICB 19":
            sector_col = COL_SECTOR_ICB19
        else:
            df.loc[:, list_score_col] = scores
            return df

        sector_keys = df[sector_col]
        valid_sectors = sector_keys.notna()
        sector_scores = scores.loc[valid_sectors].groupby(
            sector_keys.loc[valid_sectors]
        ).rank(pct=True)
        sector_min = sector_scores.groupby(
            sector_keys.loc[valid_sectors]
        ).transform("min")
        sector_max = sector_scores.groupby(
            sector_keys.loc[valid_sectors]
        ).transform("max")
        scores.loc[valid_sectors] = (
            sector_scores - sector_min
        ) / (sector_max - sector_min)
        df.loc[:, list_score_col] = scores
        return df

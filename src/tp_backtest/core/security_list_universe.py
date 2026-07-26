from __future__ import annotations

import copy
import datetime
import logging
from typing import List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from tp_backtest.utils.constants import (
    BENCH_TO_REGION,
    COL_DATE,
    COL_ESG_SCORE,
    COL_ISIN,
    COL_SECTOR_ICB11,
    COL_SECTOR_ICB19,
    STYLE_TO_TYPE,
)

logger = logging.getLogger(__name__)

from tp_backtest.core.esg_pivot import resolve_esg_pivot_score
from tp_backtest.utils.data_utils import read_liste_noire


class UniverseSelectionMixin:
    @staticmethod
    def _resolve_score_pivot_esg(
        score_pivot_esg: Optional[Union[str, float]],
        score_pivot_esg_path: Optional[str]
    ) -> Optional[float]:
        """Resolve ESG pivot configuration to a numeric threshold when provided."""
        if score_pivot_esg is None:
            return None
        if isinstance(score_pivot_esg, (int, float)):
            return float(score_pivot_esg)
        text = str(score_pivot_esg).strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            if not score_pivot_esg_path:
                raise ValueError("score_pivot_esg_path is required when score_pivot_esg is a text pivot identifier")
            return resolve_esg_pivot_score(score_pivot_esg_path, text)
    
    def filtrage_esg_liste_noire(self, df: pd.DataFrame, date: datetime.datetime) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Filter securities based on ESG score and blacklist.
        
        Parameters:
        -----------
        df : DataFrame
            Input securities data
        date : datetime
            Current date
            
        Returns:
        --------
        tuple
            (filtered_df, titles_excluded)
        """
        df_esg = copy.deepcopy(df)
        Worst_ESG = []
        Blacklisted = []
        
        # ESG filtering: absolute pivot score takes precedence over percentile exclusion.
        if date.year >= 2014 and self.score_pivot_esg is not None:
            df_esg = df.loc[pd.to_numeric(df[COL_ESG_SCORE], errors="coerce") > self.score_pivot_esg]
            Worst_ESG = df.loc[~df.index.isin(df_esg.index)].index.tolist()
        elif date.year >= 2014 and self.esg_exclusion > 0:
            esg_pct = pd.to_numeric(df[COL_ESG_SCORE], errors="coerce").rank(pct=True)
            df_esg = df.loc[esg_pct >= self.esg_exclusion]
            Worst_ESG = df.loc[~df.index.isin(df_esg.index)].index.tolist()
        
        # Blacklist filtering
        if self._liste_noire is not None:
            if isinstance(self._liste_noire, str):
                self._liste_noire = read_liste_noire(self._liste_noire, [], [])
            
            if COL_ISIN in df_esg.columns:
                Blacklisted = df_esg[df_esg[COL_ISIN].isin(self._liste_noire)].index.tolist()
                df_esg = df_esg[~df_esg[COL_ISIN].isin(self._liste_noire)]
            elif df_esg.index.name == COL_ISIN:
                Blacklisted = df_esg[df_esg.index.isin(self._liste_noire)].index.tolist()
                df_esg = df_esg[~df_esg.index.isin(self._liste_noire)]
        
        # Save companies excluded because of ESG reason
        titles_excluded = self._save_esg_blacklist(df, Worst_ESG, Blacklisted, date)
        
        return df_esg, titles_excluded
    
    def _save_esg_blacklist(
        self,
        screen: pd.DataFrame,
        worst_esg: List[str],
        blacklisted: List[str],
        date: datetime.datetime
    ) -> pd.DataFrame:
        """Create exclusion list dataframe."""
        filtered_isins = set(worst_esg).union(set(blacklisted))
        filtered_df = screen.loc[screen.index.intersection(filtered_isins)].copy()
        
        reasons = []
        for isin in filtered_df.index:
            reason = []
            if isin in worst_esg:
                reason.append("ESG Reason")
            if isin in blacklisted:
                reason.append("Blacklisted")
            reasons.append(", ".join(reason))
        
        filtered_df["Raison Exclusion"] = reasons
        final_df = filtered_df[[COL_DATE, "Raison Exclusion"]]
        
        return final_df
    
    def adjust_bench_weight_with_recommandation(
        self,
        df: pd.DataFrame,
        reco_secto: List[float],
        date: datetime.datetime
    ) -> pd.Series:
        """Adjust benchmark sector weights with sector recommendations."""
        if self.weight_neutral == "ICB 19":
            weight_secto_bench = df.groupby(COL_SECTOR_ICB19)[f'Weight in {self.bench}'].sum() / \
                               df[f'Weight in {self.bench}'].sum()
            
            # Handle missing sectors
            icb_missing = set(range(1, 20)) - set(df[COL_SECTOR_ICB19].unique())
            if len(icb_missing) > 0:
                logger.warning(f"Missing sectors in benchmark: {list(icb_missing)}")
                try:
                    indices_to_delete = [int(icb) - 1 for icb in icb_missing]
                    reco_secto = np.delete(np.array(reco_secto), indices_to_delete)
                except Exception as e:
                    logger.error(f"Error adjusting reco_secto at {date}: {e}")
            
            # Apply recommendations
            weight_secto_bench = weight_secto_bench + np.array(reco_secto)
            
            # Adjust small weight sectors
            small_weight_mask = weight_secto_bench < 0.0025
            if small_weight_mask.any():
                logger.warning("Sectors with weight < 0.0025 adjusted to 0.0025")
                weight_secto_bench[small_weight_mask] = 0.0025
        
        elif self.weight_neutral == "ICB 11":
            weight_secto_bench = df.groupby(COL_SECTOR_ICB11)[f'Weight in {self.bench}'].sum() / \
                               df[f'Weight in {self.bench}'].sum()
        
        else:
            # 默认使用 ICB 19 分类，但不应用推荐调整
            weight_secto_bench = df.groupby(COL_SECTOR_ICB19)[f'Weight in {self.bench}'].sum() / \
                               df[f'Weight in {self.bench}'].sum()
            logger.info(f"weight_neutral={self.weight_neutral}, using default ICB 19 without recommendations")
        
        return weight_secto_bench
    
    def _monthly_base_cache_key(self, date: pd.Timestamp) -> Optional[tuple]:
        """Return a reusable monthly preparation key when the setup is cache-safe."""
        if self.monthly_base_cache is None:
            return None
        if not isinstance(self.reco_secto, list):
            return None
        if self.metrics == "Multi Avg Percentile":
            return None
        if self.financial_filter_config is not None:
            return None
        return (
            pd.Timestamp(date),
            self.bench,
            self.ponderation,
            float(self.cut_mkt_cap),
            self.weight_neutral,
            tuple(self.reco_secto),
            float(self.percentile),
        )

    @staticmethod
    def _score_source_for_cache(
        source_screen: pd.DataFrame,
        list_score_col: List[str],
        target_index: pd.Index,
    ) -> pd.DataFrame:
        """Align current signal columns to a cached monthly universe."""
        score_source = source_screen
        if score_source.index.name != COL_ISIN and COL_ISIN in score_source.columns:
            score_source = score_source.set_index(COL_ISIN)
        if score_source.index.duplicated().any():
            score_source = score_source.loc[
                ~score_source.index.duplicated(keep="first")
            ]
        return score_source.loc[:, list_score_col].reindex(target_index)
    
    def get_portfolio_name(self, style: str) -> str:
        """
        Automatically select portfolio name based on investment style, benchmark, and ranking position.
        """
        if self.mode_monthly_prod:
            if self.ptf_name == "PTF TEST":
                if style not in STYLE_TO_TYPE:
                    raise ValueError(f"Style '{style}' not supported")
                
                if self.bench not in BENCH_TO_REGION:
                    raise ValueError(f"Benchmark '{self.bench}' not supported")
                
                region = BENCH_TO_REGION[self.bench]
                portfolio_type = STYLE_TO_TYPE[style]
                quintile = 'Q1' if self.Top else 'Q5'
                
                ptf_name = f"FS_{region}_{portfolio_type}_{quintile}"
                
                # Handle ESG portfolios
                if ptf_name in ['FS_EU_MF_Q1', 'FS_EU_MF_Q5'] and self.esg_exclusion > 0:
                    ptf_name = f"FS_EU_MF_ESG_{quintile}"
                
                return ptf_name
            else:
                return self.ptf_name
        else:
            return self.ptf_name
    
    def select_titles(
        self,
        group: pd.DataFrame,
        max_weight_threshold: float,
        column: str
    ) -> pd.DataFrame:
        """Select minimum number of titles per sector to respect weight constraint."""
        sector_weight = group[f'Weight in {self.bench}'].sum()
        
        if group[COL_DATE].unique()[0] >= datetime.datetime(2021, 12, 30):
            max_weight_threshold = max_weight_threshold * 100
        
        min_titles_needed = (sector_weight // max_weight_threshold) + \
                          (1 if sector_weight % max_weight_threshold != 0 else 0)
        
        selected_titles = group.nlargest(int(min_titles_needed), column)
        
        return selected_titles
    

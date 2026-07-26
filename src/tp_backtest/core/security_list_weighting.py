from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from tp_backtest.utils.constants import COL_DATE, COL_MKT_CAP

logger = logging.getLogger(__name__)

from tp_core.portfolio_weights import (
    apply_weighting_transform,
    cap_weights_preserving_group_totals,
    match_group_weight_targets,
    normalize_long_only_weights,
    normalize_weight_table,
)


class SecurityWeightingMixin:
    def transform_weighting_base(
        self,
        df: pd.DataFrame,
        mkt_cap_col: str = COL_MKT_CAP,
    ) -> pd.DataFrame:
        """Apply the configured weighting transform to the market-cap base."""
        return apply_weighting_transform(df, self.ponderation, mkt_cap_col)

    def _apply_security_weight_constraints(
        self,
        securities: pd.DataFrame,
        sector_targets: pd.Series,
    ) -> pd.DataFrame:
        """Apply the canonical normalization, neutrality and hard-cap policy."""

        result = normalize_weight_table(
            securities,
            weight_col="Weight",
            group_cols=COL_DATE,
        )
        if self.weight_neutral in {"ICB 19", "ICB 11"}:
            targets = normalize_long_only_weights(sector_targets)
            selected_sectors = set(result["Secto"].dropna().tolist())
            missing = [
                sector
                for sector, target in targets.items()
                if target > 0 and sector not in selected_sectors
            ]
            if missing:
                raise ValueError(
                    "sector-neutral weights are infeasible because selected "
                    f"securities do not cover target sectors: {missing}"
                )
            result = match_group_weight_targets(
                result,
                targets,
                weight_col="Weight",
                group_cols="Secto",
            )
            if self.cap_weight_threshold is not None:
                result = cap_weights_preserving_group_totals(
                    result,
                    weight_col="Weight",
                    max_weight=self.cap_weight_threshold,
                    group_cols=[COL_DATE, "Secto"],
                )
        else:
            result = normalize_weight_table(
                result,
                weight_col="Weight",
                group_cols=COL_DATE,
                max_weight=self.cap_weight_threshold,
            )
        return result

    def _prepare_market_cap_for_weighting(self, df: pd.DataFrame) -> pd.DataFrame:
        """Prepare a weighting base without making market cap mandatory for ranking."""
        df = df.copy()
        bench_weight_col = f'Weight in {self.bench}'
        
        if COL_MKT_CAP not in df.columns:
            df[COL_MKT_CAP] = np.nan
        
        df.loc[:, COL_MKT_CAP] = pd.to_numeric(df[COL_MKT_CAP], errors='coerce')
        df.loc[:, bench_weight_col] = pd.to_numeric(df[bench_weight_col], errors='coerce')
        
        if self.ponderation == "Equalweight":
            df.loc[:, COL_MKT_CAP] = 1.0
            return df
        
        missing_mask = df[COL_MKT_CAP].isna()
        valid_mask = (~missing_mask) & df[bench_weight_col].notna()
        
        if missing_mask.any() and valid_mask.sum() >= 2 and df.loc[valid_mask, bench_weight_col].nunique() >= 2:
            fit = np.polyfit(
                df.loc[valid_mask, bench_weight_col],
                df.loc[valid_mask, COL_MKT_CAP],
                deg=1,
            )
            func = np.poly1d(fit)
            df.loc[missing_mask, COL_MKT_CAP] = func(df.loc[missing_mask, bench_weight_col])
        elif missing_mask.any():
            logger.warning(
                "市值可用样本不足，使用 benchmark weight 作为权重代理: %s",
                pd.to_datetime(df[COL_DATE]).max(),
            )
            proxy = df[bench_weight_col].fillna(0).clip(lower=0)
            if proxy.sum() > 0:
                df.loc[missing_mask, COL_MKT_CAP] = proxy.loc[missing_mask] * 1_000_000.0
            else:
                df.loc[missing_mask, COL_MKT_CAP] = 1.0
        
        invalid_mask = df[COL_MKT_CAP].isna() | (df[COL_MKT_CAP] <= 0)
        if invalid_mask.any():
            proxy = df[bench_weight_col].fillna(0).clip(lower=0)
            if proxy.sum() > 0:
                df.loc[invalid_mask, COL_MKT_CAP] = proxy.loc[invalid_mask] * 1_000_000.0
            else:
                df.loc[invalid_mask, COL_MKT_CAP] = 1.0
        
        return df
    

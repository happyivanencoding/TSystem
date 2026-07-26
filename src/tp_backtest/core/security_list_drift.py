from __future__ import annotations

import copy
import logging
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from tp_backtest.utils.constants import COL_DATE, COL_ISIN, COL_SEDOL

logger = logging.getLogger(__name__)



class SecurityDriftMixin:
    def _get_returns_for_drift(self) -> pd.DataFrame:
        """Return a clean returns matrix required by monthly drift filling."""
        if self.returns is None:
            raise ValueError("fill_method='drift' requires returns data on SecurityListConstructor")
        if isinstance(self.returns, str):
            returns = pd.read_parquet(self.returns)
        else:
            returns = copy.deepcopy(self.returns)
        if not isinstance(returns.index, pd.DatetimeIndex):
            returns.index = pd.to_datetime(returns.index, errors="coerce")
        returns = returns[returns.index.notna()].sort_index()
        return returns

    def _attach_sedol_for_drift(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
        """Attach a temporary SEDOL column to a security list for returns lookup."""
        ptf = df.copy()
        temp_col = "__drift_sedol"
        if COL_SEDOL in ptf.columns:
            ptf[temp_col] = ptf[COL_SEDOL]
            return ptf, temp_col
        if COL_ISIN not in ptf.columns:
            raise KeyError(f"{COL_ISIN} column is required for drift filling")

        screen = self.screen.copy()
        if screen.index.name == COL_ISIN or COL_ISIN not in screen.columns:
            screen = screen.reset_index()
        if COL_ISIN not in screen.columns or COL_SEDOL not in screen.columns:
            raise KeyError(f"screen must contain {COL_ISIN} and {COL_SEDOL} for drift filling")

        sedol_map = (
            screen[[COL_ISIN, COL_SEDOL]]
            .dropna(subset=[COL_ISIN, COL_SEDOL])
            .drop_duplicates(subset=[COL_ISIN], keep="last")
            .set_index(COL_ISIN)[COL_SEDOL]
        )
        ptf[temp_col] = ptf[COL_ISIN].map(sedol_map)
        missing_count = int(ptf[temp_col].isna().sum())
        if missing_count:
            logger.warning("%s securities have no SEDOL mapping for monthly drift", missing_count)
        return ptf, temp_col

    def drift_weight(
        self,
        df_rebal: pd.DataFrame,
        date_fin_drifter: pd.Timestamp,
        col_id: str = COL_SEDOL,
        col_weight: str = "Weight",
        col_date: str = COL_DATE,
    ) -> pd.DataFrame:
        """Drift one rebalance slice to a target month using the returns matrix."""
        if df_rebal.empty:
            return df_rebal.copy()

        returns = self._get_returns_for_drift()
        result = df_rebal.copy()
        result[col_date] = pd.to_datetime(result[col_date])
        start_date = pd.to_datetime(result[col_date].min())
        end_date = pd.to_datetime(date_fin_drifter)
        result[col_date] = end_date

        if col_id not in result.columns:
            raise KeyError(f"{col_id} column is required for drift filling")

        ids = result[col_id].dropna().unique().tolist()
        available_ids = [identifier for identifier in ids if identifier in returns.columns]
        if not available_ids:
            logger.warning("No selected securities were found in returns for drift ending %s", end_date.date())
            total = pd.to_numeric(result[col_weight], errors="coerce").fillna(0).sum()
            if total != 0:
                result[col_weight] = pd.to_numeric(result[col_weight], errors="coerce").fillna(0) / total
            return result

        valid_dates = returns.index[(returns.index >= start_date) & (returns.index <= end_date)]
        if valid_dates.empty:
            logger.warning("No returns dates available between %s and %s for monthly drift", start_date.date(), end_date.date())
            total = pd.to_numeric(result[col_weight], errors="coerce").fillna(0).sum()
            if total != 0:
                result[col_weight] = pd.to_numeric(result[col_weight], errors="coerce").fillna(0) / total
            return result

        start_return_date = valid_dates.min()
        end_return_date = valid_dates.max()
        returns_slice = returns.loc[start_return_date:end_return_date, available_ids]
        returns_slice = returns_slice.apply(pd.to_numeric, errors="coerce").fillna(0)
        returns_cum = (1 + returns_slice).cumprod()
        base = returns_cum.iloc[0].replace(0, np.nan)
        multiplier = (returns_cum.iloc[-1] / base).replace([np.inf, -np.inf], np.nan).fillna(1.0)

        result["drift_multiplicator"] = result[col_id].map(multiplier).fillna(1.0)
        missing_returns = result[col_id].notna() & ~result[col_id].isin(available_ids)
        if missing_returns.any():
            logger.warning("%s selected securities have no returns column for monthly drift", int(missing_returns.sum()))

        result[col_weight] = pd.to_numeric(result[col_weight], errors="coerce").fillna(0) * result["drift_multiplicator"]
        total = result[col_weight].sum()
        if total != 0:
            result[col_weight] = result[col_weight] / total
        result.drop(columns=["drift_multiplicator"], inplace=True)
        return result

    def update_ptf_with_monthly_drift(
        self,
        df: pd.DataFrame,
        today: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        """Fill missing monthly security-list dates with return-drifted weights."""
        if df.empty:
            return df.copy()

        ptf, sedol_col = self._attach_sedol_for_drift(df)
        ptf[COL_DATE] = pd.to_datetime(ptf[COL_DATE])
        today_ts = pd.Timestamp.now().normalize() if today is None else pd.to_datetime(today)
        existing_dates = {pd.Timestamp(date) for date in pd.to_datetime(ptf[COL_DATE].dropna().unique())}

        for initial_date in sorted(existing_dates):
            current_date = pd.Timestamp(initial_date)
            next_month = current_date + pd.DateOffset(months=1)
            while next_month <= today_ts and pd.Timestamp(next_month) not in existing_dates:
                prev_ptf = ptf[ptf[COL_DATE] == current_date].copy()
                if prev_ptf.empty:
                    break
                drifted_ptf = self.drift_weight(
                    prev_ptf,
                    next_month,
                    col_id=sedol_col,
                    col_weight="Weight",
                    col_date=COL_DATE,
                )
                ptf = pd.concat([ptf, drifted_ptf], ignore_index=True).sort_values(COL_DATE).reset_index(drop=True)
                existing_dates.add(pd.Timestamp(next_month))
                current_date = pd.Timestamp(next_month)
                next_month = current_date + pd.DateOffset(months=1)

        if sedol_col in ptf.columns and sedol_col == "__drift_sedol":
            ptf.drop(columns=[sedol_col], inplace=True)
        return ptf

from __future__ import annotations

import datetime
import logging
import os
from typing import Optional

import pandas as pd

from tp_backtest.utils.constants import COL_DATE, COL_ISIN

logger = logging.getLogger(__name__)

class SecurityPersistenceMixin:
    def save_portfolio_data_incremental(
        self,
        df_concat: pd.DataFrame,
        output_dir: str,
        date_obj: Optional[datetime.datetime] = None
    ):
        """Save portfolio data to Excel file incrementally."""
        if date_obj is None:
            date_obj = pd.to_datetime(df_concat[COL_DATE]).iloc[0]
        
        folder_name = date_obj.strftime("%B %Y")
        folder_path = os.path.join(output_dir, f"Pour {folder_name}")
        output_file = os.path.join(folder_path, "PTFS TO PUSH.xlsx")
        os.makedirs(folder_path, exist_ok=True)
        
        new_data = df_concat[['PTF', COL_ISIN, 'Weight', COL_DATE]].copy()
        
        if os.path.exists(output_file):
            try:
                existing_data = pd.read_excel(output_file)
                logger.info(f"Found existing file with {len(existing_data)} records")
                existing_data = existing_data[~existing_data['PTF'].isin(new_data['PTF'])]
                combined_data = pd.concat([existing_data, new_data], ignore_index=True, axis=0)
                combined_data = combined_data.drop_duplicates(subset=['PTF', COL_ISIN, COL_DATE], keep='last')
                logger.info(f"After combining: {len(combined_data)} records")
            except Exception as e:
                logger.error(f"Error reading existing file: {e}")
                combined_data = new_data
        else:
            logger.info("Creating new file")
            combined_data = new_data
        
        try:
            with pd.ExcelWriter(output_file, datetime_format='dd/mm/yyyy') as writer:
                combined_data.to_excel(writer, index=False)
            logger.info(f"Successfully saved {len(combined_data)} records to: {output_file}")
        except Exception as e:
            logger.error(f"Error writing to file: {e}")
            raise
    

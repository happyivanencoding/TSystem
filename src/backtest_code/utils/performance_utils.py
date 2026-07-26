"""
Performance optimization utilities.
"""

import pandas as pd
import numpy as np
from functools import wraps, lru_cache
import time
import logging

logger = logging.getLogger(__name__)


def timing_decorator(func):
    """Decorator to measure function execution time."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        logger.info(f"{func.__name__} executed in {end_time - start_time:.2f} seconds")
        return result
    return wrapper


@lru_cache(maxsize=128)
def cached_sector_ranking(
    sector_tuple: tuple,
    values_tuple: tuple,
    score_neutral_type: str
) -> np.ndarray:
    """
    Cached sector-wise ranking calculation.
    
    Parameters:
    -----------
    sector_tuple : tuple
        Sector assignments (tupleified for hashing)
    values_tuple : tuple
        Values to rank (tupleified for hashing)
    score_neutral_type : str
        Type of sector neutralization
        
    Returns:
    --------
    ndarray
        Ranked percentiles
    """
    sectors = np.array(sector_tuple)
    values = np.array(values_tuple)
    
    # Initialize result
    result = np.zeros_like(values, dtype=float)
    
    # Rank within each sector
    for sector in np.unique(sectors):
        mask = sectors == sector
        sector_values = values[mask]
        
        # Rank percentile
        ranks = pd.Series(sector_values).rank(pct=True).values
        
        # Min-max scale
        if ranks.max() > ranks.min():
            scaled = (ranks - ranks.min()) / (ranks.max() - ranks.min())
        else:
            scaled = ranks
        
        result[mask] = scaled
    
    return result


def vectorized_rank_percentile(df: pd.DataFrame, columns: list, group_col: str) -> pd.DataFrame:
    """
    Vectorized rank percentile calculation across groups.
    
    Parameters:
    -----------
    df : DataFrame
        Input data
    columns : list
        Columns to rank
    group_col : str
        Column to group by
        
    Returns:
    --------
    DataFrame
        DataFrame with ranked columns
    """
    df = df.copy()
    
    # Global ranking
    df[columns] = df[columns].rank(pct=True)
    
    # Min-max scaling
    for col in columns:
        col_min = df[col].min()
        col_max = df[col].max()
        if col_max > col_min:
            df[col] = (df[col] - col_min) / (col_max - col_min)
    
    # Group-wise ranking
    for col in columns:
        df[col] = df.groupby(group_col)[col].transform(
            lambda x: (x.rank(pct=True) - x.rank(pct=True).min()) / 
                     (x.rank(pct=True).max() - x.rank(pct=True).min())
                     if x.rank(pct=True).max() > x.rank(pct=True).min()
                     else x.rank(pct=True)
        )
    
    return df


def optimized_merge_weights(
    df: pd.DataFrame,
    pairs: list,
    weight_col: str = 'Weight'
) -> pd.DataFrame:
    """
    Optimized weight merging for dual-listed securities.
    
    Uses vectorized operations where possible.
    
    Parameters:
    -----------
    df : DataFrame
        Input data with weights
    pairs : list
        List of (keep, drop) ISIN pairs
    weight_col : str
        Weight column name
        
    Returns:
    --------
    DataFrame
        DataFrame with merged weights
    """
    # Create mapping dictionaries for vectorization
    keep_isins = [p[0] for p in pairs]
    drop_isins = [p[1] for p in pairs]
    
    # Find which ISINs exist in df
    existing_keeps = df.index.isin(keep_isins)
    existing_drops = df.index.isin(drop_isins)
    
    # Create mapping from drop to keep
    drop_to_keep = dict(pairs)
    
    # For each drop ISIN, add its weight to corresponding keep ISIN
    for drop_isin in df.index[existing_drops]:
        if drop_isin in drop_to_keep:
            keep_isin = drop_to_keep[drop_isin]
            if keep_isin in df.index:
                df.at[keep_isin, weight_col] += df.at[drop_isin, weight_col]
    
    # Drop all drop ISINs at once
    df = df.drop(index=drop_isins, errors='ignore')
    
    return df


def batch_process_dataframes(
    df_list: list,
    func,
    batch_size: int = 10,
    **func_kwargs
) -> list:
    """
    Process list of dataframes in batches to reduce memory pressure.
    
    Parameters:
    -----------
    df_list : list
        List of DataFrames to process
    func : callable
        Function to apply to each DataFrame
    batch_size : int
        Number of DataFrames to process at once
    **func_kwargs
        Keyword arguments for func
        
    Returns:
    --------
    list
        List of processed DataFrames
    """
    results = []
    
    for i in range(0, len(df_list), batch_size):
        batch = df_list[i:i+batch_size]
        batch_results = [func(df, **func_kwargs) for df in batch]
        results.extend(batch_results)
        
        # Clear memory
        del batch
        del batch_results
    
    return results


class DataFrameCache:
    """Simple cache for DataFrames with size limit."""
    
    def __init__(self, max_size_mb: int = 100):
        """
        Initialize cache.
        
        Parameters:
        -----------
        max_size_mb : int
            Maximum cache size in MB
        """
        self.cache = {}
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.current_size_bytes = 0
    
    def get(self, key: str) -> pd.DataFrame:
        """Get item from cache."""
        return self.cache.get(key)
    
    def put(self, key: str, df: pd.DataFrame):
        """Put item in cache."""
        df_size = df.memory_usage(deep=True).sum()
        
        # If item too large, don't cache
        if df_size > self.max_size_bytes:
            return
        
        # Clear space if needed
        while self.current_size_bytes + df_size > self.max_size_bytes and self.cache:
            # Remove oldest item (FIFO)
            old_key = next(iter(self.cache))
            old_df = self.cache.pop(old_key)
            self.current_size_bytes -= old_df.memory_usage(deep=True).sum()
        
        # Add new item
        self.cache[key] = df
        self.current_size_bytes += df_size
    
    def clear(self):
        """Clear cache."""
        self.cache.clear()
        self.current_size_bytes = 0


def reduce_memory_usage(df: pd.DataFrame, verbose: bool = False) -> pd.DataFrame:
    """
    Reduce DataFrame memory usage by downcasting numeric types.
    
    Parameters:
    -----------
    df : DataFrame
        Input DataFrame
    verbose : bool
        Whether to print memory savings
        
    Returns:
    --------
    DataFrame
        DataFrame with optimized dtypes
    """
    start_mem = df.memory_usage(deep=True).sum() / 1024**2
    
    for col in df.columns:
        col_type = df[col].dtype
        
        if col_type != object:
            c_min = df[col].min()
            c_max = df[col].max()
            
            if str(col_type)[:3] == 'int':
                if c_min > np.iinfo(np.int8).min and c_max < np.iinfo(np.int8).max:
                    df[col] = df[col].astype(np.int8)
                elif c_min > np.iinfo(np.int16).min and c_max < np.iinfo(np.int16).max:
                    df[col] = df[col].astype(np.int16)
                elif c_min > np.iinfo(np.int32).min and c_max < np.iinfo(np.int32).max:
                    df[col] = df[col].astype(np.int32)
            else:
                if c_min > np.finfo(np.float32).min and c_max < np.finfo(np.float32).max:
                    df[col] = df[col].astype(np.float32)
    
    end_mem = df.memory_usage(deep=True).sum() / 1024**2
    
    if verbose:
        logger.info(f'Memory usage decreased from {start_mem:.2f}MB to {end_mem:.2f}MB '
                   f'({100 * (start_mem - end_mem) / start_mem:.1f}% reduction)')
    
    return df


"""
数据处理工具函数
"""

import numpy as np
import pandas as pd
from typing import List, Tuple, Optional
import warnings

warnings.filterwarnings('ignore')


def read_liste_noire(
    file_list_noire: str,
    override_exclusion: Optional[List[str]] = None,
    override_inclusion: Optional[List[str]] = None,
    key: str = "ISIN",
    exclu_type: Optional[List[str]] = None
) -> List[str]:
    """
    读取 and 处理 the blacklist from an Excel 文件.
    
    参数:
    -----------
    file_list_noire : str
        路径 to the blacklist Excel 文件
    override_exclusion : 列表, 可选
        Additional ISINs to exclude
    override_inclusion : 列表, 可选
        ISINs to include despite being in blacklist
    key : str, 默认 "ISIN"
        列 名称 to use as key
    exclu_type : 列表, 可选
        Types of exclusion to 过滤 (默认: ["ex_all"])
        
    收益率:
    --------
    列表
        Final 列表 of blacklisted ISINs
        """
    if exclu_type is None:
        exclu_type = ["ex_all"]
    if override_exclusion is None:
        override_exclusion = []
    if override_inclusion is None:
        override_inclusion = []
        
    liste_noire = pd.read_excel(file_list_noire)
    
    # 过滤 rows where at least one exclusion type 列 equals 1
    filtre = liste_noire[exclu_type].fillna(0).astype(int).any(axis=1)
    liste_noire = liste_noire[filtre]
    
    liste_noire = liste_noire.dropna(subset=key)[key].tolist()
    liste_noire_tot = np.concatenate([liste_noire, np.array(override_exclusion)])
    liste_noire_unique = np.unique(liste_noire_tot)
    liste_noire_finale = list(set(liste_noire_unique) - set(override_inclusion))
    
    return liste_noire_finale


def merge_weight_by_pairs(
    df: pd.DataFrame,
    pairs: List[Tuple[str, str]],
    weight_col: str = 'Weight in MSCI WORLD',
    drop_second: bool = True
) -> pd.DataFrame:
    """
    合并 weights for dual-listed 证券.
    
    参数:
    -----------
    df : DataFrame
        输入 DataFrame with ISIN as 索引
    pairs : 列表 of tuples
        List of (keep_isin, drop_isin) pairs
    weight_col : str
        列 名称 containing weights
    drop_second : bool
        是否 drop the second 证券 after merging
        
    收益率:
    --------
    DataFrame
        DataFrame with merged weights
        """
    # Ensure "ISIN" is the 索引 of df
    if df.index.name != "ISIN" and "ISIN" in df.columns:
        df.set_index("ISIN", inplace=True)
    
    # Ensure the 权重 列 is numeric
    if weight_col not in df.columns:
        raise KeyError(f"Column '{weight_col}' not found in DataFrame.")
    
    for keep, drop in pairs:
        has_keep = keep in df.index
        has_drop = drop in df.index
        
        if has_keep and has_drop:
            w_keep = df.at[keep, weight_col]
            w_drop = df.at[drop, weight_col]
            
            df.at[keep, weight_col] = w_keep + w_drop
            
            if drop_second:
                df.drop(index=drop, inplace=True, errors='ignore')
                
    return df


def merge_ticker_secondaire(df: pd.DataFrame, bench: str = "MSCI WORLD") -> pd.DataFrame:
    """
    合并 secondary tickers for dual-listed companies.
    
    参数:
    -----------
    df : DataFrame
        输入 DataFrame with ISIN as 索引
    bench : str
        当前基准名称，用于选择对应的 Weight in {bench} 列
        
    收益率:
    --------
    DataFrame
        DataFrame with merged secondary tickers
        """
    from .constants import ISIN_PAIRS
    
    # Convert to 列表 of (keep, drop) pairs
    if len(ISIN_PAIRS) % 2 != 0:
        raise ValueError("The ISIN list length must be even (pairs of 2).")
    
    pairs = list(zip(ISIN_PAIRS[::2], ISIN_PAIRS[1::2]))
    
    weight_col = f"Weight in {bench}"
    if weight_col not in df.columns:
        fallback_col = "Weight in MSCI WORLD"
        if fallback_col in df.columns:
            weight_col = fallback_col
        else:
            raise KeyError(f"Column '{weight_col}' not found in DataFrame.")
    
    df = merge_weight_by_pairs(
        df=df.copy(),
        pairs=pairs,
        weight_col=weight_col,
        drop_second=True
    )
    
    return df

def update_ptf_with_monthly_additions(df: pd.DataFrame) -> pd.DataFrame:
    """
    For every month present in the 投资组合 (including the first and last),
    检查 whether the following month already exists.  
    If it does not exist, 创建 a copy of the current month, shift the
    日期 forward by one month, and append it to the dataframe.
    
    参数:
    -----------
    df : DataFrame
        输入 投资组合 DataFrame with '日期' 列
        
    收益率:
    --------
    DataFrame
        投资组合 with monthly gaps filled
        """
    import datetime
    
    ptf = df.copy()
    existing_dates = set(ptf["Date"].unique())
    sorted_existing_dates = sorted(existing_dates)
    today = datetime.datetime.now()
    
    for date in sorted_existing_dates:
        next_month = date + pd.DateOffset(months=1)
        
        # Continue adding months until there are no more gaps
        while next_month not in existing_dates:
            if next_month > today:
                break
            else:
                prev_ptf = ptf[ptf["Date"] == date].copy()
                prev_ptf["Date"] = next_month
                ptf = pd.concat([ptf, prev_ptf]).sort_values("Date").reset_index(drop=True)
                
                # 更新 the 设置 so that we don't add the same month twice
                existing_dates.add(next_month)
                
                # Move to the newly added month for further checks
                date = next_month
                next_month += pd.DateOffset(months=1)
        
        if next_month > today:
            break
    
    return ptf


def find_next_closest_date(
    start_date: pd.Timestamp,
    screen_agg: pd.DataFrame,
    offset: int
) -> pd.Timestamp:
    """
    Find the next closest 日期 to start_date from the given DataFrame.
    
    参数:
    -----------
    start_date : datetime
        The reference 日期
    screen_agg : DataFrame
        A DataFrame containing a '日期' 列 with datetime objects
    offset : int
        Month parity offset (0 for odd months, 1 for even months)
        
    收益率:
    --------
    datetime
        The next closest 日期 that satisfies the conditions
        """
    screen_agg = screen_agg[screen_agg["Date"] >= start_date]
    dates = pd.to_datetime(screen_agg["Date"].unique())
    
    closest_date = min(dates, key=lambda d: abs(d - start_date))
    
    # Adjust for month parity
    if closest_date.month % 2 == offset:
        dates = screen_agg[screen_agg["Date"] > closest_date]["Date"].unique()
        dates = pd.to_datetime(dates)
        closest_date = min(dates, key=lambda d: abs(d - start_date))
    
    return closest_date


def calculate_sector_percentile_score(
    df: pd.DataFrame, 
    metric_col: str, 
    sector_col: str,
    scale: int = 10
) -> pd.Series:
    """
    计算指标在行业内的百分位，并转换为0-10分
    
    参数:
    -----------
    df : DataFrame
        包含指标和行业的DataFrame
    metric_col : str
        指标列名
    sector_col : str
        行业列名
    scale : int
        分数范围（默认10，即0-10分）
    
    返回:
    --------
    Series
        0-10的分数
    """
    # 按行业分组计算百分位
    sector_pct = df.groupby(sector_col)[metric_col].rank(pct=True)
    # 转换为0-10分
    score = (sector_pct * scale).round(1)
    # 处理NaN值
    score = score.fillna(0)
    return score


def enrich_holdings_with_metadata(
    holdings_df: pd.DataFrame,
    screen_data: pd.DataFrame,
    selected_metrics: List[str],
    sector_col: str
) -> pd.DataFrame:
    """
    为持仓数据添加元数据（公司名称、国家、指标值、行业评分等）
    
    参数:
    -----------
    holdings_df : DataFrame
        持仓数据
    screen_data : DataFrame
        完整的screen数据
    selected_metrics : list
        选中的指标列表
    sector_col : str
        行业列名
    
    返回:
    --------
    DataFrame
        添加了元数据的持仓数据
    """
    # 复制数据以避免修改原始数据
    enriched = holdings_df.copy()
    
    # 获取持仓的日期
    if 'Date' in enriched.columns:
        date = enriched['Date'].iloc[0]
    elif 'Date' in enriched.index.names:
        date = enriched.index.get_level_values('Date')[0]
    else:
        # 尝试从列中查找日期
        date = None
        for col in enriched.columns:
            if 'Date' in col or 'date' in col.lower():
                try:
                    date = pd.to_datetime(enriched[col].iloc[0])
                    break
                except:
                    continue
    
    if date is None:
        return enriched
    
    # 筛选对应日期的screen数据
    screen_date = screen_data[screen_data['Date'] == date].copy()
    
    if len(screen_date) == 0:
        # 尝试找最接近的日期
        closest_date = screen_data['Date'].iloc[(screen_data['Date'] - date).abs().argsort()[0]]
        screen_date = screen_data[screen_data['Date'] == closest_date].copy()
    
    # 确定合并键
    if 'ISIN' in enriched.columns:
        merge_key = 'ISIN'
    else:
        merge_key = enriched.index.name if enriched.index.name == 'ISIN' else None
    
    if not merge_key:
        return enriched
    
    # 准备合并
    if merge_key == 'ISIN' and merge_key in enriched.columns:
        enriched_indexed = enriched.set_index('ISIN')
    elif enriched.index.name == 'ISIN':
        enriched_indexed = enriched
    else:
        return enriched
    
    if 'ISIN' in screen_date.columns:
        screen_indexed = screen_date.set_index('ISIN')
    elif screen_date.index.name == 'ISIN':
        screen_indexed = screen_date
    else:
        return enriched
    
    # 添加基础信息（公司名称和国家）
    if 'Name' in screen_indexed.columns and 'Name' not in enriched_indexed.columns:
        enriched_indexed = enriched_indexed.join(screen_indexed[['Name']], how='left')
    
    if 'Exchange Country Name' in screen_indexed.columns and 'Country' not in enriched_indexed.columns:
        enriched_indexed = enriched_indexed.join(
            screen_indexed[['Exchange Country Name']].rename(columns={'Exchange Country Name': 'Country'}),
            how='left'
        )
    
    # 添加指标值和行业评分
    if selected_metrics:
        for metric in selected_metrics:
            if metric in screen_indexed.columns:
                # 原始指标值
                value_col = f'{metric}_Value'
                if value_col not in enriched_indexed.columns:
                    enriched_indexed = enriched_indexed.join(
                        screen_indexed[[metric]].rename(columns={metric: value_col}),
                        how='left'
                    )
                
                # 行业百分位评分（0-10分）
                score_col = f'{metric}_Sector_Score'
                if score_col not in enriched_indexed.columns and sector_col in screen_indexed.columns:
                    sector_scores = calculate_sector_percentile_score(
                        screen_indexed, metric, sector_col, scale=10
                    )
                    enriched_indexed[score_col] = sector_scores
    
    # 恢复原始索引结构
    if merge_key == 'ISIN' and merge_key in enriched.columns:
        enriched = enriched_indexed.reset_index()
    else:
        enriched = enriched_indexed
    
    return enriched
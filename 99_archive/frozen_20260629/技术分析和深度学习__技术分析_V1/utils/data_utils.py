"""
数据辅助函数
"""

import os
import pandas as pd

def merge_ticker_secondaire(screen: pd.DataFrame) -> pd.DataFrame:
    """
    合并二级代码等重复映射。最小实现：直接返回输入。
    """
    return screen

def read_liste_noire(path: str, extra1: list, extra2: list) -> list:
    """
    读取黑名单列表。支持txt/csv，每行一个代码。
    """
    result = []
    if isinstance(path, str) and os.path.exists(path):
        try:
            if path.lower().endswith('.csv'):
                df = pd.read_csv(path, header=None)
                result = df.iloc[:, 0].dropna().astype(str).tolist()
            else:
                with open(path, 'r', encoding='utf-8') as f:
                    result = [line.strip() for line in f if line.strip()]
        except Exception:
            result = []
    return list({*result, *extra1, *extra2})

def update_ptf_with_monthly_additions(df: pd.DataFrame) -> pd.DataFrame:
    """
    按月增量更新PTF。最小实现：直接返回输入。
    """
    return df

def find_next_closest_date(start_date, screen_agg: pd.DataFrame, inclusive: int = 1):
    """
    在screen聚合中找到不早于start_date的下一个日期。
    inclusive=1包含当日，0为严格未来。
    """
    if 'Date' not in screen_agg.columns:
        return start_date
    dates = pd.to_datetime(screen_agg['Date']).sort_values().unique()
    start_date = pd.to_datetime(start_date)
    if inclusive:
        candidates = [d for d in dates if d >= start_date]
    else:
        candidates = [d for d in dates if d > start_date]
    return candidates[0] if candidates else start_date


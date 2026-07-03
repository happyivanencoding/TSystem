"""
财务指标筛选模块 - 提供灵活的财务指标筛选功能
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
import logging

from utils.constants import COL_SECTOR_ICB19, COL_DATE, COL_ISIN

logger = logging.getLogger(__name__)


class FinancialFilter:
    """
    财务指标筛选器
    
    支持：
    - 绝对阈值筛选（如：Sales Growth > 3%）
    - 相对阈值筛选（如：行业内EPS Growth前10%）
    - 复杂条件组合（AND/OR逻辑）
    - 每个指标可独立设置是否按行业分组
    """
    
    def __init__(
        self, 
        screen_data: pd.DataFrame, 
        bench: str, 
        sector_col: str = COL_SECTOR_ICB19
    ):
        """
        初始化财务筛选器
        
        参数:
        -----------
        screen_data : DataFrame
            完整的screen数据
        bench : str
            基准名称
        sector_col : str
            行业列名
        """
        self.screen_data = screen_data
        self.bench = bench
        self.sector_col = sector_col
        
    def apply_filters(
        self, 
        df: pd.DataFrame, 
        filter_config: Dict[str, Any]
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        应用财务指标筛选条件
        
        参数:
        -----------
        df : DataFrame
            待筛选的数据
        filter_config : dict
            筛选配置，结构：
            {
                'conditions': [
                    {
                        'metric': str,           # 指标列名
                        'threshold': float,      # 阈值
                        'threshold_type': str,   # 'absolute' 或 'percentile'
                        'by_sector': bool,       # 是否按行业分组
                        'operator': str          # '>', '<', '>=', '<=', '=='
                    },
                    ...
                ],
                'logic': str  # 'AND' 或 'OR'
            }
            
        返回:
        --------
        tuple
            (筛选后的DataFrame, 被排除的DataFrame)
        """
        if not filter_config or 'conditions' not in filter_config:
            return df, pd.DataFrame()
        
        conditions = filter_config.get('conditions', [])
        logic = filter_config.get('logic', 'AND')
        
        if not conditions:
            return df, pd.DataFrame()
        
        # 存储每个条件的筛选结果
        condition_masks = []
        exclusion_reasons = []
        
        for i, condition in enumerate(conditions):
            mask, reason = self._apply_single_condition(df, condition, i)
            condition_masks.append(mask)
            exclusion_reasons.append(reason)
        
        # 根据逻辑组合所有条件
        if logic == 'AND':
            final_mask = pd.Series(True, index=df.index)
            for mask in condition_masks:
                final_mask = final_mask & mask
        elif logic == 'OR':
            final_mask = pd.Series(False, index=df.index)
            for mask in condition_masks:
                final_mask = final_mask | mask
        else:
            raise ValueError(f"未知的逻辑运算符: {logic}")
        
        # 筛选后的数据
        df_filtered = df[final_mask].copy()
        
        # 被排除的数据
        df_excluded = df[~final_mask].copy()
        
        # 记录排除原因
        if len(df_excluded) > 0:
            # 构建排除原因
            reasons = []
            for idx in df_excluded.index:
                idx_reasons = []
                for i, (mask, reason_prefix) in enumerate(zip(condition_masks, exclusion_reasons)):
                    if not mask.loc[idx]:
                        idx_reasons.append(f"{reason_prefix}")
                
                if logic == 'AND':
                    reasons.append(" AND ".join(idx_reasons))
                else:
                    reasons.append(" OR ".join(idx_reasons))
            
            # 创建排除记录
            date = df[COL_DATE].iloc[0] if COL_DATE in df.columns else pd.Timestamp.now()
            titles_excluded = pd.DataFrame({
                COL_DATE: date,
                'Raison Exclusion': reasons
            }, index=df_excluded.index)
            titles_excluded.index.name = COL_ISIN
        else:
            titles_excluded = pd.DataFrame(columns=[COL_DATE, 'Raison Exclusion'])
            titles_excluded.index.name = COL_ISIN
        
        logger.info(f"财务筛选: {len(df)} -> {len(df_filtered)} (排除 {len(df_excluded)})")
        
        return df_filtered, titles_excluded
    
    def _apply_single_condition(
        self, 
        df: pd.DataFrame, 
        condition: Dict[str, Any],
        condition_idx: int
    ) -> Tuple[pd.Series, str]:
        """
        应用单个筛选条件
        
        返回:
        --------
        tuple
            (通过条件的mask, 排除原因描述)
        """
        metric = condition.get('metric')
        threshold = condition.get('threshold')
        threshold_type = condition.get('threshold_type', 'absolute')
        by_sector = condition.get('by_sector', False)
        operator = condition.get('operator', '>')
        
        # 检查指标是否存在
        if metric not in df.columns:
            logger.warning(f"指标 {metric} 不存在于数据中，跳过此条件")
            return pd.Series(True, index=df.index), f"{metric} not found"
        
        # 获取指标值
        metric_values = df[metric].copy()
        
        # 计算阈值
        if threshold_type == 'percentile':
            # 相对阈值（百分位）
            if by_sector:
                # 按行业计算百分位
                threshold_values = df.groupby(self.sector_col)[metric].transform(
                    lambda x: x.quantile(1 - threshold)  # threshold=0.10表示前10%
                )
            else:
                # 全市场计算百分位
                threshold_values = metric_values.quantile(1 - threshold)
        else:
            # 绝对阈值
            threshold_values = threshold
        
        # 应用运算符
        if operator == '>':
            mask = metric_values > threshold_values
            reason = f"{metric} <= {threshold}"
        elif operator == '>=':
            mask = metric_values >= threshold_values
            reason = f"{metric} < {threshold}"
        elif operator == '<':
            mask = metric_values < threshold_values
            reason = f"{metric} >= {threshold}"
        elif operator == '<=':
            mask = metric_values <= threshold_values
            reason = f"{metric} > {threshold}"
        elif operator == '==':
            mask = metric_values == threshold_values
            reason = f"{metric} != {threshold}"
        else:
            raise ValueError(f"未知的运算符: {operator}")
        
        # 处理NaN值（将NaN视为不通过）
        mask = mask.fillna(False)
        
        # 构建排除原因描述
        if threshold_type == 'percentile':
            sector_str = "行业内" if by_sector else "全市场"
            reason_desc = f"{metric} 不在{sector_str}前{threshold*100:.0f}%"
        else:
            reason_desc = f"{metric} {operator} {threshold} 不满足"
        
        return mask, reason_desc
    
    def get_available_metrics(self, df: pd.DataFrame) -> List[str]:
        """
        获取可用的财务指标列表
        
        参数:
        -----------
        df : DataFrame
            数据框
            
        返回:
        --------
        list
            可用的指标列名列表
        """
        # 排除系统列和因子列
        exclude_patterns = [
            'Date', 'ISIN', 'SEDOL', 'Symbol', 'Name', 'Exchange', 
            'ICB', 'Benchmark', 'Weight', 'Percentile', 'Score',
            'Secto', 'PTF', 'Raison'
        ]
        
        available = []
        for col in df.columns:
            # 检查是否是数值列
            if pd.api.types.is_numeric_dtype(df[col]):
                # 检查是否不在排除列表中
                if not any(pattern in col for pattern in exclude_patterns):
                    available.append(col)
        
        return sorted(available)
    
    @staticmethod
    def validate_filter_config(filter_config: Dict[str, Any]) -> bool:
        """
        验证筛选配置的有效性
        
        参数:
        -----------
        filter_config : dict
            筛选配置
            
        返回:
        --------
        bool
            配置是否有效
        """
        if not isinstance(filter_config, dict):
            return False
        
        if 'conditions' not in filter_config:
            return False
        
        conditions = filter_config['conditions']
        if not isinstance(conditions, list):
            return False
        
        # 验证每个条件
        required_keys = ['metric', 'threshold', 'threshold_type', 'operator']
        for condition in conditions:
            if not isinstance(condition, dict):
                return False
            
            for key in required_keys:
                if key not in condition:
                    return False
            
            # 验证threshold_type
            if condition['threshold_type'] not in ['absolute', 'percentile']:
                return False
            
            # 验证operator
            if condition['operator'] not in ['>', '<', '>=', '<=', '==']:
                return False
        
        # 验证logic
        logic = filter_config.get('logic', 'AND')
        if logic not in ['AND', 'OR']:
            return False
        
        return True


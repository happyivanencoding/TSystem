"""
权重管理和漂移处理模块
"""

import pandas as pd
import numpy as np
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)


class WeightManager:
    """管理投资组合权重、漂移和上限"""
    
    @staticmethod
    def apply_weighting_scheme(
        df: pd.DataFrame,
        method: str,
        mkt_cap_col: str = 'Benchmark Market Value Millions in EUR'
    ) -> pd.DataFrame:
        """
        对市值应用加权方案
        
        参数:
        -----------
        df : DataFrame
            包含市值列的输入数据
        method : str
            加权方法: "Racine cube", "Racine carrée", "Market cap", "Log", "Equalweight"
        mkt_cap_col : str
            市值列名
            
        返回:
        --------
        DataFrame
            转换市值后的DataFrame
        """
        df = df.copy()
        
        if method == "Racine cube":
            df.loc[:, mkt_cap_col] = df[mkt_cap_col] ** (1/3)
        elif method == "Racine carrée":
            df.loc[:, mkt_cap_col] = df[mkt_cap_col] ** (1/2)
        elif method == "Market cap":
            pass  # 保持原样
        elif method == "Log":
            df.loc[:, mkt_cap_col] = np.log(df[mkt_cap_col])
        elif method == "Equalweight":
            df[mkt_cap_col] = 1/len(df)
        else:
            raise ValueError(f"未知的加权方法: {method}")
        
        return df
    
    @staticmethod
    def cap_weight_by_sector(
        ptf: pd.DataFrame,
        threshold: float,
        n_iteration: int = 30
    ) -> pd.DataFrame:
        """
        限制个股权重，同时将超额权重按比例重新分配给
        同一行业内的其他公司
        
        参数:
        -----------
        ptf : DataFrame
            包含['Date', 'Secto', 'Weight']列的投资组合
        threshold : float
            个股权重上限
        n_iteration : int
            最大迭代次数
            
        返回:
        --------
        DataFrame
            调整权重后的DataFrame
        """
        result = ptf.copy()
        
        for iteration in range(n_iteration):
            has_adjustment = False
            
            # 分别处理每个日期
            for date in result['Date'].unique():
                date_mask = result['Date'] == date
                date_data = result[date_mask].copy()
                
                # 分别处理每个行业
                for sector in date_data['Secto'].unique():
                    sector_mask = date_data['Secto'] == sector
                    sector_data = date_data[sector_mask].copy()
                    
                    # 找出超重股票
                    overweight_mask = sector_data['Weight'] > threshold
                    
                    if overweight_mask.any():
                        has_adjustment = True
                        
                        # 计算总超额权重
                        excess_weight = (sector_data.loc[overweight_mask, 'Weight'] - threshold).sum()
                        
                        # 将超重股票权重限制在阈值
                        sector_data.loc[overweight_mask, 'Weight'] = threshold
                        
                        # 找出低权重股票
                        underweight_mask = ~overweight_mask
                        underweight_data = sector_data[underweight_mask]
                        
                        if len(underweight_data) > 0:
                            underweight_total = underweight_data['Weight'].sum()
                            
                            if underweight_total > 0:
                                # 按比例分配超额权重
                                allocation_ratio = excess_weight / underweight_total
                                sector_data.loc[underweight_mask, 'Weight'] = (
                                    sector_data.loc[underweight_mask, 'Weight'] * (1 + allocation_ratio)
                                )
                        
                        # 更新结果
                        result.loc[date_mask & (result['Secto'] == sector), 'Weight'] = sector_data['Weight'].values
            
            # 如果没有进行调整则提前终止
            if not has_adjustment:
                break
        
        return result
    
    @staticmethod
    def normalize_weights(
        df: pd.DataFrame,
        weight_col: str = 'Weight',
        group_col: Optional[str] = 'Date'
    ) -> pd.DataFrame:
        """
        归一化权重使其在组内总和为1
        
        参数:
        -----------
        df : DataFrame
            输入DataFrame
        weight_col : str
            权重列名
        group_col : str, optional
            分组列 (例如 'Date')
            
        返回:
        --------
        DataFrame
            归一化权重后的DataFrame
        """
        df = df.copy()
        
        if group_col:
            df[weight_col] = df.groupby(group_col)[weight_col].transform(lambda x: x / x.sum())
        else:
            df[weight_col] = df[weight_col] / df[weight_col].sum()
        
        return df
    
    @staticmethod
    def sector_neutralize_weights(
        sec_list: pd.DataFrame,
        benchmark_sector_weights: pd.Series,
        sector_col: str,
        weight_col: str = 'Portfolio weight',
        date_col: str = 'Date'
    ) -> pd.DataFrame:
        """
        调整投资组合权重以匹配基准行业权重
        
        参数:
        -----------
        sec_list : DataFrame
            带权重的证券列表
        benchmark_sector_weights : Series
            基准行业权重 (按[Date, Sector]索引)
        sector_col : str
            行业列名
        weight_col : str
            权重列名
        date_col : str
            日期列名
            
        返回:
        --------
        DataFrame
            行业中性化权重后的证券列表
        """
        sec_list = sec_list.copy()
        
        # 计算投资组合行业权重
        sec_list['weight_secto_ptf'] = sec_list.groupby([date_col, sector_col])[weight_col].transform('sum')
        
        # 合并基准行业权重
        sec_list = sec_list.merge(
            benchmark_sector_weights.reset_index().rename(columns={0: 'bench_sector_weight'}),
            on=[date_col, sector_col],
            how='left'
        )
        
        # 调整权重
        sec_list[weight_col] = sec_list[weight_col] * (
            sec_list['bench_sector_weight'] / sec_list['weight_secto_ptf']
        )
        
        # 清理临时列
        sec_list.drop(columns=['weight_secto_ptf', 'bench_sector_weight'], inplace=True)
        
        return sec_list


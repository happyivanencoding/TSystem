"""
优化的回测引擎模块，采用向量化计算
"""

import pandas as pd
import numpy as np
import copy
from typing import Union, Optional, Tuple
from functools import lru_cache
import logging

from utils.constants import *
from core.weight_manager import WeightManager

logger = logging.getLogger(__name__)


class BacktestEngineOptimized:
    """
    优化版本的回测引擎，采用向量化操作
    """
    
    def __init__(self, returns: pd.DataFrame):
        """
        初始化回测引擎
        
        参数:
        -----------
        returns : DataFrame
            日收益率数据 (索引: 日期, 列: 证券)
        """
        if isinstance(returns, str):
            self.returns = pd.read_parquet(returns)
        elif isinstance(returns, pd.DataFrame):
            self.returns = returns  # 避免不必要的复制
        else:
            raise TypeError("returns must be str (path) or DataFrame")
        
        self.perf_ptf = None
        self.perf_bench = None
        self.buy_list = None
        
        # 中间结果缓存
        self._cache = {}
    
    @staticmethod
    def calculate_portfolio_returns_vectorized(
        df_rebal: pd.DataFrame,
        df_returns: pd.DataFrame,
        col_weight: str = COL_PORTFOLIO_WEIGHT,
        col_date: str = COL_DATE,
        col_id: str = COL_SEDOL
    ) -> pd.Series:
        """
        使用向量化操作的优化组合收益率计算
        
        该版本最小化循环并使用numpy/pandas向量化操作
        
        参数:
        -----------
        df_rebal : DataFrame
            包含权重的再平衡数据
        df_returns : DataFrame
            日收益率数据
        col_weight : str
            权重列名
        col_date : str
            日期列名
        col_id : str
            证券标识列名
            
        返回:
        --------
        Series
            投资组合累计收益率 (基数 100)
        """
        # 准备再平衡数据
        df_rebal = df_rebal.reset_index(drop=False)
        
        # 获取日期
        rebal_dates = df_rebal[col_date].unique()
        rebal_dates_sorted = pd.Series(sorted(rebal_dates))
        
        # 过滤收益率数据中存在的证券
        valid_securities = df_rebal[col_id].isin(df_returns.columns)
        df_rebal = df_rebal[valid_securities]
        
        # 使用向量化操作归一化权重
        weight_sums = df_rebal.groupby(col_date)[col_weight].transform('sum')
        df_rebal[col_weight] = df_rebal[col_weight] / weight_sums
        
        # 创建每日日期映射 (向量化)
        returns_dates = df_returns.index[df_returns.index >= rebal_dates_sorted.iloc[0]]
        
        # 为每个收益率日期查找最近的再平衡日期 (向量化searchsorted)
        rebal_dates_array = rebal_dates_sorted.values
        date_mapping = pd.DataFrame({
            'date': returns_dates,
            'rebal_date': rebal_dates_array[
                np.searchsorted(rebal_dates_array, returns_dates, side='right') - 1
            ]
        })
        
        # 将权重与日期映射合并
        df_rebal_expanded = date_mapping.merge(
            df_rebal[[col_date, col_id, col_weight]],
            left_on='rebal_date',
            right_on=col_date,
            how='left'
        ).drop(columns=[col_date]).rename(columns={'date': col_date})
        
        # 转换为宽格式以进行向量化操作
        weights_matrix = df_rebal_expanded.pivot(
            index=col_date,
            columns=col_id,
            values=col_weight
        ).fillna(0)
        
        # 与收益率对齐
        common_cols = weights_matrix.columns.intersection(df_returns.columns)
        weights_matrix = weights_matrix[common_cols]
        returns_aligned = df_returns.loc[weights_matrix.index, common_cols]
        
        # 计算漂移乘数 (向量化累积乘积)
        returns_cum = (1 + returns_aligned).cumprod()
        
        # 在每个再平衡日期重新基准化
        rebal_dates_in_returns = date_mapping.set_index('date')['rebal_date']
        
        # 按再平衡期分组
        rebal_groups = rebal_dates_in_returns.values
        unique_rebal_dates = np.unique(rebal_groups)
        
        # 计算每个再平衡期内的漂移
        drift_matrix = returns_cum.copy()
        for rebal_date in unique_rebal_dates:
            mask = rebal_groups == rebal_date
            if rebal_date in returns_cum.index:
                base_values = returns_cum.loc[rebal_date]
                drift_matrix.loc[mask] = returns_cum.loc[mask] / base_values
        
        # 计算漂移后的权重 (逐元素乘法)
        # 移位权重以使用前一天的权重
        weights_shifted = weights_matrix.shift(1).fillna(0)
        drifted_weights = weights_shifted * drift_matrix
        
        # 归一化漂移权重
        weight_sums = drifted_weights.sum(axis=1)
        weight_sums = weight_sums.replace(0, 1)  # 避免除零
        normalized_weights = drifted_weights.div(weight_sums, axis=0)
        
        # 计算每日贡献 (向量化)
        daily_contributions = (normalized_weights * returns_aligned).sum(axis=1)
        
        # 计算累计收益率
        cumulative_returns = (1 + daily_contributions.fillna(0)).cumprod() * 100
        
        return cumulative_returns
    
    @lru_cache(maxsize=128)
    def _get_sector_weights(
        self,
        indice_name: str,
        date_tuple: Tuple  # 日期元组用于哈希
    ) -> pd.Series:
        """
        缓存的行业权重计算
        
        参数:
        -----------
        indice_name : str
            指数名称
        date_tuple : tuple
            日期元组 (用于缓存键)
            
        返回:
        --------
        Series
            行业权重
        """
        # 这里将实现实际的行业权重计算
        pass
    
    @staticmethod
    def create_ptf_weight_optimized(
        sec_list: pd.DataFrame,
        indice_name: str,
        screen_agg: pd.DataFrame,
        max_weight: float,
        col_mkt_cap: str = COL_MKT_CAP,
        col_date: str = COL_DATE,
        col_sector: str = COL_SECTOR_ICB19,
        sector_neutral: bool = False,
        method: str = 'Market cap',
        col_sedol: str = COL_SEDOL,
        col_isin: str = COL_ISIN
    ) -> pd.DataFrame:
        """
        优化的投资组合权重创建，减少数据复制
        """
        # 过滤基准证券 (尽可能避免复制)
        indice = screen_agg.loc[
            screen_agg[f'Weight in {indice_name}'] > 0,
            [col_date, col_sedol, col_sector, f'Weight in {indice_name}']
        ]
        indice = indice.rename(columns={f'Weight in {indice_name}': 'Indice weight'})
        
        # 排序不复制
        indice.sort_values(by=col_date, inplace=True)
        sec_list.sort_values(by=col_date, inplace=True)
        
        # 移动日期 (就地操作)
        indice[col_date] = indice[col_date] + pd.offsets.MonthBegin(1)
        screen_agg[col_date] = screen_agg[col_date] + pd.offsets.MonthBegin(1)
        
        # 合并 (单次操作)
        sec_list = sec_list.merge(
            screen_agg[[col_date, col_isin, col_sedol, col_sector, col_mkt_cap]],
            on=[col_date, col_isin],
            how='left'
        )
        sec_list = sec_list.dropna(subset=[col_sedol])
        
        # 向量化权重计算
        if method == 'EW':
            # 使用transform的等权重 (向量化)
            sec_list[COL_PORTFOLIO_WEIGHT] = 1 / sec_list.groupby(col_date)[col_isin].transform('count')
        else:
            # 应用加权方案
            sec_list = WeightManager.apply_weighting_scheme(sec_list, method, col_mkt_cap)
            # 向量化归一化
            mkt_cap_sums = sec_list.groupby(col_date)[col_mkt_cap].transform('sum')
            sec_list[COL_PORTFOLIO_WEIGHT] = sec_list[col_mkt_cap] / mkt_cap_sums
        
        # 行业中性化 (如果需要)
        if sector_neutral:
            # 向量化行业权重计算
            indice_totals = indice.groupby(col_date)['Indice weight'].transform('sum')
            indice['Indice weight'] = indice['Indice weight'] / indice_totals
            
            weight_secto_bench = indice.groupby([col_date, col_sector])['Indice weight'].sum()
            
            ptf_totals = sec_list.groupby(col_date)[COL_PORTFOLIO_WEIGHT].transform('sum')
            sec_list[COL_PORTFOLIO_WEIGHT] = sec_list[COL_PORTFOLIO_WEIGHT] / ptf_totals
            
            weight_secto_ptf = sec_list.groupby([col_date, col_sector])[COL_PORTFOLIO_WEIGHT].transform('sum')
            
            # 合并和调整
            sec_list = sec_list.merge(
                weight_secto_bench.rename('bench_weight'),
                left_on=[col_date, col_sector],
                right_index=True,
                how='left'
            )
            
            sec_list[COL_PORTFOLIO_WEIGHT] = (
                sec_list[COL_PORTFOLIO_WEIGHT] * sec_list['bench_weight'] / weight_secto_ptf
            )
            sec_list.drop(columns=['bench_weight'], inplace=True)
        
        # 限制权重 (向量化)
        weight_totals = sec_list.groupby(col_date)[COL_PORTFOLIO_WEIGHT].transform('sum')
        sec_list[COL_PORTFOLIO_WEIGHT] = sec_list[COL_PORTFOLIO_WEIGHT] / weight_totals
        sec_list[COL_PORTFOLIO_WEIGHT] = sec_list[COL_PORTFOLIO_WEIGHT].clip(upper=max_weight)
        
        # 最终归一化
        weight_totals = sec_list.groupby(col_date)[COL_PORTFOLIO_WEIGHT].transform('sum')
        sec_list[COL_PORTFOLIO_WEIGHT] = sec_list[COL_PORTFOLIO_WEIGHT] / weight_totals
        
        return sec_list.set_index([col_date, col_sedol])[[col_isin, COL_PORTFOLIO_WEIGHT, col_sector]]
    
    def backtest_optimized(
        self,
        sec_list: pd.DataFrame,
        screen: pd.DataFrame,
        indice_name: Optional[str] = None,
        method: Optional[str] = None,
        max_weight: float = 1,
        sec_list_: bool = True,
        **kwargs
    ) -> Tuple[pd.Series, Optional[pd.DataFrame]]:
        """
        优化的回测，减少内存使用并加快计算速度
        """
        # 加载筛选数据 (如果是DataFrame避免复制)
        if isinstance(screen, pd.DataFrame):
            screen_agg = screen
        else:
            screen_agg = pd.read_parquet(screen)
        
        # 处理证券列表
        if sec_list_:
            if 'Weight' in sec_list.columns:
                # 准备证券列表
                sec_list_full = sec_list[[COL_DATE, COL_ISIN, 'Weight']].copy()
                
                # 向量化权重归一化
                weight_sums = sec_list_full.groupby(COL_DATE)['Weight'].transform('sum')
                sec_list_full['Weight'] = sec_list_full['Weight'] / weight_sums
                
                # 限制权重 (向量化)
                sec_list_full['Weight'] = sec_list_full['Weight'].clip(0, max_weight)
                
                # 重新归一化
                weight_sums = sec_list_full.groupby(COL_DATE)['Weight'].transform('sum')
                sec_list_full['Weight'] = sec_list_full['Weight'] / weight_sums
                
                sec_list_full = sec_list_full.rename(columns={'Weight': COL_PORTFOLIO_WEIGHT})
                
                # 对齐日期
                screen_agg[COL_DATE] = pd.to_datetime(screen_agg[COL_DATE]) + pd.offsets.MonthBegin(1)
                
                # 与筛选数据合并
                sec_list_full = sec_list_full.merge(
                    screen_agg[[COL_DATE, COL_ISIN, COL_SEDOL, COL_SECTOR_ICB19, COL_MKT_CAP]],
                    on=[COL_DATE, COL_ISIN],
                    how='left'
                )
                sec_list_full = sec_list_full.dropna(subset=[COL_SEDOL])
                sec_list_full = sec_list_full.set_index([COL_DATE, COL_SEDOL])
                
                # 使用优化方法计算业绩
                perf_ttr = self.calculate_portfolio_returns_vectorized(
                    sec_list_full,
                    self.returns,
                    COL_PORTFOLIO_WEIGHT,
                    COL_DATE,
                    COL_SEDOL
                )
                
                self.perf_ptf = perf_ttr
                self.buy_list = sec_list_full
                logger.info('Portfolio performance calculated (optimized)')
                
                return perf_ttr, sec_list_full
        else:
            # 基准回测
            sec_list_full = self.create_ptf_weight_optimized(
                sec_list, indice_name, screen_agg, max_weight,
                method=method or 'Market cap', **kwargs
            )
            
            perf_ttr = self.calculate_portfolio_returns_vectorized(
                sec_list_full,
                self.returns,
                COL_PORTFOLIO_WEIGHT,
                COL_DATE,
                COL_SEDOL
            )
            
            self.perf_bench = perf_ttr
            logger.info('Benchmark performance calculated (optimized)')
            
            return perf_ttr, None


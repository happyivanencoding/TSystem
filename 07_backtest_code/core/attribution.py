"""
归因 分析 模块 for 投资组合 业绩.
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
import logging

from utils.constants import *

logger = logging.getLogger(__name__)


class AttributionAnalysis:
    """
    Performs 归因 分析 on 投资组合 业绩.
    """
    
    @staticmethod
    def brinson_attribution(
        portfolio_weights: pd.DataFrame,
        benchmark_weights: pd.DataFrame,
        portfolio_returns: pd.DataFrame,
        benchmark_returns: pd.DataFrame,
        sector_col: str = 'Sector'
    ) -> Dict[str, pd.DataFrame]:
        """
        执行 Brinson 归因 分析.
        
        Decomposes excess 收益 into:
        - Allocation effect: 行业 权重 decisions
        - Selection effect: Stock selection within sectors
        - Interaction effect: Combined effect of allocation and selection
        
        参数:
        -----------
        portfolio_weights : DataFrame
            投资组合 weights by 证券 and 日期
        benchmark_weights : DataFrame
            基准 weights by 证券 and 日期
        portfolio_returns : DataFrame
            投资组合 收益率 by 证券 and 日期
        benchmark_returns : DataFrame
            基准 收益率 by 证券 and 日期
        sector_col : str
            列 名称 for 行业 classification
            
        收益率:
        --------
        字典
            Dictionary containing:
            - 'allocation': Allocation effect by 行业
            - 'selection': Selection effect by 行业
            - 'interaction': Interaction effect by 行业
            - 'total': Total 归因 by 行业
        """
        # Align dates
        common_dates = portfolio_weights.index.intersection(benchmark_weights.index)
        
        # 计算 行业-level 指标
        ptf_sector_weights = portfolio_weights.groupby([portfolio_weights.index, sector_col]).sum()
        bench_sector_weights = benchmark_weights.groupby([benchmark_weights.index, sector_col]).sum()
        
        # 计算 行业 收益率
        ptf_sector_returns = (portfolio_weights * portfolio_returns).groupby(
            [portfolio_weights.index, sector_col]
        ).sum() / ptf_sector_weights
        
        bench_sector_returns = (benchmark_weights * benchmark_returns).groupby(
            [benchmark_weights.index, sector_col]
        ).sum() / bench_sector_weights
        
        # 计算 归因 components
        # Allocation = (Wp_sector - Wb_sector) * (Rb_sector - Rb_total)
        bench_total_return = (benchmark_weights * benchmark_returns).groupby(level=0).sum() / \
                            benchmark_weights.groupby(level=0).sum()
        
        allocation = (ptf_sector_weights - bench_sector_weights) * \
                    (bench_sector_returns - bench_total_return.reindex(bench_sector_returns.index, level=0))
        
        # Selection = Wb_sector * (Rp_sector - Rb_sector)
        selection = bench_sector_weights * (ptf_sector_returns - bench_sector_returns)
        
        # Interaction = (Wp_sector - Wb_sector) * (Rp_sector - Rb_sector)
        interaction = (ptf_sector_weights - bench_sector_weights) * \
                     (ptf_sector_returns - bench_sector_returns)
        
        # Total 归因
        total = allocation + selection + interaction
        
        return {
            'allocation': allocation,
            'selection': selection,
            'interaction': interaction,
            'total': total
        }
    
    @staticmethod
    def factor_exposure(
        portfolio_weights: pd.DataFrame,
        factor_scores: pd.DataFrame,
        benchmark_weights: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """
        计算 投资组合 exposure to various 因子.
        
        参数:
        -----------
        portfolio_weights : DataFrame
            投资组合 weights (索引: 日期, columns: 证券)
        factor_scores : DataFrame
            因子 scores (索引: 日期, columns: 证券, values: 因子 scores)
            MultiIndex with (日期, 因子) if multiple 因子
        benchmark_weights : DataFrame, 可选
            基准 weights for relative exposure calculation
            
        收益率:
        --------
        DataFrame
            因子 exposures by 日期 (and relative to 基准 if provided)
        """
        # 计算 weighted average 因子 scores
        exposures = {}
        
        for date in portfolio_weights.index:
            if date in factor_scores.index:
                ptf_w = portfolio_weights.loc[date]
                factor_s = factor_scores.loc[date]
                
                # 计算 投资组合 exposure
                common_securities = ptf_w.index.intersection(factor_s.index)
                exposure = (ptf_w[common_securities] * factor_s[common_securities]).sum() / ptf_w[common_securities].sum()
                
                exposures[date] = exposure
                
                # 计算 relative exposure if 基准 provided
                if benchmark_weights is not None and date in benchmark_weights.index:
                    bench_w = benchmark_weights.loc[date]
                    common_bench = bench_w.index.intersection(factor_s.index)
                    bench_exposure = (bench_w[common_bench] * factor_s[common_bench]).sum() / bench_w[common_bench].sum()
                    exposures[date] = {'absolute': exposure, 'relative': exposure - bench_exposure}
        
        return pd.DataFrame(exposures).T
    
    @staticmethod
    def risk_decomposition(
        portfolio_returns: pd.Series,
        factor_returns: pd.DataFrame,
        benchmark_returns: Optional[pd.Series] = None
    ) -> Dict[str, float]:
        """
        Decompose 投资组合 风险 into 因子 and specific components.
        
        Uses 因子 model: R_p = alpha + beta * R_factors + epsilon
        
        参数:
        -----------
        portfolio_returns : Series
            投资组合 收益率
        factor_returns : DataFrame
            因子 收益率 (columns: 因子, 索引: dates)
        benchmark_returns : Series, 可选
            基准 收益率 for active 风险 decomposition
            
        收益率:
        --------
        字典
            风险 decomposition components:
            - 'total_risk': Total 投资组合 波动率
            - 'factor_risk': 风险 from 因子 exposures
            - 'specific_risk': Idiosyncratic 风险
            - 'factor_contributions': 风险 contribution by 因子
        """
        # Align 数据
        common_dates = portfolio_returns.index.intersection(factor_returns.index)
        ptf_ret = portfolio_returns.loc[common_dates]
        fac_ret = factor_returns.loc[common_dates]
        
        # If 基准 provided, use active 收益率
        if benchmark_returns is not None:
            bench_ret = benchmark_returns.loc[common_dates]
            ptf_ret = ptf_ret - bench_ret
        
        # Estimate 因子 model using OLS
        from sklearn.linear_model import LinearRegression
        
        model = LinearRegression()
        model.fit(fac_ret, ptf_ret)
        
        # 计算 fitted values and residuals
        fitted = model.predict(fac_ret)
        residuals = ptf_ret - fitted
        
        # 计算 风险 components
        total_risk = ptf_ret.std() * np.sqrt(252)
        
        # 因子 风险 from fitted values
        factor_risk = pd.Series(fitted, index=common_dates).std() * np.sqrt(252)
        
        # Specific 风险 from residuals
        specific_risk = residuals.std() * np.sqrt(252)
        
        # 因子 contributions to 风险
        factor_contributions = {}
        coef_dict = dict(zip(fac_ret.columns, model.coef_))
        
        for factor, beta in coef_dict.items():
            factor_vol = fac_ret[factor].std() * np.sqrt(252)
            factor_contributions[factor] = abs(beta) * factor_vol
        
        return {
            'total_risk': total_risk,
            'factor_risk': factor_risk,
            'specific_risk': specific_risk,
            'factor_contributions': factor_contributions,
            'factor_betas': coef_dict
        }
    
    @staticmethod
    def sector_contribution(
        portfolio_weights: pd.DataFrame,
        portfolio_returns: pd.DataFrame,
        sector_col: str = 'Sector'
    ) -> pd.DataFrame:
        """
        计算 行业 contribution to 投资组合 收益率.
        
        参数:
        -----------
        portfolio_weights : DataFrame
            投资组合 weights with 行业 information
        portfolio_returns : DataFrame
            证券 收益率
        sector_col : str
            列 名称 for 行业 classification
            
        收益率:
        --------
        DataFrame
            行业 contributions by 日期
        """
        # 计算 证券 contributions
        contributions = portfolio_weights * portfolio_returns
        
        # 分组 by 行业
        if sector_col in portfolio_weights.columns:
            sector_contributions = contributions.groupby(
                [contributions.index, portfolio_weights[sector_col]]
            ).sum()
        else:
            logger.warning(f"Sector column '{sector_col}' not found")
            return contributions
        
        return sector_contributions
    
    @staticmethod
    def rolling_attribution(
        portfolio_weights: pd.DataFrame,
        benchmark_weights: pd.DataFrame,
        portfolio_returns: pd.DataFrame,
        benchmark_returns: pd.DataFrame,
        window: int = 60,
        sector_col: str = 'Sector'
    ) -> pd.DataFrame:
        """
        计算 rolling 归因 分析.
        
        参数:
        -----------
        portfolio_weights : DataFrame
            投资组合 weights
        benchmark_weights : DataFrame
            基准 weights
        portfolio_returns : DataFrame
            投资组合 收益率
        benchmark_returns : DataFrame
            基准 收益率
        window : int
            Rolling window size (in periods)
        sector_col : str
            行业 列 名称
            
        收益率:
        --------
        DataFrame
            Rolling 归因 指标
        """
        dates = sorted(portfolio_weights.index.unique())
        results = []
        
        for i in range(window, len(dates)):
            window_dates = dates[i-window:i]
            
            # 获取 window 数据
            ptf_w = portfolio_weights.loc[window_dates]
            bench_w = benchmark_weights.loc[window_dates]
            ptf_r = portfolio_returns.loc[window_dates]
            bench_r = benchmark_returns.loc[window_dates]
            
            # 计算 归因
            attr = AttributionAnalysis.brinson_attribution(
                ptf_w, bench_w, ptf_r, bench_r, sector_col
            )
            
            # 聚合 归因
            result = {
                'date': dates[i],
                'allocation': attr['allocation'].sum().sum(),
                'selection': attr['selection'].sum().sum(),
                'interaction': attr['interaction'].sum().sum(),
                'total': attr['total'].sum().sum()
            }
            results.append(result)
        
        return pd.DataFrame(results).set_index('date')
    
    @staticmethod
    def performance_attribution_summary(
        portfolio_returns: pd.Series,
        benchmark_returns: pd.Series,
        attribution_results: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        创建 comprehensive 归因 summary.
        
        参数:
        -----------
        portfolio_returns : Series
            投资组合 收益率
        benchmark_returns : Series
            基准 收益率
        attribution_results : 字典
            Results from brinson_attribution
            
        收益率:
        --------
        DataFrame
            Summary of 归因 components
        """
        # 计算 total 收益率
        ptf_total = (1 + portfolio_returns).prod() - 1
        bench_total = (1 + benchmark_returns).prod() - 1
        excess = ptf_total - bench_total
        
        # 聚合 归因 components
        allocation_total = attribution_results['allocation'].sum().sum()
        selection_total = attribution_results['selection'].sum().sum()
        interaction_total = attribution_results['interaction'].sum().sum()
        
        summary = pd.DataFrame({
            'Value': [
                ptf_total,
                bench_total,
                excess,
                allocation_total,
                selection_total,
                interaction_total
            ],
            'Percentage of Excess': [
                np.nan,
                np.nan,
                100.0,
                allocation_total / excess * 100 if excess != 0 else 0,
                selection_total / excess * 100 if excess != 0 else 0,
                interaction_total / excess * 100 if excess != 0 else 0
            ]
        }, index=[
            'Portfolio Return',
            'Benchmark Return',
            'Excess Return',
            'Allocation Effect',
            'Selection Effect',
            'Interaction Effect'
        ])
        
        return summary


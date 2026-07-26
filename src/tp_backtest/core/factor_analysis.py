"""
因子 分析 模块 for quantitative research.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from scipy.stats import spearmanr, pearsonr
import logging

logger = logging.getLogger(__name__)


class FactorAnalyzer:
    """
    因子研究和分析工具
    """
    
    @staticmethod
    def calculate_ic(
        factor_scores: pd.DataFrame,
        forward_returns: pd.DataFrame,
        method: str = 'spearman'
    ) -> pd.Series:
        """
        计算 信息系数 (IC) between 因子 scores and future 收益率.
        
        IC measures the 相关性 between current 因子 values and future 收益率.
        
        参数:
        -----------
        factor_scores : DataFrame
            因子 scores (索引: 日期, columns: 证券)
        forward_returns : DataFrame
            Forward 收益率 (索引: 日期, columns: 证券)
        method : str
            相关性 method: 'spearman' or 'pearson'
            
        收益率:
        --------
        Series
            IC by 日期
        """
        ic_series = {}
        
        common_dates = factor_scores.index.intersection(forward_returns.index)
        
        for date in common_dates:
            scores = factor_scores.loc[date].dropna()
            returns = forward_returns.loc[date].dropna()
            
            # Find common 证券
            common_sec = scores.index.intersection(returns.index)
            
            if len(common_sec) > 2:
                if method == 'spearman':
                    ic, _ = spearmanr(scores[common_sec], returns[common_sec])
                elif method == 'pearson':
                    ic, _ = pearsonr(scores[common_sec], returns[common_sec])
                else:
                    raise ValueError(f"Unknown method: {method}")
                
                ic_series[date] = ic
            else:
                ic_series[date] = np.nan
        
        return pd.Series(ic_series)
    
    @staticmethod
    def ic_time_series(
        factor_scores: pd.DataFrame,
        forward_returns: pd.DataFrame,
        periods: List[int] = [1, 3, 6, 12],
        method: str = 'spearman'
    ) -> pd.DataFrame:
        """
        计算 IC 时间 series for multiple forward periods.
        
        参数:
        -----------
        factor_scores : DataFrame
            因子 scores
        forward_returns : DataFrame
            收益率 数据
        periods : 列表
            List of forward periods (in months)
        method : str
            相关性 method
            
        收益率:
        --------
        DataFrame
            IC 时间 series for each period
        """
        ic_results = {}
        
        for period in periods:
            # Shift 收益率 to 获取 forward 收益率
            fwd_returns = forward_returns.shift(-period)
            
            # 计算 IC
            ic = FactorAnalyzer.calculate_ic(factor_scores, fwd_returns, method)
            ic_results[f'{period}M'] = ic
        
        return pd.DataFrame(ic_results)
    
    @staticmethod
    def factor_return(
        factor_scores: pd.DataFrame,
        security_returns: pd.DataFrame,
        quantiles: int = 5,
        long_short: bool = False
    ) -> pd.DataFrame:
        """
        计算 因子 收益率 using quantile portfolios.
        
        参数:
        -----------
        factor_scores : DataFrame
            因子 scores (索引: 日期, columns: 证券)
        security_returns : DataFrame
            证券 收益率 (索引: 日期, columns: 证券)
        quantiles : int
            Number of quantiles to 创建
        long_short : bool
            If True, 收益 long-short 投资组合 (Q1 - Q5)
            
        收益率:
        --------
        DataFrame
            收益率 by quantile (and long-short if specified)
        """
        quantile_returns = {f'Q{i+1}': [] for i in range(quantiles)}
        dates = []
        
        common_dates = factor_scores.index.intersection(security_returns.index[1:])
        
        for date in common_dates:
            scores = factor_scores.loc[date].dropna()
            
            # 获取 next period 收益率
            next_date_idx = security_returns.index.get_loc(date) + 1
            if next_date_idx < len(security_returns):
                next_date = security_returns.index[next_date_idx]
                returns = security_returns.loc[next_date]
                
                # Find common 证券
                common_sec = scores.index.intersection(returns.index)
                
                if len(common_sec) > quantiles:
                    # Assign to quantiles
                    scores_common = scores[common_sec]
                    returns_common = returns[common_sec]
                    
                    # 创建 quantiles
                    quantile_labels = pd.qcut(
                        scores_common,
                        q=quantiles,
                        labels=[f'Q{i+1}' for i in range(quantiles)],
                        duplicates='drop'
                    )
                    
                    # 计算 equal-weighted 收益率 for each quantile
                    for q in range(1, quantiles + 1):
                        q_label = f'Q{q}'
                        q_mask = quantile_labels == q_label
                        if q_mask.sum() > 0:
                            q_return = returns_common[q_mask].mean()
                            quantile_returns[q_label].append(q_return)
                        else:
                            quantile_returns[q_label].append(np.nan)
                    
                    dates.append(next_date)
        
        result = pd.DataFrame(quantile_returns, index=dates)
        
        if long_short:
            result['Long-Short'] = result['Q1'] - result[f'Q{quantiles}']
        
        return result
    
    @staticmethod
    def correlation_matrix(
        factor_scores: Dict[str, pd.DataFrame],
        method: str = 'spearman'
    ) -> pd.DataFrame:
        """
        计算 相关性 matrix between multiple 因子.
        
        参数:
        -----------
        factor_scores : 字典
            Dictionary of 因子 DataFrames {factor_name: scores_df}
        method : str
            相关性 method
            
        收益率:
        --------
        DataFrame
            相关性 matrix
        """
        # Flatten 因子 scores to long format
        factor_data = {}
        
        for factor_name, scores_df in factor_scores.items():
            # Stack to 获取 (日期, 证券) multi-索引
            scores_stacked = scores_df.stack()
            factor_data[factor_name] = scores_stacked
        
        # Combine into single DataFrame
        combined = pd.DataFrame(factor_data)
        
        # 计算 相关性
        if method == 'spearman':
            corr_matrix = combined.corr(method='spearman')
        elif method == 'pearson':
            corr_matrix = combined.corr(method='pearson')
        else:
            raise ValueError(f"Unknown method: {method}")
        
        return corr_matrix
    
    @staticmethod
    def quantile_backtest(
        factor_scores: pd.DataFrame,
        security_returns: pd.DataFrame,
        quantiles: int = 5,
        rebalance_freq: int = 1
    ) -> Dict[str, pd.Series]:
        """
        执行 quantile-based backtest.
        
        参数:
        -----------
        factor_scores : DataFrame
            因子 scores
        security_returns : DataFrame
            证券 收益率
        quantiles : int
            Number of quantiles
        rebalance_freq : int
            Rebalancing frequency (in periods)
            
        收益率:
        --------
        字典
            Cumulative 业绩 by quantile
        """
        # 获取 因子 收益率
        quantile_returns = FactorAnalyzer.factor_return(
            factor_scores,
            security_returns,
            quantiles=quantiles,
            long_short=True
        )
        
        # 计算 cumulative 收益率
        cumulative = {}
        for col in quantile_returns.columns:
            cumulative[col] = (1 + quantile_returns[col]).cumprod() * 100
        
        return cumulative
    
    @staticmethod
    def turnover_analysis(
        factor_scores: pd.DataFrame,
        quantiles: int = 5,
        top_n: Optional[int] = None
    ) -> pd.DataFrame:
        """
        计算 投资组合 turnover for 因子-based strategies.
        
        参数:
        -----------
        factor_scores : DataFrame
            因子 scores
        quantiles : int
            Number of quantiles
        top_n : int, 可选
            If specified, 分析 top N 证券 instead of quantiles
            
        收益率:
        --------
        DataFrame
            Turnover statistics
        """
        turnovers = []
        dates = sorted(factor_scores.index)
        
        for i in range(1, len(dates)):
            prev_date = dates[i-1]
            curr_date = dates[i]
            
            prev_scores = factor_scores.loc[prev_date].dropna()
            curr_scores = factor_scores.loc[curr_date].dropna()
            
            if top_n:
                # Use top N 证券
                prev_top = set(prev_scores.nlargest(top_n).index)
                curr_top = set(curr_scores.nlargest(top_n).index)
            else:
                # Use quantiles
                prev_quantile = pd.qcut(prev_scores, q=quantiles, labels=False, duplicates='drop')
                curr_quantile = pd.qcut(curr_scores, q=quantiles, labels=False, duplicates='drop')
                
                prev_top = set(prev_scores[prev_quantile == 0].index)
                curr_top = set(curr_scores[curr_quantile == 0].index)
            
            # 计算 turnover
            common_securities = prev_top.intersection(curr_top)
            turnover = 1 - (len(common_securities) / len(prev_top))
            
            turnovers.append({
                'date': curr_date,
                'turnover': turnover,
                'common_count': len(common_securities),
                'prev_count': len(prev_top),
                'curr_count': len(curr_top)
            })
        
        return pd.DataFrame(turnovers)
    
    @staticmethod
    def ic_statistics(
        ic_series: pd.Series
    ) -> Dict[str, float]:
        """
        计算 IC statistics.
        
        参数:
        -----------
        ic_series : Series
            IC 时间 series
            
        收益率:
        --------
        字典
            IC statistics including mean, std, IR, hit rate
        """
        ic_clean = ic_series.dropna()
        
        stats = {
            'mean_ic': ic_clean.mean(),
            'std_ic': ic_clean.std(),
            'ic_ir': ic_clean.mean() / ic_clean.std() if ic_clean.std() > 0 else 0,
            'hit_rate': (ic_clean > 0).sum() / len(ic_clean),
            'positive_ic_pct': (ic_clean > 0).sum() / len(ic_clean) * 100,
            'mean_positive_ic': ic_clean[ic_clean > 0].mean(),
            'mean_negative_ic': ic_clean[ic_clean < 0].mean(),
            't_stat': ic_clean.mean() / (ic_clean.std() / np.sqrt(len(ic_clean))) if len(ic_clean) > 0 else 0
        }
        
        return stats
    
    @staticmethod
    def factor_decay(
        factor_scores: pd.DataFrame,
        security_returns: pd.DataFrame,
        max_periods: int = 12
    ) -> pd.DataFrame:
        """
        分析 因子 decay over 时间.
        
        Measures how 因子 predictive power decays over different forward periods.
        
        参数:
        -----------
        factor_scores : DataFrame
            因子 scores
        security_returns : DataFrame
            证券 收益率
        max_periods : int
            Maximum number of forward periods to 分析
            
        收益率:
        --------
        DataFrame
            IC decay by period
        """
        decay_results = {}
        
        for period in range(1, max_periods + 1):
            # Shift 收益率
            fwd_returns = security_returns.shift(-period)
            
            # 计算 IC
            ic = FactorAnalyzer.calculate_ic(factor_scores, fwd_returns, method='spearman')
            
            decay_results[f'Period_{period}'] = {
                'mean_ic': ic.mean(),
                'std_ic': ic.std(),
                'hit_rate': (ic > 0).sum() / len(ic.dropna())
            }
        
        return pd.DataFrame(decay_results).T
    
    @staticmethod
    def cross_sectional_regression(
        factor_scores: Dict[str, pd.DataFrame],
        forward_returns: pd.DataFrame
    ) -> pd.DataFrame:
        """
        执行 cross-sectional regression of 收益率 on 因子.
        
        参数:
        -----------
        factor_scores : 字典
            Dictionary of 因子 DataFrames
        forward_returns : DataFrame
            Forward 收益率
            
        收益率:
        --------
        DataFrame
            Regression coefficients by 日期
        """
        from sklearn.linear_model import LinearRegression
        
        results = []
        
        # 获取 common dates
        all_dates = set(forward_returns.index)
        for scores in factor_scores.values():
            all_dates = all_dates.intersection(scores.index)
        
        common_dates = sorted(all_dates)
        
        for date in common_dates:
            # 获取 因子 values and 收益率 for this 日期
            X_dict = {}
            for factor_name, scores_df in factor_scores.items():
                X_dict[factor_name] = scores_df.loc[date]
            
            X = pd.DataFrame(X_dict).dropna()
            y = forward_returns.loc[date]
            
            # Find common 证券
            common_sec = X.index.intersection(y.index)
            
            if len(common_sec) > len(X.columns) + 1:
                X_common = X.loc[common_sec]
                y_common = y.loc[common_sec]
                
                # Fit regression
                model = LinearRegression()
                model.fit(X_common, y_common)
                
                # Store results
                result = {'date': date}
                for i, factor_name in enumerate(X.columns):
                    result[factor_name] = model.coef_[i]
                result['intercept'] = model.intercept_
                result['r_squared'] = model.score(X_common, y_common)
                
                results.append(result)
        
        return pd.DataFrame(results).set_index('date')


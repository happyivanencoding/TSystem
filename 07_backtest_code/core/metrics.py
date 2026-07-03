"""
业绩指标计算模块
"""

import pandas as pd
import numpy as np
from typing import Union, Optional
import logging

logger = logging.getLogger(__name__)


class PerformanceMetrics:
    """Calculate portfolio performance metrics."""
    
    @staticmethod
    def annual_return(returns: Union[pd.Series, pd.DataFrame], periods_per_year: int = 252) -> float:
        """
        计算 annualized 收益.
        
        参数:
        -----------
        收益率 : Series or DataFrame
            收益 series
        periods_per_year : int
            Number of periods per year (252 for daily, 12 for monthly)
            
        收益率:
        --------
        float
            年化收益率
    """
        total_return = (1 + returns).prod() - 1
        n_periods = len(returns)
        years = n_periods / periods_per_year
        
        return (1 + total_return) ** (1 / years) - 1
    
    @staticmethod
    def annual_volatility(returns: Union[pd.Series, pd.DataFrame], periods_per_year: int = 252) -> float:
        """
        计算 annualized 波动率.
        
        参数:
        -----------
        收益率 : Series or DataFrame
            收益 series
        periods_per_year : int
            Number of periods per year
            
        收益率:
        --------
        float
            年化波动率
        """
        return returns.std() * np.sqrt(periods_per_year)
    
    @staticmethod
    def sharpe_ratio(
        returns: Union[pd.Series, pd.DataFrame],
        risk_free_rate: float = 0.0,
        periods_per_year: int = 252
    ) -> float:
        """
        计算 夏普比率.
        
        参数:
        -----------
        收益率 : Series or DataFrame
            收益 series
        risk_free_rate : float
            Annual 风险-free rate
        periods_per_year : int
            Number of periods per year
            
        收益率:
        --------
        float
            夏普比率
        """
        excess_returns = returns - (risk_free_rate / periods_per_year)
        return np.sqrt(periods_per_year) * excess_returns.mean() / excess_returns.std()
    
    @staticmethod
    def sortino_ratio(
        returns: Union[pd.Series, pd.DataFrame],
        target_return: float = 0.0,
        periods_per_year: int = 252
    ) -> float:
        """
        计算 索提诺比率 (uses downside deviation).
        
        参数:
        -----------
        收益率 : Series or DataFrame
            收益 series
        target_return : float
            Target 收益 threshold
        periods_per_year : int
            Number of periods per year
            
        收益率:
        --------
        float
            索提诺比率
        """
        excess = returns - target_return
        downside = excess[excess < 0]
        downside_std = downside.std()
        
        if downside_std == 0:
            return np.nan
        
        return np.sqrt(periods_per_year) * excess.mean() / downside_std
    
    @staticmethod
    def max_drawdown(returns: Union[pd.Series, pd.DataFrame]) -> float:
        """
        计算 maximum drawdown.
        
        参数:
        -----------
        收益率 : Series or DataFrame
            收益 series
            
        收益率:
        --------
        float
            最大回撤 (negative 值)
        """
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        
        return drawdown.min()
    
    @staticmethod
    def calmar_ratio(returns: Union[pd.Series, pd.DataFrame], periods_per_year: int = 252) -> float:
        """
        计算 卡玛比率 (annual 收益 / max drawdown).
        
        参数:
        -----------
        收益率 : Series or DataFrame
            收益 series
        periods_per_year : int
            Number of periods per year
            
        收益率:
        --------
        float
            卡玛比率
        """
        ann_return = PerformanceMetrics.annual_return(returns, periods_per_year)
        max_dd = abs(PerformanceMetrics.max_drawdown(returns))
        
        if max_dd == 0:
            return np.nan
        
        return ann_return / max_dd
    
    @staticmethod
    def information_ratio(
        returns: Union[pd.Series, pd.DataFrame],
        benchmark_returns: Union[pd.Series, pd.DataFrame],
        periods_per_year: int = 252
    ) -> float:
        """
        计算 information 比率.
        
        参数:
        -----------
        收益率 : Series or DataFrame
            投资组合 收益率
        benchmark_returns : Series or DataFrame
            基准 收益率
        periods_per_year : int
            Number of periods per year
            
        收益率:
        --------
        float
            Information 比率
        """
        active_returns = returns - benchmark_returns
        tracking_error = active_returns.std() * np.sqrt(periods_per_year)
        
        if tracking_error == 0:
            return np.nan
        
        return (active_returns.mean() * periods_per_year) / tracking_error
    
    @staticmethod
    def tracking_error(
        returns: Union[pd.Series, pd.DataFrame],
        benchmark_returns: Union[pd.Series, pd.DataFrame],
        periods_per_year: int = 252
    ) -> float:
        """
        计算 tracking error.
        
        参数:
        -----------
        收益率 : Series or DataFrame
            投资组合 收益率
        benchmark_returns : Series or DataFrame
            基准 收益率
        periods_per_year : int
            Number of periods per year
            
        收益率:
        --------
        float
            Tracking error
        """
        active_returns = returns - benchmark_returns
        return active_returns.std() * np.sqrt(periods_per_year)
    
    @staticmethod
    def win_rate(returns: Union[pd.Series, pd.DataFrame]) -> float:
        """
        计算 win rate (percentage of positive 收益率).
        
        参数:
        -----------
        收益率 : Series or DataFrame
            收益 series
            
        收益率:
        --------
        float
            Win rate (0 to 1)
        """
        return (returns > 0).sum() / len(returns)
    
    @staticmethod
    def profit_loss_ratio(returns: Union[pd.Series, pd.DataFrame]) -> float:
        """
        计算 profit/loss 比率 (average win / average loss).
        
        参数:
        -----------
        收益率 : Series or DataFrame
            收益 series
            
        收益率:
        --------
        float
            Profit/loss 比率
        """
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        
        if len(losses) == 0:
            return np.inf
        
        avg_win = wins.mean() if len(wins) > 0 else 0
        avg_loss = abs(losses.mean())
        
        if avg_loss == 0:
            return np.nan
        
        return avg_win / avg_loss
    
    @staticmethod
    def calculate_all_metrics(
        returns: Union[pd.Series, pd.DataFrame],
        benchmark_returns: Optional[Union[pd.Series, pd.DataFrame]] = None,
        risk_free_rate: float = 0.0,
        periods_per_year: int = 252
    ) -> dict:
        """
        计算 all available 指标.
        
        参数:
        -----------
        收益率 : Series or DataFrame
            投资组合 收益率
        benchmark_returns : Series or DataFrame, 可选
            基准 收益率
        risk_free_rate : float
            Annual 风险-free rate
        periods_per_year : int
            Number of periods per year
            
        收益率:
        --------
        字典
            Dictionary of all 指标
        """
        metrics = {
            'Annual Return': PerformanceMetrics.annual_return(returns, periods_per_year),
            'Annual Volatility': PerformanceMetrics.annual_volatility(returns, periods_per_year),
            'Sharpe Ratio': PerformanceMetrics.sharpe_ratio(returns, risk_free_rate, periods_per_year),
            'Sortino Ratio': PerformanceMetrics.sortino_ratio(returns, 0, periods_per_year),
            'Max Drawdown': PerformanceMetrics.max_drawdown(returns),
            'Calmar Ratio': PerformanceMetrics.calmar_ratio(returns, periods_per_year),
            'Win Rate': PerformanceMetrics.win_rate(returns),
            'Profit/Loss Ratio': PerformanceMetrics.profit_loss_ratio(returns),
        }
        
        if benchmark_returns is not None:
            metrics['Information Ratio'] = PerformanceMetrics.information_ratio(
                returns, benchmark_returns, periods_per_year
            )
            metrics['Tracking Error'] = PerformanceMetrics.tracking_error(
                returns, benchmark_returns, periods_per_year
            )
        
        return metrics


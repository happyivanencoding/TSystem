"""
Backward-compatible entry point for the refactored backtest system.
This module provides the PtfBuilder class that wraps the new modular architecture
while maintaining the same API as the original BacktestEngine.py.
"""

import numpy as np
import pandas as pd
import copy
import datetime
import os
import logging
from typing import Union, List, Optional

# Import new modular components
from core.portfolio_builder import PortfolioBuilder
from core.backtest_engine import BacktestEngine
from core.backtest_engine_optimized import BacktestEngineOptimized
from core.data_loader import DataLoader
from core.metrics import PerformanceMetrics
from utils.plotting import PlotlyVisualizer
from utils.data_utils import read_liste_noire, merge_weight_by_pairs, merge_ticker_secondaire
from utils.constants import *

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PtfBuilder:
    """
    Portfolio Builder - Main class for portfolio construction and backtesting.
    
    This class provides a backward-compatible interface to the refactored system.
    It wraps the new modular components while maintaining the same API.
    """
    
    def __init__(
        self,
        screen: Union[str, pd.DataFrame],
        returns: Union[str, pd.DataFrame],
        bench: str,
        percentile: float,
        metrics: Union[str, List[str]],
        ptf_name: str = "PTF TEST",
        ponderation: str = 'Racine cube',
        esg_exclusion: float = 0,
        cut_mkt_cap: float = 0,
        liste_noire: Optional[Union[str, List[str]]] = None,
        reco_secto: Union[List[float], pd.DataFrame] = None,
        reco_facto: Union[List[float], pd.DataFrame] = None,
        score_neutral: str = "ICB 19",
        weight_neutral: str = "ICB 19",
        Top: bool = True,
        top_mandatory: Optional[int] = None,
        multiprocessing: bool = False,
        mode_monthly_prod: bool = False,
        output_dir: Optional[str] = None,
        cap_weight_threshold: Optional[float] = None,
        financial_filter_config: Optional[dict] = None,
        use_factor_ranking: bool = True,
        score_pivot_esg: Optional[Union[str, float]] = None,
        score_pivot_esg_path: Optional[str] = None,
        optimizer_config: Optional[dict] = None
    ):
        """
        Initialize the Portfolio Builder.
        
        Parameters match the original PtfBuilder for backward compatibility.
        """
        # Initialize portfolio builder
        self.portfolio_builder = PortfolioBuilder(
            screen=screen,
            bench=bench,
            percentile=percentile,
            metrics=metrics,
            ptf_name=ptf_name,
            ponderation=ponderation,
            esg_exclusion=esg_exclusion,
            cut_mkt_cap=cut_mkt_cap,
            liste_noire=liste_noire,
            reco_secto=reco_secto,
            reco_facto=reco_facto,
            score_neutral=score_neutral,
            weight_neutral=weight_neutral,
            Top=Top,
            top_mandatory=top_mandatory,
            mode_monthly_prod=mode_monthly_prod,
            output_dir=output_dir,
            cap_weight_threshold=cap_weight_threshold,
            financial_filter_config=financial_filter_config,
            use_factor_ranking=use_factor_ranking,
            score_pivot_esg=score_pivot_esg,
            score_pivot_esg_path=score_pivot_esg_path
        )
        
        # Initialize backtest engines
        self.backtest_engine = BacktestEngine(returns=returns)
        self._optimized_backtest_engine = None
        self.portfolio_builder.returns = self.backtest_engine.returns
        self.optimizer_config = optimizer_config or {}
        
        # Keep the legacy data_loader attribute without duplicating loaded frames.
        self.data_loader = DataLoader()
        
        # Store original parameters for compatibility
        self.screen = self.portfolio_builder.screen
        self.returns = self.backtest_engine.returns
        self.data_loader.screen = self.screen
        self.data_loader.returns = self.returns
        self.bench = bench
        self.percentile = percentile
        self.metrics = metrics
        self.ptf_name = ptf_name
        self.ponderation = ponderation
        self.start_date = None
        
        # Initialize result containers
        self.sec_list_monthly = None
        self.sec_list_historical = None
        self.list_exclusion_monthly = None
        self.list_exclusion_histo = None
        self.sec_list_optimized_monthly = None
        self.optimizer_result_monthly = None
        self.perf_ptf = None
        self.perf_bench = None
        self.perf_optimized = None
        self.buy_list = None

    @property
    def optimized_backtest_engine(self):
        """Lazily initialize the optimized engine only for optimizer backtests."""
        if self._optimized_backtest_engine is None:
            self._optimized_backtest_engine = BacktestEngineOptimized(returns=self.returns)
        return self._optimized_backtest_engine
    
    def sec_list_spot(self, screen_agg_monthly: Optional[pd.DataFrame] = None):
        """Generate security list for a single month."""
        result = self.portfolio_builder.sec_list_spot(screen_agg_monthly)
        
        # Update instance variables for backward compatibility
        self.sec_list_monthly = self.portfolio_builder.sec_list_monthly
        self.list_exclusion_monthly = self.portfolio_builder.list_exclusion_monthly
        
        return result
    
    def sec_list_spot_optim(self, screen_agg_monthly: Optional[pd.DataFrame] = None, **optimizer_kwargs):
        """Generate optimizer-based sec list. Normal sec_list_spot remains ponderation-based."""
        config = dict(self.optimizer_config)
        config.update(optimizer_kwargs)
        result = self.portfolio_builder.sec_list_spot_optim(
            screen_agg_monthly=screen_agg_monthly,
            **config,
        )
        self.sec_list_optimized_monthly = self.portfolio_builder.sec_list_optimized_monthly
        self.optimizer_result_monthly = self.portfolio_builder.optimizer_result_monthly
        return result

    def backtest_optimized_sec_list(self, optimizer_result: Optional[pd.DataFrame] = None, **backtest_kwargs):
        """Backtest optimizer output with the optimized backtest bridge."""
        if optimizer_result is None:
            optimizer_result = self.optimizer_result_monthly
        if optimizer_result is None:
            raise ValueError("No optimizer_result provided. Run sec_list_spot_optim() first or pass optimizer_result.")
        result = self.optimized_backtest_engine.backtest_optimizer_result(
            optimizer_result=optimizer_result,
            **backtest_kwargs,
        )
        self.perf_optimized = result.nav
        self.perf_ptf = result.nav
        return result
    
    def generic_histo_seclist(
        self,
        start_date: datetime.datetime,
        freq_rebal: Optional[int] = None,
        screen_start_date: str = "mois_impair",
        fill_method: str = "drift"
    ):
        """Generate historical security lists."""
        result = self.portfolio_builder.generic_histo_seclist(
            start_date=start_date,
            freq_rebal=freq_rebal,
            screen_start_date=screen_start_date,
            fill_method=fill_method
        )
        
        # Update instance variables for backward compatibility
        self.sec_list_historical = self.portfolio_builder.sec_list_historical
        self.list_exclusion_histo = self.portfolio_builder.list_exclusion_histo
        self.start_date = self.portfolio_builder.start_date
        
        return result
    
    def backtest(
        self,
        sec_list: Optional[pd.DataFrame] = None,
        indice_name: Optional[str] = None,
        method: Optional[str] = None,
        max_weight: float = 1,
        col_sector: str = COL_SECTOR_ICB19,
        col_sedol: str = COL_SEDOL,
        col_isin: str = COL_ISIN,
        col_date: str = COL_DATE,
        col_mkt_cap: str = COL_MKT_CAP,
        sector_neutral: bool = False,
        sec_list_: bool = True,
        ponderation: str = 'mkt_cap',
        **kwargs  # Catch unused parameters for compatibility
    ):
        """Perform backtest on security list."""
        # Use historical sec list if not provided
        if sec_list is None:
            if self.sec_list_historical is not None:
                sec_list = self.sec_list_historical
            else:
                raise ValueError("No security list provided and no historical list available")
        
        # Perform backtest
        perf_ttr, buy_list = self.backtest_engine.backtest(
            sec_list=sec_list,
            screen=self.screen,
            indice_name=indice_name,
            method=method,
            max_weight=max_weight,
            col_sector=col_sector,
            col_sedol=col_sedol,
            col_isin=col_isin,
            col_date=col_date,
            col_mkt_cap=col_mkt_cap,
            sector_neutral=sector_neutral,
            sec_list_=sec_list_,
            ponderation=ponderation
        )
        
        # Update instance variables
        if sec_list_:
            self.perf_ptf = self.backtest_engine.perf_ptf
            self.buy_list = self.backtest_engine.buy_list
        else:
            self.perf_bench = self.backtest_engine.perf_bench
        
        return perf_ttr, buy_list
    
    def adjust_companies_ponderation(self, df: pd.DataFrame) -> pd.DataFrame:
        """兼容旧 PtfBuilder API：按当前 ponderation 转换 market-cap 权重基数。"""
        return self.portfolio_builder.adjust_companies_ponderation(df)

    def backtest_calcul_all_portfolio(
        self,
        df_rebal: pd.DataFrame,
        df_returns: pd.DataFrame,
        col_weight: str,
        col_sector: str = COL_SECTOR_ICB19,
        col_date: str = COL_DATE,
        col_id: str = COL_SEDOL,
    ) -> pd.Series:
        """兼容旧 API：按 rebalancing 权重计算组合累计净值。"""
        return self.backtest_engine.calculate_portfolio_returns(
            df_rebal=df_rebal,
            df_returns=df_returns,
            col_weight=col_weight,
            col_sector=col_sector,
            col_date=col_date,
            col_id=col_id,
        )

    def backtest_create_ptf_weight(
        self,
        sec_list: pd.DataFrame,
        indice_name: str,
        screen_agg: pd.DataFrame,
        max_weight: float,
        col_mkt_cap: str = COL_MKT_CAP,
        col_date: str = COL_DATE,
        col_sector: str = COL_SECTOR_ICB19,
        sector_neutral: bool = False,
        method: str = "Market cap",
        col_sedol: str = COL_SEDOL,
        col_isin: str = COL_ISIN,
    ) -> pd.DataFrame:
        """兼容旧 API：根据 sec list 和 screen 创建回测目标权重。"""
        return self.backtest_engine.create_ptf_weight(
            sec_list=sec_list,
            indice_name=indice_name,
            screen_agg=screen_agg,
            max_weight=max_weight,
            col_mkt_cap=col_mkt_cap,
            col_date=col_date,
            col_sector=col_sector,
            sector_neutral=sector_neutral,
            method=method,
            col_sedol=col_sedol,
            col_isin=col_isin,
        )

    def plot_tracking_error(
        self,
        window: int = 21,
        save_path: Optional[str] = None,
        show_plot: bool = True,
    ) -> pd.DataFrame:
        """兼容旧 API：画 realized rolling TE，并可叠加 optimizer constraint TE。"""
        constraint_history = getattr(self, "df_constraint", None)
        return self.backtest_engine.plot_tracking_error(
            perf_ptf=self.perf_ptf,
            perf_bench=self.perf_bench,
            constraint_history=constraint_history,
            window=window,
            save_path=save_path,
            show_plot=show_plot,
        )


    def backtest_get_bench_perf(
        self,
        screen: pd.DataFrame,
        start_date: pd.Timestamp,
        bench: str
    ):
        """Calculate benchmark performance."""
        self.backtest_engine.backtest_get_bench_perf(screen, start_date, bench)
        self.perf_bench = self.backtest_engine.perf_bench
    
    def backtest_plot_ptf_bench(
        self,
        perf_ptf: Optional[pd.Series] = None,
        perf_bench: Optional[pd.Series] = None,
        title: Optional[str] = None,
        save_path: str = "portfolio_performance.html",
        show_plot: bool = True
    ):
        """Plot portfolio vs benchmark performance."""
        # Use instance variables if not provided
        if perf_ptf is None:
            if self.perf_ptf is None:
                perf_ptf, _ = self.backtest(self.sec_list_historical)
            else:
                perf_ptf = self.perf_ptf
        
        if perf_bench is None:
            if self.perf_bench is None:
                self.backtest_get_bench_perf(self.screen, self.start_date, self.bench)
            perf_bench = self.perf_bench
        
        # Create plot
        fig = PlotlyVisualizer.plot_portfolio_vs_benchmark(
            perf_ptf=perf_ptf,
            perf_bench=perf_bench,
            title=title,
            save_path=save_path,
            show_plot=show_plot
        )
        
        return fig
    
    def backtest_plot_top_vs_bottom(
        self,
        builder_bottom: "PtfBuilder",
        perf_top: Optional[pd.Series] = None,
        perf_bottom: Optional[pd.Series] = None,
        perf_bench: Optional[pd.Series] = None,
        title: Optional[str] = None,
        save_path: str = "top_bottom_performance.html",
        show_plot: bool = True,
    ):
        """Plot top, bottom and benchmark performance with ratio comparisons."""
        if perf_top is None:
            if self.perf_ptf is None:
                perf_top, _ = self.backtest(self.sec_list_historical)
            else:
                perf_top = self.perf_ptf
        if perf_bottom is None:
            if builder_bottom.perf_ptf is None:
                perf_bottom, _ = builder_bottom.backtest(builder_bottom.sec_list_historical)
            else:
                perf_bottom = builder_bottom.perf_ptf
        if perf_bench is None:
            if self.perf_bench is None:
                self.backtest_get_bench_perf(self.screen, self.start_date, self.bench)
            perf_bench = self.perf_bench

        return PlotlyVisualizer.plot_top_bottom_vs_benchmark(
            perf_top=perf_top,
            perf_bottom=perf_bottom,
            perf_bench=perf_bench,
            title=title,
            save_path=save_path,
            show_plot=show_plot,
        )
    
    # Additional utility methods for backward compatibility
    @staticmethod
    def calculate_metrics(
        returns: pd.Series,
        benchmark_returns: Optional[pd.Series] = None,
        risk_free_rate: float = 0.0
    ) -> dict:
        """Calculate performance metrics."""
        return PerformanceMetrics.calculate_all_metrics(
            returns=returns,
            benchmark_returns=benchmark_returns,
            risk_free_rate=risk_free_rate
        )


# Export functions for backward compatibility
__all__ = [
    'PtfBuilder',
    'read_liste_noire',
    'merge_weight_by_pairs',
    'merge_ticker_secondaire',
    'PerformanceMetrics',
    'PlotlyVisualizer'
]



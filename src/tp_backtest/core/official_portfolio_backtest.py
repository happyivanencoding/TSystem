"""Official Top/Worst portfolio workflow backed by the TP NAV kernel."""

import pandas as pd
import datetime
import logging
from typing import Union, List, Optional

from tp_backtest.core.security_list_constructor import SecurityListConstructor
from tp_backtest.core.optimizer_backtest_adapter import OptimizerBacktestAdapter
from tp_backtest.core.weight_table_adapter import (
    benchmark_reference_list,
    benchmark_to_weight_table,
    plot_tracking_error,
    security_list_to_weight_table,
)
from tp_backtest.core.data_loader import DataLoader
from tp_backtest.core.metrics import PerformanceMetrics
from tp_core.security_nav_engine import (
    TargetWeightSchema,
    SecurityNavEngine,
)
from tp_backtest.execution import ExecutionAssumptions, simulate_weight_execution
from tp_backtest.utils.plotting import PlotlyVisualizer
from tp_backtest.utils.constants import *

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OfficialPortfolioBacktest:
    """Orchestrate official security lists, benchmark weights and NAV outputs."""
    
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
        optimizer_config: Optional[dict] = None,
        copy_inputs: bool = False,
        monthly_base_cache: Optional[dict] = None,
        benchmark_cache: Optional[dict] = None,
        execution_config: Optional[dict] = None,
    ):
        self.security_list_constructor = SecurityListConstructor(
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
            score_pivot_esg_path=score_pivot_esg_path,
            copy_inputs=copy_inputs,
            monthly_base_cache=monthly_base_cache,
        )
        
        self.nav_engine = SecurityNavEngine(returns=returns)
        self.execution_assumptions = ExecutionAssumptions(**(execution_config or {}))
        self._optimizer_nav_adapter = None
        self.security_list_constructor.returns = self.nav_engine.returns
        self.optimizer_config = optimizer_config or {}
        self.benchmark_cache = benchmark_cache
        if self.benchmark_cache is not None and not isinstance(
            self.benchmark_cache,
            dict,
        ):
            raise TypeError("benchmark_cache must be a dictionary or None")
        
        self.data_loader = DataLoader()

        self.screen = self.security_list_constructor.screen
        self.returns = self.nav_engine.returns
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
        self.last_result = None
        self.last_benchmark_result = None

    def _run_weight_nav(self, weights, schema):
        if self.execution_assumptions.mode == "fast_nav":
            return self.nav_engine.run_weights(weights, schema=schema)
        return simulate_weight_execution(
            weights,
            self.returns,
            assumptions=self.execution_assumptions,
            schema=schema,
        )

    @property
    def optimizer_nav_adapter(self):
        """Lazily initialize the optimizer-to-weight adapter."""
        if self._optimizer_nav_adapter is None:
            self._optimizer_nav_adapter = OptimizerBacktestAdapter(
                returns=self.returns,
                execution_assumptions=self.execution_assumptions,
            )
        return self._optimizer_nav_adapter
    
    def build_monthly_security_list(self, screen_agg_monthly: Optional[pd.DataFrame] = None):
        """Generate security list for a single month."""
        result = self.security_list_constructor.build_monthly_security_list(
            screen_agg_monthly
        )
        self.sec_list_monthly = self.security_list_constructor.sec_list_monthly
        self.list_exclusion_monthly = (
            self.security_list_constructor.list_exclusion_monthly
        )
        
        return result
    
    def build_optimized_monthly_security_list(self, screen_agg_monthly: Optional[pd.DataFrame] = None, **optimizer_kwargs):
        """Generate optimizer-based sec list. Normal build_monthly_security_list remains ponderation-based."""
        config = dict(self.optimizer_config)
        config.update(optimizer_kwargs)
        result = self.security_list_constructor.build_optimized_monthly_security_list(
            screen_agg_monthly=screen_agg_monthly,
            **config,
        )
        self.sec_list_optimized_monthly = (
            self.security_list_constructor.sec_list_optimized_monthly
        )
        self.optimizer_result_monthly = (
            self.security_list_constructor.optimizer_result_monthly
        )
        return result

    def run_optimizer_nav(self, optimizer_result: Optional[pd.DataFrame] = None, **backtest_kwargs):
        """Backtest optimizer output with the optimized backtest bridge."""
        if optimizer_result is None:
            optimizer_result = self.optimizer_result_monthly
        if optimizer_result is None:
            raise ValueError("No optimizer_result provided. Run build_optimized_monthly_security_list() first or pass optimizer_result.")
        result = self.optimizer_nav_adapter.calculate_optimizer_nav(
            optimizer_result=optimizer_result,
            **backtest_kwargs,
        )
        self.perf_optimized = result.nav
        self.perf_ptf = result.nav
        return result
    
    def build_historical_security_lists(
        self,
        start_date: datetime.datetime,
        freq_rebal: Optional[int] = None,
        screen_start_date: str = "mois_impair",
        fill_method: str = "drift"
    ):
        """Generate historical security lists."""
        result = self.security_list_constructor.build_historical_security_lists(
            start_date=start_date,
            freq_rebal=freq_rebal,
            screen_start_date=screen_start_date,
            fill_method=fill_method
        )
        
        self.sec_list_historical = (
            self.security_list_constructor.sec_list_historical
        )
        self.list_exclusion_histo = (
            self.security_list_constructor.list_exclusion_histo
        )
        self.start_date = self.security_list_constructor.start_date
        
        return result
    
    def run_portfolio_nav(
        self,
        sec_list: Optional[pd.DataFrame] = None,
        indice_name: Optional[str] = None,
        max_weight: float = 1,
        col_sector: str = COL_SECTOR_ICB19,
        col_sedol: str = COL_SEDOL,
        col_isin: str = COL_ISIN,
        col_date: str = COL_DATE,
        col_mkt_cap: str = COL_MKT_CAP,
        sector_neutral: bool = False,
        sec_list_: bool = True,
        ponderation: Optional[str] = None,
    ):
        """Perform backtest on security list."""
        # Use historical sec list if not provided
        if sec_list is None:
            if self.sec_list_historical is not None:
                sec_list = self.sec_list_historical
            else:
                raise ValueError("No security list provided and no historical list available")
        
        if sec_list_:
            weights = security_list_to_weight_table(
                sec_list,
                self.screen,
                max_weight=max_weight,
                col_sector=col_sector,
                col_sedol=col_sedol,
                col_isin=col_isin,
                col_date=col_date,
                col_mkt_cap=col_mkt_cap,
            )
            result = self._run_weight_nav(
                weights.reset_index(),
                TargetWeightSchema(
                    date_col=col_date,
                    id_col=col_sedol,
                    weight_col=COL_PORTFOLIO_WEIGHT,
                ),
            )
            self.last_result = result
            self.perf_ptf = result.nav
            self.buy_list = weights
            perf_ttr = result.nav
            buy_list = weights
        else:
            if indice_name is None:
                raise ValueError("indice_name is required for benchmark backtests")
            weights = benchmark_to_weight_table(
                sec_list,
                indice_name,
                self.screen,
                max_weight,
                col_mkt_cap=col_mkt_cap,
                col_date=col_date,
                col_sector=col_sector,
                sector_neutral=sector_neutral,
                method=ponderation or self.ponderation,
                col_sedol=col_sedol,
                col_isin=col_isin,
            )
            result = self._run_weight_nav(
                weights.reset_index(),
                TargetWeightSchema(
                    date_col=col_date,
                    id_col=col_sedol,
                    weight_col=COL_PORTFOLIO_WEIGHT,
                ),
            )
            self.last_benchmark_result = result
            self.perf_bench = result.nav
            perf_ttr = result.nav
            buy_list = self.buy_list
        
        return perf_ttr, buy_list
    
    def transform_weighting_base(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the configured weighting transform to the market-cap base."""
        return self.security_list_constructor.transform_weighting_base(df)

    def plot_tracking_error(
        self,
        window: int = 21,
        save_path: Optional[str] = None,
        show_plot: bool = True,
    ) -> pd.DataFrame:
        """Plot realized rolling TE and optional optimizer constraint TE."""
        constraint_history = getattr(self, "df_constraint", None)
        return plot_tracking_error(
            perf_ptf=self.perf_ptf,
            perf_bench=self.perf_bench,
            constraint_history=constraint_history,
            window=window,
            save_path=save_path,
            show_plot=show_plot,
        )


    def run_benchmark_nav(
        self,
        screen: pd.DataFrame,
        start_date: pd.Timestamp,
        bench: str
    ):
        """Calculate benchmark performance."""
        cache_key = None
        if self.benchmark_cache is not None:
            cache_key = (
                id(screen),
                id(self.returns),
                str(bench),
                pd.Timestamp(start_date),
            )
            cached = self.benchmark_cache.get(cache_key)
            if cached is not None:
                self.perf_bench = cached
                return
        indice_ref = benchmark_reference_list(screen, start_date, bench)
        self.run_portfolio_nav(
            sec_list=indice_ref,
            indice_name=bench,
            sec_list_=False,
            ponderation=self.ponderation,
        )
        if cache_key is not None:
            self.benchmark_cache[cache_key] = self.perf_bench.copy(deep=True)
    
    def plot_portfolio_vs_benchmark(
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
                perf_ptf, _ = self.run_portfolio_nav(self.sec_list_historical)
            else:
                perf_ptf = self.perf_ptf
        
        if perf_bench is None:
            if self.perf_bench is None:
                self.run_benchmark_nav(self.screen, self.start_date, self.bench)
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
    
    def plot_top_vs_bottom(
        self,
        bottom_workflow: "OfficialPortfolioBacktest",
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
                perf_top, _ = self.run_portfolio_nav(self.sec_list_historical)
            else:
                perf_top = self.perf_ptf
        if perf_bottom is None:
            if bottom_workflow.perf_ptf is None:
                perf_bottom, _ = bottom_workflow.run_portfolio_nav(
                    bottom_workflow.sec_list_historical
                )
            else:
                perf_bottom = bottom_workflow.perf_ptf
        if perf_bench is None:
            if self.perf_bench is None:
                self.run_benchmark_nav(self.screen, self.start_date, self.bench)
            perf_bench = self.perf_bench

        return PlotlyVisualizer.plot_top_bottom_vs_benchmark(
            perf_top=perf_top,
            perf_bottom=perf_bottom,
            perf_bench=perf_bench,
            title=title,
            save_path=save_path,
            show_plot=show_plot,
        )
    
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


__all__ = ["OfficialPortfolioBacktest"]

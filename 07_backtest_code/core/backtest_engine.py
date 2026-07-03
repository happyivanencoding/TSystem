"""
回测引擎模块 - 处理投资组合回测计算
"""

import pandas as pd
import numpy as np
import copy
from typing import Union, Optional, Tuple
import logging

from utils.constants import *
from core.weight_manager import WeightManager
from tp_core.general_backtest import GeneralBacktestEngine

logger = logging.getLogger(__name__)


class BacktestEngine(GeneralBacktestEngine):
    """
    对证券列表执行回测计算
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
            self.returns = copy.deepcopy(returns)
        else:
            raise TypeError("returns must be str (path) or DataFrame")
        
        self.perf_ptf = None
        self.perf_bench = None
        self.buy_list = None
        self.last_result = None
    
    @staticmethod
    def calculate_portfolio_returns(
        df_rebal: pd.DataFrame,
        df_returns: pd.DataFrame,
        col_weight: str = COL_PORTFOLIO_WEIGHT,
        col_sector: str = COL_SECTOR_ICB19,
        col_date: str = COL_DATE,
        col_id: str = COL_SEDOL
    ) -> pd.Series:
        """
        计算投资组合收益率并处理权重漂移
        
        参数:
        -----------
        df_rebal : DataFrame
            包含权重的再平衡数据
        df_returns : DataFrame
            日收益率数据
        col_weight : str
            权重列名
        col_sector : str
            行业列名
        col_date : str
            日期列名
        col_id : str
            证券标识列名
            
        返回:
        --------
        Series
            投资组合累计收益率 (基数 100)
        """
        # 获取再平衡日期和收益率日期
        liste_rebal_date = list(df_rebal.index.get_level_values(col_date).unique())
        liste_date_returns = list(df_returns[df_returns.index >= liste_rebal_date[0]].index)
        
        # 重置索引以便处理
        df_rebal.reset_index(inplace=True)
        
        # 过滤出收益率数据中存在的证券
        df_rebal = df_rebal[df_rebal[col_id].isin(df_returns.columns)]
        df_rebal.set_index(col_date, inplace=True)
        
        # 归一化权重
        df_rebal[col_weight] = df_rebal.groupby(col_date)[col_weight].transform(lambda x: x / x.sum())
        
        df_rebal.reset_index(inplace=True)
        
        # 调整再平衡日期以匹配可用的收益率日期
        for i in range(len(liste_rebal_date)):
            if liste_rebal_date[i] not in liste_date_returns:
                try:
                    serie_date_returns = pd.Series(liste_date_returns)
                    new_date_rebal = serie_date_returns[serie_date_returns > liste_rebal_date[i]].iloc[1]
                except (ValueError, IndexError):
                    # 如果找不到未来日期，使用之前的日期
                    new_date_rebal = max(d for d in liste_date_returns if d < liste_rebal_date[i])
            else:
                serie_date_returns = pd.Series(liste_date_returns)
                new_date_rebal = serie_date_returns[serie_date_returns > liste_rebal_date[i]].iloc[0]
            
            df_rebal = df_rebal.replace(liste_rebal_date[i], new_date_rebal)
            liste_rebal_date[i] = new_date_rebal
        
        # 创建每日日期框架
        liste_date_all = list(set(liste_rebal_date).union(set(liste_date_returns)))
        nouvelle_liste_dates = sorted(liste_date_all)
        
        new_df = pd.DataFrame(data=nouvelle_liste_dates, columns=['Date_returns'])
        
        # 将再平衡日期映射到每个收益率日期
        new_df['Date_screen'] = new_df['Date_returns'].apply(
            lambda x: df_rebal.loc[df_rebal[col_date] <= x, col_date].max()
        )
        
        # 将再平衡数据与每日日期合并
        df_merge = pd.merge(df_rebal, new_df, how='left', left_on=col_date, right_on='Date_screen')
        df_merge.drop(columns=col_date, inplace=True)
        df_merge.rename(columns={'Date_returns': col_date}, inplace=True)
        df_merge.sort_values(by=col_date, inplace=True)
        
        # 从第一个再平衡日期开始计算累计收益率
        df_returns = df_returns[new_df['Date_screen'].min():]
        returns_cum = (1 + df_returns).cumprod()
        
        # 在每个再平衡日期重新基准化漂移
        returns_drift = returns_cum.apply(
            lambda x: x / returns_cum.loc[new_df.loc[new_df['Date_screen'] <= x.name, 'Date_screen'].max()],
            axis=1
        )
        
        # 展平漂移乘数
        returns_drift_flat = returns_drift.stack().to_frame().reset_index(names=[col_date, col_id])
        returns_drift_flat.columns = [col_date, col_id, 'drift_multiplicator']
        
        # 展平收益率
        returns_flat = df_returns.stack().to_frame().reset_index()
        returns_flat.columns = [col_date, col_id, 'Return']
        
        # 合并漂移和收益率
        df_merge = df_merge.merge(returns_drift_flat, how='left', on=[col_date, col_id])
        df_merge = df_merge.merge(returns_flat, how='left', on=[col_date, col_id])
        
        # 计算漂移后的权重
        df_merge[col_weight + '_drifted'] = df_merge[col_weight] * df_merge['drift_multiplicator']
        
        # 准备投资组合数据
        columns = [col_date, col_id, col_weight, col_weight + '_drifted', col_sector, 'Return']
        portfolio_tet = df_merge[columns]
        
        # 按日期计算权重总和
        weight_sum_date = portfolio_tet.groupby(col_date, group_keys=False)[[col_weight + '_drifted']].sum()
        weight_sum_date.columns = ['Weight_sum']
        weight_sum_date.reset_index(inplace=True)
        
        # 合并权重总和
        portfolio_tet = portfolio_tet.merge(weight_sum_date, how='left', on=col_date)
        
        # 计算重新基准化的权重
        portfolio_tet['W_rebased'] = portfolio_tet[col_weight + '_drifted'] / portfolio_tet['Weight_sum']
        
        # 移位权重以计算贡献
        portfolio_tet['W_rebased_shift1'] = portfolio_tet.groupby(col_id)['W_rebased'].shift(1)
        
        # 计算贡献
        portfolio_tet['Contrib'] = portfolio_tet['W_rebased_shift1'] * portfolio_tet['Return']
        total_return_by_date = portfolio_tet.groupby(col_date)['Contrib'].sum()
        
        # 计算累计收益率 (基数 100)
        total_return_by_date.sort_index(inplace=True)
        serie_ttr = (1 + total_return_by_date.fillna(0)).cumprod() * 100
        
        return serie_ttr
    
    @staticmethod
    def create_ptf_weight(
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
        从证券列表创建投资组合权重
        
        参数:
        -----------
        sec_list : DataFrame
            证券列表
        indice_name : str
            指数/基准名称
        screen_agg : DataFrame
            筛选聚合数据
        max_weight : float
            每个证券的最大权重
        col_mkt_cap : str
            市值列名
        col_date : str
            日期列名
        col_sector : str
            行业列名
        sector_neutral : bool
            是否应用行业中性化
        method : str
            加权方法
        col_sedol : str
            SEDOL列名
        col_isin : str
            ISIN列名
            
        返回:
        --------
        DataFrame
            带权重的投资组合
        """
        screen_agg = copy.deepcopy(screen_agg)
        
        # 过滤基准相关证券
        indice = screen_agg.loc[
            screen_agg[f'Weight in {indice_name}'] > 0,
            [col_date, col_sedol, col_sector, f'Weight in {indice_name}']
        ].reset_index()
        indice.rename(columns={f'Weight in {indice_name}': 'Indice weight'}, inplace=True)
        
        indice.sort_values(by=col_date, inplace=True)
        sec_list.sort_values(by=col_date, inplace=True)
        
        # 将日期移至下月第一天
        indice[col_date] = indice[col_date] + pd.offsets.MonthBegin(1)
        screen_agg[col_date] = screen_agg[col_date] + pd.offsets.MonthBegin(1)
        
        # 将筛选列添加到证券列表
        sec_list = sec_list.merge(
            right=screen_agg.reset_index()[[col_date, col_isin, col_sedol, col_sector, col_mkt_cap]],
            on=[col_date, col_isin],
            how='left'
        )
        sec_list = sec_list[sec_list[col_sedol].notna()]
        
        # 应用加权方法
        if method == 'EW':
            sec_list.set_index(col_date, inplace=True)
            sec_list[COL_PORTFOLIO_WEIGHT] = sec_list.groupby(col_date, group_keys=False).apply(lambda x: 1 / len(x))
            sec_list.reset_index(inplace=True)
        else:
            sec_list = sec_list[sec_list[col_mkt_cap].notna()]
            sec_list = WeightManager.apply_weighting_scheme(sec_list, method, col_mkt_cap)
            sec_list.set_index(col_date, inplace=True)
            sec_list[COL_PORTFOLIO_WEIGHT] = sec_list[col_mkt_cap] / sec_list.groupby(col_date)[col_mkt_cap].sum()
            sec_list.reset_index(inplace=True)
        
        # 如果需要应用行业中性化
        if sector_neutral:
            indice.set_index(col_date, inplace=True)
            indice['Indice weight'] /= indice.groupby(col_date)['Indice weight'].sum()
            indice.reset_index(inplace=True)
            weight_secto_bench = indice.groupby([col_date, col_sector])['Indice weight'].sum().reset_index()
            
            sec_list.set_index(col_date, inplace=True)
            sec_list[COL_PORTFOLIO_WEIGHT] /= sec_list.groupby(col_date)[COL_PORTFOLIO_WEIGHT].sum()
            sec_list.reset_index(inplace=True)
            sec_list.set_index([col_date, col_sector], inplace=True)
            sec_list['weight_secto_ptf'] = sec_list.groupby([col_date, col_sector], group_keys=False)[COL_PORTFOLIO_WEIGHT].sum()
            sec_list.reset_index(inplace=True)
            
            sec_list = sec_list.merge(
                weight_secto_bench[[col_date, col_sector, 'Indice weight']],
                on=[col_date, col_sector],
                how='left'
            )
            sec_list[COL_PORTFOLIO_WEIGHT] = sec_list[COL_PORTFOLIO_WEIGHT] * (
                sec_list['Indice weight'] / sec_list['weight_secto_ptf']
            )
        
        # 处理异常值
        sec_list.set_index(col_date, inplace=True)
        sec_list[COL_PORTFOLIO_WEIGHT] /= sec_list.groupby(col_date)[COL_PORTFOLIO_WEIGHT].sum()
        sec_list[COL_PORTFOLIO_WEIGHT] = sec_list[COL_PORTFOLIO_WEIGHT].apply(lambda x: min(x, max_weight))
        sec_list[COL_PORTFOLIO_WEIGHT] /= sec_list.groupby(col_date)[COL_PORTFOLIO_WEIGHT].sum()
        sec_list.reset_index(inplace=True)
        
        return sec_list[[col_date, col_sedol, col_isin, COL_PORTFOLIO_WEIGHT, col_sector]].set_index([col_date, col_sedol])
    
    def backtest(
        self,
        sec_list: pd.DataFrame,
        screen: pd.DataFrame,
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
        ponderation: str = 'Market cap'
    ) -> Tuple[pd.Series, pd.DataFrame]:
        """
        对证券列表执行回测
        
        参数:
        -----------
        sec_list : DataFrame
            要回测的证券列表
        screen : DataFrame
            筛选聚合数据
        indice_name : str, optional
            基准名称 (用于基准回测)
        method : str, optional
            加权方法
        max_weight : float
            每个证券的最大权重
        col_sector : str
            行业列名
        col_sedol : str
            SEDOL列名
        col_isin : str
            ISIN列名
        col_date : str
            日期列名
        col_mkt_cap : str
            市值列名
        sector_neutral : bool
            是否应用行业中性化
        sec_list_ : bool
            True表示投资组合回测, False表示基准回测
        ponderation : str
            加权方案
            
        返回:
        --------
        tuple
            (业绩序列, 购买列表)
        """
        # 加载数据
        if isinstance(screen, str):
            screen_agg = pd.read_parquet(screen)
        else:
            screen_agg = copy.deepcopy(screen)
        
        if isinstance(self.returns, str):
            df_returns = pd.read_parquet(self.returns)
        else:
            df_returns = copy.deepcopy(self.returns)
        
        buy_list = copy.deepcopy(sec_list)
        
        # 对于普通投资组合 (带权重)
        if sec_list_:
            if 'Weight' in buy_list.columns:
                sec_list_full = buy_list[[col_date, col_isin, 'Weight']].copy()
                
                # 归一化权重
                sec_list_full['Weight'] = sec_list_full.groupby(col_date)['Weight'].transform(
                    lambda w: w / w.sum()
                )
                
                # 处理异常值
                sec_list_full['Weight'] = sec_list_full['Weight'].apply(lambda x: max(x, 0))
                sec_list_full['Weight'] = sec_list_full['Weight'].apply(lambda x: min(x, max_weight))
                
                # 重新归一化
                sec_list_full["WeightSum"] = sec_list_full.groupby(col_date)["Weight"].transform("sum")
                sec_list_full['Weight'] /= sec_list_full["WeightSum"]
                
                sec_list_full.reset_index(inplace=True)
                sec_list_full.rename(columns={'Weight': COL_PORTFOLIO_WEIGHT}, inplace=True)
                
                # 对齐日期
                screen_agg[col_date] = pd.to_datetime(screen_agg[col_date])
                screen_agg[col_date] = screen_agg[col_date] + pd.offsets.MonthBegin(1)
                
                # 生成最终证券列表
                sec_list_full = sec_list_full.merge(
                    right=screen_agg.reset_index()[[col_date, col_isin, col_sedol, col_sector, col_mkt_cap]],
                    on=[col_date, col_isin],
                    how='left'
                )
                sec_list_full = sec_list_full[sec_list_full[col_sedol].notna()]
                sec_list_full = sec_list_full[[col_date, col_sedol, col_isin, COL_PORTFOLIO_WEIGHT, col_sector]].set_index([col_date, col_sedol])
                
                # 计算业绩
                perf_ttr = self.calculate_portfolio_returns(
                    sec_list_full, df_returns, COL_PORTFOLIO_WEIGHT, col_sector, col_date, col_sedol
                )
                
                self.perf_ptf = perf_ttr
                self.buy_list = sec_list_full
                logger.info('Portfolio performance calculated')
            else:
                logger.error("Not a valid sec_list (missing 'Weight' column)")
        
        # 对于基准回测
        else:
            sec_list_full = self.create_ptf_weight(
                buy_list, indice_name, screen_agg, max_weight, col_mkt_cap,
                col_date, col_sector, sector_neutral, ponderation, col_sedol, col_isin
            )
            perf_ttr = self.calculate_portfolio_returns(
                sec_list_full, df_returns, COL_PORTFOLIO_WEIGHT, col_sector, col_date, col_sedol
            )
            
            self.perf_bench = perf_ttr
            logger.info('Benchmark performance calculated')
        
        return perf_ttr, self.buy_list
    
    def backtest_get_bench_perf(
        self,
        screen: pd.DataFrame,
        start_date: pd.Timestamp,
        bench: str
    ):
        """
        计算基准业绩
        
        参数:
        -----------
        screen : DataFrame
            筛选数据
        start_date : Timestamp
            开始日期
        bench : str
            基准名称
        """
        indice_ref = screen[
            (screen[COL_DATE] >= start_date) & (screen[f'Weight in {bench}'] > 0)
        ].reset_index()[[COL_DATE, COL_ISIN]]
        
        indice_ref[COL_DATE] = pd.to_datetime(indice_ref[COL_DATE])
        indice_ref[COL_DATE] = indice_ref[COL_DATE] + pd.offsets.MonthBegin(1)
        
        self.backtest(sec_list=indice_ref, screen=screen, indice_name=bench, sec_list_=False)


    @staticmethod
    def rolling_tracking_error(
        perf_ptf: pd.Series,
        perf_bench: pd.Series,
        window: int = 21,
        periods_per_year: int = 252,
    ) -> pd.Series:
        """计算组合相对 benchmark 的年化 rolling tracking error。"""
        df_plot = pd.concat([perf_ptf, perf_bench], axis=1).dropna()
        if df_plot.shape[1] != 2:
            raise ValueError("perf_ptf and perf_bench must provide exactly two aligned series")
        returns = df_plot.pct_change().dropna()
        active_return = returns.iloc[:, 0] - returns.iloc[:, 1]
        rolling_te = active_return.rolling(window=window).std() * np.sqrt(periods_per_year)
        rolling_te.name = "TE realise"
        return rolling_te

    def plot_tracking_error(
        self,
        perf_ptf: Optional[pd.Series] = None,
        perf_bench: Optional[pd.Series] = None,
        constraint_history: Optional[pd.DataFrame] = None,
        window: int = 21,
        save_path: Optional[str] = None,
        show_plot: bool = True,
    ) -> pd.DataFrame:
        """画 realized rolling TE，并在提供约束历史时同时显示 ex-ante TE。"""
        perf_ptf = self.perf_ptf if perf_ptf is None else perf_ptf
        perf_bench = self.perf_bench if perf_bench is None else perf_bench
        if perf_ptf is None or perf_bench is None:
            raise ValueError("perf_ptf and perf_bench are required before plotting tracking error")

        rolling_te = self.rolling_tracking_error(perf_ptf, perf_bench, window=window)
        result = rolling_te.to_frame()
        if constraint_history is not None and "Tracking Error" in constraint_history.columns:
            result = result.merge(
                constraint_history[["Tracking Error"]],
                left_index=True,
                right_index=True,
                how="outer",
            )
            result["Tracking Error"] = result["Tracking Error"].ffill()
            result = result.rename(columns={"Tracking Error": "TE ex-ante"})

        ax = result.plot(figsize=(12, 6), linewidth=2, title="Evolution du Tracking Error")
        ax.set_ylabel("Tracking Error")
        ax.set_ylim(bottom=0)
        fig = ax.get_figure()
        if save_path:
            fig.savefig(save_path, dpi=150, bbox_inches="tight")
        if show_plot:
            import matplotlib.pyplot as plt
            plt.show()
        else:
            import matplotlib.pyplot as plt
            plt.close(fig)
        return result

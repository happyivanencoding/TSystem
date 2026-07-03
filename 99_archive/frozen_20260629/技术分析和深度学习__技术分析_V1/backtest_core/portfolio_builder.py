"""
投资组合构建模块 - 处理证券选择和组合构建
"""

import pandas as pd
import numpy as np
import copy
import datetime
import os
from typing import Union, List, Optional, Tuple
import logging

from utils.data_utils import merge_ticker_secondaire, read_liste_noire, update_ptf_with_monthly_additions, find_next_closest_date
from utils.constants import *
from .weight_manager import WeightManager

logger = logging.getLogger(__name__)


class PortfolioBuilder:
    """
    基于因子得分和约束条件构建投资组合
    """
    
    def __init__(
        self,
        screen: Union[str, pd.DataFrame],
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
        mode_monthly_prod: bool = False,
        output_dir: Optional[str] = None,
        cap_weight_threshold: Optional[float] = None,
        financial_filter_config: Optional[dict] = None,
        use_factor_ranking: bool = True
    ):
        """
        初始化投资组合构建器
        
        参数:
        -----------
        screen : str or DataFrame
            筛选数据 (路径或DataFrame)
        bench : str
            基准名称
        percentile : float
            证券选择的百分位阈值
        metrics : str or list
            用于排名的因子指标
        ptf_name : str
            投资组合名称
        ponderation : str
            加权方案
        esg_exclusion : float
            ESG排除阈值
        cut_mkt_cap : float
            市值下限
        liste_noire : str or list, optional
            黑名单文件路径或列表
        reco_secto : list or DataFrame, optional
            行业建议
        reco_facto : list or DataFrame, optional
            因子建议
        score_neutral : str
            得分中性化级别
        weight_neutral : str
            权重中性化级别
        Top : bool
            如果为True选择顶部证券；如果为False选择底部
        top_mandatory : int, optional
            基准中包含的顶级持仓数量
        mode_monthly_prod : bool
            生产模式标志
        output_dir : str, optional
            结果输出目录
        cap_weight_threshold : float, optional
            每个证券的最大权重阈值
        financial_filter_config : dict, optional
            财务指标筛选配置
        use_factor_ranking : bool
            是否使用因子排名选股（False时为纯财务筛选模式）
        """
        # 验证输入
        if ponderation not in WEIGHTING_METHODS:
            raise ValueError(f"ponderation必须是以下之一: {WEIGHTING_METHODS}")
        
        # 存储参数
        self.bench = bench
        self.percentile = percentile
        self.cut_mkt_cap = cut_mkt_cap
        self.metrics = metrics
        self.ptf_name = ptf_name
        self.ponderation = ponderation
        self.score_neutral = score_neutral
        self.weight_neutral = weight_neutral
        self.esg_exclusion = esg_exclusion
        self._liste_noire = liste_noire
        self.top_mandatory = top_mandatory
        self.Top = Top
        self.mode_monthly_prod = mode_monthly_prod
        self.output_dir = output_dir
        self.cap_weight_threshold = cap_weight_threshold
        self.financial_filter_config = financial_filter_config
        self.use_factor_ranking = use_factor_ranking
        
        # 初始化结果容器
        self.sec_list_monthly = None
        self.sec_list_historical = None
        self.list_exclusion_monthly = None
        self.list_exclusion_histo = None
        self.start_date = None
        
        # 加载数据
        if isinstance(screen, str):
            self.screen = pd.read_pickle(screen)
        elif isinstance(screen, pd.DataFrame):
            self.screen = copy.deepcopy(screen)
        else:
            raise TypeError("screen必须是字符串或DataFrame")
        
        # 处理建议
        if reco_secto is None:
            reco_secto = [0] * 19
        if isinstance(reco_secto, (list, pd.DataFrame)):
            self.reco_secto = copy.deepcopy(reco_secto)
        else:
            raise TypeError("reco_secto必须是列表或DataFrame")
        
        if reco_facto is None:
            reco_facto = [0] * 5
        if isinstance(reco_facto, (list, pd.DataFrame)):
            self.reco_facto = copy.deepcopy(reco_facto)
        else:
            raise TypeError("reco_facto必须是列表或DataFrame")
    
    def filtrage_esg_liste_noire(self, df: pd.DataFrame, date: datetime.datetime) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Filter securities based on ESG score and blacklist.
        
        Parameters:
        -----------
        df : DataFrame
            Input securities data
        date : datetime
            Current date
            
        Returns:
        --------
        tuple
            (filtered_df, titles_excluded)
        """
        df_esg = copy.deepcopy(df)
        Worst_ESG = []
        Blacklisted = []
        
        # ESG filtering
        if date.year >= 2014 and self.esg_exclusion > 0:
            esg_pct = df[COL_ESG_SCORE].rank(pct=True)
            df_esg = df.loc[esg_pct >= self.esg_exclusion]
            Worst_ESG = df.loc[~df.index.isin(df_esg.index)].index.tolist()
        
        # Blacklist filtering
        if self._liste_noire is not None:
            if isinstance(self._liste_noire, str):
                self._liste_noire = read_liste_noire(self._liste_noire, [], [])
            
            if COL_ISIN in df_esg.columns:
                Blacklisted = df_esg[df_esg[COL_ISIN].isin(self._liste_noire)].index.tolist()
                df_esg = df_esg[~df_esg[COL_ISIN].isin(self._liste_noire)]
            elif df_esg.index.name == COL_ISIN:
                Blacklisted = df_esg[df_esg.index.isin(self._liste_noire)].index.tolist()
                df_esg = df_esg[~df_esg.index.isin(self._liste_noire)]
        
        # Save companies excluded because of ESG reason
        titles_excluded = self._save_esg_blacklist(df, Worst_ESG, Blacklisted, date)
        
        return df_esg, titles_excluded
    
    def _save_esg_blacklist(
        self,
        screen: pd.DataFrame,
        worst_esg: List[str],
        blacklisted: List[str],
        date: datetime.datetime
    ) -> pd.DataFrame:
        """Create exclusion list dataframe."""
        filtered_isins = set(worst_esg).union(set(blacklisted))
        filtered_df = screen.loc[screen.index.intersection(filtered_isins)].copy()
        
        reasons = []
        for isin in filtered_df.index:
            reason = []
            if isin in worst_esg:
                reason.append("ESG Reason")
            if isin in blacklisted:
                reason.append("Blacklisted")
            reasons.append(", ".join(reason))
        
        filtered_df["Raison Exclusion"] = reasons
        final_df = filtered_df[[COL_DATE, "Raison Exclusion"]]
        
        return final_df
    
    def adjust_bench_weight_with_recommandation(
        self,
        df: pd.DataFrame,
        reco_secto: List[float],
        date: datetime.datetime
    ) -> pd.Series:
        """Adjust benchmark sector weights with sector recommendations."""
        if self.weight_neutral == "ICB 19":
            weight_secto_bench = df.groupby(COL_SECTOR_ICB19)[f'Weight in {self.bench}'].sum() / \
                               df[f'Weight in {self.bench}'].sum()
            
            # Handle missing sectors
            icb_missing = set(range(1, 20)) - set(df[COL_SECTOR_ICB19].unique())
            if len(icb_missing) > 0:
                logger.warning(f"Missing sectors in benchmark: {list(icb_missing)}")
                try:
                    indices_to_delete = [int(icb) - 1 for icb in icb_missing]
                    reco_secto = np.delete(np.array(reco_secto), indices_to_delete)
                except Exception as e:
                    logger.error(f"Error adjusting reco_secto at {date}: {e}")
            
            # Apply recommendations
            weight_secto_bench = weight_secto_bench + np.array(reco_secto)
            
            # Adjust small weight sectors
            small_weight_mask = weight_secto_bench < 0.0025
            if small_weight_mask.any():
                logger.warning(f"Sectors with weight < 0.0025 adjusted to 0.0025")
                weight_secto_bench[small_weight_mask] = 0.0025
        
        elif self.weight_neutral == "ICB 11":
            weight_secto_bench = df.groupby(COL_SECTOR_ICB11)[f'Weight in {self.bench}'].sum() / \
                               df[f'Weight in {self.bench}'].sum()
        
        else:
            # 默认使用 ICB 19 分类，但不应用推荐调整
            weight_secto_bench = df.groupby(COL_SECTOR_ICB19)[f'Weight in {self.bench}'].sum() / \
                               df[f'Weight in {self.bench}'].sum()
            logger.info(f"weight_neutral={self.weight_neutral}, using default ICB 19 without recommendations")
        
        return weight_secto_bench
    
    def neutralise_score_by_secteur(self, df: pd.DataFrame, list_score_col: List[str]) -> pd.DataFrame:
        """
        Neutralize scores by sector using rank percentile.
        """
        df = df.copy()
        df.loc[:, list_score_col] = df[list_score_col].rank(pct=True)
        df.loc[:, list_score_col] = (df[list_score_col] - df[list_score_col].min()) / \
                                    (df[list_score_col].max() - df[list_score_col].min())
        
        if self.score_neutral == "ICB 11":
            sector_col = COL_SECTOR_ICB11
        elif self.score_neutral == "ICB 19":
            sector_col = COL_SECTOR_ICB19
        else:
            return df
        
        for secto in df[sector_col].unique():
            mask = df[sector_col] == secto
            df.loc[mask, list_score_col] = df.loc[mask, list_score_col].rank(pct=True)
            df.loc[mask, list_score_col] = (df.loc[mask, list_score_col] - df.loc[mask, list_score_col].min()) / \
                                           (df.loc[mask, list_score_col].max() - df.loc[mask, list_score_col].min())
        
        return df
    
    def get_portfolio_name(self, style: str) -> str:
        """
        Automatically select portfolio name based on investment style, benchmark, and ranking position.
        """
        if self.mode_monthly_prod:
            if self.ptf_name == "PTF TEST":
                if style not in STYLE_TO_TYPE:
                    raise ValueError(f"Style '{style}' not supported")
                
                if self.bench not in BENCH_TO_REGION:
                    raise ValueError(f"Benchmark '{self.bench}' not supported")
                
                region = BENCH_TO_REGION[self.bench]
                portfolio_type = STYLE_TO_TYPE[style]
                quintile = 'Q1' if self.Top else 'Q5'
                
                ptf_name = f"FS_{region}_{portfolio_type}_{quintile}"
                
                # Handle ESG portfolios
                if ptf_name in ['FS_EU_MF_Q1', 'FS_EU_MF_Q5'] and self.esg_exclusion > 0:
                    ptf_name = f"FS_EU_MF_ESG_{quintile}"
                
                return ptf_name
            else:
                return self.ptf_name
        else:
            return self.ptf_name
    
    def select_titles(
        self,
        group: pd.DataFrame,
        max_weight_threshold: float,
        column: str
    ) -> pd.DataFrame:
        """Select minimum number of titles per sector to respect weight constraint."""
        sector_weight = group[f'Weight in {self.bench}'].sum()
        
        if group[COL_DATE].unique()[0] >= datetime.datetime(2021, 12, 30):
            max_weight_threshold = max_weight_threshold * 100
        
        min_titles_needed = (sector_weight // max_weight_threshold) + \
                          (1 if sector_weight % max_weight_threshold != 0 else 0)
        
        selected_titles = group.nlargest(int(min_titles_needed), column)
        
        return selected_titles
    
    def save_portfolio_data_incremental(
        self,
        df_concat: pd.DataFrame,
        output_dir: str,
        date_obj: Optional[datetime.datetime] = None
    ):
        """Save portfolio data to Excel file incrementally."""
        if date_obj is None:
            date_obj = pd.to_datetime(df_concat[COL_DATE]).iloc[0]
        
        folder_name = date_obj.strftime("%B %Y")
        folder_path = os.path.join(output_dir, f"Pour {folder_name}")
        output_file = os.path.join(folder_path, "PTFS TO PUSH.xlsx")
        os.makedirs(folder_path, exist_ok=True)
        
        new_data = df_concat[['PTF', COL_ISIN, 'Weight', COL_DATE]].copy()
        
        if os.path.exists(output_file):
            try:
                existing_data = pd.read_excel(output_file)
                logger.info(f"Found existing file with {len(existing_data)} records")
                existing_data = existing_data[~existing_data['PTF'].isin(new_data['PTF'])]
                combined_data = pd.concat([existing_data, new_data], ignore_index=True, axis=0)
                combined_data = combined_data.drop_duplicates(subset=['PTF', COL_ISIN, COL_DATE], keep='last')
                logger.info(f"After combining: {len(combined_data)} records")
            except Exception as e:
                logger.error(f"Error reading existing file: {e}")
                combined_data = new_data
        else:
            logger.info("Creating new file")
            combined_data = new_data
        
        try:
            with pd.ExcelWriter(output_file, datetime_format='dd/mm/yyyy') as writer:
                combined_data.to_excel(writer, index=False)
            logger.info(f"Successfully saved {len(combined_data)} records to: {output_file}")
        except Exception as e:
            logger.error(f"Error writing to file: {e}")
            raise
    
    def sec_list_spot(
        self,
        screen_agg_monthly: Optional[pd.DataFrame] = None
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Generate best scored security list for 1 month according to chosen metrics.
        
        Parameters:
        -----------
        screen_agg_monthly : DataFrame, optional
            Monthly screen data. If None, uses last month from self.screen
            
        Returns:
        --------
        tuple
            (result_sec_list, titles_excluded)
        """
        # Determine which screen to use
        if isinstance(screen_agg_monthly, pd.DataFrame):
            screen = copy.deepcopy(screen_agg_monthly)
        else:
            screen = self.screen[self.screen[COL_DATE] == self.screen[COL_DATE].max()]
        
        # Handle metrics input
        if isinstance(self.metrics, str):
            list_score_col = [self.metrics]
        else:
            list_score_col = self.metrics
        
        # Get current date
        date = pd.to_datetime(screen[COL_DATE].max())
        
        # Remove duplicates
        if screen.index.duplicated().any():
            screen = screen[~screen.index.duplicated(keep='first')]
        
        # Merge secondary tickers
        screen = merge_ticker_secondaire(screen)
        
        # Filter for benchmark securities
        df = screen[screen[f'Weight in {self.bench}'] > 0]
        list_exclusion_bench = screen.loc[~screen.index.isin(df.index)].index.tolist()
        
        # Determine number of securities to select
        if self.percentile > 1:
            nb_securities = self.percentile
        else:
            nb_securities = round(len(df) * self.percentile)
        
        # Move to first day of next month
        date += pd.offsets.MonthBegin(1)
        
        # Handle Multi Avg Percentile (composite factor)
        if self.metrics == "Multi Avg Percentile":
            if isinstance(self.reco_facto, list):
                reco_facto = np.array(self.reco_facto)
            elif isinstance(self.reco_facto, pd.DataFrame):
                try:
                    reco_facto = self.reco_facto.loc[date]
                except:
                    logger.error(f"{date} not in reco_facto")
                    raise KeyError
            
            if reco_facto.sum() == 0:
                reco_facto = np.array([0.2] * 5)
            else:
                reco_facto = np.array(reco_facto / reco_facto.sum())
            
            list_style = ['Growth Avg Percentile', 'LowVol Avg Percentile', 
                         'Mom Avg Percentile', 'Quality Avg Percentile', 'Value Avg Percentile']
            df.loc[:, 'Multi Avg Percentile'] = df[list_style].dot(reco_facto)
        
        # Fill missing market cap values using regression
        valid_mask = pd.isna(df[COL_MKT_CAP]) == False
        fit = np.polyfit(
            df.loc[valid_mask, f'Weight in {self.bench}'],
            df.loc[valid_mask, COL_MKT_CAP],
            deg=1
        )
        func = np.poly1d(fit)
        missing_mask = pd.isna(df[COL_MKT_CAP])
        df.loc[missing_mask, COL_MKT_CAP] = func(df.loc[missing_mask, f'Weight in {self.bench}'])
        
        # Market cap cut filter
        df.loc[df[COL_MKT_CAP] <= self.cut_mkt_cap, list_score_col] = np.nan
        list_exclusion_market_cut = df[df[COL_MKT_CAP] <= self.cut_mkt_cap].index.tolist()
        
        df = df.copy()
        df.loc[:, COL_DATE] = date
        
        # Apply weighting scheme
        df = WeightManager.apply_weighting_scheme(df, self.ponderation, COL_MKT_CAP)
        
        # Get sector recommendations
        if isinstance(self.reco_secto, list):
            reco_secto = copy.deepcopy(self.reco_secto)
        elif isinstance(self.reco_secto, pd.DataFrame):
            try:
                reco_secto = self.reco_secto.loc[date].tolist()
            except:
                logger.error(f"{date} not in reco_secto")
                raise KeyError
        
        weight_secto_bench = self.adjust_bench_weight_with_recommandation(df, reco_secto, date)
        
        # Initialize exclusion dataframe (必须在任何筛选之前初始化)
        titles_excluded = pd.DataFrame(columns=[COL_DATE, "Raison Exclusion"])
        
        # 【新增】财务指标筛选
        if self.financial_filter_config is not None:
            logger.info("应用财务指标筛选...")
            from .financial_filter import FinancialFilter
            fin_filter = FinancialFilter(self.screen, self.bench, COL_SECTOR_ICB19)
            df_before = df.copy()
            df, financial_excluded = fin_filter.apply_filters(df, self.financial_filter_config)
            logger.info(f"财务筛选: {len(df_before)} -> {len(df)}")
            # 记录被排除的证券
            if not financial_excluded.empty:
                titles_excluded = pd.concat([titles_excluded, financial_excluded], axis=0)
        
        # ESG and blacklist filtering (only for top portfolios)
        if self.Top:
            df, titles_excluded = self.filtrage_esg_liste_noire(df, date)
        
        # Combine exclusions
        default_date = titles_excluded[COL_DATE].iloc[0] if not titles_excluded.empty else date
        
        # Add market cut exclusions
        new_entries_exclusion = pd.DataFrame({
            COL_DATE: [default_date] * len(list_exclusion_market_cut),
            'Raison Exclusion': ['Cut Market'] * len(list_exclusion_market_cut)
        }, index=list_exclusion_market_cut)
        titles_excluded = pd.concat([titles_excluded, new_entries_exclusion], axis=0)
        
        # Add benchmark exclusions
        new_entries_not_in_bench = pd.DataFrame({
            COL_DATE: [default_date] * len(list_exclusion_bench),
            'Raison Exclusion': ["Not in Bench"] * len(list_exclusion_bench)
        }, index=list_exclusion_bench)
        titles_excluded = pd.concat([titles_excluded, new_entries_not_in_bench], axis=0)
        
        # Neutralize scores by sector
        df = self.neutralise_score_by_secteur(df, list_score_col)
        
        df["Raison Repechage"] = ""
        
        columns = ['PTF', COL_ISIN, 'Weight', COL_DATE, "Raison Repechage"]
        result_sec_list = pd.DataFrame()
        
        # 【修改】支持纯财务模式（跳过因子排名）
        if not self.use_factor_ranking:
            logger.info("纯财务筛选模式：直接使用所有筛选后的股票")
            # 纯财务模式：使用筛选后的所有股票，不进行因子排名
            df_top = df.copy()
            df_top['Raison Repechage'] = "Financial Filter"
            
            # Sector neutralization
            temp_df = pd.DataFrame(columns=columns)
            temp_df[COL_ISIN] = df_top.index
            
            if self.weight_neutral == "ICB 19":
                temp_df['Secto'] = df_top[COL_SECTOR_ICB19].values
            elif self.weight_neutral == "ICB 11":
                temp_df['Secto'] = df_top[COL_SECTOR_ICB11].values
            else:
                temp_df['Secto'] = df_top[COL_SECTOR_ICB19].values
            
            temp_df['Weight'] = df_top[COL_MKT_CAP].values
            temp_df['Score'] = 0  # 纯财务模式没有因子得分
            temp_df[COL_DATE] = df_top[COL_DATE].values
            temp_df['Raison Repechage'] = df_top['Raison Repechage'].values
            
            # Apply sector weights
            if self.weight_neutral in ["ICB 19", "ICB 11"]:
                temp_df_sectors = set(temp_df['Secto'].unique())
                benchmark_sectors = set(weight_secto_bench.index)
                if temp_df_sectors.issubset(benchmark_sectors):
                    secto_weight_sum = temp_df.groupby('Secto')['Weight'].transform('sum')
                    secto_benchmark_weight = temp_df['Secto'].map(weight_secto_bench)
                    scaling_factor = secto_benchmark_weight / secto_weight_sum
                    temp_df['Weight'] = temp_df['Weight'] * scaling_factor
                    temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
            else:
                temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
            
            # Cap weights if necessary
            if self.cap_weight_threshold is not None:
                temp_df = WeightManager.cap_weight_by_sector(temp_df, self.cap_weight_threshold)
            
            # Assign portfolio name
            temp_df['PTF'] = self.ptf_name
            
            result_sec_list = temp_df
        else:
            # 标准模式：使用因子排名选股
            # Process each metric
            for i in range(len(list_score_col)):
                if self.Top:
                    df_top = df.nlargest(nb_securities, list_score_col[i])
                    df_top['Raison Repechage'] = list_score_col[i]
                    
                    # Add mandatory sector holdings if weight threshold is set
                    if self.cap_weight_threshold is not None:
                        df_top_sector = df.groupby(COL_SECTOR_ICB19).apply(
                            self.select_titles,
                            max_weight_threshold=self.cap_weight_threshold,
                            column=list_score_col[i]
                        )
                        df_top_sector = df_top_sector.drop(columns=[COL_SECTOR_ICB19])
                        df_top_sector = df_top_sector.reset_index(drop=False)
                        df_top_sector.index = df_top_sector[COL_ISIN]
                        df_top_sector = df_top_sector.drop(columns=[COL_ISIN])
                        df_top_sector["Raison Repechage"] = "Sector"
                        
                        df_top_combined = pd.concat([df_top, df_top_sector], axis=0)
                        df_top = df_top_combined[~df_top_combined.index.duplicated(keep='first')]
                    
                    # Add exclusions for non-selected titles
                    list_exclusion_metrics = df.loc[~df.index.isin(df_top.index)].index.tolist()
                    new_entries_exclusion = pd.DataFrame({
                        COL_DATE: [default_date] * len(list_exclusion_metrics),
                        'Raison Exclusion': [f"Bad {list_score_col[i]}"] * len(list_exclusion_metrics)
                    }, index=list_exclusion_metrics)
                    
                    titles_excluded = pd.concat([titles_excluded, new_entries_exclusion], axis=0)
                    titles_excluded.index.name = COL_ISIN
                    titles_excluded = titles_excluded.reset_index()
                else:
                    df_top = df.nsmallest(nb_securities, list_score_col[i])
                    df_top['Raison Repechage'] = "Worst Metric"
                
                # Add top mandatory holdings
                if isinstance(self.top_mandatory, (int, float)):
                    nb_top_mandatory = int(self.top_mandatory)
                    liste_top_mandatory = df.nlargest(nb_top_mandatory, f'Weight in {self.bench}')
                    liste_top_mandatory['Raison Repechage'] = "Top Obligatoire par Région"
                    
                    df_top_combined = pd.concat([liste_top_mandatory, df_top], axis=0)
                    df_top = df_top_combined[~df_top_combined.index.duplicated(keep='first')]
                
                # Sector neutralization
                temp_df = pd.DataFrame(columns=columns)
                temp_df[COL_ISIN] = df_top.index
                
                if self.weight_neutral == "ICB 19":
                    temp_df['Secto'] = df_top[COL_SECTOR_ICB19].values
                elif self.weight_neutral == "ICB 11":
                    temp_df['Secto'] = df_top[COL_SECTOR_ICB11].values
                else:
                    # 默认使用 ICB 19 分类
                    temp_df['Secto'] = df_top[COL_SECTOR_ICB19].values
                
                temp_df['Weight'] = df_top[COL_MKT_CAP].values
                temp_df['Score'] = df_top[list_score_col[i]].values
                temp_df[COL_DATE] = df_top[COL_DATE].values
                temp_df['Raison Repechage'] = df_top['Raison Repechage'].values
                
                # Security check: sectors must be subset of benchmark sectors
                temp_df_sectors = set(temp_df['Secto'].unique())
                benchmark_sectors = set(weight_secto_bench.index)
                if not temp_df_sectors.issubset(benchmark_sectors):
                    missing_sectors = temp_df_sectors.difference(benchmark_sectors)
                    raise ValueError(f"Error: Sectors {missing_sectors} not defined in weight_secto_bench")
                
                # Apply sector weights (只有在明确设置了行业中性化时才应用)
                if self.weight_neutral in ["ICB 19", "ICB 11"]:
                    secto_weight_sum = temp_df.groupby('Secto')['Weight'].transform('sum')
                    secto_benchmark_weight = temp_df['Secto'].map(weight_secto_bench)
                    scaling_factor = secto_benchmark_weight / secto_weight_sum
                    temp_df['Weight'] = temp_df['Weight'] * scaling_factor
                    temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
                else:
                    # 当权重中性化为None时，简单归一化权重使其总和为1
                    temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
            
                # Cap weights if necessary
                if self.cap_weight_threshold is not None:
                    temp_df = WeightManager.cap_weight_by_sector(temp_df, self.cap_weight_threshold)
                
                # Assign portfolio name
                temp_df['PTF'] = self.get_portfolio_name(list_score_col[i])
                
                result_sec_list = pd.concat([result_sec_list, temp_df], ignore_index=True)
        
        # Save results if output directory is specified
        if self.output_dir is not None:
            if self.mode_monthly_prod:
                self.save_portfolio_data_incremental(result_sec_list, self.output_dir)
            else:
                result_save_path = os.path.join(self.output_dir, "sec_list_result.xlsx")
                result_sec_list.to_excel(result_save_path)
                logger.info(f"Sec list generated at: {result_save_path}")
        
        self.sec_list_monthly = result_sec_list.copy(deep=True)
        self.list_exclusion_monthly = titles_excluded.copy(deep=True)
        
        return result_sec_list, titles_excluded
    
    def generic_histo_seclist(
        self,
        start_date: datetime.datetime,
        freq_rebal: Optional[int] = None,
        screen_start_date: str = "mois_impair"
    ) -> pd.DataFrame:
        """
        Generate historical security lists across multiple periods.
        
        Parameters:
        -----------
        start_date : datetime
            Starting date for the backtest
        freq_rebal : int, optional
            Rebalancing frequency in months (None for monthly)
        screen_start_date : str
            "mois_impair" (odd months), "mois_pair" (even months), or None
            
        Returns:
        --------
        DataFrame
            Historical security lists
        """
        screen_agg = copy.deepcopy(self.screen)
        if isinstance(screen_agg, str):
            screen_agg = pd.read_pickle(screen_agg)
        
        # Determine start date based on month parity
        if screen_start_date == "mois_pair":
            self.start_date = find_next_closest_date(start_date, screen_agg, 1)
        elif screen_start_date == "mois_impair":
            self.start_date = find_next_closest_date(start_date, screen_agg, 0)
        else:
            self.start_date = start_date
        
        logger.info(f"First screen_agg date: {self.start_date}")
        
        # Filter by start_date
        screen_agg = screen_agg[screen_agg[COL_DATE] >= self.start_date]
        all_dates = sorted(screen_agg[COL_DATE].unique())
        
        if not all_dates:
            return pd.DataFrame()
        
        # Determine dates to keep based on frequency
        if freq_rebal is None:
            dates_to_keep = all_dates
        else:
            dates_to_keep = all_dates[::freq_rebal]
        
        dates_to_keep = sorted(dates_to_keep)
        
        # Create subsets for each date
        screen_list = [screen_agg.loc[screen_agg[COL_DATE] == date_] for date_ in dates_to_keep]
        
        total = len(screen_list)
        
        # Try to use tqdm for progress bar
        try:
            from tqdm import tqdm
            has_tqdm = True
        except ImportError:
            has_tqdm = False
        
        if has_tqdm:
            iterator = tqdm(screen_list, desc="Generating security lists")
        else:
            iterator = screen_list
            logger.info(f"Processing {total} monthly screens...")
        
        result_sec_list = []
        result_exclusion = []
        
        # Simple progress reporting if tqdm not available
        if not has_tqdm and total > 0:
            step = max(1, total // 10)
        else:
            step = None
        
        for i, screen in enumerate(iterator):
            if step is not None:
                if i % step == 0 or i == total - 1:
                    logger.info(f"Progress: {i+1}/{total} months ({(i+1)*100/total:.0f}%)")
            
            result = self.sec_list_spot(screen_agg_monthly=screen)
            result_sec_list.append(result[0])
            result_exclusion.append(result[1])
        
        # Concatenate results
        if result_sec_list and isinstance(result_sec_list[0], pd.DataFrame):
            df = pd.concat(result_sec_list, ignore_index=True)
        else:
            df = pd.DataFrame(result_sec_list)
        
        if result_exclusion and isinstance(result_exclusion[0], pd.DataFrame):
            df_exclusion = pd.concat(result_exclusion, ignore_index=True)
        else:
            df_exclusion = pd.DataFrame(result_exclusion)
        
        # For bimonthly situations, fill gaps
        self.sec_list_historical = df.copy()
        self.sec_list_historical = update_ptf_with_monthly_additions(self.sec_list_historical)
        
        self.list_exclusion_histo = df_exclusion.copy()
        self.list_exclusion_histo = update_ptf_with_monthly_additions(self.list_exclusion_histo)
        
        logger.info("Historical sec list generated")
        logger.info("Historical exclusion list generated")
        
        return df

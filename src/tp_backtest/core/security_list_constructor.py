"""
投资组合构建模块 - 处理证券选择和组合构建
"""

import copy
import datetime
import logging
from typing import List, Optional, Tuple, Union

import pandas as pd

from tp_backtest.core.security_list_drift import SecurityDriftMixin
from tp_backtest.core.security_list_neutralization import ScoreNeutralizationMixin
from tp_backtest.core.security_list_optimizer_adapter import (
    SecurityOptimizerAdapterMixin,
)
from tp_backtest.core.security_list_persistence import SecurityPersistenceMixin
from tp_backtest.core.security_list_universe import UniverseSelectionMixin
from tp_backtest.core.security_list_weighting import SecurityWeightingMixin
from tp_backtest.utils.constants import COL_DATE, WEIGHTING_METHODS
from tp_backtest.utils.data_utils import (
    find_next_closest_date,
    update_ptf_with_monthly_additions,
)

logger = logging.getLogger(__name__)


class SecurityListConstructor(
    UniverseSelectionMixin,
    ScoreNeutralizationMixin,
    SecurityWeightingMixin,
    SecurityOptimizerAdapterMixin,
    SecurityDriftMixin,
    SecurityPersistenceMixin,
):
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
        use_factor_ranking: bool = True,
        score_pivot_esg: Optional[Union[str, float]] = None,
        score_pivot_esg_path: Optional[str] = None,
        copy_inputs: bool = False,
        monthly_base_cache: Optional[dict] = None,
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
        score_pivot_esg : str or float, optional
            ESG 绝对分数阈值，或 pivot 文件中的 sec_id 文本键
        score_pivot_esg_path : str, optional
            ESG pivot 文件根目录，仅当 score_pivot_esg 为文本键时需要
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
        self.score_pivot_esg_path = score_pivot_esg_path
        self.score_pivot_esg = self._resolve_score_pivot_esg(score_pivot_esg, score_pivot_esg_path)
        self.monthly_base_cache = monthly_base_cache
        
        # 初始化结果容器
        self.sec_list_monthly = None
        self.sec_list_historical = None
        self.list_exclusion_monthly = None
        self.list_exclusion_histo = None
        self.sec_list_optimized_monthly = None
        self.optimizer_result_monthly = None
        self.optimizer_constraint_log = pd.DataFrame()
        self.start_date = None
        self.returns: Optional[pd.DataFrame] = None
        
        # 加载数据
        if isinstance(screen, str):
            self.screen = pd.read_parquet(screen)
        elif isinstance(screen, pd.DataFrame):
            self.screen = copy.deepcopy(screen) if copy_inputs else screen
        else:
            raise TypeError("screen必须是字符串或DataFrame")

        if self.monthly_base_cache is not None:
            if not isinstance(self.monthly_base_cache, dict):
                raise TypeError("monthly_base_cache必须是字典或None")
            source_id = id(self.screen)
            if self.monthly_base_cache.get("_source_id") != source_id:
                self.monthly_base_cache.clear()
                self.monthly_base_cache["_source_id"] = source_id
        
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
    
    def build_monthly_security_list(
        self,
        screen_agg_monthly: Optional[pd.DataFrame] = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Build one monthly list through the staged portfolio service."""

        from tp_backtest.portfolio.monthly_security_list import (
            build_monthly_security_list,
        )

        return build_monthly_security_list(self, screen_agg_monthly)
    def build_historical_security_lists(
        self,
        start_date: datetime.datetime,
        freq_rebal: Optional[int] = None,
        screen_start_date: str = "mois_impair",
        fill_method: str = "drift"
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
        fill_method : str
            "drift" 使用 returns 漂移补齐缺失月份；"copy" 直接复制上月清单
            
        Returns:
        --------
        DataFrame
            Historical security lists
        """
        screen_agg = self.screen
        if isinstance(screen_agg, str):
            screen_agg = pd.read_parquet(screen_agg)
        
        # Determine start date based on month parity
        if screen_start_date == "mois_pair":
            self.start_date = find_next_closest_date(start_date, screen_agg, 1)
        elif screen_start_date == "mois_impair":
            self.start_date = find_next_closest_date(start_date, screen_agg, 0)
        else:
            self.start_date = start_date
        
        logger.info(f"First screen_agg date: {self.start_date}")
        
        # Filter by start_date
        screen_agg = screen_agg.loc[
            screen_agg[COL_DATE] >= self.start_date
        ]
        all_dates = sorted(screen_agg[COL_DATE].unique())
        
        if not all_dates:
            return pd.DataFrame()
        
        # Determine dates to keep based on frequency
        if freq_rebal is None:
            dates_to_keep = all_dates
        else:
            dates_to_keep = all_dates[::freq_rebal]
        
        dates_to_keep = sorted(dates_to_keep)
        monthly_positions = {
            pd.Timestamp(date): positions
            for date, positions in screen_agg.groupby(
                COL_DATE,
                sort=False,
                observed=True,
            ).indices.items()
        }
        
        total = len(dates_to_keep)
        
        # Try to use tqdm for progress bar
        try:
            from tqdm import tqdm
            has_tqdm = True
        except ImportError:
            has_tqdm = False
        
        if has_tqdm:
            iterator = tqdm(dates_to_keep, desc="Generating security lists")
        else:
            iterator = dates_to_keep
            logger.info(f"Processing {total} monthly screens...")
        
        result_sec_list = []
        result_exclusion = []
        
        # Simple progress reporting if tqdm not available
        if not has_tqdm and total > 0:
            step = max(1, total // 10)
        else:
            step = None
        
        for i, date_ in enumerate(iterator):
            if step is not None:
                if i % step == 0 or i == total - 1:
                    logger.info(f"Progress: {i+1}/{total} months ({(i+1)*100/total:.0f}%)")

            screen = screen_agg.iloc[monthly_positions[pd.Timestamp(date_)]]
            result = self.build_monthly_security_list(screen_agg_monthly=screen)
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
        
        # For bimonthly or lower-frequency situations, fill monthly gaps.
        self.sec_list_historical = df.copy()
        if fill_method == "drift":
            self.sec_list_historical = self.update_ptf_with_monthly_drift(self.sec_list_historical)
        elif fill_method == "copy":
            self.sec_list_historical = update_ptf_with_monthly_additions(self.sec_list_historical)
        else:
            raise ValueError("fill_method must be 'drift' or 'copy'")
        
        self.list_exclusion_histo = df_exclusion.copy()
        self.list_exclusion_histo = update_ptf_with_monthly_additions(self.list_exclusion_histo)
        
        logger.info("Historical sec list generated")
        logger.info("Historical exclusion list generated")
        
        return df

"""
投资组合构建模块 - 处理证券选择和组合构建
"""

import pandas as pd
import numpy as np
import copy
import datetime
import os
import sys
from typing import Union, List, Optional, Tuple
import logging
from pathlib import Path

from utils.data_utils import merge_ticker_secondaire, read_liste_noire, update_ptf_with_monthly_additions, find_next_closest_date
from utils.constants import *
from core.weight_manager import WeightManager
from core.esg_pivot import resolve_esg_pivot_score

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
        use_factor_ranking: bool = True,
        score_pivot_esg: Optional[Union[str, float]] = None,
        score_pivot_esg_path: Optional[str] = None
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
    
    @staticmethod
    def _resolve_score_pivot_esg(
        score_pivot_esg: Optional[Union[str, float]],
        score_pivot_esg_path: Optional[str]
    ) -> Optional[float]:
        """Resolve ESG pivot configuration to a numeric threshold when provided."""
        if score_pivot_esg is None:
            return None
        if isinstance(score_pivot_esg, (int, float)):
            return float(score_pivot_esg)
        text = str(score_pivot_esg).strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            if not score_pivot_esg_path:
                raise ValueError("score_pivot_esg_path is required when score_pivot_esg is a text pivot identifier")
            return resolve_esg_pivot_score(score_pivot_esg_path, text)
    
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
        
        # ESG filtering: absolute pivot score takes precedence over percentile exclusion.
        if date.year >= 2014 and self.score_pivot_esg is not None:
            df_esg = df.loc[pd.to_numeric(df[COL_ESG_SCORE], errors="coerce") > self.score_pivot_esg]
            Worst_ESG = df.loc[~df.index.isin(df_esg.index)].index.tolist()
        elif date.year >= 2014 and self.esg_exclusion > 0:
            esg_pct = pd.to_numeric(df[COL_ESG_SCORE], errors="coerce").rank(pct=True)
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
    
    def adjust_companies_ponderation(
        self,
        df: pd.DataFrame,
        mkt_cap_col: str = COL_MKT_CAP,
    ) -> pd.DataFrame:
        """兼容旧 PtfBuilder API：按当前 ponderation 转换 market-cap 权重基数。"""
        return WeightManager.apply_weighting_scheme(df, self.ponderation, mkt_cap_col)

    def adjust_companies_ponderation_legacy(
        self,
        df: pd.DataFrame,
        mkt_cap_col: str = COL_MKT_CAP,
    ) -> pd.DataFrame:
        """Alias for notebooks that used the legacy wording explicitly."""
        return self.adjust_companies_ponderation(df, mkt_cap_col=mkt_cap_col)

    def _prepare_market_cap_for_weighting(self, df: pd.DataFrame) -> pd.DataFrame:
        """Prepare a weighting base without making market cap mandatory for ranking."""
        df = df.copy()
        bench_weight_col = f'Weight in {self.bench}'
        
        if COL_MKT_CAP not in df.columns:
            df[COL_MKT_CAP] = np.nan
        
        df.loc[:, COL_MKT_CAP] = pd.to_numeric(df[COL_MKT_CAP], errors='coerce')
        df.loc[:, bench_weight_col] = pd.to_numeric(df[bench_weight_col], errors='coerce')
        
        if self.ponderation == "Equalweight":
            df.loc[:, COL_MKT_CAP] = 1.0
            return df
        
        missing_mask = df[COL_MKT_CAP].isna()
        valid_mask = (~missing_mask) & df[bench_weight_col].notna()
        
        if missing_mask.any() and valid_mask.sum() >= 2 and df.loc[valid_mask, bench_weight_col].nunique() >= 2:
            fit = np.polyfit(
                df.loc[valid_mask, bench_weight_col],
                df.loc[valid_mask, COL_MKT_CAP],
                deg=1,
            )
            func = np.poly1d(fit)
            df.loc[missing_mask, COL_MKT_CAP] = func(df.loc[missing_mask, bench_weight_col])
        elif missing_mask.any():
            logger.warning(
                "市值可用样本不足，使用 benchmark weight 作为权重代理: %s",
                pd.to_datetime(df[COL_DATE]).max(),
            )
            proxy = df[bench_weight_col].fillna(0).clip(lower=0)
            if proxy.sum() > 0:
                df.loc[missing_mask, COL_MKT_CAP] = proxy.loc[missing_mask] * 1_000_000.0
            else:
                df.loc[missing_mask, COL_MKT_CAP] = 1.0
        
        invalid_mask = df[COL_MKT_CAP].isna() | (df[COL_MKT_CAP] <= 0)
        if invalid_mask.any():
            proxy = df[bench_weight_col].fillna(0).clip(lower=0)
            if proxy.sum() > 0:
                df.loc[invalid_mask, COL_MKT_CAP] = proxy.loc[invalid_mask] * 1_000_000.0
            else:
                df.loc[invalid_mask, COL_MKT_CAP] = 1.0
        
        return df
    
    @staticmethod
    def _get_optimizer_engine():
        """Import the active download_09 optimizer engine without affecting normal sec-list mode."""
        tp_root = Path(__file__).resolve().parents[2]
        optimiser_root = tp_root / "06_optimiser"
        if str(optimiser_root) not in sys.path:
            sys.path.insert(0, str(optimiser_root))
        import optimizer_engine

        return optimizer_engine

    def _prepare_screen_for_optimizer(self, screen: pd.DataFrame) -> pd.DataFrame:
        """Prepare screen columns expected by the download_09 optimizer."""
        out = screen.copy()
        bench_col = f"Weight in {self.bench}"
        if bench_col in out.columns:
            out["Weight in MSCI WORLD"] = out[bench_col]
        if "Score ML" not in out.columns:
            metric = self.metrics[0] if isinstance(self.metrics, list) else self.metrics
            if metric in out.columns:
                out["Score ML"] = pd.to_numeric(out[metric], errors="coerce").rank(pct=True) * 10.0
            else:
                out["Score ML"] = 0.0
        if "Name" not in out.columns:
            out["Name"] = out.index.astype(str)
        if "Exchange Country Region" not in out.columns:
            out["Exchange Country Region"] = "Others"
        if COL_ESG_SCORE not in out.columns:
            out[COL_ESG_SCORE] = 100.0
        return out

    def _default_optimizer_params(self, current_params: Optional[dict] = None) -> dict:
        params = {
            "margin_title": 0.005,
            "margin_country": 0.03,
            "margin_sector": 0.02,
            "nb_max_titres": 120,
            "nb_min_titres": 20,
            "max_turnover": 0.30,
            "min_score_target": 0.0,
            "te_max": 0.03,
        }
        if current_params:
            params.update(current_params)
        return params

    @staticmethod
    def _default_optimizer_ub_config() -> dict:
        return {
            "North America": {"bins": [0, 0.0005, 0.001, 0.0025, 0.005, 0.01, 1], "values": [0.001, 0.002, 0.003, 0.005, 0.0075, 0.01]},
            "West Europe": {"bins": [0, 0.0005, 0.001, 0.0025, 0.005, 0.01, 1], "values": [0.001, 0.002, 0.003, 0.005, 0.0075, 0.01]},
            "Others": {"bins": [0, 0.0005, 0.001, 0.0025, 0.005, 0.01, 1], "values": [0.0005, 0.001, 0.002, 0.003, 0.005, 0.0075]},
        }

    @staticmethod
    def _default_optimizer_lb_config() -> dict:
        return {"North America": 0.0001, "West Europe": 0.0001, "Others": 0.0}

    def _build_current_optimizer_targets(self, result_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Build no-tilt sector/geo targets when no Excel sector recommendation is supplied."""
        bench_col = f"Weight in {self.bench}"
        result_df["Key_Secto_Geo"] = result_df["Secto"].astype(int).astype(str) + "_" + result_df["Exchange Country Region"].astype(str)
        df_sector_cible = (
            result_df.groupby("Key_Secto_Geo", as_index=False)[bench_col]
            .sum()
            .rename(columns={bench_col: f"Weight in {self.bench}"})
        )
        df_sector_cible["Before tilt W in MSCI WORLD"] = df_sector_cible[f"Weight in {self.bench}"]
        df_pays_cible = result_df.groupby("Exchange Country Region", as_index=False)[bench_col].sum()
        return self._ensure_optimizer_target_weight_aliases(df_sector_cible), self._ensure_optimizer_target_weight_aliases(df_pays_cible)

    def _ensure_optimizer_target_weight_aliases(self, target: pd.DataFrame) -> pd.DataFrame:
        """Keep download_09 optimizer target tables compatible with non-MSCI benchmarks."""
        out = target.copy()
        bench_col = f"Weight in {self.bench}"
        if bench_col in out.columns:
            out["Weight in MSCI WORLD"] = out[bench_col]
        if bench_col not in out.columns and "Weight in MSCI WORLD" in out.columns:
            out[bench_col] = out["Weight in MSCI WORLD"]
        return out
    def sec_list_spot_optim(
        self,
        screen_agg_monthly: Optional[pd.DataFrame] = None,
        ptf_last: Optional[pd.DataFrame] = None,
        drift: bool = True,
        init: bool = True,
        secto_reco_path: Optional[str] = None,
        current_params: Optional[dict] = None,
        scip_options: Optional[dict] = None,
        lb_title: Optional[dict] = None,
        config_ub: Optional[dict] = None,
        top_mandatory: Optional[int] = None,
        model_cov: str = "norm",
        path_output: Optional[str] = None,
        obj_func: str = "Min_TE",
        te_constraint: bool = False,
        te_threshold: float = 0.03,
        mois_rebal_europe: Optional[List[int]] = None,
        mois_rebal_us: Optional[List[int]] = None,
        alpha_score_target: float = 0.0,
    ) -> pd.DataFrame:
        """Generate an optimized sec list. Normal sec_list_spot() remains ponderation-based."""
        optimizer_engine = self._get_optimizer_engine()
        screen = self.screen[self.screen[COL_DATE] == self.screen[COL_DATE].max()] if screen_agg_monthly is None else screen_agg_monthly
        screen = self._prepare_screen_for_optimizer(screen)
        returns = self._get_returns_for_drift()
        liste_noire = []
        if self._liste_noire is not None:
            liste_noire = read_liste_noire(self._liste_noire, [], []) if isinstance(self._liste_noire, str) else list(self._liste_noire)
        if ptf_last is None:
            ptf_last = pd.DataFrame()

        result_df = optimizer_engine.generate_screen_for_optim(
            screen=screen,
            ptf_last=ptf_last,
            returns=returns,
            bench=self.bench,
            liste_noire=liste_noire,
            init=init,
            drift=drift,
        )
        bench_col = f"Weight in {self.bench}"
        if bench_col in result_df.columns:
            result_df["Weight in MSCI WORLD"] = result_df[bench_col]
        date = pd.to_datetime(result_df[COL_DATE].max())
        bool_rebal_europe, bool_rebal_us = optimizer_engine.define_bool_rebal(
            date,
            mois_rebal_europe or list(range(1, 13)),
            mois_rebal_us or list(range(1, 13)),
        )
        params = self._default_optimizer_params(current_params)
        params["min_score_target"] = params.get("min_score_target", 0.0) + alpha_score_target

        if secto_reco_path:
            df_sector_cible, df_pays_cible, result_df = optimizer_engine.define_secto_target_and_geo_target2(
                secto_reco_path=secto_reco_path,
                df=result_df,
                date=date,
                bench=self.bench,
                bool_rebal_Europe=bool_rebal_europe,
                bool_rebal_US=bool_rebal_us,
            )
        else:
            df_sector_cible, df_pays_cible = self._build_current_optimizer_targets(result_df)

        result_df = optimizer_engine.define_lb_ub(
            df_full=result_df,
            lb_title=lb_title or self._default_optimizer_lb_config(),
            CONFIG_UB=config_ub or self._default_optimizer_ub_config(),
            bench_4_ub=self.bench,
            margin_title=params["margin_title"],
            top_mandatory=top_mandatory or self.top_mandatory or 5,
            bool_rebal_Europe=bool_rebal_europe,
            bool_rebal_US=bool_rebal_us,
        )
        prob_secto_add, prob_pays_add = optimizer_engine.verifier_contraintes(
            result_df,
            params["margin_country"],
            params["margin_sector"],
            df_sector_cible,
            df_pays_cible,
            name_col=bench_col,
        )
        while len(prob_secto_add + prob_pays_add) > 0:
            eligible_before = len(result_df[result_df["ub"] > 0.0010])
            result_df = optimizer_engine.selection_repechage(
                result_df,
                prob_secto_add,
                prob_pays_add,
                self.bench,
                config_ub or self._default_optimizer_ub_config(),
                lb_title or self._default_optimizer_lb_config(),
            )
            prob_secto_add, prob_pays_add = optimizer_engine.verifier_contraintes(
                result_df,
                params["margin_country"],
                params["margin_sector"],
                df_sector_cible,
                df_pays_cible,
                name_col=bench_col,
            )
            if eligible_before == len(result_df[result_df["ub"] > 0.0010]):
                break

        df_sector_tmp = df_sector_cible.rename(columns={bench_col: "PoidsSectGeo"})
        if "Before tilt W in MSCI WORLD" in df_sector_tmp.columns:
            result_df = result_df.merge(df_sector_tmp[["Key_Secto_Geo", "PoidsSectGeo", "Before tilt W in MSCI WORLD"]], how="left", on="Key_Secto_Geo")
        if "PoidsSectGeo" in result_df.columns:
            zero_target_mask = result_df["PoidsSectGeo"] == 0
            result_df.loc[zero_target_mask, "lb"] = 0
            result_df.loc[zero_target_mask, "ub"] = 10e-6

        sigma = optimizer_engine.generate_covariance_matrix(result_df, returns, model_cov)
        result_df, state = optimizer_engine.optimize(
            result_df,
            sigma,
            df_sector_cible,
            df_pays_cible,
            self.bench,
            params,
            init,
            scip_options or {},
            bool_rebal_europe,
            bool_rebal_us,
            path_output=path_output,
            obj_func=obj_func,
            TE_constraint=te_constraint,
            te_threshold=te_threshold,
        )
        if state not in ["optimal", "optimal_inaccurate"]:
            raise RuntimeError(f"Optimizer failed with status: {state}")

        result_df2, rapport_pays, rapport_secto = optimizer_engine.generate_exposure_reports(result_df, df_pays_cible, df_sector_cible)
        if bench_col not in result_df2.columns and "Weight in MSCI WORLD" in result_df2.columns:
            result_df2[bench_col] = result_df2["Weight in MSCI WORLD"]
        self.optimizer_constraint_log = optimizer_engine.log_constraints(
            self.optimizer_constraint_log,
            result_df2,
            date,
            rapport_secto,
            rapport_pays,
            params,
            sigma,
            self.bench,
        )
        optimized = result_df2.rename(columns={"Wopt": "Weight"})
        optimized = optimized[optimized["Weight"] > 0.0001].copy()
        optimized["PTF"] = f"{self.ptf_name} OPTIM"
        columns = [
            "PTF", "Name", COL_ISIN, COL_SEDOL, "Weight", "Exchange Country Region",
            "Key_Secto_Geo", COL_DATE, "Secto", "Score ML", "Raison Exclusion",
            "lb", "ub", "Weight_last_drift",
        ]
        columns = [column for column in columns if column in optimized.columns]
        result_sec_list = optimized[columns].copy()
        self.optimizer_result_monthly = result_df.copy()
        self.sec_list_optimized_monthly = result_sec_list.copy(deep=True)
        return result_sec_list

    def _get_returns_for_drift(self) -> pd.DataFrame:
        """Return a clean returns matrix required by monthly drift filling."""
        if self.returns is None:
            raise ValueError("fill_method='drift' requires returns data on PortfolioBuilder")
        if isinstance(self.returns, str):
            returns = pd.read_parquet(self.returns)
        else:
            returns = copy.deepcopy(self.returns)
        if not isinstance(returns.index, pd.DatetimeIndex):
            returns.index = pd.to_datetime(returns.index, errors="coerce")
        returns = returns[returns.index.notna()].sort_index()
        return returns

    def _attach_sedol_for_drift(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
        """Attach a temporary SEDOL column to a security list for returns lookup."""
        ptf = df.copy()
        temp_col = "__drift_sedol"
        if COL_SEDOL in ptf.columns:
            ptf[temp_col] = ptf[COL_SEDOL]
            return ptf, temp_col
        if COL_ISIN not in ptf.columns:
            raise KeyError(f"{COL_ISIN} column is required for drift filling")

        screen = self.screen.copy()
        if screen.index.name == COL_ISIN or COL_ISIN not in screen.columns:
            screen = screen.reset_index()
        if COL_ISIN not in screen.columns or COL_SEDOL not in screen.columns:
            raise KeyError(f"screen must contain {COL_ISIN} and {COL_SEDOL} for drift filling")

        sedol_map = (
            screen[[COL_ISIN, COL_SEDOL]]
            .dropna(subset=[COL_ISIN, COL_SEDOL])
            .drop_duplicates(subset=[COL_ISIN], keep="last")
            .set_index(COL_ISIN)[COL_SEDOL]
        )
        ptf[temp_col] = ptf[COL_ISIN].map(sedol_map)
        missing_count = int(ptf[temp_col].isna().sum())
        if missing_count:
            logger.warning("%s securities have no SEDOL mapping for monthly drift", missing_count)
        return ptf, temp_col

    def drift_weight(
        self,
        df_rebal: pd.DataFrame,
        date_fin_drifter: pd.Timestamp,
        col_id: str = COL_SEDOL,
        col_weight: str = "Weight",
        col_date: str = COL_DATE,
    ) -> pd.DataFrame:
        """Drift one rebalance slice to a target month using the returns matrix."""
        if df_rebal.empty:
            return df_rebal.copy()

        returns = self._get_returns_for_drift()
        result = df_rebal.copy()
        result[col_date] = pd.to_datetime(result[col_date])
        start_date = pd.to_datetime(result[col_date].min())
        end_date = pd.to_datetime(date_fin_drifter)
        result[col_date] = end_date

        if col_id not in result.columns:
            raise KeyError(f"{col_id} column is required for drift filling")

        ids = result[col_id].dropna().unique().tolist()
        available_ids = [identifier for identifier in ids if identifier in returns.columns]
        if not available_ids:
            logger.warning("No selected securities were found in returns for drift ending %s", end_date.date())
            total = pd.to_numeric(result[col_weight], errors="coerce").fillna(0).sum()
            if total != 0:
                result[col_weight] = pd.to_numeric(result[col_weight], errors="coerce").fillna(0) / total
            return result

        valid_dates = returns.index[(returns.index >= start_date) & (returns.index <= end_date)]
        if valid_dates.empty:
            logger.warning("No returns dates available between %s and %s for monthly drift", start_date.date(), end_date.date())
            total = pd.to_numeric(result[col_weight], errors="coerce").fillna(0).sum()
            if total != 0:
                result[col_weight] = pd.to_numeric(result[col_weight], errors="coerce").fillna(0) / total
            return result

        start_return_date = valid_dates.min()
        end_return_date = valid_dates.max()
        returns_slice = returns.loc[start_return_date:end_return_date, available_ids]
        returns_slice = returns_slice.apply(pd.to_numeric, errors="coerce").fillna(0)
        returns_cum = (1 + returns_slice).cumprod()
        base = returns_cum.iloc[0].replace(0, np.nan)
        multiplier = (returns_cum.iloc[-1] / base).replace([np.inf, -np.inf], np.nan).fillna(1.0)

        result["drift_multiplicator"] = result[col_id].map(multiplier).fillna(1.0)
        missing_returns = result[col_id].notna() & ~result[col_id].isin(available_ids)
        if missing_returns.any():
            logger.warning("%s selected securities have no returns column for monthly drift", int(missing_returns.sum()))

        result[col_weight] = pd.to_numeric(result[col_weight], errors="coerce").fillna(0) * result["drift_multiplicator"]
        total = result[col_weight].sum()
        if total != 0:
            result[col_weight] = result[col_weight] / total
        result.drop(columns=["drift_multiplicator"], inplace=True)
        return result

    def update_ptf_with_monthly_drift(
        self,
        df: pd.DataFrame,
        today: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        """Fill missing monthly security-list dates with return-drifted weights."""
        if df.empty:
            return df.copy()

        ptf, sedol_col = self._attach_sedol_for_drift(df)
        ptf[COL_DATE] = pd.to_datetime(ptf[COL_DATE])
        today_ts = pd.Timestamp.now().normalize() if today is None else pd.to_datetime(today)
        existing_dates = {pd.Timestamp(date) for date in pd.to_datetime(ptf[COL_DATE].dropna().unique())}

        for initial_date in sorted(existing_dates):
            current_date = pd.Timestamp(initial_date)
            next_month = current_date + pd.DateOffset(months=1)
            while next_month <= today_ts and pd.Timestamp(next_month) not in existing_dates:
                prev_ptf = ptf[ptf[COL_DATE] == current_date].copy()
                if prev_ptf.empty:
                    break
                drifted_ptf = self.drift_weight(
                    prev_ptf,
                    next_month,
                    col_id=sedol_col,
                    col_weight="Weight",
                    col_date=COL_DATE,
                )
                ptf = pd.concat([ptf, drifted_ptf], ignore_index=True).sort_values(COL_DATE).reset_index(drop=True)
                existing_dates.add(pd.Timestamp(next_month))
                current_date = pd.Timestamp(next_month)
                next_month = current_date + pd.DateOffset(months=1)

        if sedol_col in ptf.columns and sedol_col == "__drift_sedol":
            ptf.drop(columns=[sedol_col], inplace=True)
        return ptf

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
        screen = merge_ticker_secondaire(screen, self.bench)
        
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
        
        # Market cap is a weighting input, not a ranking requirement.
        df = self._prepare_market_cap_for_weighting(df)
        
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
            from core.financial_filter import FinancialFilter
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
        screen_agg = copy.deepcopy(self.screen)
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








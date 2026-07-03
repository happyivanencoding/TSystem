"""
BacktestEngine.py
=================

组织架构说明
------------
本文件实现了一个“选股 + 组合构建 + 历史回测 + 可视化”的一体化多因子回测引擎，
主要用于基于月度股票筛选结果生成组合，并结合日频收益率数据计算组合净值表现。

整体组织架构分为 4 层：

1. 数据准备层
   - 负责读取和整理黑名单、证券基础信息、收益率、基准权重等输入数据。
   - 典型输入包括：
     * screen：月度证券池 / 打分表 / benchmark 暴露信息
     * returns：日频收益率矩阵
     * bench：基准名称，如 MSCI US、SP500、STOXX EUROPE 600 等
   - 相关函数：
     * read_liste_noire()
     * merge_weight_by_pairs()
     * merge_ticker_secondaire()

2. 组合构建层
   - 负责根据风格因子、ESG 规则、黑名单、行业中性约束、市值权重规则等，
     在每个调仓时点生成证券列表（sec list）及其组合权重。
   - 核心逻辑包括：
     * 市值口径修正与补全
     * 次级 ticker 合并
     * ESG / blacklist 过滤
     * 因子分数行业中性化
     * 行业推荐权重调整
     * 单票权重上限控制
   - 核心类与方法：
     * PtfBuilder
     * fix_companies_ponderation()
     * filtrage_esg_liste_noire()
     * adjust_bench_weight_with_recommandation()
     * neutralise_score_by_secteur()
     * sec_list_spot()

3. 历史回测层
   - 负责将月度调仓结果扩展到历史区间，映射到日频收益率数据，
     计算每日漂移权重、收益贡献及累计净值。
   - 支持：
     * 单期证券列表回测
     * 多期历史证券列表批量生成
     * 基准组合回测
   - 核心方法：
     * generic_histo_seclist()
     * update_ptf_with_monthly_additions()
     * backtest_create_ptf_weight()
     * backtest_calcul_all_portfolio()
     * backtest()
     * backtest_get_bench_perf()

4. 输出与可视化层
   - 负责导出证券列表、排除名单、增量保存组合结果，并绘制组合与基准的业绩曲线。
   - 核心方法：
     * save_portfolio_data_incremental()
     * save_esg_blacklist()
     * backtest_plot_ptf_bench()

引擎说明
--------
本引擎的目标是：从月度股票池出发，结合风格因子、ESG 约束、黑名单和行业中性规则，
构建可投资组合，并使用日频收益率对组合进行历史回测。

核心流程如下：

A. 输入数据
   - screen：包含证券标识、日期、因子分数、行业分类、benchmark 权重、市值等信息
   - returns：日频收益率数据，列通常为证券标识（如 SEDOL）
   - bench：用于定义基准权重与行业中性参考
   - metrics：用于选股的单因子或多因子评分列

B. 单期选股与建仓
   - 在给定月份内，从 screen 中筛出属于 benchmark 的可投资证券
   - 根据市值门槛、ESG 排除、黑名单规则等进行过滤
   - 对指定因子进行行业中性化处理
   - 根据 percentile / Top / reco_secto / reco_facto 等参数生成目标证券列表
   - 根据市值、开方、立方根、对数或等权方式生成组合初始权重

C. 历史扩展
   - 对多个调仓月重复执行单期选股逻辑，生成历史 sec_list
   - 必要时自动补齐缺失月份，使组合持仓在回测区间内连续

D. 回测计算
   - 将月度权重映射到日频收益率
   - 在调仓日之间使用 drift 机制更新持仓权重
   - 按上一日权重乘以当日收益的方式计算组合每日贡献
   - 最终累积得到组合净值序列

E. 结果输出
   - 输出月度证券列表、排除名单、组合净值、基准净值
   - 支持将结果保存到 Excel
   - 支持用 Plotly 绘制组合与基准的表现对比图

核心对象说明
------------
PtfBuilder 是本文件的主类，承担以下职责：
- 保存回测参数与输入数据
- 生成单期 / 历史证券列表
- 构建组合权重
- 计算组合与基准表现
- 输出结果和图表

使用者通常只需要：
1. 初始化 PtfBuilder
2. 调用 generic_histo_seclist() 生成历史证券列表
3. 调用 backtest() 计算组合表现
4. 调用 backtest_get_bench_perf() 和 backtest_plot_ptf_bench() 做基准比较与展示

适用场景
--------
- 多因子股票策略回测
- 行业中性 / 风格偏离控制组合
- 带 ESG 过滤和黑名单约束的策略研究
- 月度调仓、日频收益归因式净值计算
- 研究组合与 benchmark 的相对表现

注意事项
--------
- screen 和 returns 的字段名需要与本引擎内部逻辑保持一致
- benchmark 权重列、行业列、证券标识列必须完整
- 若存在双上市 / 双 ticker 证券，需要通过 merge_ticker_secondaire() 合并处理
- 若使用 ESG 过滤，请确保 ESG score 与 blacklist 数据可用
- 回测结果依赖输入数据质量，尤其是调仓日期与收益率日期的映射关系

版本建议
--------
当前版本适合作为研究型回测引擎使用。
如果后续要进一步工程化，建议继续补充：
- 类型注解（type hints）
- 日志系统（logging）
- 参数校验
- 自定义异常类
- 单元测试
- 配置文件化（yaml / json）
- 性能分析与并行优化
"""



import numpy as np
import pandas as pd
import scipy
import datetime
import os
import copy
import math
# from scipy import stats
from multiprocessing import Pool
from dateutil.relativedelta import relativedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import warnings
warnings.filterwarnings('ignore')

def  read_liste_noire(file_list_noire, override_exclusion=[], override_inclusion=[], key="ISIN", exclu_type=["ex_all"]):
    """
    exclu_type = ["ex_all"] or ["ex_all", "Controverse"]
    """
    liste_noire = pd.read_excel(file_list_noire)

    # Filtrer les lignes où au moins une des colonnes de exclu_type vaut 1
    filtre = liste_noire[exclu_type].fillna(0).astype(int).any(axis=1)
    liste_noire = liste_noire[filtre]

    liste_noire = liste_noire.dropna(subset=key)[key].tolist()
    liste_noire_tot = np.concatenate([liste_noire,np.array(override_exclusion)])
    liste_noire_unique = np.unique(liste_noire_tot)
    liste_noire_finale = list(set(liste_noire_unique) - set(override_inclusion))
    return liste_noire_finale

def merge_weight_by_pairs(df: pd.DataFrame,
                        pairs,
                        weight_col='Weight in MSCI WORLD',
                        drop_second=True): 

    # Ensure "ISIN" is the index of df
    if df.index.name != "ISIN" and "ISIN" in df.columns:
        df.set_index("ISIN", inplace=True)

    # Ensure the weight column is numeric (coerce errors to NaN)
    if weight_col not in df.columns:
        raise KeyError(f"Column '{weight_col}' not found in DataFrame.")

    for keep, drop in pairs:
        has_keep = keep in df.index
        has_drop = drop in df.index

        if has_keep and has_drop: # Only when entreprisese existent dans le screen
            w_keep = df.at[keep, weight_col]
            w_drop = df.at[drop, weight_col] # same as loc but only for one value

            df.at[keep, weight_col] = w_keep + w_drop

            if drop_second:
                # errors='ignore' avoids exceptions if it was dropped elsewhere
                df.drop(index=drop, inplace=True, errors='ignore')
    return df

def add_country_group(df,
                      bench,
                      country_col='Exchange Country Name',
                      top_n=3,
                      new_col='Country Group'):
    """按基准权重保留 top_n 个国家，其余归为 Others（EM 分散国别用）。"""
    weight_col = 'Weight in ' + bench
    if weight_col not in df.columns:
        raise KeyError(f"缺少列 {weight_col}")
    if country_col not in df.columns:
        raise KeyError(f"缺少列 {country_col}")
    top_countries = (
        df.groupby(country_col)[weight_col]
          .sum()
          .nlargest(top_n)
          .index
          .tolist()
    )
    df = df.copy()
    df[new_col] = df[country_col].where(df[country_col].isin(top_countries), other='Others')
    return df

def _renormalize_bench_targets_for_subset(temp_df, bench_series, group_col):
    """仅在 temp_df 中出现的组上保留基准权重并归一化为 1（避免子集与全样本边际不可行）。"""
    if not isinstance(bench_series, pd.Series):
        bench_series = pd.Series(bench_series)
    present = temp_df[group_col].dropna().unique()
    sub = bench_series.reindex(present).fillna(0.0)
    total = float(sub.sum())
    if total <= 1e-12:
        # 无基准信息时在出现的组上均匀
        if len(present) == 0:
            return {}
        u = 1.0 / len(present)
        return {g: u for g in present}
    return {g: float(sub[g]) / total for g in present}


def optimize_weights(df, target_secto, target_country, max_weight=0.15, objective="min_mvt", margin=0.05):
    """行业+国家约束下的凸优化权重；需安装 cvxpy。若联合约束不可行则自动降级（仅行业 → 仅盒约束）。"""
    try:
        import cvxpy as cp
    except ImportError:
        raise ImportError("country_sector_optimize 需要安装 cvxpy（pip install cvxpy）") from None

    df = df.copy()
    if len(df) == 0:
        return df

    w_cap = float(df["Weight"].max())
    df["Weight"] = df["Weight"] / df["Weight"].sum()

    nan_count = df["Score"].isna().sum()
    if nan_count >= 1:
        score_mean = df["Score"].mean()
        df["Score"] = df["Score"].fillna(score_mean)

    df["Weight"] = df["Weight"] / df["Weight"].sum()

    n = len(df)
    w0 = df["Weight"].values
    initial_scores = df["Score"].values

    ts_sub = _renormalize_bench_targets_for_subset(df, target_secto, "Secto")
    tc_sub = _renormalize_bench_targets_for_subset(df, target_country, "Country Group")

    per_stock_cap = max(w_cap + 0.02, 1.0 / max(n, 1))

    if objective == "min_mvt":
        def build_obj(w):
            return cp.Minimize(cp.sum_squares(w - w0))
    elif objective == "max_score":
        def build_obj(w):
            return cp.Maximize(cp.sum(cp.multiply(w, initial_scores)))
    else:
        raise ValueError(f"objective 应为 min_mvt 或 max_score，收到: {objective}")

    def sector_country_constraints(w, ts, tc, m):
        c = [cp.sum(w) == 1, w >= 0, w <= per_stock_cap]
        for s, target in ts.items():
            idx = (df["Secto"] == s).to_numpy()
            if not np.any(idx) or target <= 1e-12:
                continue
            c.append(cp.sum(w[idx]) >= target * (1 - m))
            c.append(cp.sum(w[idx]) <= target * (1 + m))
        for grp, target in tc.items():
            idx = (df["Country Group"] == grp).to_numpy()
            if not np.any(idx) or target <= 1e-12:
                continue
            c.append(cp.sum(w[idx]) >= target * (1 - m))
            c.append(cp.sum(w[idx]) <= target * (1 + m))
        return c

    def sector_only_constraints(w, ts, m):
        c = [cp.sum(w) == 1, w >= 0, w <= per_stock_cap]
        for s, target in ts.items():
            idx = (df["Secto"] == s).to_numpy()
            if not np.any(idx) or target <= 1e-12:
                continue
            c.append(cp.sum(w[idx]) >= target * (1 - m))
            c.append(cp.sum(w[idx]) <= target * (1 + m))
        return c

    def box_only_constraints(w):
        return [cp.sum(w) == 1, w >= 0, w <= per_stock_cap]

    attempts = [
        ("sector+country", lambda wv: sector_country_constraints(wv, ts_sub, tc_sub, margin)),
        ("sector+country宽松", lambda wv: sector_country_constraints(wv, ts_sub, tc_sub, min(0.35, margin * 3))),
        ("仅行业", lambda wv: sector_only_constraints(wv, ts_sub, margin)),
        ("仅行业宽松", lambda wv: sector_only_constraints(wv, ts_sub, min(0.35, margin * 3))),
        ("仅盒约束", lambda wv: box_only_constraints(wv)),
    ]

    last_status = None
    for name, mkcon in attempts:
        w = cp.Variable(n)
        cons = mkcon(w)
        obj = build_obj(w)
        prob = cp.Problem(obj, cons)
        try:
            prob.solve(solver=cp.OSQP if objective == "min_mvt" else cp.SCS)
        except Exception:
            prob.solve()

        last_status = prob.status
        if prob.status in ["optimal", "optimal_inaccurate"]:
            out = df.copy()
            out["Weight"] = w.value
            return out

    raise RuntimeError(
        f"组合优化未收敛: status={last_status}（已尝试：行业+国家 → 放宽 → 仅行业 → 盒约束）"
    )

def merge_ticker_secondaire(df, bench='MSCI WORLD'):
        """合并双上市 ISIN；权重列名为 Weight in <bench>。"""
        isin_pairs = [
                        "US02079K3059", # Google
                        "US02079K1079",

                        "DK0010244508", # A.P. Moller
                        "DK0010244425", 
                        
                        "SE0017486889", # Atlas Copco
                        "SE0017486897",

                        "DE0005190003", # Bayerische Motoren Werke
                        "DE0005190037",

                        "SE0015658109", # Epiroc
                        "SE0015658117",

                        "CH0012032048",
                        "CH0012032113", # Roche Holding

                        "CH0024638196",
                        "CH0024638212", # Schindler


                        "CH0010570767", # Lindt
                        "CH0010570759",

                        "DE0006048432", # Henkel
                        "DE0006048408",

                        "SE0000107203", # Industrivarden
                        "SE0000190126"
                ]

        # Convert to list of (keep, drop) pairs in order
        if len(isin_pairs) % 2 != 0:
                raise ValueError("The ISIN list length must be even (pairs of 2).")

        pairs = list(zip(isin_pairs[::2], isin_pairs[1::2]))

        df = merge_weight_by_pairs(
                        df=df,
                        pairs=pairs,
                        weight_col='Weight in ' + bench,
                        drop_second=True    # drop the second ISIN after merging
                        )
        return df

class PtfBuilder:
    @staticmethod
    def _normalize_screen_columns(screen):
        if not isinstance(screen, pd.DataFrame):
            return screen

        canonical_col = 'Benchmark Market Value Millions in EUR'
        legacy_col = 'Benchmark Market Value Millions in EUR '
        backup_col = 'Benchmark Market Value Millions in EUR BK'

        if legacy_col in screen.columns and canonical_col not in screen.columns:
            screen = screen.rename(columns={legacy_col: canonical_col})

        if canonical_col not in screen.columns:
            screen[canonical_col] = np.nan

        if legacy_col in screen.columns:
            screen[canonical_col] = screen[canonical_col].fillna(screen[legacy_col])

        if backup_col in screen.columns:
            screen[canonical_col] = screen[canonical_col].fillna(screen[backup_col])

        return screen

    @staticmethod
    def _scale_score_frame(score_df):
        ranked = score_df.rank(pct=True)
        min_vals = ranked.min()
        max_vals = ranked.max()
        denom = (max_vals - min_vals).replace(0, np.nan)
        return ranked.subtract(min_vals).div(denom)

    @staticmethod
    def _normalize_group_token(token):
        return str(token).strip().casefold().replace("_", " ").replace("-", " ")

    def _resolve_group_columns(self, group_spec):
        if group_spec in [None, False]:
            return []

        if isinstance(group_spec, (list, tuple)):
            raw_tokens = list(group_spec)
        elif isinstance(group_spec, str):
            if "+" in group_spec:
                raw_tokens = [part.strip() for part in group_spec.split("+") if part.strip()]
            else:
                raw_tokens = [group_spec]
        else:
            raise ValueError(f"Unsupported group spec: {group_spec}")

        alias_map = {
            "icb 11": " Benchmark ICB Industry ",
            "icb11": " Benchmark ICB Industry ",
            "industry": " Benchmark ICB Industry ",
            "benchmark icb industry": " Benchmark ICB Industry ",
            "icb 19": " Benchmark ICB Supersector ",
            "icb19": " Benchmark ICB Supersector ",
            "supersector": " Benchmark ICB Supersector ",
            "benchmark icb supersector": " Benchmark ICB Supersector ",
        }

        resolved = []
        for token in raw_tokens:
            normalized = self._normalize_group_token(token)
            column = alias_map.get(normalized, token)
            if column not in resolved:
                resolved.append(column)

        return resolved

    def _prepare_group_column(self, df, group_spec, output_col):
        group_cols = self._resolve_group_columns(group_spec)
        if not group_cols:
            return df.copy(), None

        missing_cols = [col for col in group_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Missing group columns for spec '{group_spec}': {missing_cols}")

        df = df.copy()
        if len(group_cols) == 1:
            return df, group_cols[0]

        # 联合分组时在运行时拼出临时键，避免修改原始表结构。
        df[output_col] = (
            df[group_cols]
            .fillna("Missing")
            .astype(str)
            .agg(" | ".join, axis=1)
        )
        return df, output_col

    def __init__(self,
                screen, 
                returns, 
                bench, 
                percentile, 
                metrics, 
                ptf_name = "PTF TEST", 
                ponderation='Racine cube',
                esg_exclusion=0.2,
                cut_mkt_cap=0,
                liste_noire=r"\\groupe-ufg.com\commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_BASE\_ ESG DATA\Liste_Noire_Exclusion.xlsx",
                reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
                reco_facto = [0,0,0,0,0],
                score_neutral="ICB 19", 
                weight_neutral="ICB 19",
                Top=True,
                top_mandatory = None, 
                multiprocessing=False,
                mode_monthly_prod=False, 
                output_dir=None,
                cap_weight_threshold=None,
                country_sector_optimize=False,
                country_group_top_n=3,
                country_col='Exchange Country Name',
                top_mandatory_by_country=False,
                optimize_objective="min_mvt",
                optimize_margin=0.05):
        """
        initialisation des paramètres de la classe 

        order for "reco_secto" :
            1: "Auto & Parts",  
            2: "Banks",  
            3: "Basic Resources",  
            4: "Chemicals",  
            5: "Construction",  
            6: "Financial Services",  
            7: "Food, Beverage & Tobacco",  
            8: "Health Care",  
            9: "Industrial Goods & Services",  
            10: "Insurance",  
            11: "Media",  
            12: "Energy",  
            13: "Personal & Household Goods",  
            14: "Real Estate",  
            15: "Retail",  
            16: "Technology",  
            17: "Telecommunications",  
            18: "Travel & Leisure",  
            19: "Utilities"  
        
        order for "reco_facto" :
            1: "Growth",
            2: "Low Vol",
            3: "Momentum",
            4: "Quality",
            5: "Value"

        """
        if ponderation not in ["Racine cube","Racine carrée", "Market cap","Log","Equalweight"]:
            print(" ponderation must be Racine cube, Racine carrée, Market cap, Log or Equalweight")
        else:
            self.ponderation=ponderation

        self.bench=bench
        self.percentile=percentile
        self.cut_mkt_cap=cut_mkt_cap
        self.metrics=metrics
        self.ptf_name=ptf_name
        self.score_neutral=score_neutral
        self.weight_neutral=weight_neutral
        self.esg_exclusion=esg_exclusion
        self._liste_noire=liste_noire
        self.top_mandatory=top_mandatory
        self.multiprocessing=multiprocessing
        self.sec_list_monthly=None
        self.sec_list_historical=None
        self.list_exclusion_monthly =None
        self.list_exclusion_histo=None
        self.perf_ptf=None
        self.perf_bench=None
        self.buy_list=None
        self.Top = Top
        self.mode_monthly_prod = mode_monthly_prod
        self.output_dir = output_dir
        self.cap_weight_threshold = cap_weight_threshold
        self.country_sector_optimize = country_sector_optimize
        self.country_group_top_n = country_group_top_n
        self.country_col = country_col
        self.top_mandatory_by_country = top_mandatory_by_country
        self.optimize_objective = optimize_objective
        self.optimize_margin = optimize_margin

        if type(screen) not in [str,type(pd.DataFrame())]:
            print("screen must be string or DataFrame")
        else:
            self.screen=copy.deepcopy(screen)
            self.screen=self._normalize_screen_columns(self.screen)

        if type(returns) !=type(pd.DataFrame()):
            print("returns must be DataFrame")
        else:
            self.returns=copy.deepcopy(returns)

        if type(reco_secto) not in [str, list, type(pd.DataFrame())]:
            print("reco_secto must be list or DataFrame")
        else:
            self.reco_secto=copy.deepcopy(reco_secto)

        if type(reco_facto) not in [str, list, type(pd.DataFrame())]:
            print("reco_facto must be list or DataFrame")
        else:
            self.reco_facto=copy.deepcopy(reco_facto)


    def fix_companies_ponderation(self,df):
        """
        pondération des Benchmarck Market Value pour réduire les effets de taille
        
        """
        df = df.copy()

        if self.ponderation == "Racine cube":
            df.loc[:, 'Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
        elif self.ponderation == "Racine carrée":
            df.loc[:, 'Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
        elif self.ponderation == "Market cap":
            df.loc[:, 'Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']
        elif self.ponderation == "Log":
            df.loc[:, 'Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
        elif self.ponderation == "Equalweight":
            df['Benchmark Market Value Millions in EUR'] = 1/len(df)

        return df
    
    def filtrage_esg_liste_noire(self, df, date):
        """
        Filtrage en fonction des performances ESG et de la liste noire.
        Retourne le DataFrame filtré, la liste des exclusions ESG, et la liste noire.
        """
        import copy
        df_esg = copy.deepcopy(df)
        Worst_ESG = []
        Blacklisted = []

        # ESG filtering
        if date.year >= 2014 and self.esg_exclusion > 0:
            esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
            df_esg = df.loc[esg_pct >= self.esg_exclusion]
            
            # Toutes les lignes exclues (non dans df_esg) sont les "Worst ESG"
            Worst_ESG = df.loc[~df.index.isin(df_esg.index)].index.tolist()


        # Blacklist filtering
        if self._liste_noire is not None:
            if isinstance(self._liste_noire, str):
                self._liste_noire = read_liste_noire(self._liste_noire, [], [])

            if 'ISIN' in df_esg.columns:
                Blacklisted = df_esg[df_esg['ISIN'].isin(self._liste_noire)].index.tolist()
                df_esg = df_esg[~df_esg['ISIN'].isin(self._liste_noire)]
            elif df_esg.index.name == 'ISIN':
                Blacklisted = df_esg[df_esg.index.isin(self._liste_noire)].index.tolist()
                df_esg = df_esg[~df_esg.index.isin(self._liste_noire)]

        # Save companies excluded beaucause of ESG reason 
        titles_excluded = self.save_esg_blacklist(df, Worst_ESG, Blacklisted)

        return df_esg, titles_excluded

    

    def adjust_bench_weight_with_recommandation(self, df, reco_secto, date):
        df_grouped, group_col = self._prepare_group_column(
            df,
            self.weight_neutral,
            "__weight_neutral_group__",
        )
        if group_col is None:
            return None

        weight_secto_bench = (
            df_grouped.groupby(group_col)['Weight in ' + self.bench].sum()
            / df_grouped['Weight in ' + self.bench].sum()
        )

        if group_col == ' Benchmark ICB Supersector ':
            icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(df_grouped[group_col].unique())
            if len(icb_missing) > 0:
                print(f"Warning: follwing sectors are missing in benchmark: {list(icb_missing)}")
                try:
                    indices_to_delete = [int(icb)-1 for icb in icb_missing] # find out where need to be deleted and then mark it as 1
                    reco_secto = np.delete(np.array(reco_secto), indices_to_delete) # delete function can delete several values at a same time, no need to do iteration
                except:
                    print(date)

            
            # Recommandation sectorielle
            weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1)   

            # Adjust small weight sectors
            small_weight_mask = weight_secto_bench < 0.0025
            sectors_to_be_adjusted = weight_secto_bench[small_weight_mask].index
            if not sectors_to_be_adjusted.empty:
                # print(f"Warning: follwing sectors have weight lower than 0.0025, their weight will be replace as 0.0025: {sectors_to_be_adjusted.tolist()}")
                weight_secto_bench[small_weight_mask] = 0.0025
        
        return weight_secto_bench

    def neutralise_score_by_secteur(self, df, list_score_col):
        """
            Permet de générer le weight des secteurs économique dans le bench
        """
        df = df.copy()
        df.loc[:, list_score_col] = self._scale_score_frame(df[list_score_col])

        df_grouped, group_col = self._prepare_group_column(
            df,
            self.score_neutral,
            "__score_neutral_group__",
        )
        if group_col is None:
            return df

        for group_value in df_grouped[group_col].dropna().unique():
            mask = df_grouped[group_col] == group_value
            fallback_scores = df_grouped.loc[mask, list_score_col].copy()
            scaled_scores = self._scale_score_frame(fallback_scores)
            # 小组或零方差组保持全局标准化结果，避免联合分组后被 NaN 污染。
            df_grouped.loc[mask, list_score_col] = scaled_scores.where(
                scaled_scores.notna(),
                fallback_scores,
            ).values

        return df_grouped


    def get_portfolio_name(self, style):
        """
        Automatically select portfolio name based on investment style, benchmark, and ranking position
        
        Parameters:
        style (str): Investment style, choose from list_style
        bench (str): Benchmark, supports "SP500" and "STOXX EUROPE 600"
        top (bool): True for Q1 (top 25%), False for Q5 (bottom 25%)
        
        Returns:
        str: Corresponding portfolio name
        """
        
        if self.mode_monthly_prod:
            if self.ptf_name == "PTF TEST":
                # Define investment style list
                list_style = ['Size Avg Percentile', 'Value Avg Percentile','Quality Avg Percentile',
                            'Mom Avg Percentile','LowVol Avg Percentile','Growth Avg Percentile', 
                            'Multi Avg Percentile']
                
                # Define benchmark to region mapping
                bench_to_region = {
                    'SP500': 'US',
                    'MSCI US': 'US',
                    'STOXX EUROPE 600': 'EU'
                }
                
                # Define style to portfolio type mapping
                style_to_type = {
                    'Size Avg Percentile': 'SIZE',
                    'Value Avg Percentile': 'VALUE',  
                    'Quality Avg Percentile': 'QUALITY',
                    'Mom Avg Percentile': 'MOM',
                    'LowVol Avg Percentile': 'LOWVOL',
                    'Growth Avg Percentile': 'GROWTH',
                    'Multi Avg Percentile': 'MF'
                }
                
                # Validate input parameters
                if style not in list_style:
                    raise ValueError(f"Style '{style}' not in supported style list: {list_style}")
                
                if self.bench not in bench_to_region:
                    raise ValueError(f"Benchmark '{self.bench}' not supported. Supported benchmarks: {list(bench_to_region.keys())}")
                
                # Get region and portfolio type
                region = bench_to_region[self.bench]
                portfolio_type = style_to_type[style]
                
                # Select Q1 or Q5 based on top parameter
                quintile = 'Q1' if self.Top else 'Q5'
                
                # Construct portfolio name
                ptf_name = f"FS_{region}_{portfolio_type}_{quintile}"

                if ptf_name == 'FS_EU_MF_Q1' and self.esg_exclusion>0:
                    ptf_name = "FS_EU_MF_ESG_Q1"
                if ptf_name == 'FS_EU_MF_Q5' and self.esg_exclusion>0:
                    ptf_name = "FS_EU_MF_ESG_Q5"
            
            if self.ptf_name != "PTF TEST":
                ptf_name = self.ptf_name

        if self.mode_monthly_prod != True:
            ptf_name = self.ptf_name

        return ptf_name

    def save_portfolio_data_incremental(self, df_concat, output_dir, date_obj=None):
        """
        Save portfolio data to Excel file incrementally.
        Creates file if it doesn't exist, otherwise appends new data.
        
        Parameters:
        df_concat (DataFrame): New data to save
        output_dir (str): Output directory path
        date_obj (datetime.date): Date object for folder naming (default: current date)
        """
        
        if date_obj is None:
            date_obj = pd.to_datetime(df_concat['Date']).iloc[0]
        
        # Create output file path
        folder_name = date_obj.strftime("%B %Y")
        folder_path = os.path.join(output_dir, f"Pour {folder_name}")
        output_file = os.path.join(folder_path, "PTFS TO PUSH.xlsx")
        # Create directory if it doesn't exist
        os.makedirs(folder_path, exist_ok=True)
        
        # Prepare new data
        new_data = df_concat[['PTF', 'ISIN', 'Weight', 'Date']].copy()
        
        # Check if file exists
        if os.path.exists(output_file):
            try:
                # Read existing data
                existing_data = pd.read_excel(output_file)
                print(f"Found existing file with {len(existing_data)} records")
                # Supprimer les lignes de existing_data dont 'PTF' est présent dans new_data
                existing_data = existing_data[~existing_data['PTF'].isin(new_data['PTF'])]


                # Combine existing and new data
                combined_data = pd.concat([existing_data, new_data], ignore_index=True, axis=0)
                
                # Remove duplicates based on all columns (optional)
                # You might want to modify this logic based on your needs
                combined_data = combined_data.drop_duplicates(subset=['PTF', 'ISIN', 'Date'], keep='last')
                
                print(f"After combining and deduplicating: {len(combined_data)} records")
                
            except Exception as e:
                print(f"Error reading existing file: {e}")
                print("Creating new file with current data only")
                combined_data = new_data
        else:
            print("File doesn't exist, creating new file")
            combined_data = new_data
        
        # Write combined data to Excel
        try:
            with pd.ExcelWriter(output_file, datetime_format='dd/mm/yyyy') as writer:
                combined_data.to_excel(writer, index=False)
            
            print(f"Successfully saved {len(combined_data)} records to: {output_file}")
            
        except Exception as e:
            print(f"Error writing to file: {e}")
            raise

    def cap_weight_by_sector(self, ptf, n_iteration=30):
        """
        Cap individual stock weights while redistributing excess weight proportionally
        to other companies within the same sector
    
        Parameters:
        ptf: DataFrame with columns ['Date', 'Secto', 'Weight']
        threshold: Maximum weight limit for individual stocks
        n_iteration: Maximum number of iterations
    
        Returns:
        DataFrame with adjusted weights
        """
        threshold = self.cap_weight_threshold

        result = ptf.copy()
    
        for iteration in range(n_iteration):
            
            # Track if any adjustment was made for early termination
            has_adjustment = False
        
            # Process each date separately
            for date in result['Date'].unique():
                date_mask = result['Date'] == date
                date_data = result[date_mask].copy()
                
                # Process each sector separately
                for sector in date_data['Secto'].unique():
                    sector_mask = date_data['Secto'] == sector
                    sector_data = date_data[sector_mask].copy()
                
                    # Find overweight stocks
                    overweight_mask = sector_data['Weight'] > threshold
                
                    if overweight_mask.any():
                        has_adjustment = True
                    
                        # Calculate total excess weight
                        excess_weight = (sector_data.loc[overweight_mask, 'Weight'] - threshold).sum()
                    
                        # Cap overweight stocks to threshold
                        sector_data.loc[overweight_mask, 'Weight'] = threshold
                    
                        # Find underweight stocks (those not exceeding threshold)
                        underweight_mask = ~overweight_mask
                        underweight_data = sector_data[underweight_mask]
                    
                        if len(underweight_data) > 0:
                            # Calculate total weight of underweight stocks
                            underweight_total = underweight_data['Weight'].sum()
                        
                            if underweight_total > 0:
                                # Distribute excess weight proportionally to underweight stocks
                                allocation_ratio = excess_weight / underweight_total
                                sector_data.loc[underweight_mask, 'Weight'] = (
                                    sector_data.loc[underweight_mask, 'Weight'] * (1 + allocation_ratio)
                                )
                    
                        # Update results
                        result.loc[date_mask & (result['Secto'] == sector), 'Weight'] = sector_data['Weight'].values
        
            # Early termination if no adjustments were made
            if not has_adjustment:
                break
        
        return result

    def save_esg_blacklist(self, screen: pd.DataFrame, Worst_ESG: list, Blacklisted: list) -> pd.DataFrame:
        """
        Filters the screen DataFrame to include only ISINs present in Worst_ESG or Blacklisted.
        Adds a 'Raison Exclusion' column indicating the reason(s) for exclusion.
        Keeps only rows where at least one of these flags is True.

        Parameters:
        - screen: pd.DataFrame with ISINs as index and a 'Date' column.
        - Worst_ESG: list of ISINs flagged for worst ESG.
        - Blacklisted: list of ISINs that are blacklisted.

        Returns:
        - pd.DataFrame with 'Date' and 'Raison Exclusion' columns.
        """
        # Combine ISINs from both lists
        filtered_isins = set(Worst_ESG).union(set(Blacklisted))

        # Filter the screen DataFrame to include only relevant ISINs
        filtered_df = screen.loc[screen.index.intersection(filtered_isins)].copy()

        # Determine reasons for exclusion
        reasons = []
        for isin in filtered_df.index:
            reason = []
            if isin in Worst_ESG:
                reason.append("ESG Reason")
            if isin in Blacklisted:
                reason.append("Blacklisted")
            reasons.append(", ".join(reason))

        # Assign the reasons to a new column
        filtered_df["Raison Exclusion"] = reasons

        # Keep only the required columns
        final_df = filtered_df[["Date", "Raison Exclusion"]]

        return final_df


    def select_titles(self, group, max_weight_threshold, column):
        sector_weight = group['Weight in ' + self.bench].sum()  # Get the sector's total weight
        if group["Date"].unique()[0]>=datetime.datetime(2021,12,30): #Car poid passe de [0,1] à [0,100] en decembre 2021
            max_weight_threshold = max_weight_threshold * 100
        min_titles_needed = (sector_weight // max_weight_threshold) + (1 if sector_weight % max_weight_threshold != 0 else 0) # Division euclidienne pour connaitre le min de titre a avoir
        

        sector = group[" Benchmark ICB Supersector "].unique()
        # Choisir les minimum de titres pour respecter la contrainte
        selected_titles = group.nlargest(int(min_titles_needed), column)  
        
        return selected_titles

    def sec_list_spot(self,screen_agg_monthly=None):
        """
        Generate Best Scored Sec List for 1 Month, According to the Metrics Chosen
        """

        if isinstance(screen_agg_monthly, pd.DataFrame):
            screen=copy.deepcopy(screen_agg_monthly)
        elif screen_agg_monthly==None: # If single month dataframe is not defined, then use the last month data to generate ptf
            screen = self.screen[self.screen['Date'] == self.screen['Date'].max()] 

        
        if type(self.metrics)==str:
            list_score_col = [self.metrics]
        else:
            list_score_col = self.metrics


        ################ use only the last month's screen (production mode) ################ 
        date = pd.to_datetime(screen['Date'].max())
        # screen=screen[screen['Date']==date]

        if screen.index.duplicated().any():
            screen = screen[~screen.index.duplicated(keep='first')]

        ################ Merging les tickers secondaires ################
        screen = merge_ticker_secondaire(screen, self.bench)

        ################ Filtrage Bench ################
        df = screen[screen['Weight in ' + self.bench]>0] # on conserve que les weights positifs
        list_exclusion_bench = screen.loc[~screen.index.isin(df.index)].index.to_list() # For later merge with other list of exclusion

        ################ Fixer le nombre de boite à choisir pour plus tard avant que le df soit modifié ################
        if self.percentile > 1:   ##### If percentile is bigger than 1, then this variable means exact number of securities to pick
            nb_securities=self.percentile
        else: ##### If percentile is less than 1, then this variable means the percentage of securities in investable univers to pick
            nb_securities = round(len(df) * self.percentile)

        ################ donne le 1er jour du mois suivant ################
        date +=pd.offsets.MonthBegin(1)

        ################################################################################################################################
        if self.metrics == "Multi Avg Percentile":  ### Reco facto will only activated when using "Multi Avg Percentile" as metric
            # Recommandtions Sectorielles à la date donnée
            if isinstance(self.reco_facto, list):
                reco_facto =np.array(self.reco_facto)
            elif isinstance(self.reco_facto, pd.DataFrame):
                try:
                    reco_facto = self.reco_facto.loc[date] 
                except : 
                    print(f"{date} not in reco_facto")
                    raise KeyError
                
            if (reco_facto.sum() == 0) : 
                reco_facto = np.array([0.2]*5)
            else:
                reco_facto = np.array(reco_facto/reco_facto.sum())

            list_style = ['Growth Avg Percentile','LowVol Avg Percentile','Mom Avg Percentile','Quality Avg Percentile','Value Avg Percentile']
            df.loc[:, 'Multi Avg Percentile'] = df[list_style].dot(reco_facto)

        ################################################################################################################################
        # regression de Benchmark value sur weight in bench pour compléter les valeurs manquantes
        fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in ' + self.bench],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
        func = np.poly1d(fit)
        df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in ' + self.bench])
        # Market cut filtrage
        df.loc[df['Benchmark Market Value Millions in EUR'] <= self.cut_mkt_cap, list_score_col] = np.nan
        list_exclusion_market_cut = df[df['Benchmark Market Value Millions in EUR'] <= self.cut_mkt_cap].index.to_list()  # on note les entreprises hors de benchmark, For later merge with other list of exclusion
        
        df = df.copy()
        df.loc[:, 'Date'] = date
    
        # debut pondération
        df=self.fix_companies_ponderation(df)

        # 国家分组：EM 国别优化或按国别 top_mandatory 时需要
        if self.country_sector_optimize or self.top_mandatory_by_country:
            df = add_country_group(
                df,
                self.bench,
                country_col=self.country_col,
                top_n=self.country_group_top_n,
            )

        # Recommandtions Sectorielles à la date donnée
        if isinstance(self.reco_secto, list):
            reco_secto =copy.deepcopy(self.reco_secto)
        elif isinstance(self.reco_secto, pd.DataFrame):
            try:
                reco_secto = self.reco_secto.loc[date].to_list() 
            except : 
                print(f"{date} not in reco_secto")
                raise KeyError
        
        weight_secto_bench = None
        weight_pays_bench = None
        if self.country_sector_optimize:
            w_b = 'Weight in ' + self.bench
            weight_secto_bench = (
                df.groupby(' Benchmark ICB Supersector ')[w_b].sum() / df[w_b].sum()
            )
            weight_pays_bench = (
                df.groupby('Country Group')[w_b].sum() / df[w_b].sum()
            )
        elif self.weight_neutral is not None:
            weight_secto_bench = self.adjust_bench_weight_with_recommandation(df, reco_secto, date)

        # Initiate Dataframe for liste exclusion
        titles_excluded = pd.DataFrame(columns=['Date', "Raison Exclusion"])

        # Filtrage ESG only if we choose Top ptf
        if self.Top:
            df, titles_excluded = self.filtrage_esg_liste_noire(df,date)  

        # Combine titles_excluded with Market Cut Exclusion
        default_date = titles_excluded['Date'].iloc[0] if not titles_excluded.empty else date  # Add date for exclusion liste dataframe

        # Create exclusion dataframe for market cut reason
        new_entries_exclusion = pd.DataFrame({
            'Date': [default_date] * len(list_exclusion_market_cut),
            'Raison Exclusion': ['Cut Market'] * len(list_exclusion_market_cut)
        }, index=list_exclusion_market_cut)

        titles_excluded = pd.concat([titles_excluded, new_entries_exclusion], axis=0) # Concat avec le dataframe de début

        # Create exclusion dataframe for not in bench reason reason
        new_entries_not_in_bench = pd.DataFrame({
            'Date': [default_date] * len(list_exclusion_bench),
            'Raison Exclusion': ["Not in Bnech"] * len(list_exclusion_bench)
        }, index=list_exclusion_bench)

        titles_excluded = pd.concat([titles_excluded, new_entries_not_in_bench], axis=0)


        df = self.neutralise_score_by_secteur(df, list_score_col) 

        df["Raison Repechage"] = ""

        columns = ['PTF', 'ISIN', 'Weight', 'Date', "Raison Repechage"]
        result_sec_list = pd.DataFrame()

        for i in range(len(list_score_col)):

            if self.Top == True:
                df_top = df.nlargest(nb_securities,list_score_col[i])
                df_top['Raison Repechage'] = list_score_col[i]  # Mettre la métrique de repechage comme raison, ex. Score ML/ Growth Avg Percentile

                if self.cap_weight_threshold is not None:
                    # Selection du minimum de titres minimum par secteur pour respecter la contrainte de poid max (self.cap_weight_threshold)
                    df_top_sector =  df.groupby(' Benchmark ICB Supersector ').apply(self.select_titles, max_weight_threshold=self.cap_weight_threshold, column = list_score_col[i])
                    df_top_sector = df_top_sector.drop( columns = [" Benchmark ICB Supersector "] )
                    df_top_sector = df_top_sector.reset_index(drop=False)
                    if "ISIN" not in df_top_sector.columns:
                        if "level_1" in df_top_sector.columns:
                            df_top_sector = df_top_sector.rename(columns={"level_1": "ISIN"})
                        elif "index" in df_top_sector.columns:
                            df_top_sector = df_top_sector.rename(columns={"index": "ISIN"})
                        elif len(df_top_sector.columns) > 1:
                            df_top_sector = df_top_sector.rename(columns={df_top_sector.columns[1]: "ISIN"})
                    df_top_sector.index = df_top_sector["ISIN"]
                    df_top_sector = df_top_sector.drop( columns = ["ISIN"] )
                    df_top_sector["Raison Repechage"] = "Sector"
                    
                    # Concat les deux top list
                    df_top_combined = pd.concat([df_top, df_top_sector], axis=0)
                    df_top = df_top_combined[~df_top_combined.index.duplicated(keep='first')]  # Prioritize top selected with classical way

                # Add non selected titles in list exclusion beacause of metrics
                list_exclusion_metrics = df.loc[~df.index.isin(df_top.index)].index.to_list()
                new_entries_exclusion = pd.DataFrame({
                    'Date': [default_date] * len(list_exclusion_metrics),
                    'Raison Exclusion': [f"Bad {list_score_col[i]}"] * len(list_exclusion_metrics)
                }, index=list_exclusion_metrics)

                # Append to the existing final_df
                titles_excluded = pd.concat([titles_excluded, new_entries_exclusion], axis=0)
                titles_excluded.index.name = "ISIN"
                titles_excluded = titles_excluded.reset_index()


            if self.Top == False:
                df_top=df.nsmallest(nb_securities,list_score_col[i])
                df_top['Raison Repechage'] = "Worst Metric"

            if isinstance(self.top_mandatory, int) or isinstance(self.top_mandatory, float):
                nb_top_mandatory = int(self.top_mandatory)
                wcol = 'Weight in ' + self.bench
                if self.top_mandatory_by_country:
                    liste_top_mandatory = (
                        df.sort_values(wcol, ascending=False)
                        .groupby('Country Group', group_keys=False)
                        .head(nb_top_mandatory)
                    )
                else:
                    liste_top_mandatory = df.nlargest(nb_top_mandatory, wcol)
                liste_top_mandatory['Raison Repechage'] = "Top Obligatoire par Région"

                df_top_combined = pd.concat([liste_top_mandatory, df_top], axis=0)
                df_top = df_top_combined[~df_top_combined.index.duplicated(keep='first')]  # Prioritize top selected with top mandatory


            ##### Ajustement Secteur Neutre
            temp_df = pd.DataFrame(columns = columns)
            temp_df['ISIN'] = df_top.index

            if self.country_sector_optimize:
                if self.weight_neutral is None:
                    raise ValueError("country_sector_optimize=True 时请设置 weight_neutral（如 ICB 19）")
                w_b = 'Weight in ' + self.bench
                temp_df['Weight'] = df_top[w_b].values
                temp_df['Score'] = df_top[list_score_col[i]].values
                temp_df['Date'] = df_top['Date'].values
                temp_df['Raison Repechage'] = df_top['Raison Repechage'].values
                if self.weight_neutral == "ICB 19":
                    temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
                elif self.weight_neutral == "ICB 11":
                    temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
                else:
                    df_top_grouped, group_col = self._prepare_group_column(
                        df_top,
                        self.weight_neutral,
                        "__weight_neutral_group__",
                    )
                    temp_df['Secto'] = df_top_grouped[group_col].values
                temp_df['Country Group'] = df_top['Country Group'].values

                temp_df_sectors = set(temp_df['Secto'].dropna().unique())
                benchmark_sectors = set(weight_secto_bench.index)
                if not temp_df_sectors.issubset(benchmark_sectors):
                    missing_sectors = temp_df_sectors.difference(benchmark_sectors)
                    raise ValueError(
                        f"Secto 不在 weight_secto_bench 中: {missing_sectors}"
                    )

                temp_df = optimize_weights(
                    temp_df,
                    weight_secto_bench,
                    weight_pays_bench,
                    objective=self.optimize_objective,
                    margin=self.optimize_margin,
                )
                temp_df = temp_df.drop(columns=['Score', 'Country Group'], errors='ignore')
            else:
                temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values

                temp_df['Score'] = df_top[list_score_col[i]].values
                temp_df['Date'] = df_top['Date'].values
                temp_df['Raison Repechage'] = df_top['Raison Repechage'].values

                if self.weight_neutral is not None:
                    df_top_grouped, group_col = self._prepare_group_column(
                        df_top,
                        self.weight_neutral,
                        "__weight_neutral_group__",
                    )
                    temp_df['Secto'] = df_top_grouped[group_col].values

                    ###################### Security check : secto in temp_df is a subset of secto in weight_secto_bench ############################
                    temp_df_sectors = set(temp_df['Secto'].dropna().unique())
                    benchmark_sectors = set(weight_secto_bench.index)
                    if not temp_df_sectors.issubset(benchmark_sectors):
                        missing_sectors = temp_df_sectors.difference(benchmark_sectors)
                        raise ValueError(f"Error: Sectors in temp_df {missing_sectors} are not defined in weight_secto_bench")
                    #################################################################################################################################

                    secto_weight_sum = temp_df.groupby('Secto')['Weight'].transform('sum')
                    secto_benchmark_weight = temp_df['Secto'].map(weight_secto_bench)
                    scaling_factor = secto_benchmark_weight / secto_weight_sum
                    temp_df['Weight'] = temp_df['Weight'] * scaling_factor
                    temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()

            ############ cap weight by sector if necessary ################
            if self.cap_weight_threshold is not None:
                # print(f"Capping generated portfolio, no more than {self.cap_weight_threshold} for each title")
                temp_df = self.cap_weight_by_sector(temp_df)

            ##### Give name to ptf generated
            temp_df['PTF'] = self.get_portfolio_name(list_score_col[i])

            result_sec_list = pd.concat([result_sec_list,temp_df], ignore_index=True)
        
        if self.output_dir is not None:
            if self.mode_monthly_prod:
                self.save_portfolio_data_incremental(result_sec_list, self.output_dir)
            else:
                result_save_path = os.path.join(self.output_dir, "sec_list_result.xlsx")
                result_sec_list.to_excel(result_save_path)
                print(f"Sec list is generated at path : {result_save_path}")

        self.sec_list_monthly = result_sec_list.copy(deep=True)
        # print(f"Monthly sec list is generated for {date}, you can check 'self.sec_list_monthly' attribute for more details.")

        self.list_exclusion_monthly = titles_excluded.copy(deep=True)

        return result_sec_list, titles_excluded
    
    def update_ptf_with_monthly_additions(self, df):
        """
        For every month present in the portfolio (including the first and last),
        check whether the following month already exists.  
        If it does **not** exist, create a copy of the current month, shift the
        date forward by one month, and append it to the dataframe.
        """
        # keep a set for O(1) membership checks
        ptf = df.copy()

        existing_dates = set(ptf["Date"].unique())
        # print("Longueur sec_list avant : " , len(existing_dates))

        sorted_existing_dates = sorted(existing_dates)  # Exemple : 01-10 , 03-10 , 05-10 ect
        today = datetime.datetime.now()
        for date in sorted_existing_dates:  
            
            next_month = date + pd.DateOffset(months=1)
            
            # Continue adding months until there are no more gaps
            while next_month not in existing_dates :
                if  next_month > today : # Condition pour sortir : si next month est superieur 
                    break
                else :    
                    prev_ptf = ptf[ptf["Date"] == date].copy()
                    prev_ptf["Date"] = next_month
                    ptf = pd.concat([ptf, prev_ptf]).sort_values("Date").reset_index(drop=True)
                    
                    # Update the set so that we don't add the same month twice
                    existing_dates.add(next_month)
                    
                    # Move to the newly added month for further checks
                    date = next_month
                    next_month += pd.DateOffset(months=1)
                
            if next_month > today  :
                break
        
        # print("Longueur sec_list après : ", len(existing_dates))
        return ptf
    

    def find_next_closest_date(self, start_date, offset):
        """
        Finds the next closest date to start_date from the given DataFrame.

        Parameters:
        - start_date (datetime): The reference date.
        - screen_agg (pd.DataFrame): A DataFrame containing a 'Date' column with datetime objects.

        Returns:
        - datetime: The next closest date that satisfies the conditions.
        
        Raises:
        - ValueError: If start_date is not a datetime object or if no valid dates are found.
        """
        screen_agg = copy.deepcopy(self.screen)
        
        # Calculer les différences absolues entre chaque date et la start_date
        screen_agg = screen_agg[screen_agg["Date"]>=start_date]
        dates = screen_agg["Date"].unique()
        dates = pd.to_datetime(dates)

        closest_date = min(dates, key=lambda d: abs(d - start_date)) # Prend la date du screen_agg après start_date la plus proche


        # Si offset = 0, je rentre dans le if si closest_date est un mois pair cela permettra de prendre la date d'apres qui est forcement un mois impair
        # Si offset = 1, je rentre dans le if si closest_date est un mois impair cela permettra de prendre la date d'apres qui est forcement un mois pair
        if closest_date.month%2==offset:   
            dates = screen_agg[screen_agg["Date"]>closest_date]["Date"].unique()
            dates = pd.to_datetime(dates)

            closest_date = min(dates, key=lambda d: abs(d - start_date))

        return closest_date

    def generic_histo_seclist(self, start_date, freq_rebal=None, screen_start_date = "mois_impair"):
        """
        Apply a function to subsets of financial data based on specified frequency.
        
        Parameters:
        -----------
        func : function
            The function to apply to each subset of data
        start_date : str or datetime
            The earliest date to include in the analysis
        *args : 
            First argument is screen_agg (DataFrame or path to parquet file)
            Remaining arguments are passed to func
        freq : int, optional
            The frequency in months for selecting dates
        rebalancing_start_backward : datetime, optional
            If provided, the latest date will be the date in the month before this date
        
        Returns:
        --------
        DataFrame
            Combined results from the function applied to each subset
        """
        
        screen_agg = copy.deepcopy(self.screen)
        if type(screen_agg) == str:
            screen_agg = pd.read_parquet(screen_agg)
            screen_agg = self._normalize_screen_columns(screen_agg)
        

        #START DATE commence en  mois pair
        if screen_start_date == "mois_pair" :
            self.start_date  = self.find_next_closest_date(start_date,1)
        elif screen_start_date == "mois_impair" :
            self.start_date  = self.find_next_closest_date(start_date,0)
        else:
            self.start_date = start_date

        print( "Premiere date du screen_agg prise en compte : " , self.start_date)

        # Filter by start_date
        screen_agg = screen_agg[screen_agg['Date'] >= self.start_date]
        all_dates = sorted(screen_agg['Date'].unique())
        
        if not all_dates:
            return pd.DataFrame()  # Return empty DataFrame if no dates
        
        # Determine which dates to keep based on frequency
        if freq_rebal == None:
            # Keep all dates for monthly frequency (original behavior)
            dates_to_keep = all_dates
        else:
            months_step = freq_rebal
            dates_to_keep = all_dates[::months_step]
        
        # Sort the dates to keep
        dates_to_keep = sorted(dates_to_keep)

        # Create subsets for each date
        screen_list = [screen_agg.loc[screen_agg['Date'] == date_] for date_ in dates_to_keep]
        
        
        # Apply function with progress bar
        func = self.sec_list_spot
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
        
        result_sec_list = []
        result_exclusion = []
        
        # Setup for simple progress reporting if tqdm is not available
        if not has_tqdm and total > 0:
            step = max(1, total // 10)
            print(f"Processing {total} monthly screens...")
        else:
            step = None
        
        for i, screen in enumerate(iterator):
            if step is not None:
                if i % step == 0 or i == total - 1:
                    print(f"  Progress: {i+1}/{total} months ({(i+1)*100/total:.0f}%)")
            
            result = func(screen_agg_monthly=screen)  # result[0] is sec_list, result[1] is liste exclusion
            result_sec_list.append(result[0])
            result_exclusion.append(result[1])
            
        # Concatenate seclist results
        if result_sec_list and isinstance(result_sec_list[0], pd.DataFrame):
            df = pd.concat(result_sec_list, ignore_index=True)
        else:
            # Handle the case where func doesn't return DataFrames
            df = pd.DataFrame(result_sec_list)

        # Concatenate exclusion results
        if result_exclusion and isinstance(result_exclusion[0], pd.DataFrame):
            df_exclusion = pd.concat(result_exclusion, ignore_index=True)
        else:
            # Handle the case where func doesn't return DataFrames
            df_exclusion = pd.DataFrame(result_exclusion)

        # for bimestriel situation
        self.sec_list_historical = df.copy()
        self.sec_list_historical  = self.update_ptf_with_monthly_additions(self.sec_list_historical)

        self.list_exclusion_histo = df_exclusion.copy()
        self.list_exclusion_histo = self.update_ptf_with_monthly_additions(self.list_exclusion_histo)

        print(f"Historical sec list is generated, you can check 'self.sec_list_historical' attribute for more details.")
        print(f"Historical exclusion list is generated, you can check 'self.list_exclusion' attribute for more details.")
        
        return df
    

    def backtest_calcul_all_portfolio(self,df_rebal, df_returns, col_weight,col_sector = ' Benchmark ICB Supersector ', col_date='Date', col_id = 'Company SEDOL'):
        """
        permet de générer les returns des portfolios
        df_rebal: contient les coefficients de poids 
        df_returns: returns des actifs
        """
        
        # Creating a list of available date in sec list (MONTHLY) - premier jour du mois
        liste_rebal_date = list(df_rebal.index.get_level_values(col_date).unique())
        # Creating a list of date (DAILY), but from returns dataframe, starting from the first date of the sec list
        liste_date_returns = list(df_returns[df_returns.index>=liste_rebal_date[0]].index)

        #filtrer pour avoir la période du portefeuille
        df_rebal.reset_index(inplace=True)
    
        df_rebal = df_rebal[df_rebal[col_id].isin(df_returns.columns)] #SUPPRESSION DES TITRES QUI NE SONT PAS DS LE parquet RETURN
        df_rebal.set_index(col_date,inplace=True)

        # Normalisation
        df_rebal['Portfolio weight'] = (
                                        df_rebal.groupby(col_date)['Portfolio weight']
                                        .transform(lambda x: x / x.sum())
                                        )
        
        df_rebal.reset_index(inplace=True)
    
    
        # Boucle dans le cas d'une date de rebalancement non présente dans df_returns -> changement de la date de rebalancement avec la 2eme date future la plus proche
        for i in range(len(liste_rebal_date)) :
            if  liste_rebal_date[i] not in liste_date_returns :

                try:
                    # Try pour chercher la 2eme date future la plus proche

                    # Supposons que liste_date_returns soit une liste de pd.Timestamp
                    serie_date_returns = pd.Series(liste_date_returns)

                    new_date_rebal = serie_date_returns[serie_date_returns > liste_rebal_date[i]].iloc[1]

                except ValueError:
                    # Si pas de future date trouvée, on prend la date antérieure la plus proche (cas frequency=1 dernière date est une date de rebalancement)
                    new_date_rebal = max(d for d in liste_date_returns if d < liste_rebal_date[i])
                except IndexError:
                    print(f"Cette date a un pb : {liste_rebal_date[i]}")


            else :
                # Supposons que liste_date_returns soit une liste de pd.Timestamp
                serie_date_returns = pd.Series(liste_date_returns)

                new_date_rebal = serie_date_returns[serie_date_returns > liste_rebal_date[i]].iloc[0]

            df_rebal = df_rebal.replace(liste_rebal_date[i], new_date_rebal)
            liste_rebal_date[i] = new_date_rebal

        # Tri avec la fonction sorted()
        liste_date_all = list(set(liste_rebal_date).union(set(liste_date_returns)))
        nouvelle_liste_dates = sorted(liste_date_all)
    
        #df_rebal = df_rebal.set_index([col_id,col_date])
    
        new_df = pd.DataFrame(data=nouvelle_liste_dates, columns=['Date_returns']) #INSTANCIATION dataframe AVEC COLONNE DE DATE DAILY
        
        #ON MET DS LE DF DAILY LES DATES DE REBAL POUR ENSUITE PRENDRE LES POIDS REBAL SANS LES FAIRE DRIFTER. A chaque date du mois on a la derniere date de rebal
        """
        This code does the following:
        For each date in the "Date_returns" column of the new_df dataframe, it searches in the df_rebal dataframe for all dates in the 
        col_date column that are less than or equal to the given date. 
        Then, it selects the maximum of these dates, representing the most recent REBALACING date before or on that date. 
        This value is then assigned to the "Date_screen" column in new_df.
        """
        new_df['Date_screen'] = new_df['Date_returns'].apply(lambda x: df_rebal.loc[df_rebal[col_date]<=x, col_date].max())
        
        #ON DUPPLIQUE LES DATES DE SCREEN MENSUEL POUR CHAQUE DATE de new DF dont la colonne Date Screen = col_date de df_rebal (date de rebalancement)
        df_merge = pd.merge(df_rebal,new_df, how='left', left_on=col_date, right_on = 'Date_screen')
        df_merge.drop(columns=col_date, inplace=True)
        df_merge.rename(columns={'Date_returns':col_date},inplace=True) #BONNE COLONNE DE DATE
        df_merge.sort_values(by=col_date, inplace=True)
    
        df_returns = df_returns[new_df['Date_screen'].min():] # ON garde LES RETURN A PARTIR DE LA PREMIERE DATE des returns
        returns_cum = (1+df_returns).cumprod() # On a le ttr calculé pour à partir de la 1ère date de rebalancement
        
        #ON REBASE LES DRIFT CUMULE à 1 à chaque date de rebal
        returns_drift = returns_cum.apply(lambda x:x/returns_cum.loc[(new_df.loc[new_df['Date_screen']<=x.name,'Date_screen'].max())], axis=1)
        """
        Date	Asset_A (drift_multiplicator)	Asset_B (drift_multiplicator)
        2021-01-01	1.00	1.00
        2021-01-02	1.10	0.95
        2021-01-03	1.15	1.05
        XXXXXXXXXX
        2021-02-01  1.00    1.00
        """

        #ON FLATTEN POUR METTRE EN 1 COLONNE
        returns_drift_flat = returns_drift.stack().to_frame().reset_index(names=[col_date, col_id])
        returns_drift_flat.columns=[col_date, col_id, 'drift_multiplicator']
        """
        Date	    Asset	drift_multiplicator
        2021-01-01	Asset_A	    1.00
        2021-01-01	Asset_B	    1.00
        2021-01-02	Asset_A	    1.10
        2021-01-02	Asset_B	    0.95
        2021-01-03	Asset_A	    1.15
        2021-01-03	Asset_B	    1.05
        """

        returns_flat=df_returns.stack().to_frame().reset_index()
        returns_flat.columns=[col_date, col_id, 'Return']
        """
        Date		Asset		Return
        2021-01-01	Asset_A		0.00
        2021-01-01	Asset_B		0.00
        2021-01-02	Asset_A		0.10
        2021-01-02	Asset_B		-0.05
        2021-01-03	Asset_A		0.05
        2021-01-03	Asset_B		0.10
        """

    
        df_merge = df_merge.merge(returns_drift_flat, how='left', on = [col_date, col_id]) #AJOUT DE 'drift_multiplicator'
        df_merge = df_merge.merge(returns_flat, how='left', on = [col_date, col_id])
        
        #CHAQUE POIDS DAILY est DRIFTé dont celui du rebal qui est aussi drifté par 1
        df_merge[col_weight+'_drifted'] = df_merge[col_weight]*df_merge['drift_multiplicator'] 
        """ EX. the weight af asset A is 0.6, drift_multiplicator is 1.1, then drifted weight : 0.6 * 1.1 = 0.66 """
        

        # Select the date, asset identifier, original weight, drift-adjusted weight, sector (or segment), 
        # and return data to form a new data frame `portfolio_tet`, facilitating subsequent calculations by date and asset.
        columns = [col_date, col_id, col_weight, col_weight+'_drifted', col_sector, 'Return']
        portfolio_tet=df_merge[columns]
        
        # Sum the drifted weights of all assets by date to obtain the total drift weight of all assets for that day
        weight_sum_date = portfolio_tet.groupby(col_date,group_keys=False)[[col_weight+'_drifted']].sum()
        weight_sum_date.columns = ['Weight_sum']
        weight_sum_date.reset_index(inplace=True)
        
        # Merge this total drift weight into portfolio_tet
        portfolio_tet = portfolio_tet.merge(weight_sum_date, how='left', on = col_date)
        
        # Divide the drifted weight of each asset by the total drift weight of that day to obtain the normalized weight W_rebased. 
        # This ensures that the sum of the normalized weights of all assets for each date equals 1.
        portfolio_tet['W_rebased'] = portfolio_tet[col_weight+'_drifted'] / portfolio_tet['Weight_sum']

        """
        Ex:
        Suppose on a given day, the drifted weight of Asset A is 0.66, and the drifted weight of Asset B is 0.38. The total drifted weight is 0.66 + 0.38 = 1.04.

        The normalized weight of Asset A: 0.66 / 1.04 ≈ 0.635  
        The normalized weight of Asset B: 0.38 / 1.04 ≈ 0.365
        """

        # For each asset (grouped by col_id), shift the normalized weight W_rebased down by one row, i.e., retrieve the normalized weight from the previous day.
        # This is typically done to calculate the daily contribution of each asset by multiplying the previous day's weight BY the current day's return, 
        # thereby determining the asset's contribution to the portfolio's daily return.
        portfolio_tet['W_rebased_shift1'] = portfolio_tet.groupby(col_id)['W_rebased'].shift(1)
        
        # Calculate the contribution of each asset: multiply the previous day's normalized weight by the current day's return.
        # Then, sum the contributions of all assets by date to obtain the total return contribution of the portfolio for each day.
        portfolio_tet['Contrib'] = portfolio_tet['W_rebased_shift1'] * portfolio_tet['Return']
        total_return_by_date = portfolio_tet.groupby(col_date)['Contrib'].sum()
        """
        Ex.
        If on a given day, Asset A's previous day weight is 0.635 and its current day return is 0.10, its contribution is 0.0635.
        If Asset B's previous day weight is 0.365 and its current day return is -0.05, its contribution is -0.01825.
        Total contribution = 0.0635 + (-0.01825) ≈ 0.04525.
        """

        # Starting with an initial value of 1, add the daily total return contribution (filling missing values with 0) and calculate the cumulative product to obtain the cumulative return of the entire portfolio
        total_return_by_date.sort_index(inplace=True)
        serie_ttr=(1 + total_return_by_date.fillna(0)).cumprod() * 100 
        """
        Example:
        Assume the cumulative calculation is as follows:
        Contribution on the first day is 0.00 → (1 + 0.00) = 1.00
        Contribution on the second day is 0.04525 → Cumulative return is 1.00 × 1.04525 ≈ 1.04525
        Contribution on the third day is 0.02 → Cumulative return is 1.04525 × 1.02 ≈ 1.06516
        Multiplying by 100, the cumulative return is 106.516%, representing a growth of 6.516% relative to the initial value.
        """    

        return serie_ttr
        
    def backtest_create_ptf_weight(self,sec_list, 
                        indice_name, 
                        screen_agg,
                        max_weight ,  
                        col_mkt_cap='Benchmark Market Value Millions in EUR', 
                        col_date = 'Date', 
                        col_sector = ' Benchmark ICB Supersector ', 
                        sector_neutral=False, method='mkt_cap', 
                        col_sedol = 'Company SEDOL', 
                        col_isin= 'ISIN'
                        ):
        
        # INDICE, SCREENAGGREGATE et SECLIST SERONT INVESTI AU 1er du mois
        # Filter Bench related securities and take the weight of bench as sec list
        screen_agg=copy.deepcopy(screen_agg)
        screen_agg, group_col = self._prepare_group_column(
            screen_agg,
            col_sector,
            "__backtest_neutral_group__",
        )
        indice = screen_agg.loc[screen_agg['Weight in '+indice_name]>0, [col_date, col_sedol,group_col,'Weight in '+indice_name]].reset_index()
        indice.rename(columns={'Weight in '+indice_name:'Indice weight'}, inplace= True)
    
        indice.sort_values(by=col_date,inplace=True)
        sec_list.sort_values(by=col_date,inplace=True)

        indice[col_date] = indice[col_date] + pd.offsets.MonthBegin(1)
        screen_agg[col_date] = screen_agg[col_date] + pd.offsets.MonthBegin(1)

        # Add some columns of screen in sec list
        sec_list = sec_list.merge(right = screen_agg.reset_index()[[col_date,col_isin,col_sedol,group_col, col_mkt_cap]], on=[col_date,col_isin], how='left')
        sec_list = sec_list[sec_list[col_sedol].notna()]
    
        if method=='EW': # Equal weight
            sec_list.set_index(col_date,inplace=True)
            sec_list['Portfolio weight'] = sec_list.groupby(col_date, group_keys=False).apply(lambda x: 1/len(x))
            sec_list.reset_index(inplace=True)
        else:
            sec_list = sec_list[sec_list[col_mkt_cap].notna()]                                                                      
            if method == "Racine cube":
                sec_list[col_mkt_cap] = sec_list[col_mkt_cap]**(1/3)
            elif method == "Racine carrée":
                sec_list[col_mkt_cap] = sec_list[col_mkt_cap]**(1/2)
            elif method == "Log":
                sec_list[col_mkt_cap] = np.log(sec_list[col_mkt_cap])
            sec_list.set_index(col_date,inplace=True)
            sec_list['Portfolio weight'] = sec_list[col_mkt_cap]/sec_list.groupby(col_date)[col_mkt_cap].sum()
            sec_list.reset_index(inplace=True)
    
        # Calculate the ratio of the benchmark index's total sector weight to the portfolio's total sector weight, which serves as the adjustment factor for each sector.  
        # Adjust the weight of each stock in the portfolio according to this ratio, ensuring that the total sector weight in the adjusted portfolio matches the sector weight of the benchmark index.
        if sector_neutral:
            indice.set_index(col_date,inplace=True)
            indice['Indice weight'] /= indice.groupby(col_date)['Indice weight'].sum()
            indice.reset_index(inplace=True)
            weight_secto_bench = (indice.groupby([col_date,group_col])['Indice weight'].sum()).reset_index()
        
            sec_list.set_index(col_date,inplace=True)
            sec_list['Portfolio weight'] /= sec_list.groupby(col_date)['Portfolio weight'].sum()
            sec_list.reset_index(inplace=True)
            sec_list.set_index([col_date,group_col],inplace=True)
            sec_list['weight_secto_ptf'] = sec_list.groupby([col_date,group_col],group_keys=False)['Portfolio weight'].sum()
            sec_list.reset_index(inplace=True)
    
            sec_list = sec_list.merge(weight_secto_bench[[col_date,group_col,'Indice weight']], on=[col_date,group_col], how='left')
            sec_list['Portfolio weight'] = sec_list['Portfolio weight'] * (sec_list['Indice weight']/sec_list['weight_secto_ptf'])
    
        # Handle outliers
        sec_list.set_index(col_date,inplace=True)
        sec_list['Portfolio weight'] /= sec_list.groupby(col_date)['Portfolio weight'].sum()
        sec_list['Portfolio weight'] = sec_list['Portfolio weight'].apply(lambda x : min(x,max_weight))
        sec_list['Portfolio weight'] /= sec_list.groupby(col_date)['Portfolio weight'].sum()
        sec_list.reset_index(inplace=True)
        
        return sec_list[[col_date, col_sedol,col_isin, 'Portfolio weight', group_col]].set_index([col_date,col_sedol])
    
    def backtest(self,sec_list=None,
                indice_name=None,
                method=None,    
                max_weight = 1, 
                col_sector= ' Benchmark ICB Supersector ', 
                col_sedol='Company SEDOL', 
                col_isin='ISIN', 
                col_date = 'Date', 
                col_mkt_cap = 'Benchmark Market Value Millions in EUR', 
                sector_neutral=False,
                sec_list_=True, 
                ponderation='mkt_cap', critere='Score ML',
                max_weights= [0.025,0.015,0.02,0.02,0.02,0.02,0.02,0.03,0.015,0.02,0.02,0.035,0.03,0.02,0.02,0.02,0.02,0.02,0.02], 
                list_secto=[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19], repechage_filter=['Sector ICB19'], 
                nb_titres= 150, te_max= 0.03,rebalancing_start_backward=None):
        
        # if sec_list is not provided used self.sec_list
        if  sec_list is None:
                if self.sec_list_historical is not None:
                    sec_list=self.sec_list_historical
                else:
                    sec_list=self.generic_histo_seclist( method=method, critere=critere,max_weights= max_weights, 
                            list_secto=list_secto, repechage_filter=repechage_filter, 
                            nb_titres= nb_titres, te_max=te_max,rebalancing_start_backward=rebalancing_start_backward)

        # if input is path, then read the parquet, if it's a df, then use it directly
        if type(self.screen)==str:
            screen_agg = pd.read_parquet(self.screen)
            screen_agg = self._normalize_screen_columns(screen_agg)
        else:
            screen_agg=copy.deepcopy(self.screen)

        screen_agg, resolved_col_sector = self._prepare_group_column(
            screen_agg,
            col_sector,
            "__backtest_neutral_group__",
        )
    
        if type(self.returns)==str:
            df_returns = pd.read_parquet(self.returns)
        else:
            df_returns=copy.deepcopy(self.returns)

        # Loading sec_list
        buy_list = copy.deepcopy(sec_list)


        
        # For a normal ptf that weight column is included
        if sec_list_ :
            if 'Weight' in buy_list.columns:
                # AVOIR UNE SECLIST AU 1ER DU MOIS pour MATCHER AVEC SCREEN AGGREGATE QUI SERA SHIFTé du 31 du mois au 1er du mois suivant
                sec_list_full = buy_list[[col_date,col_isin,'Weight']].copy()  ## COPY for avoid warning

                ### Rebalancing weight for each date ###
                sec_list_full['Weight'] = (
                                            sec_list_full.groupby(col_date)['Weight']
                                            .transform(lambda w: w / w.sum())
                                            )
                
                # Outliers transformation into [0, 1]
                sec_list_full['Weight'] = sec_list_full['Weight'].apply(lambda x : max(x,0))
                sec_list_full['Weight'] = sec_list_full['Weight'].apply(lambda x : min(x,max_weight))


                ### Redo rebalancing
                sec_list_full["WeightSum"] = sec_list_full.groupby("Date")["Weight"].transform("sum")
                sec_list_full['Weight'] /= sec_list_full["WeightSum"]

                sec_list_full.reset_index(inplace=True)

                sec_list_full.rename(columns={'Weight':'Portfolio weight'},inplace=True) # Rename column of weight

                # Make sure that column of date is datetime format
                screen_agg[col_date] = pd.to_datetime(screen_agg[col_date])

                # Then push the date to the first day of the next month
                screen_agg[col_date] = screen_agg[col_date] + pd.offsets.MonthBegin(1)

                # Generating final seclist
                sec_list_full = sec_list_full.merge(right = screen_agg.reset_index()[[col_date,col_isin,col_sedol,resolved_col_sector, col_mkt_cap]], on=[col_date,col_isin], how='left')
                sec_list_full = sec_list_full[sec_list_full[col_sedol].notna()] # Remove empty sedol companies
                sec_list_full = sec_list_full[[col_date, col_sedol,col_isin, 'Portfolio weight', resolved_col_sector]].set_index([col_date,col_sedol])
                
                # Calcule TTR
                perf_ttr = self.backtest_calcul_all_portfolio(sec_list_full, df_returns, 'Portfolio weight', resolved_col_sector, col_date, col_sedol)
                self.perf_ptf, self.buy_list=perf_ttr, sec_list_full[[col_date,col_isin,'Portfolio weight', resolved_col_sector]]
                print('Performance of sec_list is calculated, please check attribute "self.perf_ptf" for more details')
            else:
                print("Is not a sec_list")
            
        # For generating all titles sec list for a BENCHMARK
        else:
            # AVOIR UNE SECLIST AU 1ER DU MOIS pour MATCHER AVEC SCREEN AGGREGATE QUI SERA SHIFTé du 31 du mois au 1er du mois suivant
            sec_list_full = self.backtest_create_ptf_weight(buy_list, indice_name, screen_agg, max_weight, col_mkt_cap, col_date, resolved_col_sector, sector_neutral,ponderation,col_sedol, col_isin)
            perf_ttr = self.backtest_calcul_all_portfolio(sec_list_full, df_returns, 'Portfolio weight', resolved_col_sector, col_date, col_sedol)
            
            self.perf_bench = perf_ttr
            print('Performance of benchmark is calculated, please check attribute "self.perf_bench" for more details')

        return perf_ttr, self.buy_list

    def backtest_get_bench_perf(self,screen,start_date,bench):
        indice_ref = screen[(screen['Date']>=start_date) & (screen['Weight in '+bench]>0)].reset_index()[['Date','ISIN']]
        indice_ref["Date"] = pd.to_datetime(indice_ref["Date"])
        indice_ref["Date"] = indice_ref["Date"] + pd.offsets.MonthBegin(1)
        self.backtest(sec_list=indice_ref,indice_name=bench,sec_list_=False)

    def backtest_plot_ptf_bench(self, perf_ptf=None, perf_bench=None, title=None, save_path="portfolio_performance.html", show_plot=True):

        if self.perf_ptf is None:
            perf_ptf, buy_list = self.backtest(self.sec_list_historical)
        perf_ptf, buy_list = self.perf_ptf, self.buy_list

        if self.perf_bench is None:
            self.backtest_get_bench_perf(self.screen, self.start_date, self.bench)
        perf_bench = self.perf_bench
        
        # Concatenate dataframes
        df_plot = pd.concat([perf_ptf, perf_bench], axis=1)

        # Create subplots
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                            subplot_titles=("Performance", "Ratio"))

        # Add traces for performance
        for i, col in enumerate(df_plot.columns):
            label = 'Perf PTF' if i == 0 else 'Perf Bench'

            # Add line trace
            fig.add_trace(go.Scatter(
                x=df_plot.index,
                y=df_plot.iloc[:, i],
                mode='lines',
                name=label,
                line=dict(width=2)
            ), row=1, col=1)

            # Add annotation for last value
            last_x = df_plot.index[-1]
            last_y = df_plot.iloc[:, i].iloc[-1]

            fig.add_annotation(
                x=last_x,
                y=last_y,
                text=f'{last_y:.2f}',
                showarrow=False,
                xanchor='left',
                font=dict(size=10),
                bgcolor='rgba(255,255,255,0.8)',
                bordercolor='rgba(0,0,0,0.2)',
                borderwidth=1
            )

        # Add trace for the ratio
        ratio = df_plot.iloc[:, 0] / df_plot.iloc[:, 1]
        fig.add_trace(go.Scatter(
            x=df_plot.index,
            y=ratio,
            mode='lines',
            name='Ratio',
            line=dict(width=2, color='red')
        ), row=2, col=1)

        # Add annotation for last value of the ratio
        last_ratio = ratio.iloc[-1]
        fig.add_annotation(
            x=last_x,
            y=last_ratio,
            text=f'{last_ratio:.2f}',
            showarrow=False,
            xanchor='left',
            font=dict(size=10),
            bgcolor='rgba(255,255,255,0.8)',
            bordercolor='rgba(0,0,0,0.2)',
            borderwidth=1
        )

        # Update layout
        fig.update_layout(
            title=title if title else "",
            width=700,
            height=600,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            margin=dict(l=50, r=50, t=50, b=50),
            plot_bgcolor='white',
            paper_bgcolor='white'
        )

        # Update axes
        fig.update_xaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor='lightgray',
            showline=True,
            linewidth=1,
            linecolor='black'
        )

        fig.update_yaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor='lightgray',
            showline=True,
            linewidth=1,
            linecolor='black'
        )

        # Handle different environments
        if save_path:
            # Save as HTML file
            fig.write_html(save_path)
            print(f"Plot saved as HTML to: {save_path}")

        if show_plot:
            try:
                # Try to show in browser
                fig.show()
            except Exception as e:
                print(f"Cannot display plot directly: {e}")
                # Save as temporary HTML file and provide instructions
                temp_path = "temp_plot.html"
                fig.write_html(temp_path)
                print(f"Plot saved as HTML to: {temp_path}")
                print("Please open this file in your web browser to view the plot.")

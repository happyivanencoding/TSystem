import pandas as pd
import numpy as np
import datetime
from dateutil import relativedelta
import os
import copy
from tp_core.optimisation import (
    add_dev_facto,
    add_dev_secto,
    optimizer,
    transform_flag_to_theme,
    turnover,
)

def create_mock_tech_data(num_stocks=50):
    """创建模拟技术面数据"""
    np.random.seed(42)
    
    isins = [f'ISIN{i:06d}' for i in range(num_stocks)]
    
    industries = ['Auto & Parts', 'Banks', 'Basic Resources', 'Chemicals', 
                  'Construction & Materials', 'Financial Services', 'Food, Beverage & Tobacco',
                  'Health Care', 'Industrial Goods & Services', 'Insurance', 'Media', 'Energy',
                  'Personal & Household Goods', 'Real Estate', 'Retail', 'Technology',
                  'Telecommunications', 'Travel & Leisure', 'Utilities']
    
    data = {
        'Date': [datetime.date.today() - datetime.timedelta(days=5)] * num_stocks,
        'Company Name': [f'Company {i}' for i in range(num_stocks)],
        'FactSet Ind': np.random.choice(industries, num_stocks),
        ' Benchmark ICB Supersector ': np.random.choice(industries, num_stocks),
        'Weight in MSCI ACWI': np.random.uniform(0.0001, 0.01, num_stocks),
        'Weight in univ norm': np.random.uniform(0.0001, 0.01, num_stocks),
        'Benchmark Market Value Millions in EUR': np.random.uniform(1000, 50000, num_stocks),
        'Growth Avg Percentile': np.random.uniform(0, 1, num_stocks),
        'LowVol Avg Percentile': np.random.uniform(0, 1, num_stocks),
        'Mom Avg Percentile': np.random.uniform(0, 1, num_stocks),
        'Quality Avg Percentile': np.random.uniform(0, 1, num_stocks),
        'Value Avg Percentile': np.random.uniform(0, 1, num_stocks),
        'Size Avg Percentile': np.random.uniform(0, 1, num_stocks)
    }
    
    return pd.DataFrame(data, index=isins)

def create_mock_mapping_data():
    """创建模拟映射表数据"""
    industries = ['Auto & Parts', 'Banks', 'Basic Resources', 'Chemicals', 
                  'Construction & Materials', 'Financial Services', 'Food, Beverage & Tobacco',
                  'Health Care', 'Industrial Goods & Services', 'Insurance', 'Media', 'Energy',
                  'Personal & Household Goods', 'Real Estate', 'Retail', 'Technology',
                  'Telecommunications', 'Travel & Leisure', 'Utilities']
    
    fs_industries = ['Automobiles', 'Banking', 'Materials', 'Chemicals', 
                    'Construction', 'Financial Services', 'Food & Beverage',
                    'Healthcare', 'Industrials', 'Insurance', 'Media', 'Energy',
                    'Consumer Goods', 'Real Estate', 'Retail', 'Technology',
                    'Telecom', 'Travel', 'Utilities']
    
    data = {
        ' Benchmark ICB Supersector ': industries,
        'FactSet Ind': fs_industries,
        'Transco_ICB_19': industries,
        'ICB19_ID': list(range(1, 20))
    }
    
    return pd.DataFrame(data)

def create_mock_old_portfolio(tech_data=None, num_stocks=30):
    """创建模拟旧投资组合数据"""
    if tech_data is not None:
        sample_size = min(num_stocks, len(tech_data))
        indices = np.random.choice(tech_data.index, sample_size, replace=False)
        old_portfolio = tech_data.loc[indices].copy()
        weights = np.random.uniform(0.01, 0.1, sample_size)
        old_portfolio['Weight'] = weights / weights.sum()
        return old_portfolio
    else:
        mock_data = create_mock_tech_data(num_stocks)
        weights = np.random.uniform(0.01, 0.1, num_stocks)
        mock_data['Weight'] = weights / weights.sum()
        return mock_data

def push_mf_tilt_bloom_new(file_tech, file_fonda=None, region="EU", output_dir=None, curr_path=None, 
                          percentile=0.7, old_ptf=None, cut_mkt_cap=0,
                          reco_secto=None, reco_facto=None):
    """
    创建多因子倾斜的投资组合
    
    参数:
        file_tech (pd.DataFrame): 技术面数据DataFrame
        file_fonda (pd.DataFrame, optional): 基本面数据DataFrame
        region (str): 区域代码，如'EU', 'US'等
        output_dir (str): 输出目录路径，如果为None则不输出文件
        curr_path (pd.DataFrame): 映射表DataFrame
        percentile (float): 百分位数阈值
        old_ptf (pd.DataFrame): 旧投资组合DataFrame
        cut_mkt_cap (float): 市值截断阈值
        reco_secto (list): 19个行业的权重推荐列表
        reco_facto (list): 5个因子的权重推荐列表
    
    返回:
        pd.DataFrame: 生成的投资组合数据
    """
    if reco_secto is None:
        reco_secto = [0.05] * 19
    if reco_facto is None:
        reco_facto = [0.2] * 5

    list_score_col = ["Growth Avg Percentile", "LowVol Avg Percentile", "Mom Avg Percentile", 
                      "Quality Avg Percentile", "Value Avg Percentile", "Size Avg Percentile"]
    
    # 处理输入数据
    df = file_tech.copy()
    df_mapping = curr_path.copy() if curr_path is not None else create_mock_mapping_data()
    
    # 数据清洗和预处理
    df = df[~df.index.duplicated(keep='first')]
    df = df.loc[df.index.notna()]
    df = df.loc[(df['Weight in MSCI ACWI'] > 0) & (pd.isna(df['FactSet Ind']) == False)]
    
    # 处理日期
    date = pd.to_datetime(df['Date'].iloc[0]) + relativedelta.relativedelta(months=1, day=1)
    
    # 如果提供了不同的基本面数据
    if file_fonda is not None and not file_fonda is file_tech:
        df2 = file_fonda.copy()
        df2 = df2[~df2.index.duplicated(keep='first')]
        df2 = df2.loc[df2.index.notna()]
        df2 = df2.loc[(df2['Weight in MSCI ACWI'] > 0) & (pd.isna(df2['FactSet Ind']) == False)]
        df.drop(["Growth Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"], axis=1, inplace=True)    
        df = pd.merge(df, df2[["Growth Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"]], 
                      how='left', left_index=True, right_index=True)
    
    # 处理缺失的市值数据
    if 'Benchmark Market Value Millions in EUR' in df.columns:
        valid_mask = pd.isna(df['Benchmark Market Value Millions in EUR']) == False
        if valid_mask.any():
            fit = np.polyfit(df.loc[valid_mask, 'Weight in MSCI ACWI'],
                             df.loc[valid_mask, 'Benchmark Market Value Millions in EUR'], deg=1)
            func = np.poly1d(fit)
            df.loc[~valid_mask, 'Benchmark Market Value Millions in EUR'] = func(df.loc[~valid_mask, 'Weight in MSCI ACWI'])
    
    # 基于区域设置参数
    mkt_cap_min = 2000  # 默认值
    if region == 'EU' or region == 'Europe':
        # 检查'Weight in STOXX EUROPE 600'列是否存在
        if 'Weight in STOXX EUROPE 600' in df.columns:
            df = df.loc[df['Weight in STOXX EUROPE 600'] > 0]
        ptf_name = [["EU_MFT_" + date.strftime('%Y%m%d')]]
        mkt_cap_min = 2000
    elif region == 'US':
        # 检查'Exchange Country Name'列是否存在
        if 'Exchange Country Name' in df.columns:
            df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        ptf_name = [["US_MFT_" + date.strftime('%Y%m%d')]]
        mkt_cap_min = 4000
    
    # 应用市值截断
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap
    
    # 基于市值筛选因子得分
    for i in range(len(list_score_col)):
        if list_score_col[i] != "Size Avg Percentile" and list_score_col[i] in df.columns:
            df.loc[df.get('Benchmark Market Value Millions in EUR', np.inf) <= mkt_cap_min, list_score_col[i]] = np.NaN
    
    if "Size Avg Percentile" in df.columns:
        df.loc[df.get('Benchmark Market Value Millions in EUR', np.inf) <= (mkt_cap_min/10), "Size Avg Percentile"] = np.NaN
    
    # 计算多因子平均得分
    score_cols = [col for col in list_score_col[:-1] if col in df.columns]
    if score_cols:
        df['Multi Avg Percentile'] = df[score_cols].mean(skipna=False, axis=1)
        list_score_col.append("Multi Avg Percentile")
    
    # 输出目录处理
    if output_dir:
        month_dir = os.path.join(output_dir, "Pour " + date.strftime("%B %Y"))
        os.makedirs(month_dir, exist_ok=True)
    
    # 更新日期
    df['Date'] = date
    
    # 对因子得分进行归一化
    avail_score_cols = [col for col in list_score_col if col in df.columns]
    if avail_score_cols:
        df[avail_score_cols] = df[avail_score_cols].rank(pct=True)
        min_vals = df[avail_score_cols].min()
        max_vals = df[avail_score_cols].max()
        for col in avail_score_cols:
            if max_vals[col] > min_vals[col]:
                df[col] = (df[col] - min_vals[col])/(max_vals[col] - min_vals[col])
    
    # 将ICB行业代码映射
    if ' Benchmark ICB Supersector ' in df.columns and 'ICB19_ID' in df_mapping.columns:
        df = df.reset_index()
        icb_mapping = df_mapping.loc[df_mapping['ICB19_ID'].notna(), [' Benchmark ICB Supersector ', 'ICB19_ID']]
        df = df.merge(icb_mapping, how='left', on=' Benchmark ICB Supersector ')
        df.set_index('ISIN', inplace=True)
    
    # 将FactSet行业映射到ICB19
    if 'FactSet Ind' in df.columns and 'Transco_ICB_19' in df_mapping.columns:
        fs_icb = df_mapping[['FactSet Ind', 'Transco_ICB_19']].copy()
        fs_icb.rename(columns={'Transco_ICB_19': 'ICB19'}, inplace=True)
        df = df.reset_index()
        df = df.merge(fs_icb, how='left', on='FactSet Ind')
        df.set_index('ISIN', inplace=True)
        df.loc[df[' Benchmark ICB Supersector '] == 0, ' Benchmark ICB Supersector '] = df.loc[df[' Benchmark ICB Supersector '] == 0, 'ICB19'].values
    
    # 立方根转换市值
    if 'Benchmark Market Value Millions in EUR' in df.columns:
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    
    # 计算行业权重
    weight_secto_bench = None
    if ' Benchmark ICB Supersector ' in df.columns and 'Weight in MSCI ACWI' in df.columns:
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
    
    # 对每个行业内部的多因子得分进行归一化
    if 'Multi Avg Percentile' in df.columns and ' Benchmark ICB Supersector ' in df.columns:
        for secto in np.unique(df[' Benchmark ICB Supersector ']):
            sector_mask = df[' Benchmark ICB Supersector '] == secto
            if sector_mask.any():
                sector_scores = df.loc[sector_mask, 'Multi Avg Percentile']
                df.loc[sector_mask, 'Multi Avg Percentile'] = sector_scores.rank(pct=True)
                min_val = sector_scores.min()
                max_val = sector_scores.max()
                if max_val > min_val:
                    df.loc[sector_mask, 'Multi Avg Percentile'] = (sector_scores - min_val)/(max_val - min_val)
    
    # 结果列
    columns = ['PTF', 'ISIN', 'ICB19', 'Weight', 'Score', 'Date', 'Success', 'Poids secto base', 
              'Poids secto modif', 'Poids facto base', 'Poids facto modif', 'Turnover']
    
    # 选择股票
    nb_securities = round(len(df.loc[pd.isna(df.get('Multi Avg Percentile', np.nan)) == False]) * percentile)
    df_top = df.nlargest(nb_securities, 'Multi Avg Percentile')
    
    # 创建结果DataFrame
    result_df = pd.DataFrame(columns=columns)
    result_df['ISIN'] = df_top.index
    result_df['ICB19'] = df_top[' Benchmark ICB Supersector '].values if ' Benchmark ICB Supersector ' in df_top.columns else None
    result_df['Weight'] = df_top.get('Benchmark Market Value Millions in EUR', 1).values
    result_df['Score'] = df_top.get('Multi Avg Percentile', 0).values
    result_df['PTF'] = f"{region}_MFT_{date.strftime('%Y%m%d')}"
    result_df['Date'] = date
    result_df['Success'] = 1
    
    # 按行业重新平衡权重
    if weight_secto_bench is not None and 'ICB19' in result_df.columns:
        for secto in result_df['ICB19'].unique():
            sector_mask = result_df['ICB19'] == secto
            if sector_mask.any() and secto in weight_secto_bench.index:
                sector_weight_sum = result_df.loc[sector_mask, 'Weight'].sum()
                if sector_weight_sum > 0:
                    result_df.loc[sector_mask, 'Weight'] = result_df.loc[sector_mask, 'Weight'] * weight_secto_bench.loc[secto] / sector_weight_sum
    
    # 归一化权重
    weight_sum = result_df['Weight'].sum()
    if weight_sum > 0:
        result_df['Weight'] = result_df['Weight'] / weight_sum
    
    # 如果需要应用因子倾斜和行业倾斜
    if (np.sum(np.abs(reco_facto)) != 0 or np.sum(np.abs(reco_secto)) != 0) and all(col in df_top.columns for col in 
                                                                   ["Growth Avg Percentile", "LowVol Avg Percentile", 
                                                                    "Mom Avg Percentile", "Quality Avg Percentile", 
                                                                    "Value Avg Percentile"]):
        # 添加因子标志列
        result_df[["Growth Avg Percentile", "LowVol Avg Percentile", "Mom Avg Percentile", 
                  "Quality Avg Percentile", "Value Avg Percentile"]] = df_top[
                  ["Growth Avg Percentile", "LowVol Avg Percentile", "Mom Avg Percentile", 
                   "Quality Avg Percentile", "Value Avg Percentile"]].values
        
        # 创建因子标志
        result_df[["Growth Flag", "LowVol Flag", "Mom Flag", "Quality Flag", "Value Flag"]] = 0
        result_df.loc[result_df["Growth Avg Percentile"] >= 0.8, "Growth Flag"] = 1
        result_df.loc[result_df["LowVol Avg Percentile"] >= 0.8, "LowVol Flag"] = 1
        result_df.loc[result_df["Mom Avg Percentile"] >= 0.8, "Mom Flag"] = 1
        result_df.loc[result_df["Quality Avg Percentile"] >= 0.8, "Quality Flag"] = 1
        result_df.loc[result_df["Value Avg Percentile"] >= 0.8, "Value Flag"] = 1
        
        # 准备优化约束
        theme_facto = np.concatenate((
            transform_flag_to_theme(result_df['Growth Flag'], True),
            transform_flag_to_theme(result_df['LowVol Flag'], True),
            transform_flag_to_theme(result_df['Mom Flag'], True),
            transform_flag_to_theme(result_df['Quality Flag'], True),
            transform_flag_to_theme(result_df['Value Flag'], True)), axis=0)
        
        theme_secto = transform_flag_to_theme(result_df['ICB19']) if 'ICB19' in result_df.columns else np.array([])
        
        # 检查是否有缺失的行业
        icb_missing = set()
        if 'ICB19' in result_df.columns:
            icb_missing = set(range(1, 20)) - set(result_df['ICB19'].unique())
        
        # 设置权重上下界
        lb = [0.001] * len(result_df)  # 权重下界
        ub = [0.10] * len(result_df)   # 权重上界
        
        # 计算每个行业的票数
        nb_titres = np.zeros(19)
        if 'ICB19' in result_df.columns:
            for i in range(1, 20):
                nb_titres[i-1] = len(result_df[result_df['ICB19'] == i])
        
        # 计算行业权重上下限
        max_secto = nb_titres * 0.10  # 假设单只票最大权重10%
        min_secto = nb_titres * 0.001 # 假设单只票最小权重0.1%
        
        # 处理缺失行业
        if len(icb_missing) == 0 and 'ICB19' in result_df.columns:
            weight_ref_optim = weight_secto_bench.copy() if weight_secto_bench is not None else None
            ub_secto = max_secto.copy()
            lb_secto = min_secto.copy()
        else:
            weight_ref_optim = None
            if weight_secto_bench is not None:
                weight_ref_optim = weight_secto_bench.copy()
                for icb19 in icb_missing:
                    if int(icb19) in weight_ref_optim.index:
                        weight_ref_optim = weight_ref_optim.drop([int(icb19)])
                
            ub_secto = max_secto.copy()
            lb_secto = min_secto.copy()
            if icb_missing:
                reco_secto_adjusted = list(reco_secto)
                for icb19 in sorted(icb_missing, reverse=True):
                    ub_secto = np.delete(ub_secto, int(icb19) - 1)
                    lb_secto = np.delete(lb_secto, int(icb19) - 1)
                    if int(icb19) - 1 < len(reco_secto_adjusted):
                        del reco_secto_adjusted[int(icb19) - 1]
                reco_secto = reco_secto_adjusted
        
        # 初始权重
        x0 = result_df['Weight'].values
        
        # 约束矩阵
        A = np.array([])
        if len(theme_facto) > 0 and len(theme_secto) > 0:
            A = np.concatenate((theme_facto, theme_secto, theme_facto*(-1), theme_secto*(-1)), axis=0)
        elif len(theme_facto) > 0:
            A = np.concatenate((theme_facto, theme_facto*(-1)), axis=0)
        elif len(theme_secto) > 0:
            A = np.concatenate((theme_secto, theme_secto*(-1)), axis=0)
        
        # 等式约束 (权重和为1)
        eq_cons_sum = np.array([1])
        
        # 旧权重 (用于计算换手率)
        old_weight = result_df['Weight'].values
        
        # 计算因子权重
        facto_repart = pd.Series([0.0] * 5)
        if all(col in result_df.columns for col in ["Growth Flag", "LowVol Flag", "Mom Flag", "Quality Flag", "Value Flag"]):
            facto_repart = result_df['Weight'].dot(result_df[["Growth Flag", "LowVol Flag", "Mom Flag", "Quality Flag", "Value Flag"]])
        
        # 计算行业和因子权重的变化范围
        weight_min_secto = None
        weight_max_secto = None
        weight_min_facto = None
        weight_max_facto = None
        
        if weight_ref_optim is not None and len(reco_secto) > 0:
            weight_min_secto, weight_max_secto = add_dev_secto(weight_ref_optim, reco_secto, ub_secto, lb_secto)
        
        if len(reco_facto) > 0:
            weight_min_facto, weight_max_facto = add_dev_facto(facto_repart, reco_facto)
        
        # 创建不等式约束
        ineq = np.array([])
        if weight_min_facto is not None and weight_min_secto is not None:
            ineq = np.concatenate((weight_min_facto, weight_min_secto, weight_max_facto*(-1), weight_max_secto*(-1)), axis=0)
        elif weight_min_facto is not None:
            ineq = np.concatenate((weight_min_facto, weight_max_facto*(-1)), axis=0)
        elif weight_min_secto is not None:
            ineq = np.concatenate((weight_min_secto, weight_max_secto*(-1)), axis=0)
        
        # 如果有足够的约束条件，进行优化
        if len(A) > 0 and len(ineq) > 0:
            # 换手率约束（默认为30%）
            ineq_turnover = 0.3
            
            # 执行优化
            i = 1
            weights = None
            success = False
            obj = 0
            
            # 尝试优化，如果失败则放宽约束
            if old_ptf is not None:
                try:
                    # 检查约束矩阵和约束向量的尺寸是否匹配
                    if A.shape[0] != len(ineq):
                        print(f"警告: 约束矩阵A的行数 ({A.shape[0]}) 与约束向量ineq的长度 ({len(ineq)}) 不匹配")
                        print("跳过优化步骤，使用初始权重")
                        weights = x0
                        success = False
                        obj = 0
                    else:
                        # 计算优化后的权重
                        weights, success, obj = optimizer(turnover, x0, A, eq_cons_sum, ineq, ub, lb, old_weight, ineq_turnover)
                        
                        # 如果优化失败，放宽约束重试
                        while success == False and i < 40 and np.prod(A @ weights - ineq >= 0) == 0:
                            i += 1
                            if weight_min_facto is not None:
                                weight_min_facto[weight_min_facto > 0.01] -= 0.01
                            if weight_max_facto is not None:
                                weight_max_facto[weight_max_facto < 0.99] += 0.01
                            
                            # 更新不等式约束
                            if weight_min_facto is not None and weight_min_secto is not None:
                                ineq = np.concatenate((weight_min_facto, weight_min_secto, weight_max_facto*(-1), weight_max_secto*(-1)), axis=0)
                            elif weight_min_facto is not None:
                                ineq = np.concatenate((weight_min_facto, weight_max_facto*(-1)), axis=0)
                            elif weight_min_secto is not None:
                                ineq = np.concatenate((weight_min_secto, weight_max_secto*(-1)), axis=0)
                            
                            # 再次尝试优化
                            if A.shape[0] == len(ineq):
                                weights, success, obj = optimizer(turnover, x0, A, eq_cons_sum, ineq, ub, lb, old_weight, ineq_turnover)
                            else:
                                print(f"警告: 优化过程中约束尺寸不匹配 A: {A.shape}, ineq: {len(ineq)}")
                                break
                except Exception as e:
                    print(f"优化过程中发生错误: {str(e)}")
                    print("使用初始权重")
                    weights = x0
                    success = False
                    obj = 0
            
            # 更新权重
            if weights is not None:
                result_df['Weight'] = weights
            
            # 记录优化成功状态
            result_df['Success'] = i

        # 记录因子和行业基准以及实际权重
        result_df['Poids secto base'] = str(weight_secto_bench.tolist()) if weight_secto_bench is not None else None
        result_df['Poids secto modif'] = str(result_df.groupby('ICB19')['Weight'].sum().tolist()) if 'ICB19' in result_df.columns else None
        
        # 计算和记录因子权重
        facto_weights = pd.Series([0.0] * 5)
        if all(col in result_df.columns for col in ["Growth Flag", "LowVol Flag", "Mom Flag", "Quality Flag", "Value Flag"]):
            facto_weights = result_df['Weight'].dot(result_df[["Growth Flag", "LowVol Flag", "Mom Flag", "Quality Flag", "Value Flag"]])
        
        result_df['Poids facto base'] = str(facto_repart.tolist()) if not facto_repart.empty else None
        result_df['Poids facto modif'] = str(facto_weights.tolist()) if not facto_weights.empty else None
        result_df['Turnover'] = obj if 'obj' in locals() else 0
    
    # 输出到文件（如果指定了输出目录）
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{region}_MFT_{date.strftime('%Y%m%d')}.csv")
        result_df.to_csv(output_file, index=False)
    
    return result_df

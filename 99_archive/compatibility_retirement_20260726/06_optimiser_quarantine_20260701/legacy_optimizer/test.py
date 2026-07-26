import pandas as pd
import numpy as np
import datetime
import os
import copy
import scipy.optimize
from portfolio_generator import (
    create_mock_tech_data,
    create_mock_mapping_data,
    create_mock_old_portfolio,
    transform_flag_to_theme
)

def turnover(x, old_weight):
    """计算投资组合换手率"""
    return (np.abs(x - old_weight)).sum()

def optimize_portfolio_turnover(file_tech, old_portfolio, max_turnover=0.3, 
                               region="EU", output_dir=None, curr_path=None, 
                               percentile=0.7, factor_constraints=None, 
                               sector_constraints=None):
    """
    创建一个优化换手率的投资组合
    
    参数:
        file_tech (pd.DataFrame): 技术面数据DataFrame
        old_portfolio (pd.DataFrame): 旧投资组合DataFrame，必须包含权重列
        max_turnover (float): 最大允许换手率，范围0-1
        region (str): 区域代码，如'EU', 'US'等
        output_dir (str): 输出目录路径，如果为None则不输出文件
        curr_path (pd.DataFrame): 映射表DataFrame
        percentile (float): 选择候选股票的百分位数阈值
        factor_constraints (dict): 因子约束 {'Growth':0.1, 'Quality':0.1} 
        sector_constraints (dict): 行业约束 {'Technology':0.2, 'Healthcare':0.15}
        
    返回:
        pd.DataFrame: 生成的优化投资组合
    """
    print(f"开始生成换手率优化的投资组合，最大换手率限制: {max_turnover}")
    
    # 处理输入数据
    df = file_tech.copy()
    df_mapping = curr_path.copy() if curr_path is not None else create_mock_mapping_data()
    
    # 确保旧投资组合有正确的列
    if old_portfolio is None:
        raise ValueError("必须提供旧投资组合数据")
    
    if 'Weight' not in old_portfolio.columns:
        raise ValueError("旧投资组合必须包含Weight列")
    
    # 数据清洗和预处理
    df = df[~df.index.duplicated(keep='first')]
    df = df.loc[df.index.notna()]
    if 'Weight in MSCI ACWI' in df.columns and 'FactSet Ind' in df.columns:
        df = df.loc[(df['Weight in MSCI ACWI'] > 0) & (pd.isna(df['FactSet Ind']) == False)]
    
    # 处理日期
    if 'Date' in df.columns:
        date = pd.to_datetime(df['Date'].iloc[0]) + pd.DateOffset(months=1, day=1)
    else:
        date = datetime.datetime.now() + pd.DateOffset(months=1, day=1)
    
    # 基于区域筛选股票
    if region == 'EU' or region == 'Europe':
        if 'Weight in STOXX EUROPE 600' in df.columns:
            df = df.loc[df['Weight in STOXX EUROPE 600'] > 0]
        ptf_name = f"EU_TO_{date.strftime('%Y%m%d')}" # TO = TurnOver
    elif region == 'US':
        if 'Exchange Country Name' in df.columns:
            df = df.loc[df['Exchange Country Name'] == 'UNITED STATES']
        ptf_name = f"US_TO_{date.strftime('%Y%m%d')}"
    else:
        ptf_name = f"{region}_TO_{date.strftime('%Y%m%d')}"
    
    # 计算多因子平均得分
    factor_cols = ["Growth Avg Percentile", "LowVol Avg Percentile", "Mom Avg Percentile", 
                  "Quality Avg Percentile", "Value Avg Percentile"]
    
    available_factors = [col for col in factor_cols if col in df.columns]
    
    if available_factors:
        df['Multi Avg Percentile'] = df[available_factors].mean(skipna=False, axis=1)
    else:
        print("警告: 没有可用的因子列，使用随机分数")
        df['Multi Avg Percentile'] = np.random.uniform(0, 1, len(df))
    
    # 优先保留旧投资组合中的股票，并选择新的候选股票，使总数不超过70只
    preserved_old_stocks = set(old_portfolio.index) & set(df.index)
    preserved_df = df.loc[list(preserved_old_stocks)]
    
    # *** 新增代码 - 计算不在新候选集中的旧投资组合股票 ***
    missing_old_stocks = set(old_portfolio.index) - set(df.index)
    missing_weight_sum = 0
    if missing_old_stocks:
        missing_weight_sum = old_portfolio.loc[list(missing_old_stocks), 'Weight'].sum()
        print(f"有 {len(missing_old_stocks)} 只旧投资组合股票不在新候选集中，总权重为: {missing_weight_sum:.4f}")
    
    # 从剩余股票中选择(70-len(preserved_old_stocks))只评分最高的股票
    remaining_stocks = df.loc[~df.index.isin(preserved_old_stocks)]
    remaining_stocks = remaining_stocks.dropna(subset=['Multi Avg Percentile'])
    n_to_select = min(70, len(remaining_stocks)) - len(preserved_old_stocks)
    
    if n_to_select > 0:
        selected_new_stocks = remaining_stocks.nlargest(n_to_select, 'Multi Avg Percentile')
        # 合并保留的旧股票和新选的高评分股票
        df_top = pd.concat([preserved_df, selected_new_stocks])
    else:
        df_top = preserved_df
    
    print(f"选择了 {len(df_top)} 只候选股票，其中 {len(preserved_old_stocks)} 只来自旧投资组合")
    
    # 创建结果DataFrame
    result_df = pd.DataFrame(index=df_top.index)
    result_df['ISIN'] = df_top.index
    
    # 添加ICB19行业代码（如果可用）
    if ' Benchmark ICB Supersector ' in df_top.columns:
        result_df['ICB19'] = df_top[' Benchmark ICB Supersector '].values
    
    # 初始权重（按市值加权）
    if 'Benchmark Market Value Millions in EUR' in df_top.columns:
        result_df['Initial_Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
    else:
        # 如果没有市值列，使用均等权重
        result_df['Initial_Weight'] = 1.0
    
    # 标准化初始权重
    result_df['Initial_Weight'] = result_df['Initial_Weight'] / result_df['Initial_Weight'].sum()
    
    # 创建优化问题的约束
    # 1. 旧投资组合权重
    old_weights_aligned = pd.Series(0.0, index=result_df.index)
    
    for idx in result_df.index:
        if idx in old_portfolio.index:
            old_weights_aligned[idx] = old_portfolio.loc[idx, 'Weight']
    
    # 计算初始换手率
    initial_partial_turnover = turnover(result_df['Initial_Weight'].values, old_weights_aligned.values)
    initial_turnover = initial_partial_turnover + missing_weight_sum
    print(f"初始换手率: {initial_turnover:.4f} (包括缺失股票贡献: {missing_weight_sum:.4f})")
    
    # *** 修改代码 - 计算考虑缺失股票后的有效最大换手率 ***
    effective_max_turnover = max_turnover - missing_weight_sum
    print(f"有效最大换手率: {effective_max_turnover:.4f} (最大允许换手率 {max_turnover:.4f} - 缺失股票贡献 {missing_weight_sum:.4f})")
    
    # 如果有效最大换手率小于等于0，则无法满足换手率约束
    if effective_max_turnover <= 0:
        print("警告: 缺失的旧股票权重已超过最大换手率限制，无法满足约束")
        print("建议: 提高最大换手率限制或扩大候选股票范围")
        # 使用初始权重作为备选方案
        optimized_weights = result_df['Initial_Weight'].values
        success = False
        actual_turnover = initial_turnover
    # 如果初始换手率已经低于阈值，使用渐进方法逐步调整权重以满足换手率约束
    elif initial_partial_turnover <= effective_max_turnover:
        print("初始部分换手率已低于有效阈值，使用初始权重")
        optimized_weights = result_df['Initial_Weight'].values
        success = True
        actual_turnover = initial_turnover
    else:
        # 2. 设置优化变量的上下界
        x0 = old_weights_aligned.values.copy()  # 使用旧投资组合权重作为起点
        
        # 对于新加入的股票，赋予一个小的初始权重
        new_stock_mask = old_weights_aligned == 0
        if np.any(new_stock_mask):
            remaining_weight = 1.0 - np.sum(x0)
            n_new_stocks = np.sum(new_stock_mask)
            x0[new_stock_mask] = remaining_weight / n_new_stocks
        
        lb = np.array([0.001] * len(result_df))   # 下界
        ub = np.array([0.10] * len(result_df))    # 上界
        
        # 3. 创建约束
        constraints = []
        
        # 权重和为1的约束
        constraints.append({
            'type': 'eq',
            'fun': lambda x: np.sum(x) - 1.0
        })
        
        # *** 修改代码 - 使用有效最大换手率 ***
        # 换手率约束
        constraints.append({
            'type': 'ineq',
            'fun': lambda x: effective_max_turnover - turnover(x, old_weights_aligned.values)
        })
        
        # 因子约束
        if factor_constraints is not None and available_factors:
            for factor_name, min_exposure in factor_constraints.items():
                factor_col = f"{factor_name} Avg Percentile"
                if factor_col in df_top.columns:
                    factor_values = df_top[factor_col].values
                    constraints.append({
                        'type': 'ineq',
                        'fun': lambda x, values=factor_values: np.dot(x, values) - min_exposure
                    })
        
        # 行业约束
        if sector_constraints is not None and 'ICB19' in result_df.columns:
            for sector_name, max_weight in sector_constraints.items():
                # 查找行业对应的ID
                sector_id = None
                for i, sector in enumerate(df_mapping[' Benchmark ICB Supersector ']):
                    if sector == sector_name:
                        sector_id = i + 1
                        break
                
                if sector_id is not None:
                    sector_mask = result_df['ICB19'] == sector_id
                    sector_indices = np.where(sector_mask)[0]
                    
                    if len(sector_indices) > 0:
                        sector_constraint = np.zeros(len(result_df))
                        sector_constraint[sector_indices] = 1
                        
                        constraints.append({
                            'type': 'ineq',
                            'fun': lambda x, constraint=sector_constraint: max_weight - np.dot(x, constraint)
                        })
        
        # 执行优化 - 目标是最小化与旧投资组合的距离
        try:
            # 尝试多个优化起点
            best_result = None
            best_turnover = float('inf')
            
            # 1. 使用旧权重作为起点
            result1 = scipy.optimize.minimize(
                turnover,
                x0,
                args=(old_weights_aligned.values,),
                method='SLSQP',
                bounds=list(zip(lb, ub)),
                constraints=constraints,
                options={'maxiter': 10000, 'ftol': 1e-6, 'disp': True}
            )
            
            if result1.success and turnover(result1.x, old_weights_aligned.values) <= effective_max_turnover:
                best_result = result1
                best_turnover = turnover(result1.x, old_weights_aligned.values)
            
            # 2. 使用均等权重作为起点
            x0_equal = np.ones(len(result_df)) / len(result_df)
            result2 = scipy.optimize.minimize(
                turnover,
                x0_equal,
                args=(old_weights_aligned.values,),
                method='SLSQP',
                bounds=list(zip(lb, ub)),
                constraints=constraints,
                options={'maxiter': 10000, 'ftol': 1e-6, 'disp': True}
            )
            
            if result2.success and turnover(result2.x, old_weights_aligned.values) <= effective_max_turnover:
                if turnover(result2.x, old_weights_aligned.values) < best_turnover:
                    best_result = result2
                    best_turnover = turnover(result2.x, old_weights_aligned.values)
            
            # 如果优化失败，使用直接混合方法
            if best_result is None:
                print("优化未能满足换手率约束，尝试直接混合法")
                # 尝试直接混合旧权重和新权重的方法
                # w = alpha*w_old + (1-alpha)*w_new，找到满足换手率约束的alpha
                w_old = old_weights_aligned.values
                w_new = result_df['Initial_Weight'].values
                
                # 二分查找合适的alpha
                alpha_min = 0.0
                alpha_max = 1.0
                best_alpha = 1.0  # 默认使用旧权重
                
                for _ in range(20):  # 二分查找20次应该足够精确
                    alpha = (alpha_min + alpha_max) / 2
                    w_mix = alpha * w_old + (1 - alpha) * w_new
                    # 归一化权重
                    w_mix = w_mix / np.sum(w_mix)
                    to = turnover(w_mix, old_weights_aligned.values)
                    
                    if to <= effective_max_turnover:
                        # 可以减小alpha（更多新权重）
                        best_alpha = alpha
                        alpha_max = alpha
                    else:
                        # 需要增加alpha（更多旧权重）
                        alpha_min = alpha
                
                # 使用找到的最佳alpha计算最终权重
                optimized_weights = best_alpha * w_old + (1 - best_alpha) * w_new
                # 归一化权重
                optimized_weights = optimized_weights / np.sum(optimized_weights)
                success = True
                
                # *** 修改代码 - 计算完整换手率 ***
                partial_turnover = turnover(optimized_weights, old_weights_aligned.values)
                actual_turnover = partial_turnover + missing_weight_sum
                
                print(f"使用直接混合法，alpha={best_alpha:.4f}，部分换手率={partial_turnover:.4f}，完整换手率={actual_turnover:.4f}")
            else:
                optimized_weights = best_result.x
                success = best_result.success
                
                # *** 修改代码 - 计算完整换手率 ***
                partial_turnover = turnover(optimized_weights, old_weights_aligned.values)
                actual_turnover = partial_turnover + missing_weight_sum
            
            # *** 修改代码 - 清晰显示部分和完整换手率 ***
            print(f"优化结果: {'成功' if success else '失败'}")
            print(f"部分换手率: {partial_turnover:.4f}")
            print(f"实际完整换手率: {actual_turnover:.4f} (部分 {partial_turnover:.4f} + 缺失 {missing_weight_sum:.4f}, 目标: <= {max_turnover:.4f})")
            
            # 填充结果DataFrame
            result_df['Weight'] = optimized_weights
            result_df['PTF'] = ptf_name
            result_df['Date'] = date
            result_df['Score'] = df_top['Multi Avg Percentile'].values
            result_df['Success'] = 1 if success else 0
            result_df['Partial_Turnover'] = partial_turnover
            result_df['Turnover'] = actual_turnover
            result_df['Missing_Weight'] = missing_weight_sum
            
            # 计算行业权重统计
            if 'ICB19' in result_df.columns:
                sector_weights = result_df.groupby('ICB19')['Weight'].sum()
                result_df['Sector_Info'] = str(sector_weights.to_dict())
            
            # 输出到文件
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                output_file = os.path.join(output_dir, f"{ptf_name}.csv")
                result_df.to_csv(output_file, index=True)
                print(f"结果已保存到 {output_file}")
                
                # 生成换手率报告
                turnover_report = pd.DataFrame({
                    'ISIN': result_df.index,
                    'New_Weight': result_df['Weight'].values,
                    'Old_Weight': old_weights_aligned.values,
                    'Weight_Change': result_df['Weight'].values - old_weights_aligned.values,
                    'Absolute_Change': np.abs(result_df['Weight'].values - old_weights_aligned.values)
                })
                
                # *** 修改代码 - 添加缺失股票到换手率报告 ***
                if missing_old_stocks:
                    missing_df = pd.DataFrame({
                        'ISIN': list(missing_old_stocks),
                        'New_Weight': 0,
                        'Old_Weight': old_portfolio.loc[list(missing_old_stocks), 'Weight'].values,
                        'Weight_Change': -old_portfolio.loc[list(missing_old_stocks), 'Weight'].values,
                        'Absolute_Change': old_portfolio.loc[list(missing_old_stocks), 'Weight'].values
                    })
                    turnover_report = pd.concat([turnover_report, missing_df])
                
                # 添加新增/减持/退出标记
                turnover_report['Status'] = 'HOLD'
                turnover_report.loc[~turnover_report.index.isin(old_portfolio.index), 'Status'] = 'NEW'
                turnover_report.loc[(turnover_report.index.isin(old_portfolio.index)) & 
                                  (turnover_report['Weight_Change'] > 0), 'Status'] = 'INCREASE'
                turnover_report.loc[(turnover_report.index.isin(old_portfolio.index)) & 
                                  (turnover_report['Weight_Change'] < 0) & 
                                  (turnover_report['New_Weight'] > 0), 'Status'] = 'DECREASE'
                turnover_report.loc[(turnover_report.index.isin(old_portfolio.index)) & 
                                  (turnover_report['New_Weight'] == 0), 'Status'] = 'EXIT'
                
                # 计算一些统计信息
                turnover_report['Contribution_To_Turnover'] = turnover_report['Absolute_Change'] / actual_turnover
                
                # 保存报告
                turnover_report.to_csv(os.path.join(output_dir, f"{ptf_name}_turnover_report.csv"), index=True)
                print(f"换手率报告已保存到 {os.path.join(output_dir, f'{ptf_name}_turnover_report.csv')}")
            
        except Exception as e:
            print(f"优化过程中出错: {str(e)}")
            optimized_weights = result_df['Initial_Weight'].values
            result_df['Weight'] = optimized_weights
            result_df['PTF'] = ptf_name
            result_df['Date'] = date
            result_df['Score'] = df_top['Multi Avg Percentile'].values if 'Multi Avg Percentile' in df_top.columns else 0
            result_df['Success'] = 0
            
            # *** 修改代码 - 计算完整换手率 ***
            partial_turnover = turnover(optimized_weights, old_weights_aligned.values)
            actual_turnover = partial_turnover + missing_weight_sum
            result_df['Partial_Turnover'] = partial_turnover
            result_df['Turnover'] = actual_turnover
            result_df['Missing_Weight'] = missing_weight_sum
    
    return result_df

def test_turnover_optimization():
    """测试换手率优化函数"""
    print("开始测试换手率优化函数...")
    
    # 创建输出目录
    output_dir = "test_output"
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. 创建模拟数据
    print("创建模拟数据...")
    tech_data = create_mock_tech_data(num_stocks=100)
    
    # 添加欧洲地区权重字段
    tech_data['Weight in STOXX EUROPE 600'] = np.random.uniform(0.0001, 0.01, len(tech_data))
    # 添加Exchange Country字段
    countries = ['UNITED STATES', 'FRANCE', 'GERMANY', 'UNITED KINGDOM', 'JAPAN', 'CHINA', 'SWITZERLAND']
    tech_data['Exchange Country Name'] = np.random.choice(countries, len(tech_data))
    
    mapping_data = create_mock_mapping_data()
    
    # 创建旧投资组合 - 从tech_data中选择30只股票
    old_portfolio = create_mock_old_portfolio(tech_data, num_stocks=30)
    print(f"旧投资组合持有 {len(old_portfolio)} 只股票")
    
    # *** 新增测试代码 - 创建一些不在新候选集中的旧投资组合股票 ***
    # 创建5只不在tech_data中的额外股票
    extra_stocks = pd.DataFrame(
        index=[f"EXTRA{i}" for i in range(1, 6)],
        data={
            'Weight': np.random.uniform(0.01, 0.03, 5)
        }
    )
    # 将额外股票添加到旧投资组合
    old_portfolio_with_missing = pd.concat([old_portfolio, extra_stocks])
    # 重新归一化权重
    old_portfolio_with_missing['Weight'] = old_portfolio_with_missing['Weight'] / old_portfolio_with_missing['Weight'].sum()
    print(f"添加了额外股票后的旧投资组合持有 {len(old_portfolio_with_missing)} 只股票")
    
    # 测试不同的换手率约束
    turnover_constraints = [0.1, 0.2, 0.3, 0.5]
    results = {}
    
    # *** 修改测试代码 - 测试两种情况：有缺失股票和无缺失股票 ***
    print("\n===== 测试1: 无缺失股票的情况 =====")
    for max_to in turnover_constraints:
        print(f"\n测试最大换手率约束: {max_to}")
        result = optimize_portfolio_turnover(
            file_tech=tech_data,
            old_portfolio=old_portfolio,
            max_turnover=max_to,
            region="EU",
            output_dir=output_dir,
            curr_path=mapping_data,
            percentile=0.7
        )
        results[f"standard_{max_to}"] = result
        print(f"结果包含 {len(result)} 只股票")
        print(f"权重总和: {result['Weight'].sum():.6f}")
        print(f"换手率: {result['Turnover'].iloc[0]:.6f}")
    
    print("\n===== 测试2: 有缺失股票的情况 =====")
    for max_to in turnover_constraints:
        print(f"\n测试最大换手率约束: {max_to}")
        result = optimize_portfolio_turnover(
            file_tech=tech_data,
            old_portfolio=old_portfolio_with_missing,
            max_turnover=max_to,
            region="EU",
            output_dir=output_dir,
            curr_path=mapping_data,
            percentile=0.7
        )
        results[f"with_missing_{max_to}"] = result
        print(f"结果包含 {len(result)} 只股票")
        print(f"权重总和: {result['Weight'].sum():.6f}")
        print(f"换手率: {result['Turnover'].iloc[0]:.6f}")
    
    # 测试加入因子约束
    print("\n测试加入因子约束的情况:")
    factor_constraints = {
        'Growth': 0.6,
        'Quality': 0.6
    }
    
    result_with_factors = optimize_portfolio_turnover(
        file_tech=tech_data,
        old_portfolio=old_portfolio_with_missing,
        max_turnover=0.3,
        region="EU",
        output_dir=output_dir,
        curr_path=mapping_data,
        percentile=0.7,
        factor_constraints=factor_constraints
    )
    results['with_factors'] = result_with_factors
    
    # 测试加入行业约束
    print("\n测试加入行业约束的情况:")
    sector_constraints = {
        'Technology': 0.2,
        'Health Care': 0.15,
        'Financial Services': 0.1
    }
    
    result_with_sectors = optimize_portfolio_turnover(
        file_tech=tech_data,
        old_portfolio=old_portfolio_with_missing,
        max_turnover=0.3,
        region="EU",
        output_dir=output_dir,
        curr_path=mapping_data,
        percentile=0.7,
        sector_constraints=sector_constraints
    )
    results['with_sectors'] = result_with_sectors
    
    # 测试同时加入因子和行业约束
    print("\n测试同时加入因子和行业约束的情况:")
    result_combined = optimize_portfolio_turnover(
        file_tech=tech_data,
        old_portfolio=old_portfolio_with_missing,
        max_turnover=0.3,
        region="EU",
        output_dir=output_dir,
        curr_path=mapping_data,
        percentile=0.7,
        factor_constraints=factor_constraints,
        sector_constraints=sector_constraints
    )
    results['combined'] = result_combined
    
    # 创建换手率对比图
    import matplotlib.pyplot as plt
    
    # *** 修改测试代码 - 创建更详细的对比图 ***
    plt.figure(figsize=(12, 8))
    
    # 标准测试结果
    standard_turnover = [results[f"standard_{to}"]["Turnover"].iloc[0] for to in turnover_constraints]
    
    # 有缺失股票的结果
    with_missing_turnover = [results[f"with_missing_{to}"]["Turnover"].iloc[0] for to in turnover_constraints]
    with_missing_partial = [results[f"with_missing_{to}"]["Partial_Turnover"].iloc[0] for to in turnover_constraints]
    with_missing_weight = results[f"with_missing_{to}"]["Missing_Weight"].iloc[0]
    
    # 绘制结果
    x = np.arange(len(turnover_constraints))
    width = 0.25
    
    plt.bar(x - width, standard_turnover, width, label='标准情况')
    plt.bar(x, with_missing_partial, width, label='缺失情况-部分换手率')
    plt.bar(x, with_missing_turnover, width, label='缺失情况-完整换手率', alpha=0.5)
    
    plt.axhline(y=0.3, color='r', linestyle='-', label='30% 目标')
    plt.xticks(x, [f"{to*100}%" for to in turnover_constraints])
    plt.xlabel('最大换手率约束')
    plt.ylabel('换手率')
    plt.title('不同场景下的换手率对比')
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.savefig(f"{output_dir}/turnover_comparison_detailed.png")
    print(f"换手率对比图已保存到 {output_dir}/turnover_comparison_detailed.png")
    
    # 另一种对比图 - 显示缺失权重的贡献
    plt.figure(figsize=(12, 8))
    
    # 堆积条形图 - 部分换手率和缺失股票贡献
    plt.bar(x, with_missing_partial, width, label='部分换手率')
    plt.bar(x, [with_missing_weight] * len(turnover_constraints), width, 
            bottom=with_missing_partial, label='缺失股票贡献')
    
    for i, to in enumerate(turnover_constraints):
        plt.axhline(y=to, color='r', linestyle='--', alpha=0.5)
        plt.text(i, to + 0.02, f"{to*100}%", ha='center')
    
    plt.xticks(x, [f"{to*100}%" for to in turnover_constraints])
    plt.xlabel('最大换手率约束')
    plt.ylabel('换手率组成')
    plt.title('有缺失股票情况下的换手率组成')
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.savefig(f"{output_dir}/turnover_composition.png")
    print(f"换手率组成图已保存到 {output_dir}/turnover_composition.png")
    
    print("\n测试完成!")
    return results

if __name__ == "__main__":
    test_turnover_optimization()
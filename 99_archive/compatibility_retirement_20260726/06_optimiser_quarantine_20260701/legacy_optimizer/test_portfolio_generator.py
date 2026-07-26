import pandas as pd
import numpy as np
import datetime
import os
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from portfolio_generator import (
    create_mock_tech_data, 
    create_mock_mapping_data, 
    create_mock_old_portfolio,
    push_mf_tilt_bloom_new
)

def test_push_mf_tilt_bloom_new(tmp_path):
    """测试多因子倾斜投资组合生成函数"""
    print("开始测试push_mf_tilt_bloom_new函数...")
    
    # 创建输出目录
    output_dir = str(tmp_path)
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. 创建模拟数据
    print("创建模拟数据...")
    
    # 修改模拟数据创建以包含必要的字段
    tech_data = create_mock_tech_data(num_stocks=100)
    print(f"创建的技术数据形状: {tech_data.shape}")
    print(f"技术数据索引: {tech_data.index.name}")
    print(f"技术数据列: {tech_data.columns.tolist()}")
    
    # 添加欧洲地区权重字段
    tech_data['Weight in STOXX EUROPE 600'] = np.random.uniform(0.0001, 0.01, len(tech_data))
    # 添加Exchange Country字段
    countries = ['UNITED STATES', 'FRANCE', 'GERMANY', 'UNITED KINGDOM', 'JAPAN', 'CHINA', 'SWITZERLAND']
    tech_data['Exchange Country Name'] = np.random.choice(countries, len(tech_data))
    
    mapping_data = create_mock_mapping_data()
    print(f"映射数据形状: {mapping_data.shape}")
    print(f"映射数据列: {mapping_data.columns.tolist()}")
    
    old_portfolio = create_mock_old_portfolio(tech_data, num_stocks=30)
    print(f"旧投资组合形状: {old_portfolio.shape}")
    
    # 确保数据有ISIN索引
    if tech_data.index.name is None:
        if isinstance(tech_data.index, pd.Index) and tech_data.index.name != 'ISIN':
            tech_data.index.name = 'ISIN'
        else:
            # 如果没有索引，则创建一个ISIN列并设为索引
            if 'ISIN' not in tech_data.columns:
                tech_data['ISIN'] = [f'ISIN{i:06d}' for i in range(len(tech_data))]
            tech_data.set_index('ISIN', inplace=True)
    
    # 2. 测试基本功能（无因子和行业倾斜）
    print("\n测试基本功能（无因子和行业倾斜）...")
    result_basic = push_mf_tilt_bloom_new(
        file_tech=tech_data,
        region="EU",
        output_dir=output_dir,
        curr_path=mapping_data,
        percentile=0.7
    )
    print(f"基本结果包含 {len(result_basic)} 只股票")
    print("权重总和:", result_basic['Weight'].sum())
    print("最大权重:", result_basic['Weight'].max())
    print("最小权重:", result_basic['Weight'].min())
    
    # 3. 测试因子倾斜功能
    print("\n测试因子倾斜功能...")
    reco_facto = [1, 0, 0, 1, 0]  # 倾向于Growth和Quality因子
    result_facto = push_mf_tilt_bloom_new(
        file_tech=tech_data,
        region="EU",
        output_dir=output_dir,
        curr_path=mapping_data,
        percentile=0.7,
        reco_facto=reco_facto
    )
    print(f"因子倾斜结果包含 {len(result_facto)} 只股票")
    print("权重总和:", result_facto['Weight'].sum())
    
    # 4. 测试行业倾斜功能
    print("\n测试行业倾斜功能...")
    # 创建19个行业的权重推荐，其中3个为1（偏好），3个为-1（避免）
    reco_secto = [0] * 19
    reco_secto[2] = 1  # 偏好Basic Resources
    reco_secto[7] = 1  # 偏好Health Care
    reco_secto[15] = 1 # 偏好Technology
    reco_secto[1] = -1 # 避免Banks
    reco_secto[4] = -1 # 避免Construction & Materials
    reco_secto[11] = -1 # 避免Energy
    
    result_secto = push_mf_tilt_bloom_new(
        file_tech=tech_data,
        region="EU",
        output_dir=output_dir,
        curr_path=mapping_data,
        percentile=0.7,
        reco_secto=reco_secto
    )
    print(f"行业倾斜结果包含 {len(result_secto)} 只股票")
    print("权重总和:", result_secto['Weight'].sum())
    
    # 5. 测试同时使用因子和行业倾斜
    print("\n测试同时使用因子和行业倾斜...")
    result_combined = push_mf_tilt_bloom_new(
        file_tech=tech_data,
        region="EU",
        output_dir=output_dir,
        curr_path=mapping_data,
        percentile=0.7,
        reco_secto=reco_secto,
        reco_facto=reco_facto
    )
    print(f"组合倾斜结果包含 {len(result_combined)} 只股票")
    print("权重总和:", result_combined['Weight'].sum())
    
    # 6. 测试换手率约束（使用旧投资组合）
    print("\n测试换手率约束（使用旧投资组合）...")
    result_turnover = push_mf_tilt_bloom_new(
        file_tech=tech_data,
        region="EU",
        output_dir=output_dir,
        curr_path=mapping_data,
        percentile=0.7,
        old_ptf=old_portfolio,
        reco_secto=reco_secto,
        reco_facto=reco_facto
    )
    print(f"带换手率约束结果包含 {len(result_turnover)} 只股票")
    print("权重总和:", result_turnover['Weight'].sum())
    if 'Turnover' in result_turnover.columns:
        turnover_val = result_turnover['Turnover'].iloc[0]
        if isinstance(turnover_val, list):
            print("换手率: N/A (列表格式)")
        else:
            print(f"换手率: {turnover_val}")
    
    # 7. 可视化不同结果的行业分布
    print("\n可视化不同结果的行业分布...")
    if 'ICB19' in result_basic.columns:
        try:
            # 创建一个简单的行业分布图表
            fig, ax = plt.subplots(figsize=(12, 8))
            
            # 获取行业权重
            basic_weights = result_basic.groupby('ICB19')['Weight'].sum()
            facto_weights = result_facto.groupby('ICB19')['Weight'].sum()
            secto_weights = result_secto.groupby('ICB19')['Weight'].sum()
            
            # 准备数据
            industries = mapping_data[' Benchmark ICB Supersector '].unique()
            indices = range(len(industries))
            
            # 对齐数据
            weights_data = []
            for i in indices:
                icb_id = i + 1
                basic_weight = basic_weights.loc[icb_id] if icb_id in basic_weights.index else 0
                facto_weight = facto_weights.loc[icb_id] if icb_id in facto_weights.index else 0
                secto_weight = secto_weights.loc[icb_id] if icb_id in secto_weights.index else 0
                weights_data.append([basic_weight, facto_weight, secto_weight])
            
            weights_data = np.array(weights_data)
            
            # 绘制图表
            bar_width = 0.25
            r1 = np.arange(len(industries))
            r2 = [x + bar_width for x in r1]
            r3 = [x + bar_width for x in r2]
            
            ax.bar(r1, weights_data[:, 0], width=bar_width, label='Baseline')
            ax.bar(r2, weights_data[:, 1], width=bar_width, label='Factor tilt')
            ax.bar(r3, weights_data[:, 2], width=bar_width, label='Sector tilt')
            
            ax.set_xticks([r + bar_width for r in range(len(industries))])
            ax.set_xticklabels(industries, rotation=90)
            ax.set_ylabel('Weight')
            ax.set_title('Industry weight distribution by strategy')
            ax.legend()
            
            plt.tight_layout()
            plt.savefig(f"{output_dir}/industry_weights_comparison.png")
            plt.close(fig)
            print(f"图表已保存到 {output_dir}/industry_weights_comparison.png")
        except Exception as e:
            print(f"绘制图表时出错: {str(e)}")
    else:
        print("结果中没有ICB19列，无法绘制行业分布图")
    
    print("\n测试完成!")
    assert not result_basic.empty
    assert not result_facto.empty
    assert not result_secto.empty
    assert not result_combined.empty
    assert not result_turnover.empty

if __name__ == "__main__":
    test_push_mf_tilt_bloom_new() 
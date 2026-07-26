"""
财务筛选模块的单元测试
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime

from tp_backtest.core.financial_filter import FinancialFilter
from tp_backtest.utils.constants import COL_SECTOR_ICB19, COL_DATE, COL_ISIN


@pytest.fixture
def sample_screen_data():
    """创建示例screen数据"""
    np.random.seed(42)
    n_stocks = 100
    n_sectors = 5
    
    data = {
        COL_DATE: [datetime(2023, 1, 1)] * n_stocks,
        COL_ISIN: [f'ISIN{i:04d}' for i in range(n_stocks)],
        COL_SECTOR_ICB19: np.random.randint(1, n_sectors+1, n_stocks),
        'EPS NTM 3M Growth': np.random.normal(0.05, 0.10, n_stocks),
        'Sales Growth': np.random.normal(0.03, 0.05, n_stocks),
        'ROE': np.random.normal(0.12, 0.05, n_stocks),
        'Debt to Equity': np.random.uniform(0.2, 1.5, n_stocks),
        'Weight in STOXX EUROPE 600': np.random.uniform(0.001, 0.02, n_stocks)
    }
    
    df = pd.DataFrame(data)
    df = df.set_index(COL_ISIN)
    return df


class TestFinancialFilter:
    """财务筛选器测试类"""
    
    def test_init(self, sample_screen_data):
        """测试初始化"""
        fin_filter = FinancialFilter(
            sample_screen_data,
            'STOXX EUROPE 600',
            COL_SECTOR_ICB19
        )
        
        assert fin_filter.bench == 'STOXX EUROPE 600'
        assert fin_filter.sector_col == COL_SECTOR_ICB19
    
    def test_absolute_threshold_filter(self, sample_screen_data):
        """测试绝对阈值筛选"""
        fin_filter = FinancialFilter(
            sample_screen_data,
            'STOXX EUROPE 600',
            COL_SECTOR_ICB19
        )
        
        config = {
            'conditions': [
                {
                    'metric': 'ROE',
                    'threshold': 0.15,
                    'threshold_type': 'absolute',
                    'by_sector': False,
                    'operator': '>'
                }
            ],
            'logic': 'AND'
        }
        
        df_filtered, excluded = fin_filter.apply_filters(
            sample_screen_data.copy(), 
            config
        )
        
        # 验证筛选结果
        assert len(df_filtered) < len(sample_screen_data)
        assert all(df_filtered['ROE'] > 0.15)
        assert len(df_filtered) + len(excluded) == len(sample_screen_data)
    
    def test_percentile_threshold_filter(self, sample_screen_data):
        """测试相对阈值（百分位）筛选"""
        fin_filter = FinancialFilter(
            sample_screen_data,
            'STOXX EUROPE 600',
            COL_SECTOR_ICB19
        )
        
        config = {
            'conditions': [
                {
                    'metric': 'EPS NTM 3M Growth',
                    'threshold': 0.10,  # 前10%
                    'threshold_type': 'percentile',
                    'by_sector': False,
                    'operator': '>='
                }
            ],
            'logic': 'AND'
        }
        
        df_filtered, excluded = fin_filter.apply_filters(
            sample_screen_data.copy(),
            config
        )
        
        # 验证筛选结果：应该大约保留10%的股票
        expected_count = int(len(sample_screen_data) * 0.10)
        assert abs(len(df_filtered) - expected_count) <= 2  # 允许小误差
    
    def test_sector_percentile_filter(self, sample_screen_data):
        """测试行业内百分位筛选"""
        fin_filter = FinancialFilter(
            sample_screen_data,
            'STOXX EUROPE 600',
            COL_SECTOR_ICB19
        )
        
        config = {
            'conditions': [
                {
                    'metric': 'ROE',
                    'threshold': 0.20,  # 行业内前20%
                    'threshold_type': 'percentile',
                    'by_sector': True,
                    'operator': '>='
                }
            ],
            'logic': 'AND'
        }
        
        df_filtered, excluded = fin_filter.apply_filters(
            sample_screen_data.copy(),
            config
        )
        
        # 每个行业应该都有股票被选中
        sectors_before = set(sample_screen_data[COL_SECTOR_ICB19].unique())
        sectors_after = set(df_filtered[COL_SECTOR_ICB19].unique())
        
        # 至少应该有一些行业有股票被选中
        assert len(sectors_after) > 0
    
    def test_and_logic(self, sample_screen_data):
        """测试AND逻辑"""
        fin_filter = FinancialFilter(
            sample_screen_data,
            'STOXX EUROPE 600',
            COL_SECTOR_ICB19
        )
        
        config = {
            'conditions': [
                {
                    'metric': 'ROE',
                    'threshold': 0.10,
                    'threshold_type': 'absolute',
                    'by_sector': False,
                    'operator': '>'
                },
                {
                    'metric': 'Debt to Equity',
                    'threshold': 1.0,
                    'threshold_type': 'absolute',
                    'by_sector': False,
                    'operator': '<'
                }
            ],
            'logic': 'AND'
        }
        
        df_filtered, excluded = fin_filter.apply_filters(
            sample_screen_data.copy(),
            config
        )
        
        # 所有筛选后的股票都应该满足两个条件
        assert all(df_filtered['ROE'] > 0.10)
        assert all(df_filtered['Debt to Equity'] < 1.0)
    
    def test_or_logic(self, sample_screen_data):
        """测试OR逻辑"""
        fin_filter = FinancialFilter(
            sample_screen_data,
            'STOXX EUROPE 600',
            COL_SECTOR_ICB19
        )
        
        config = {
            'conditions': [
                {
                    'metric': 'ROE',
                    'threshold': 0.20,
                    'threshold_type': 'absolute',
                    'by_sector': False,
                    'operator': '>'
                },
                {
                    'metric': 'Sales Growth',
                    'threshold': 0.10,
                    'threshold_type': 'absolute',
                    'by_sector': False,
                    'operator': '>'
                }
            ],
            'logic': 'OR'
        }
        
        df_filtered, excluded = fin_filter.apply_filters(
            sample_screen_data.copy(),
            config
        )
        
        # 筛选后的股票应该至少满足一个条件
        for idx in df_filtered.index:
            assert (df_filtered.loc[idx, 'ROE'] > 0.20) or \
                   (df_filtered.loc[idx, 'Sales Growth'] > 0.10)
    
    def test_get_available_metrics(self, sample_screen_data):
        """测试获取可用指标"""
        fin_filter = FinancialFilter(
            sample_screen_data,
            'STOXX EUROPE 600',
            COL_SECTOR_ICB19
        )
        
        metrics = fin_filter.get_available_metrics(sample_screen_data)
        
        # 应该包含财务指标但不包含系统列
        assert 'EPS NTM 3M Growth' in metrics
        assert 'ROE' in metrics
        assert COL_DATE not in metrics
        assert COL_ISIN not in metrics
    
    def test_validate_filter_config(self):
        """测试配置验证"""
        # 有效配置
        valid_config = {
            'conditions': [
                {
                    'metric': 'ROE',
                    'threshold': 0.15,
                    'threshold_type': 'absolute',
                    'operator': '>'
                }
            ],
            'logic': 'AND'
        }
        
        assert FinancialFilter.validate_filter_config(valid_config) == True
        
        # 无效配置：缺少必需字段
        invalid_config = {
            'conditions': [
                {
                    'metric': 'ROE'
                    # 缺少其他必需字段
                }
            ],
            'logic': 'AND'
        }
        
        assert FinancialFilter.validate_filter_config(invalid_config) == False
        
        # 无效配置：错误的logic值
        invalid_config2 = {
            'conditions': [
                {
                    'metric': 'ROE',
                    'threshold': 0.15,
                    'threshold_type': 'absolute',
                    'operator': '>'
                }
            ],
            'logic': 'INVALID'
        }
        
        assert FinancialFilter.validate_filter_config(invalid_config2) == False
    
    def test_empty_config(self, sample_screen_data):
        """测试空配置"""
        fin_filter = FinancialFilter(
            sample_screen_data,
            'STOXX EUROPE 600',
            COL_SECTOR_ICB19
        )
        
        # 空配置应该返回原始数据
        df_filtered, excluded = fin_filter.apply_filters(
            sample_screen_data.copy(),
            None
        )
        
        assert len(df_filtered) == len(sample_screen_data)
        assert len(excluded) == 0
    
    def test_nan_handling(self, sample_screen_data):
        """测试NaN值处理"""
        # 添加一些NaN值
        data_with_nan = sample_screen_data.copy()
        data_with_nan.loc[data_with_nan.index[:10], 'ROE'] = np.nan
        
        fin_filter = FinancialFilter(
            data_with_nan,
            'STOXX EUROPE 600',
            COL_SECTOR_ICB19
        )
        
        config = {
            'conditions': [
                {
                    'metric': 'ROE',
                    'threshold': 0.10,
                    'threshold_type': 'absolute',
                    'by_sector': False,
                    'operator': '>'
                }
            ],
            'logic': 'AND'
        }
        
        df_filtered, excluded = fin_filter.apply_filters(
            data_with_nan.copy(),
            config
        )
        
        # NaN值的股票应该被排除
        assert not df_filtered.index.isin(data_with_nan.index[:10]).any()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


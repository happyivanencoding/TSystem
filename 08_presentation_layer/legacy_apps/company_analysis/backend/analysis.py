import pandas as pd
import numpy as np
import os
import sys
from pathlib import Path

_TP_ROOT = Path(__file__).resolve().parents[4]
_TP_CORE_PATH = _TP_ROOT / "01_tp_core"
for _path in (_TP_ROOT, _TP_CORE_PATH):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from tp_core.data_sources import FACTSET_ICB_MAPPING_PATH
from tp_core.data_sources import LAST_SCREEN_PATH
from tp_core.data_sources import RETURNS_PATH as CANONICAL_RETURNS_PATH
from tp_core.data_sources import SCREEN_AGGREGATE_PATH
from tp_core.data_sources import SCREEN_DIR
from presentation_layer import PresentationDataRepository

PRESENTATION_REPOSITORY = PresentationDataRepository()

# 配置路径
DATA_DIR = str(SCREEN_DIR)
PARQUET_PATH = str(LAST_SCREEN_PATH)
AGGREGATE_PATH = str(SCREEN_AGGREGATE_PATH)
MAPPING_PATH = str(FACTSET_ICB_MAPPING_PATH)
RETURNS_PATH = str(CANONICAL_RETURNS_PATH)

def factset_icb_mapping(df, path_params=MAPPING_PATH):
    """
    映射 FactSet 行业分类到 ICB 分类
    """
    if not os.path.exists(path_params):
        print(f"Warning: Mapping file not found at {path_params}")
        return df

    # 读取映射文件
    df_mapping = pd.read_excel(path_params, sheet_name='Mapping', header=0, na_values="@NA")
    df_mapping.rename(columns={
        'Benchmark ICB Supersector 19': ' Benchmark ICB Supersector ',
        'Benchmark ICB Industry 11': ' Benchmark ICB Industry '
    }, inplace=True)
    
    # 创建映射字典
    mapping_sector_to_id = (df_mapping.dropna(subset=['ICB19_ID'])
                            .drop_duplicates(subset=[' Benchmark ICB Supersector '])
                            .set_index(' Benchmark ICB Supersector ')['ICB19_ID']
                            .to_dict())
    
    mapping_factset_to_icb19 = (df_mapping
                                .drop_duplicates(subset=['FactSet Ind'])
                                .set_index('FactSet Ind')['Transco_ICB_19']
                                .to_dict())
    
    mapping_industry_to_id = (df_mapping.dropna(subset=['ICB11_ID'])
                              .drop_duplicates(subset=[' Benchmark ICB Industry '])
                              .set_index(' Benchmark ICB Industry ')['ICB11_ID']
                              .to_dict())
    
    mapping_icb19_to_icb11 = (df_mapping
                              .drop_duplicates(subset=['ICB_19_mapping'])
                              .set_index('ICB_19_mapping')['Transco_ICB_11']
                              .to_dict())
    
    # 重置索引
    if 'ISIN' in df.index.names:
        df = df.reset_index()
    elif 'ISIN' not in df.columns:
        # 如果 ISIN 既不在索引也不在列中，可能在索引但没名字，或者数据有问题
        # 假设重置索引后的第一列或者是索引
        pass
    
    # 确保有 Benchmark ICB Supersector 列
    if ' Benchmark ICB Supersector ' not in df.columns:
        # 如果没有这一列，尝试创建或忽略，这里假设必须有
        if 'FactSet Ind' in df.columns:
             df[' Benchmark ICB Supersector '] = np.nan
        else:
            return df

    # 处理 Supersector 列
    df[' Benchmark ICB Supersector '] = df[' Benchmark ICB Supersector '].map(mapping_sector_to_id)
    
    # 补全 Supersector
    temp_icb19 = df['FactSet Ind'].map(mapping_factset_to_icb19) if 'FactSet Ind' in df.columns else pd.Series()
    mask_sector_zero = (df[' Benchmark ICB Supersector '] == 0) | (df[' Benchmark ICB Supersector '].isna())
    if not temp_icb19.empty:
        df.loc[mask_sector_zero, ' Benchmark ICB Supersector '] = temp_icb19[mask_sector_zero]
    
    # 处理 Industry 列
    if ' Benchmark ICB Industry ' in df.columns:
        df[' Benchmark ICB Industry '] = df[' Benchmark ICB Industry '].map(mapping_industry_to_id)
        
        temp_icb11 = df[' Benchmark ICB Supersector '].map(mapping_icb19_to_icb11)
        mask_industry_zero = (df[' Benchmark ICB Industry '] == 0) | (df[' Benchmark ICB Industry '].isna())
        df.loc[mask_industry_zero, ' Benchmark ICB Industry '] = temp_icb11[mask_industry_zero]
    
    # 设置索引
    if 'ISIN' in df.columns:
        df.set_index('ISIN', inplace=True)
    
    # 日期转换
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'])
    
    return df

def add_icb_supersector_names(dataframe, icb_code_column=' Benchmark ICB Supersector '):
    """
    添加 ICB Supersector 名称
    """
    icb_supersectors = {  
        "Auto & Parts": 1, "Banks": 2, "Basic Resources": 3, "Chemicals": 4,  
        "Construction": 5, "Financial Services": 6, "Food, Beverage & Tobacco": 7,  
        "Health Care": 8, "Industrial Goods & Services": 9, "Insurance": 10,  
        "Media": 11, "Energy": 12, "Personal & Household Goods": 13,  
        "Real Estate": 14, "Retail": 15, "Technology": 16,  
        "Telecommunications": 17, "Travel & Leisure": 18, "Utilities": 19  
    }
    icb_supersectors_reverse = {v: k for k, v in icb_supersectors.items()}  
    
    dataframe_updated = dataframe.copy()
    if icb_code_column in dataframe_updated.columns:
        dataframe_updated['Supersector'] = dataframe_updated[icb_code_column].map(icb_supersectors_reverse)
    else:
        dataframe_updated['Supersector'] = "Unknown"
        
    return dataframe_updated

# 定义重命名规则，供加载和历史数据查询使用
RENAME_DICT = {
    'Dividend Avg Percentile': 'Dividend Score (Histo + FY1)',
    'Value Avg Percentile' : 'Value Score (Histo + FY1)',
    'Quality Avg Percentile' : 'Quality Score (Histo + FY1)',
    'Growth Avg Percentile' : 'Growth Score (Histo + FY1)',
    'Mom Avg Percentile' : 'Momentum Score (Histo + FY1)',
    'Size Avg Percentile' : 'Size Score (Histo + FY1)',
    'LowVol Avg Percentile' : 'LowVol Score (Histo + FY1)',
    'Dividend_NTM Avg Percentile' : 'Dividend Score (Histo + NTM)',
    'Value_NTM Avg Percentile' : 'Value Score (Histo + NTM)',
    'Quality_NTM Avg Percentile' : 'Quality Score (Histo + NTM)',
    'Growth_NTM Avg Percentile' : 'Growth Score (Histo + NTM)',
    'Value_Forward Avg Percentile' : 'Value Score (FY1)',
    'Value_Spot_Avg Percentile' : 'Value Score (Histo)',
    'Value_NTM Avg Percentile.1' : 'Value Score (NTM)',
    'Growth_Forward_Avg Percentile' : 'Growth Score (FY1)',
    'Growth_Historical_Avg Percentile' : 'Growth Score (Histo)',
    'Growth_NTM_Avg Percentile': 'Growth Score (NTM)'
}

def load_and_process_data():
    """
    加载并处理数据，返回处理后的 DataFrame
    """
    df = PRESENTATION_REPOSITORY.screen(last_only=True).copy()
    
    # 1. 映射处理
    df = factset_icb_mapping(df)
    
    # 2. 重命名列
    df.rename(columns=RENAME_DICT, inplace=True)
    
    # 3. 添加板块名称
    if 'Supersector' not in df.columns:
        df = add_icb_supersector_names(df, icb_code_column=' Benchmark ICB Supersector ')
        
    # 4. 计算排位 (Rank)
    cols = [
        'Dividend Score (Histo + FY1)', 'Value Score (Histo + FY1)',
        'Quality Score (Histo + FY1)', 'Growth Score (Histo + FY1)',
        'Momentum Score (Histo + FY1)', 'Size Score (Histo + FY1)',
        'LowVol Score (Histo + FY1)', 'Dividend Score (Histo + NTM)',
        'Value Score (Histo + NTM)', 'Quality Score (Histo + NTM)',
        'Growth Score (Histo + NTM)', 'Value Score (FY1)',
        'Value Score (Histo)', 'Value Score (NTM)',
        'Growth Score (FY1)', 'Growth Score (Histo)',
        'Growth Score (NTM)',
        'Score ML'
    ]
    
    # # 确保列存在
    # existing_cols = [c for c in cols if c in df.columns]
    
    # if 'Exchange Country Region' in df.columns and 'Supersector' in df.columns:
    #     try:
    #         df[existing_cols] = df.groupby(["Exchange Country Region", 'Supersector'])[existing_cols].rank(pct=True) * 10
    #     except Exception as e:
    #         print(f"Ranking calculation error: {e}")

    # 5. 清理列
    drop_cols = [
        'FactSet Ind', 'FactSet Economy', 
        ' Benchmark ICB Industry ', ' Benchmark ICB Supersector '
    ]
    df.drop(columns=[c for c in drop_cols if c in df.columns], inplace=True)
    
    # 重置索引以便 JSON 序列化
    df = df.reset_index()
    
    # 移除 replace({np.nan: None})，保持 NaN 以便后续计算中位数
    # df = df.replace({np.nan: None})
    
    return df

# 全局缓存数据，避免每次请求都读取
_cached_df = None
_cached_medians = None
_cached_returns = None

def get_returns_cache():
    """加载并缓存 returns.parquet（index=日期，columns=SEDOL，值=日涨跌幅%）"""
    global _cached_returns
    if _cached_returns is None:
        _cached_returns = PRESENTATION_REPOSITORY.returns()
    return _cached_returns

    return _cached_returns

def get_stock_returns(isin):
    """根据 ISIN 查找公司 SEDOL，返回累计股价回报时间序列"""
    df = get_data()
    company_row = df[df['ISIN'] == isin]
    if company_row.empty:
        return []

    sedol = company_row.iloc[0].get('Company SEDOL')
    if not sedol or (isinstance(sedol, float) and np.isnan(sedol)):
        return []
    sedol = str(sedol).strip()

    returns_df = get_returns_cache()
    if returns_df.empty or sedol not in returns_df.columns:
        return []

    series = returns_df[sedol].dropna().sort_index()
    if series.empty:
        return []

    # 100 起点价格指数（第一个交易日 = 100）
    cum_raw = (1 + series).cumprod()
    indexed = (cum_raw / cum_raw.iloc[0]) * 100
    return [
        {'Date': pd.Timestamp(d).strftime('%Y-%m-%d'), 'PriceIndex': round(float(v), 4)}
        for d, v in indexed.items()
    ]

def get_data():
    global _cached_df
    if _cached_df is None:
        _cached_df = load_and_process_data()
    return _cached_df

def get_data_date():
    """
    返回数据集中最近的日期字符串
    """
    df = get_data()
    if 'Date' in df.columns:
        dates = pd.to_datetime(df['Date'], errors='coerce').dropna()
        if not dates.empty:
            return dates.max().strftime('%Y-%m-%d')
    return None

def get_medians_data():
    """
    计算并缓存各区域行业的各项指标中位数
    """
    global _cached_medians
    if _cached_medians is None:
        df = get_data()
        
        # 必须包含分组键
        if 'Exchange Country Region' in df.columns and 'Supersector' in df.columns:
            try:
                # 排除非数值列，只计算数值列的中位数
                numeric_df = df.select_dtypes(include=[np.number])
                
                # 将分组列加回来用于 groupby
                group_cols = ['Exchange Country Region', 'Supersector']
                
                # 构建用于计算中位数的子集
                # 注意：如果 group_cols 本身不是 numeric (它们是字符串)，需要手动把它们并入
                cols_to_use = numeric_df.columns.tolist()
                
                # 如果 group_cols 已经在 numeric_df 中（不太可能），避免重复
                final_cols = list(set(cols_to_use + group_cols))
                subset = df[final_cols]

                medians_df = subset.groupby(group_cols).median()
                
                # 转为字典 {(Region, Sector): {col: value}}
                _cached_medians = medians_df.to_dict(orient='index')
            except Exception as e:
                print(f"Median calculation error: {e}")
                _cached_medians = {}
        else:
             _cached_medians = {}
             
    return _cached_medians

def remove_outliers_iqr_7(series):
    """
    Removes outliers from a pandas Series using 7*IQR.
    Outliers are replaced by the last valid observation (forward fill).
    """
    # 确保是数值类型
    if not np.issubdtype(series.dtype, np.number):
        return series

    Q1 = series.quantile(0.25)
    Q3 = series.quantile(0.75)
    IQR = Q3 - Q1
    
    lower_bound = Q1 - 7 * IQR
    upper_bound = Q3 + 7 * IQR
    
    # 找出 outlier
    is_outlier = (series < lower_bound) | (series > upper_bound)
    
    if not is_outlier.any():
        return series
        
    # 将 outlier 设为 NaN
    cleaned_series = series.copy()
    cleaned_series[is_outlier] = np.nan
    
    # Forward fill: 使用上一个非 outlier 值填充
    # 如果第一个值就是 outlier，fillna(method='ffill') 可能填不上，
    # 这种情况可以考虑 backfill 或者保持 NaN
    cleaned_series = cleaned_series.ffill().bfill()
    
    return cleaned_series

def get_history_data(isin):
    """
    获取指定 ISIN 的历史数据，并去除 7*IQR 之外的异常值
    """
    try:
        df = PRESENTATION_REPOSITORY.company_history(isin)
        
        if df.empty:
            return []
        
        # 应用相同的重命名规则，确保字段名一致
        df.rename(columns=RENAME_DICT, inplace=True)
            
        # reset index 如果需要
        if 'ISIN' not in df.columns:
            df = df.reset_index()
            
        # 确保 Date 是 datetime
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'])
            
        # 排序 (按日期)
        df = df.sort_values('Date')
        
        # --- Outlier Cleaning ---
        # 对所有数值列应用去除 outlier 逻辑
        # 我们只关心要在图表中展示的列，或者干脆对所有数值列做处理
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        
        for col in numeric_cols:
            df[col] = remove_outliers_iqr_7(df[col])
            
        # 格式化日期字符串
        if 'Date' in df.columns:
            df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
            
        return clean_nan(df.to_dict(orient='records'))
        
    except Exception as e:
        print(f"Error reading history for {isin}: {e}")
        return []

def clean_nan(obj):
    """
    递归处理数据结构，将 NaN/NaT 转换为 None，以便 JSON 序列化
    """
    if isinstance(obj, float):
        return None if np.isnan(obj) else obj
    if isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_nan(v) for v in obj]
    if pd.isna(obj): # Catch-all for pd.NA, pd.NaT etc
        return None
    return obj

def format_for_clipboard(row):
    """
    格式化单行数据为 Python 字典字符串格式
    """
    # 转换 row (Series) 为 dict
    data_dict = row.to_dict()
    
    # 过滤掉 None/NaN 值
    
    formatted_dict = {}
    for k, v in data_dict.items():
        if pd.isna(v):
            continue # 如果是空值则不包含在字典中
        else:
            formatted_dict[k] = v
            
    obj_key = row.name if hasattr(row, 'name') else 0
    
    def py_repr(v):
        if isinstance(v, pd.Timestamp):
            return f"Timestamp('{v}')"
        if isinstance(v, str):
            return f"'{v}'"
        if v is None:
            return "None"
        return str(v)

    # 手动构建字符串以匹配要求的格式
    lines = []
    for k, v in formatted_dict.items():
        if k == "index": continue # 忽略内部索引
        lines.append(f"  '{k}': {py_repr(v)}")
    
    content = ",\n\n".join(lines)
    result = f"{{{obj_key}: {{\n{content}}}}}"
    return result



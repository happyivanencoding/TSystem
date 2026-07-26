"""项目配置：数据路径、地区定义、起始日期、特征字段。"""
from pathlib import Path

from tp_core.data_sources import RETURNS_PATH as CANONICAL_RETURNS_PATH
from tp_core.data_sources import SCREEN_AGGREGATE_PATH, TP_ROOT

# 数据源路径
SCREEN_PATH = SCREEN_AGGREGATE_PATH
RETURNS_PATH = CANONICAL_RETURNS_PATH

# 输出目录
REGIME_DIR = TP_ROOT / "03_regime_model"
OUTPUT_DIR = REGIME_DIR / "output"
MACRO_PATH = REGIME_DIR / "macro_data.parquet"
MACRO2_PATH = TP_ROOT / "00_screen" / "production_inputs" / "maj cycle macro2.xlsx"

# 地区 -> 指数成分权重列（权重>0 即为当期成分，天然 point-in-time）
REGION_WEIGHT_COL = {
    "US": "Weight in SP500",
    "EU": "Weight in STOXX EUROPE 600",
}

MACRO_FEATURE_COLS = {
    "US": {
        "US_BFCIUS Index": "macro_fin_conditions",
        "US_BFCIUS Index EWMA": "macro_fin_conditions_ewma",
    },
    "EU": {
        "EU_BFCIEU Index": "macro_fin_conditions",
        "EU_BFCIEU Index EWMA": "macro_fin_conditions_ewma",
    },
}

MACRO2_SHEETS = {"US": "US", "EU": "Europe"}
MACRO2_FEATURE_COLS = {
    "macro2_citi_raw": "macro2_citi_raw",
    "macro2_citi_ewma": "macro2_citi_ewma",
    "macro2_bnp_raw": "macro2_bnp_raw",
    "macro2_bnp_ewma": "macro2_bnp_ewma",
}

# 起始日期：经敏感性检验, 2007(含GFC)为最佳起点; 2005-2006平静牛市无增量且略稀释EU
START_DATE = "2007-01-31"

# 2009 前无真实指数成分 -> 用"地区内市值前 N"代理池(仅作样本扩展, 已标记)
# 真实指数权重起点：SP500 2009-03 / STOXX600 2009-06
PROXY_END = "2009-06-30"                 # 此日期前为代理池区间(用于标记/敏感性检验)
MKT_CAP_COL = "Benchmark Market Value Millions in EUR"  # 原始市值, 2007Q1起有值
PROXY_REGION = {"US": "North America", "EU": "West Europe"}  # 地区 -> Exchange Country Region
PROXY_N = {"US": 500, "EU": 600}         # 对应 SP500 / STOXX600 规模

# 固定状态数：EU/US 统一为 4，便于跨市场对应与向客户解释（BIC 选 K 仅作参考）
FIXED_K = 4

# 横截面聚合所需的个股字段（按主题分组）
# 估值
VAL_COLS = ["Earns Yield NTM", "DVD Yield NTM", "PCT PE NTM", "PCT EVEBITDA NTM"]
# 盈利修正 / 成长
GROWTH_COLS = ["EPS Revision Ratio", "EPS NTM 3M Growth", "EPS Growth NTM", "Sales Growth NTM"]
# 质量 / 杠杆
QUALITY_COLS = ["ROE avg FY0", "NetDebt to EBITDA exFIN"]
# 风险 / 波动（仅用全历史覆盖的字段）
RISK_COLS = ["Daily Vol 260J", "Daily Vol 90J", "Daily Vol 60J"]
# 动量水平
MOM_COLS = ["MOM Score"]
# 已实现月度总收益（trailing，无前视）；个股标识用于因子价差的滞后排序
RETURN_COL = "Total Return"
ID_COL = "Company SEDOL"
# 因子中性化分组：区域 × 行业（行业列带前后空格、0%缺失）
REGION_NEUTRAL_COL = "Exchange Country Region"
SECTOR_COL = " Benchmark ICB Supersector "
# 组内 rank 的最小有效成分数：组内非空个股少于此数则剔除（rank 不稳定）
MIN_SECTOR_SIZE = 5

# ICB Supersector 代码的防御板块（其余非0代码视为周期）；用于周期-防御收益差
DEFENSIVE_SECTORS = {7.0, 8.0, 17.0, 19.0}  # 食品饮料烟草/医疗/电信/公用事业
# 因子分位（用于构造多空价差收益）
FACTOR_PCTILE_COLS = {
    "Value": "Value Avg Percentile",
    "Quality": "Quality Avg Percentile",
    "Mom": "Mom Avg Percentile",
    "LowVol": "LowVol Avg Percentile",
}

# 读取 screen 时需要的全部列
def screen_columns() -> list[str]:
    base = ["Date", ID_COL, RETURN_COL, REGION_NEUTRAL_COL, SECTOR_COL, MKT_CAP_COL]
    base += list(REGION_WEIGHT_COL.values())
    feat = VAL_COLS + GROWTH_COLS + QUALITY_COLS + RISK_COLS + MOM_COLS
    feat += list(FACTOR_PCTILE_COLS.values())
    # 去重保序
    seen, out = set(), []
    for c in base + feat:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out

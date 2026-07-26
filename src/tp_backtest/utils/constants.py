"""
回测系统的常量和配置值
"""

from typing import Dict, List

# ICB 19 Supersector names
ICB_19_SECTORS: Dict[int, str] = {
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
}

# 因子 names
FACTORS: Dict[int, str] = {
    1: "Growth",
    2: "Low Vol",
    3: "Momentum",
    4: "Quality",
    5: "Value"
}

# Available 因子 columns
FACTOR_COLUMNS: List[str] = [
    'Growth Avg Percentile',
    'LowVol Avg Percentile',
    'Mom Avg Percentile',
    'Quality Avg Percentile',
    'Value Avg Percentile',
    'Size Avg Percentile',
    'Dividend Avg Percentile'
]

# Weighting methods
WEIGHTING_METHODS: List[str] = [
    "Racine cube",
    "Racine carrée",
    "Market cap",
    "Log",
    "Equalweight"
]

# 得分 neutralization options
SCORE_NEUTRAL_OPTIONS: List[str] = [
    "ICB 11",
    "ICB 19"
]

# 权重 neutralization options
WEIGHT_NEUTRAL_OPTIONS: List[str] = [
    "ICB 11",
    "ICB 19"
]

# 基准 to region mapping
BENCH_TO_REGION: Dict[str, str] = {
    'SP500': 'US',
    'MSCI US': 'US',
    'STOXX EUROPE 600': 'EU'
}

# Style to 投资组合 type mapping
STYLE_TO_TYPE: Dict[str, str] = {
    'Size Avg Percentile': 'SIZE',
    'Value Avg Percentile': 'VALUE',
    'Quality Avg Percentile': 'QUALITY',
    'Mom Avg Percentile': 'MOM',
    'LowVol Avg Percentile': 'LOWVOL',
    'Growth Avg Percentile': 'GROWTH',
    'Multi Avg Percentile': 'MF'
}

# Dual-listed 证券 ISIN pairs (keep first, 合并 second)
ISIN_PAIRS: List[str] = [
    "US02079K3059",  # Google
    "US02079K1079",
    
    "DK0010244508",  # A.P. Moller
    "DK0010244425",
    
    "SE0017486889",  # Atlas Copco
    "SE0017486897",
    
    "DE0005190003",  # Bayerische Motoren Werke
    "DE0005190037",
    
    "SE0015658109",  # Epiroc
    "SE0015658117",
    
    "CH0012032048",  # Roche Holding
    "CH0012032113",
    
    "CH0024638196",  # Schindler
    "CH0024638212",
    
    "CH0010570767",  # Lindt
    "CH0010570759",
    
    "DE0006048432",  # Henkel
    "DE0006048408",
    
    "SE0000107203",  # Industrivarden
    "SE0000190126"
]

# 列 名称 constants
COL_DATE = 'Date'
COL_ISIN = 'ISIN'
COL_SEDOL = 'Company SEDOL'
COL_SECTOR_ICB11 = ' Benchmark ICB Industry '
COL_SECTOR_ICB19 = ' Benchmark ICB Supersector '
COL_MKT_CAP = 'Benchmark Market Value Millions in EUR'
COL_ESG_SCORE = 'ESG_ANALYST_SCORE'
COL_PORTFOLIO_WEIGHT = 'Portfolio weight'

# 默认 values
DEFAULT_PERCENTILE = 0.25
DEFAULT_ESG_EXCLUSION = 0
DEFAULT_CUT_MKT_CAP = 0
DEFAULT_PONDERATION = 'Racine cube'
DEFAULT_SCORE_NEUTRAL = 'ICB 19'
DEFAULT_WEIGHT_NEUTRAL = 'ICB 19'

# 财务指标筛选预设组合
FINANCIAL_FILTER_PRESETS: Dict[str, Dict] = {
    "高成长组合": {
        "description": "EPS增长在行业前10% 且 营收增长>3%",
        "conditions": [
            {
                "metric": "EPS NTM 3M Growth",
                "threshold": 0.10,
                "threshold_type": "percentile",
                "by_sector": True,
                "operator": ">="
            },
            {
                "metric": "Sales Growth",
                "threshold": 0.03,
                "threshold_type": "absolute",
                "by_sector": False,
                "operator": ">"
            }
        ],
        "logic": "AND"
    },
    "稳健盈利组合": {
        "description": "ROE>15% 且 负债率<50%",
        "conditions": [
            {
                "metric": "ROE",
                "threshold": 0.15,
                "threshold_type": "absolute",
                "by_sector": False,
                "operator": ">"
            },
            {
                "metric": "Debt to Equity",
                "threshold": 0.5,
                "threshold_type": "absolute",
                "by_sector": False,
                "operator": "<"
            }
        ],
        "logic": "AND"
    },
    "高质量组合": {
        "description": "ROE在行业前20% 且 利润率在行业前20%",
        "conditions": [
            {
                "metric": "ROE",
                "threshold": 0.20,
                "threshold_type": "percentile",
                "by_sector": True,
                "operator": ">="
            },
            {
                "metric": "Net Margin",
                "threshold": 0.20,
                "threshold_type": "percentile",
                "by_sector": True,
                "operator": ">="
            }
        ],
        "logic": "AND"
    },
    "价值成长组合": {
        "description": "低P/E(行业前30%) 且 EPS增长>10%",
        "conditions": [
            {
                "metric": "P/E",
                "threshold": 0.30,
                "threshold_type": "percentile",
                "by_sector": True,
                "operator": "<="
            },
            {
                "metric": "EPS NTM 3M Growth",
                "threshold": 0.10,
                "threshold_type": "absolute",
                "by_sector": False,
                "operator": ">"
            }
        ],
        "logic": "AND"
    },
    "高股息组合": {
        "description": "股息率>3% 且 派息率<80%",
        "conditions": [
            {
                "metric": "Dividend Yield",
                "threshold": 0.03,
                "threshold_type": "absolute",
                "by_sector": False,
                "operator": ">"
            },
            {
                "metric": "Payout Ratio",
                "threshold": 0.80,
                "threshold_type": "absolute",
                "by_sector": False,
                "operator": "<"
            }
        ],
        "logic": "AND"
    }
}

# 常用财务指标的中文名称映射
FINANCIAL_METRICS_CN: Dict[str, str] = {
    "EPS NTM 3M Growth": "EPS增长率",
    "Sales Growth": "营收增长率",
    "ROE": "净资产收益率",
    "Debt to Equity": "负债权益比",
    "Net Margin": "净利率",
    "P/E": "市盈率",
    "P/B": "市净率",
    "Dividend Yield": "股息率",
    "Payout Ratio": "派息率",
    "ROIC": "投入资本回报率",
    "FCF Yield": "自由现金流收益率",
    "Asset Turnover": "资产周转率",
    "Current Ratio": "流动比率",
    "Quick Ratio": "速动比率",
    "Gross Margin": "毛利率",
    "Operating Margin": "营业利润率",
    "EBITDA Margin": "EBITDA利润率"
}

# 筛选模式
FILTER_MODES: List[str] = [
    "纯因子模式",
    "财务+因子组合",
    "纯财务筛选"
]


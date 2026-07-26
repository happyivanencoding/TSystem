"""TP 项目共享的 canonical 数据源路径。

所有活跃项目都应从本模块导入 canonical screen/returns 路径，避免在各项目中硬编码自己的副本。
环境变量覆盖也集中在这里，防止临时实验演变成项目级数据分叉。
"""

from __future__ import annotations

import os
from pathlib import Path


TP_ROOT = Path(os.environ.get("TP_ROOT", Path(__file__).resolve().parents[2]))
SCREEN_DIR = Path(os.environ.get("TP_SCREEN_DIR", TP_ROOT / "00_screen"))

SCREEN_AGGREGATE_PATH = Path(
    os.environ.get("TP_SCREEN_AGGREGATE_PATH", SCREEN_DIR / "screen_aggregate.parquet")
)
RETURNS_PATH = Path(os.environ.get("TP_RETURNS_PATH", SCREEN_DIR / "returns.parquet"))
LAST_SCREEN_PATH = Path(os.environ.get("TP_LAST_SCREEN_PATH", SCREEN_DIR / "last_screen.parquet"))
SCREEN_AGGREGATE_5Y_PATH = Path(
    os.environ.get("TP_SCREEN_AGGREGATE_5Y_PATH", SCREEN_DIR / "screen_aggregate_5Y.parquet")
)
TRANSCO_FACTSET_ICB_PATH = Path(
    os.environ.get("TP_TRANSCO_FACTSET_ICB_PATH", SCREEN_DIR / "Transco_FactSet_ICB.xlsx")
)
FACTSET_ICB_MAPPING_PATH = Path(
    os.environ.get("TP_FACTSET_ICB_MAPPING_PATH", SCREEN_DIR / "factset_icb_mapping.xlsx")
)
PRODUCTION_INPUTS_DIR = Path(
    os.environ.get("TP_PRODUCTION_INPUTS_DIR", SCREEN_DIR / "production_inputs")
)
PRODUCTION_INCOMING_DIR = Path(
    os.environ.get("TP_PRODUCTION_INCOMING_DIR", PRODUCTION_INPUTS_DIR / "incoming")
)
CIQ_NEW_DIR = Path(os.environ.get("TP_CIQ_NEW_DIR", PRODUCTION_INCOMING_DIR))
SUPPLEMENTAL_DIR = Path(
    os.environ.get("TP_SUPPLEMENTAL_DIR", SCREEN_DIR / "supplemental")
)
SUPPLEMENTAL_RAW_DIR = SUPPLEMENTAL_DIR / "raw"
SUPPLEMENTAL_NORMALIZED_DIR = SUPPLEMENTAL_DIR / "normalized"
SUPPLEMENTAL_RESOLVED_DIR = SUPPLEMENTAL_DIR / "resolved"
SUPPLEMENTAL_QA_DIR = SUPPLEMENTAL_DIR / "qa"


CANONICAL_DATA_SOURCES = {
    "screen_aggregate": SCREEN_AGGREGATE_PATH,
    "returns": RETURNS_PATH,
    "last_screen": LAST_SCREEN_PATH,
    "screen_aggregate_5y": SCREEN_AGGREGATE_5Y_PATH,
    "transco_factset_icb": TRANSCO_FACTSET_ICB_PATH,
    "factset_icb_mapping": FACTSET_ICB_MAPPING_PATH,
    "ciq_new_dir": CIQ_NEW_DIR,
    "production_inputs": PRODUCTION_INPUTS_DIR,
    "production_incoming": PRODUCTION_INCOMING_DIR,
}

SUPPLEMENTAL_DATA_SOURCES = {
    "supplemental": SUPPLEMENTAL_DIR,
    "supplemental_raw": SUPPLEMENTAL_RAW_DIR,
    "supplemental_normalized": SUPPLEMENTAL_NORMALIZED_DIR,
    "supplemental_resolved": SUPPLEMENTAL_RESOLVED_DIR,
    "supplemental_qa": SUPPLEMENTAL_QA_DIR,
}

ALL_DATA_SOURCES = {**CANONICAL_DATA_SOURCES, **SUPPLEMENTAL_DATA_SOURCES}


def as_str(path: Path) -> str:
    """返回兼容旧配置字典的 Windows 字符串路径。"""
    return str(path)


def data_sources(as_strings: bool = False) -> dict[str, Path] | dict[str, str]:
    """返回 canonical 与 supplemental 数据源注册表。"""
    if as_strings:
        return {name: as_str(path) for name, path in ALL_DATA_SOURCES.items()}
    return ALL_DATA_SOURCES.copy()


def validate_data_sources(required: tuple[str, ...] = ("screen_aggregate", "returns")) -> dict[str, bool]:
    """检查必需的 canonical 数据源当前是否存在。"""
    missing = [name for name in required if name not in CANONICAL_DATA_SOURCES]
    if missing:
        raise KeyError(f"未知的 canonical 数据源键：{missing}")
    return {name: CANONICAL_DATA_SOURCES[name].exists() for name in required}

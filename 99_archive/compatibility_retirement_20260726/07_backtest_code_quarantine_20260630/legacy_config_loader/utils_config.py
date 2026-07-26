"""
全局配置加载模块 - 统一从 config/config.yaml 读取数据路径等配置
"""

import os
import sys
from pathlib import Path
import yaml

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'config.yaml')
_TP_ROOT = Path(__file__).resolve().parents[2]
if str(_TP_ROOT) not in sys.path:
    sys.path.insert(0, str(_TP_ROOT))

from tp_core.data_sources import RETURNS_PATH as CANONICAL_RETURNS_PATH
from tp_core.data_sources import SCREEN_AGGREGATE_PATH


def load_config() -> dict:
    """读取并返回完整配置字典"""
    with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# 暴露常用路径常量，供其他模块直接 import 使用
_cfg = load_config()
_cfg.setdefault("data", {})
_cfg["data"]["screen_path"] = str(SCREEN_AGGREGATE_PATH)
_cfg["data"]["returns_path"] = str(CANONICAL_RETURNS_PATH)
SCREEN_PATH: str = _cfg["data"]["screen_path"]
RETURNS_PATH: str = _cfg["data"]["returns_path"]


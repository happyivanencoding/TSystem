"""兼容入口：区域分桶规则已迁入 tp_core.presentation。"""
from __future__ import annotations

from tp_core.presentation import NORTH_AMERICA, OTHERS, WEST_EUROPE, region_bucket_value

__all__ = ["NORTH_AMERICA", "OTHERS", "WEST_EUROPE", "region_bucket_value"]

"""月度因子推荐配置加载器。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_DIR = PACKAGE_ROOT / "16_factor_recommendation_model" / "config"
DEFAULT_FACTOR_DEFINITIONS_PATH = DEFAULT_CONFIG_DIR / "factor_definitions_v1.json"
DEFAULT_REGION_UNIVERSES_PATH = DEFAULT_CONFIG_DIR / "region_universes_v1.json"


@dataclass(frozen=True)
class FactorRecommendationConfig:
    """运行时配置；数据路径仍由 canonical data_sources 或 CLI 显式提供。"""

    model_version: str = "factor_recommendation_v1"
    pit_lag_months: int = 1
    target_horizon_months: int = 1
    model_type: str = "ridge"
    alpha: float = 1.0
    l1_ratio: float = 0.5
    top_quantile: float = 0.2
    min_train_rows: int = 6
    factor_definitions_path: Path = DEFAULT_FACTOR_DEFINITIONS_PATH
    region_universes_path: Path = DEFAULT_REGION_UNIVERSES_PATH

    def __post_init__(self) -> None:
        if self.pit_lag_months < 1:
            raise ValueError("pit_lag_months must be >= 1")
        if self.target_horizon_months != 1:
            raise ValueError("only next-month targets are supported")
        if not 0 < self.top_quantile <= 0.5:
            raise ValueError("top_quantile must be in (0, 0.5]")
        if self.alpha < 0:
            raise ValueError("alpha must be non-negative")
        if not 0 <= self.l1_ratio <= 1:
            raise ValueError("l1_ratio must be in [0, 1]")


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_runtime_config(
    *,
    factor_definitions_path: str | Path | None = None,
    region_universes_path: str | Path | None = None,
    **overrides: Any,
) -> FactorRecommendationConfig:
    """加载两个只读 JSON 配置并应用显式运行参数。"""

    factor_path = Path(factor_definitions_path or DEFAULT_FACTOR_DEFINITIONS_PATH)
    region_path = Path(region_universes_path or DEFAULT_REGION_UNIVERSES_PATH)
    factor_data = _read_json(factor_path)
    _read_json(region_path)  # fail early if the universe contract is malformed JSON
    values: dict[str, Any] = {
        "model_version": factor_data.get("model_version", "factor_recommendation_v1"),
        "factor_definitions_path": factor_path,
        "region_universes_path": region_path,
    }
    values.update(overrides)
    return FactorRecommendationConfig(**values)


__all__ = [
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_FACTOR_DEFINITIONS_PATH",
    "DEFAULT_REGION_UNIVERSES_PATH",
    "FactorRecommendationConfig",
    "load_runtime_config",
]

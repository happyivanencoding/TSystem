"""因子推荐包的轻量 typed contracts。

这里使用标准库 dataclass，而不是把 pandas DataFrame 隐式当成 API。所有
日期字段都使用月末 Timestamp；``feature_as_of_date`` 必须早于决策日，
``target_date`` 必须晚于决策日。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

import pandas as pd


DATE_COLUMN = "Date"
ID_COLUMN = "ISIN"
SEDOL_COLUMN = "Company SEDOL"
FEATURE_AS_OF_COLUMN = "feature_as_of_date"
TARGET_DATE_COLUMN = "target_date"


class Region(str, Enum):
    """支持的研究区域。"""

    US = "US"
    EUROPE = "EUROPE"
    JAPAN = "JAPAN"
    ASIA = "ASIA"
    GLOBAL = "GLOBAL"


def normalize_region(value: str | Region) -> str:
    text = value.value if isinstance(value, Region) else str(value).strip().upper()
    aliases = {"EU": "EUROPE", "EUR": "EUROPE", "JP": "JAPAN", "WORLD": "GLOBAL"}
    return aliases.get(text, text)


@dataclass(frozen=True)
class RecommendationContract:
    """推荐结果的逻辑主键和时间语义。"""

    schema_version: str = "factor_recommendation.recommendation.v1"
    model_version: str = "factor_recommendation_v1"
    key_columns: tuple[str, ...] = ("region", DATE_COLUMN, "factor", "model_version")
    probability_semantics: str = "not_available_for_regression"


@dataclass(frozen=True)
class TargetContract:
    """未来一个月目标的约束。"""

    horizon_months: int = 1
    date_column: str = DATE_COLUMN
    target_date_column: str = TARGET_DATE_COLUMN
    target_prefix: str = "target_"

    def __post_init__(self) -> None:
        if self.horizon_months != 1:
            raise ValueError("factor recommendation v1 只支持 next-month target")


@dataclass(frozen=True)
class FeatureContract:
    """特征的 PIT 约束。"""

    pit_lag_months: int = 1
    date_column: str = DATE_COLUMN
    feature_as_of_column: str = FEATURE_AS_OF_COLUMN

    def __post_init__(self) -> None:
        if self.pit_lag_months < 1:
            raise ValueError("factor recommendation v1 要求至少一个月 PIT lag")


@dataclass(frozen=True)
class UniverseSelection:
    """一次区域筛选的结果和治理标记。"""

    frame: pd.DataFrame
    region: str
    research_only: bool
    benchmark_approved: bool
    components: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.region == Region.ASIA.value and (
            not self.research_only or self.benchmark_approved
        ):
            raise ValueError("ASIA aggregate must be research_only and benchmark_unapproved")


@dataclass(frozen=True)
class ModelFit:
    """模型拟合元数据；``estimator`` 可以是 sklearn 或 numpy fallback。"""

    model_name: str
    backend: str
    feature_names: tuple[str, ...]
    estimator: Any
    trained_rows: int
    fallback_reason: str | None = None


@dataclass(frozen=True)
class EvaluationResult:
    """交叉验证输出，概率字段明确表示是否真的可得。"""

    metrics: Mapping[str, Any]
    predictions: pd.DataFrame
    probability_available: bool = False
    probability_note: str = "regression outputs do not imply calibrated probabilities"


def validate_temporal_contract(frame: pd.DataFrame) -> None:
    """检查 feature/target 的基本时间方向，不修改输入。"""

    required = [DATE_COLUMN, FEATURE_AS_OF_COLUMN, TARGET_DATE_COLUMN]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise KeyError(f"temporal contract missing columns: {missing}")
    dates = frame[required].apply(pd.to_datetime, errors="coerce")
    if dates.isna().any().any():
        raise ValueError("temporal contract contains non-datetime values")
    if not (dates[FEATURE_AS_OF_COLUMN] < dates[DATE_COLUMN]).all():
        raise ValueError("feature_as_of_date must be strictly before Date")
    if not (dates[TARGET_DATE_COLUMN] > dates[DATE_COLUMN]).all():
        raise ValueError("target_date must be strictly after Date")


def as_jsonable(value: Any) -> Any:
    """将常见 contract 值转换成可序列化对象。"""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): as_jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [as_jsonable(item) for item in value]
    return value

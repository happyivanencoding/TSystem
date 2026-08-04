"""月度因子推荐核心包。

该包只读取 TP canonical screen/returns；输出由调用方显式传入路径，避免
在模型层复制或修改 canonical 数据。
"""

from .config import FactorRecommendationConfig, load_runtime_config
from .contracts import (
    EvaluationResult,
    FeatureContract,
    ModelFit,
    Region,
    RecommendationContract,
    TargetContract,
)
from .audit import write_audit_artifacts
from .evaluation import evaluate_factor_models, same_month_grouped_folds
from .exporter import export_recommendations
from .factor_definitions import FactorDefinition, load_factor_definitions
from .features import build_monthly_features, build_security_feature_panel, latest_month_features
from .inputs import ResearchInputs, load_research_inputs
from .models import (
    fit_factor_models,
    fit_factor_recommendation_models,
    fit_model,
    predict_factor_recommendations,
)
from .persistence import upsert_frame
from .sleeve_engine import OfficialSleeveAdapter, OfficialSleeveResult, run_official_sleeve
from .targets import build_factor_sleeve_targets, build_next_month_targets
from .universe import (
    RegionUniverse,
    UniverseComponent,
    load_region_universes,
    select_universe,
)

__all__ = [
    "FactorDefinition",
    "FactorRecommendationConfig",
    "EvaluationResult",
    "FeatureContract",
    "ModelFit",
    "OfficialSleeveAdapter",
    "OfficialSleeveResult",
    "RegionUniverse",
    "RecommendationContract",
    "ResearchInputs",
    "Region",
    "TargetContract",
    "UniverseComponent",
    "build_factor_sleeve_targets",
    "build_monthly_features",
    "build_next_month_targets",
    "build_security_feature_panel",
    "evaluate_factor_models",
    "export_recommendations",
    "fit_factor_models",
    "fit_factor_recommendation_models",
    "fit_model",
    "latest_month_features",
    "load_factor_definitions",
    "load_region_universes",
    "load_research_inputs",
    "load_runtime_config",
    "predict_factor_recommendations",
    "run_official_sleeve",
    "same_month_grouped_folds",
    "select_universe",
    "upsert_frame",
    "write_audit_artifacts",
]

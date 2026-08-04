"""Shared TP system registry for the presentation-layer control tower."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tp_core.data_sources import (
    LAST_SCREEN_PATH,
    PRODUCTION_INPUTS_DIR,
    RETURNS_PATH,
    SCREEN_AGGREGATE_5Y_PATH,
    SCREEN_AGGREGATE_PATH,
    TP_ROOT,
)
from tp_core.workspace import (
    BACKTEST_OUTPUT_RUNS_DIR,
    CANDIDATES_DIR,
    PIPELINE_MANIFESTS_DIR,
    PIPELINE_RUNS_DIR,
    PORTFOLIOS_DIR,
    REPORTS_DIR,
    SIGNALS_DIR,
)


PIPELINE_STEPS: tuple[str, ...] = (
    "refresh_data",
    "refresh_ml",
    "refresh_small_cap",
    "refresh_factor_recommendation",
    "export_signals",
    "build_candidates",
    "optimize_portfolio",
    "run_backtest",
    "generate_report",
    "run_all",
)


@dataclass(frozen=True)
class DataAssetEntry:
    project_id: str
    name: str
    path: Path
    kind: str
    date_column: str | None = None
    required: bool = True


@dataclass(frozen=True)
class ProjectRegistryEntry:
    project_id: str
    role: str
    root_path: Path
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    commands: tuple[str, ...]
    smoke_test: str
    data_assets: tuple[str, ...]
    status: str = "active"
    manifest_required: bool = False
    pipeline_step: str | None = None


PROJECT_REGISTRY: tuple[ProjectRegistryEntry, ...] = (
    ProjectRegistryEntry(
        project_id="00_screen",
        role="核心数据库、月更、returns、CIQ、QA",
        root_path=TP_ROOT / "00_screen",
        inputs=("production_inputs/incoming", "CIQ/FactSet exports"),
        outputs=("screen_aggregate", "returns", "last_screen", "screen_aggregate_5Y", "QA profiles"),
        commands=("python -m tp_pipelines.refresh_data",),
        smoke_test="python -m tp_pipelines.refresh_data --inspect-only",
        data_assets=("screen_aggregate", "returns", "last_screen", "screen_aggregate_5Y"),
        manifest_required=True,
        pipeline_step="refresh_data",
    ),
    ProjectRegistryEntry(
        project_id="tp_core",
        role="共享路径、契约、IO、returns 审计、通用回测",
        root_path=TP_ROOT / "src" / "tp_core",
        inputs=("canonical data sources",),
        outputs=("shared Python APIs", "returns audit"),
        commands=("python -P -c \"import tp_core\"",),
        smoke_test="python -P -c \"import tp_core\"",
        data_assets=(),
    ),
    ProjectRegistryEntry(
        project_id="pipelines",
        role="主流水线薄编排与 manifest",
        root_path=TP_ROOT / "src" / "tp_pipelines",
        inputs=("canonical data", "signals", "candidates", "weights"),
        outputs=("artifacts/pipeline_runs/manifests", "artifacts/reports/latest_pipeline_report.md"),
        commands=("python -m tp_pipelines.run_all",),
        smoke_test="python -m tp_pipelines.generate_report --step refresh_data",
        data_assets=("pipeline_manifests",),
        manifest_required=True,
        pipeline_step="run_all",
    ),
    ProjectRegistryEntry(
        project_id="03_ml_enhanced",
        role="ML Score 生产 CLI 和信号导出",
        root_path=TP_ROOT / "03_ml_enhanced",
        inputs=("screen_aggregate", "returns"),
        outputs=("artifacts/signals/ml_signals.parquet",),
        commands=("python -m tp_models.ml.cli inspect", "python -m tp_models.ml.cli export-signals"),
        smoke_test="python -m tp_models.ml.cli export-signals --output <tmp>",
        data_assets=("ml_signals",),
        manifest_required=True,
        pipeline_step="export_signals",
    ),
    ProjectRegistryEntry(
        project_id="03_regime_model",
        role="Regime 风险预算信号",
        root_path=TP_ROOT / "03_regime_model",
        inputs=("screen_aggregate", "returns"),
        outputs=("artifacts/signals/regime_risk_budget.parquet",),
        commands=("python -m tp_models.regime.export_risk_budget",),
        smoke_test="python -m tp_models.regime.export_risk_budget --output <tmp>",
        data_assets=("regime_risk_budget",),
        manifest_required=True,
        pipeline_step="export_signals",
    ),
    ProjectRegistryEntry(
        project_id="03_technical_analysis",
        role="技术指标与形态信号",
        root_path=TP_ROOT / "03_technical_analysis",
        inputs=("screen_aggregate", "returns"),
        outputs=("artifacts/signals/technical_signals.parquet",),
        commands=("python -m tp_models.technical_signals",),
        smoke_test="python -m tp_models.technical_signals --output <tmp>",
        data_assets=("technical_signals",),
        manifest_required=True,
        pipeline_step="export_signals",
    ),
    ProjectRegistryEntry(
        project_id="signals",
        role="统一信号表标准产物",
        root_path=SIGNALS_DIR,
        inputs=("ML signals", "technical signals", "regime risk budget", "country model"),
        outputs=("ml_signals", "technical_signals", "regime_risk_budget", "country_model_signals"),
        commands=("python -m tp_pipelines.export_signals",),
        smoke_test="python -m tp_core.signals artifacts/signals/ml_signals.parquet",
        data_assets=("ml_signals", "technical_signals", "regime_risk_budget", "country_model_signals"),
        manifest_required=True,
        pipeline_step="export_signals",
    ),
    ProjectRegistryEntry(
        project_id="candidates",
        role="候选池生成",
        root_path=CANDIDATES_DIR,
        inputs=("artifacts/signals/*.parquet",),
        outputs=("latest_candidates",),
        commands=("python -m tp_pipelines.build_candidates",),
        smoke_test="python -m tp_pipelines.build_candidates --output <tmp>",
        data_assets=("latest_candidates",),
        manifest_required=True,
        pipeline_step="build_candidates",
    ),
    ProjectRegistryEntry(
        project_id="optimizer",
        role="优化器导入、solver 与权重转换",
        root_path=TP_ROOT / "src" / "tp_portfolio",
        inputs=("latest_candidates",),
        outputs=("optimizer result in memory",),
        commands=("python -m pytest tests/portfolio/test_optimizer.py -q",),
        smoke_test="optimizer unit tests",
        data_assets=(),
    ),
    ProjectRegistryEntry(
        project_id="portfolios",
        role="目标权重生成",
        root_path=PORTFOLIOS_DIR,
        inputs=("artifacts/candidates/latest_candidates.parquet",),
        outputs=("latest_target_weights",),
        commands=("python -m tp_pipelines.optimize_portfolio",),
        smoke_test="python -m tp_pipelines.optimize_portfolio --output <tmp>",
        data_assets=("latest_target_weights",),
        manifest_required=True,
        pipeline_step="optimize_portfolio",
    ),
    ProjectRegistryEntry(
        project_id="backtests",
        role="回测主线、YAML 配置、批量运行产物",
        root_path=TP_ROOT / "src" / "tp_backtest",
        inputs=("screen_aggregate", "returns", "latest_target_weights"),
        outputs=("historical backtest runs", "run_backtest manifests"),
        commands=("python -m tp_pipelines.run_backtest", "python -m tp_backtest.cli inspect"),
        smoke_test="python -m tp_backtest.cli inspect",
        data_assets=("backtest_runs",),
        manifest_required=True,
        pipeline_step="run_backtest",
    ),
    ProjectRegistryEntry(
        project_id="08_presentation_layer",
        role="统一展示层、控制塔、公司展示、公司分析和报告入口",
        root_path=TP_ROOT / "src" / "presentation_layer",
        inputs=("core database", "signals", "manifests", "reports"),
        outputs=("system dashboard", "company browser", "company API", "portfolio reports"),
        commands=(
            "python -m presentation_layer.cli system-dashboard",
            "python -m presentation_layer.cli web-companies",
            "python -m presentation_layer.cli company-api",
        ),
        smoke_test="python -m pytest tests/presentation/test_presentation_layer_entrypoints.py -q",
        data_assets=(),
    ),
    ProjectRegistryEntry(
        project_id="reports",
        role="最新 pipeline 和投资生产报告",
        root_path=REPORTS_DIR,
        inputs=("artifacts/pipeline_runs/manifests",),
        outputs=("latest_pipeline_report.md",),
        commands=("python -m tp_pipelines.generate_report",),
        smoke_test="latest report exists",
        data_assets=("latest_pipeline_report",),
        manifest_required=True,
        pipeline_step="generate_report",
    ),
    ProjectRegistryEntry(
        project_id="pipeline_runs",
        role="运行 manifest、审计证据、latest 指针",
        root_path=PIPELINE_RUNS_DIR,
        inputs=("all pipeline steps",),
        outputs=("manifests/<step>/<step>_latest.json",),
        commands=("python -m presentation_layer.cli system-checks",),
        smoke_test="read run_all_latest.json",
        data_assets=("pipeline_manifests",),
    ),
    ProjectRegistryEntry(
        project_id="11_docs",
        role="系统文档、主线约束、开发说明",
        root_path=TP_ROOT / "11_docs",
        inputs=("codebase decisions",),
        outputs=("README.md", "INVESTMENT_PLATFORM_MAINLINE.md", "schema docs"),
        commands=("python -m presentation_layer.cli inventory",),
        smoke_test="README exists",
        data_assets=("docs_readme",),
    ),
    ProjectRegistryEntry(
        project_id="13_sector_score_model",
        role="行业打分模型、行业偏离回测和行业配置研究",
        root_path=TP_ROOT / "13_sector_score_model",
        inputs=("screen_aggregate", "returns", "factset_icb_mapping"),
        outputs=(
            "sector_scores_panel_us",
            "sector_scores_panel_eu",
            "sector_backtest_summary_us",
            "sector_backtest_summary_eu",
        ),
        commands=(
            "python -m tp_models.sector.model --market US",
            "python -m tp_models.sector.model --market EU",
        ),
        smoke_test="latest sector model outputs exist",
        data_assets=(
            "sector_scores_panel_us",
            "sector_scores_panel_eu",
            "sector_backtest_summary_us",
            "sector_backtest_summary_eu",
        ),
    ),
    ProjectRegistryEntry(
        project_id="14_country_model",
        role="国家模型数据库、Excel 复刻与 country signal",
        root_path=TP_ROOT / "14_country_model",
        inputs=("modele_pays.xlsb",),
        outputs=("country_model_database", "country_model_signals", "country_model_single_country_scores"),
        commands=("python -m tp_models.country",),
        smoke_test="python -m tp_models.country --use-existing-database",
        data_assets=("country_model_database", "country_model_signals", "country_model_single_country_scores"),
        manifest_required=True,
        pipeline_step="export_signals",
    ),
    ProjectRegistryEntry(
        project_id="15_small_cap_model",
        role="欧洲小盘六风格防守倾斜模型与标准信号",
        root_path=TP_ROOT / "15_small_cap_model",
        inputs=("screen_aggregate",),
        outputs=("small_cap_model_signals", "eu_small_model_scores_latest", "eu_small_model_summary"),
        commands=("python -m tp_pipelines.refresh_small_cap",),
        smoke_test="python -m tp_pipelines.refresh_small_cap --inspect-only",
        data_assets=("small_cap_model_signals", "eu_small_model_scores_latest", "eu_small_model_summary"),
        manifest_required=True,
        pipeline_step="refresh_small_cap",
    ),
    ProjectRegistryEntry(
        project_id="16_factor_recommendation_model",
        role="research-only 月度因子推荐、历史面板和研究信号",
        root_path=TP_ROOT / "16_factor_recommendation_model",
        inputs=("screen_aggregate", "returns", "universe/factor/model config"),
        outputs=(
            "factor_recommendation_panel",
            "factor_recommendation_history",
            "factor_recommendation_signals",
            "refresh_factor_recommendation manifest",
        ),
        commands=("python -m tp_pipelines.refresh_factor_recommendation",),
        smoke_test="python -m tp_pipelines.refresh_factor_recommendation --inspect-only",
        data_assets=(
            "factor_recommendation_panel",
            "factor_recommendation_history",
            "factor_recommendation_signals",
            "factor_recommendation_manifest",
        ),
        # Research-only outputs are optional and must not fail the production
        # control tower while the refresh step remains disabled by default.
        manifest_required=False,
        pipeline_step="refresh_factor_recommendation",
    ),
)


DATA_ASSET_REGISTRY: tuple[DataAssetEntry, ...] = (
    DataAssetEntry("00_screen", "screen_aggregate", SCREEN_AGGREGATE_PATH, "core parquet", "Date"),
    DataAssetEntry("00_screen", "returns", RETURNS_PATH, "core parquet", "__index_level_0__"),
    DataAssetEntry("00_screen", "last_screen", LAST_SCREEN_PATH, "core parquet", "Date"),
    DataAssetEntry("00_screen", "screen_aggregate_5Y", SCREEN_AGGREGATE_5Y_PATH, "core parquet", "Date"),
    DataAssetEntry(
        "00_screen",
        "input_inventory",
        PRODUCTION_INPUTS_DIR / "manifests" / "input_inventory_latest.json",
        "manifest json",
    ),
    DataAssetEntry("signals", "ml_signals", SIGNALS_DIR / "ml_signals.parquet", "signal parquet", "Date"),
    DataAssetEntry(
        "signals",
        "technical_signals",
        SIGNALS_DIR / "technical_signals.parquet",
        "signal parquet",
        "Date",
    ),
    DataAssetEntry(
        "signals",
        "regime_risk_budget",
        SIGNALS_DIR / "regime_risk_budget.parquet",
        "signal parquet",
        "Date",
    ),
    DataAssetEntry(
        "14_country_model",
        "country_model_database",
        TP_ROOT / "14_country_model" / "data" / "country_model_database.parquet",
        "country model database parquet",
        "Date",
    ),
    DataAssetEntry(
        "signals",
        "country_model_signals",
        SIGNALS_DIR / "country_model_signals.parquet",
        "signal parquet",
        "Date",
    ),
    DataAssetEntry(
        "signals",
        "small_cap_model_signals",
        SIGNALS_DIR / "small_cap_model_signals.parquet",
        "signal parquet",
        "Date",
    ),
    DataAssetEntry(
        "14_country_model",
        "country_model_single_country_scores",
        TP_ROOT / "14_country_model" / "outputs" / "country_model_single_country_scores.parquet",
        "country model detail parquet",
        "Date",
    ),
    DataAssetEntry(
        "15_small_cap_model",
        "eu_small_model_scores_latest",
        TP_ROOT / "15_small_cap_model" / "outputs" / "eu_small_model_scores_latest.parquet",
        "small-cap model parquet",
        "Date",
    ),
    DataAssetEntry(
        "15_small_cap_model",
        "eu_small_model_summary",
        TP_ROOT / "15_small_cap_model" / "outputs" / "eu_small_model_summary.json",
        "small-cap model summary json",
    ),
    DataAssetEntry(
        "16_factor_recommendation_model",
        "factor_recommendation_panel",
        TP_ROOT
        / "16_factor_recommendation_model"
        / "outputs"
        / "factor_recommendation_panel.parquet",
        "factor recommendation panel parquet",
        "Date",
        required=False,
    ),
    DataAssetEntry(
        "16_factor_recommendation_model",
        "factor_recommendation_history",
        TP_ROOT
        / "16_factor_recommendation_model"
        / "outputs"
        / "factor_recommendation_history.parquet",
        "factor recommendation history parquet",
        "Date",
        required=False,
    ),
    DataAssetEntry(
        "16_factor_recommendation_model",
        "factor_recommendation_signals",
        SIGNALS_DIR / "factor_recommendation_signals.parquet",
        "research signal parquet",
        "Date",
        required=False,
    ),
    DataAssetEntry(
        "16_factor_recommendation_model",
        "factor_recommendation_manifest",
        PIPELINE_MANIFESTS_DIR
        / "refresh_factor_recommendation"
        / "refresh_factor_recommendation_latest.json",
        "pipeline manifest json",
        required=False,
    ),
    DataAssetEntry(
        "13_sector_score_model",
        "sector_scores_panel_us",
        TP_ROOT / "13_sector_score_model" / "outputs_fs_sector_default" / "sector_scores_panel.parquet",
        "sector model parquet",
        "Date",
    ),
    DataAssetEntry(
        "13_sector_score_model",
        "sector_scores_panel_eu",
        TP_ROOT / "13_sector_score_model" / "outputs_eu" / "sector_scores_panel.parquet",
        "sector model parquet",
        "Date",
    ),
    DataAssetEntry(
        "13_sector_score_model",
        "sector_backtest_summary_us",
        TP_ROOT / "13_sector_score_model" / "outputs_fs_sector_default" / "backtest_summary.json",
        "sector model summary json",
    ),
    DataAssetEntry(
        "13_sector_score_model",
        "sector_backtest_summary_eu",
        TP_ROOT / "13_sector_score_model" / "outputs_eu" / "backtest_summary.json",
        "sector model summary json",
    ),
    DataAssetEntry(
        "candidates",
        "latest_candidates",
        CANDIDATES_DIR / "latest_candidates.parquet",
        "candidate parquet",
        "candidate_date",
    ),
    DataAssetEntry(
        "portfolios",
        "latest_target_weights",
        PORTFOLIOS_DIR / "latest_target_weights.parquet",
        "portfolio parquet",
        "candidate_date",
    ),
    DataAssetEntry("backtests", "backtest_runs", BACKTEST_OUTPUT_RUNS_DIR, "run directory"),
    DataAssetEntry("reports", "latest_pipeline_report", REPORTS_DIR / "latest_pipeline_report.md", "markdown"),
    DataAssetEntry("pipeline_runs", "pipeline_manifests", PIPELINE_MANIFESTS_DIR, "manifest directory"),
    DataAssetEntry("11_docs", "docs_readme", TP_ROOT / "11_docs" / "README.md", "markdown"),
)


FLOW_NODES: tuple[str, ...] = (
    "生产输入",
    "核心数据库",
    "ML / Regime / Technical",
    "统一信号",
    "候选池",
    "组合权重",
    "回测",
    "报告 / Dashboard",
)

FLOW_EDGES: tuple[tuple[str, str, int], ...] = (
    ("生产输入", "核心数据库", 4),
    ("核心数据库", "ML / Regime / Technical", 3),
    ("ML / Regime / Technical", "统一信号", 3),
    ("统一信号", "候选池", 2),
    ("候选池", "组合权重", 2),
    ("组合权重", "回测", 2),
    ("回测", "报告 / Dashboard", 2),
    ("统一信号", "报告 / Dashboard", 1),
    ("核心数据库", "报告 / Dashboard", 1),
)


PROJECTS_BY_ID = {entry.project_id: entry for entry in PROJECT_REGISTRY}


def project_by_id(project_id: str) -> ProjectRegistryEntry:
    return PROJECTS_BY_ID[project_id]


__all__ = [
    "DATA_ASSET_REGISTRY",
    "FLOW_EDGES",
    "FLOW_NODES",
    "PIPELINE_STEPS",
    "PROJECTS_BY_ID",
    "PROJECT_REGISTRY",
    "DataAssetEntry",
    "ProjectRegistryEntry",
    "project_by_id",
]

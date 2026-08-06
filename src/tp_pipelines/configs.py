"""Typed configuration contracts for production pipeline steps."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, TypeVar

from tp_core.data_sources import (
    FACTSET_ICB_MAPPING_PATH,
    LAST_SCREEN_PATH,
    RETURNS_PATH,
    SCREEN_AGGREGATE_PATH,
    TP_ROOT,
)
from tp_core.workspace import CANDIDATES_DIR, PORTFOLIOS_DIR, REPORTS_DIR, SIGNALS_DIR

TConfig = TypeVar("TConfig", bound="StepConfig")


@dataclass
class StepConfig:
    """Base class that confines ``argparse.Namespace`` to CLI adapters."""

    @classmethod
    def from_namespace(cls: type[TConfig], args: argparse.Namespace) -> TConfig:
        values = {field.name: getattr(args, field.name) for field in fields(cls)}
        return cls(**values)


@dataclass
class RefreshDataConfig(StepConfig):
    base_dir: str | None
    input_month: str | None
    screen_excel: str | None
    returns_delta: str | None
    update_mode: str
    ciq_dir: str | None
    skip_ciq: bool
    dry_run: bool
    inspect_only: bool
    qa_report: str | None
    run_type: str
    apply: bool = False
    partition_writer: bool = False
    compatibility_exports: bool | None = None
    stage_timing_path: str | None = None


@dataclass
class RefreshSupplementalConfig(StepConfig):
    source: list[str] | None
    from_date: str
    to_date: str | None
    config: str
    security_map: str
    max_jobs: int | None
    timeout_seconds: int
    resume: bool
    dry_run: bool
    inspect_only: bool
    promote_to_canonical: bool
    run_type: str


@dataclass
class RefreshRegimeConfig(StepConfig):
    regime_output: str
    run_type: str


@dataclass
class RefreshSectorConfig(StepConfig):
    screen: str
    returns: str
    mapping: str
    us_output_dir: str
    eu_output_dir: str
    legacy_us_output_dir: str | None
    start_date: str
    score_column: str
    top_n: int
    bottom_n: int
    inspect_only: bool
    run_type: str


@dataclass
class RefreshCountryConfig(StepConfig):
    workbook: str
    database_output: str
    output_dir: str
    signal_output: str
    all_history: bool
    use_existing_database: bool
    inspect_only: bool
    run_type: str


@dataclass
class RefreshMLConfig(StepConfig):
    date: list[str] | None
    from_date: str | None
    to_date: str | None
    universe: list[str] | None
    inspect_only: bool
    timeout_seconds: int
    run_type: str


@dataclass
class RefreshTechnicalConfig(StepConfig):
    returns: str
    screen: str
    output: str
    max_lag_days: int
    timeout_seconds: int
    inspect_only: bool
    run_type: str


@dataclass
class ExportSignalsConfig(StepConfig):
    as_of: str | None
    all_history: bool
    skip_ml: bool
    skip_technical: bool
    skip_regime: bool
    skip_country: bool
    regime_oos: bool
    region: list[str] | None
    patterns: str
    returns: str
    ml_output: str
    technical_output: str
    regime_output: str
    country_output: str
    country_workbook: str
    country_database: str
    run_type: str


@dataclass
class RefreshSmallCapConfig(StepConfig):
    as_of: str | None
    screen: str
    config: str
    output_dir: str
    signal_output: str
    all_history: bool
    inspect_only: bool
    min_coverage: float
    run_type: str


@dataclass
class RefreshFactorRecommendationConfig(StepConfig):
    """Research-only factor recommendation refresh contract.

    The step deliberately has its own output and signal paths.  Keeping this
    contract separate from the production signal export prevents a research
    refresh from changing the security candidate or optimizer inputs.
    """

    inspect_only: bool
    as_of: str | None
    screen: str
    returns: str
    universe_config: str
    factor_config: str
    model_config: str
    output_dir: str
    signal_output: str
    all_history: bool
    use_frozen_model: bool
    minimum_coverage: float
    run_type: str


@dataclass
class BuildCandidatesConfig(StepConfig):
    as_of: str | None
    output: str
    top_n: int | None
    top_pct: float
    ml_weight: float
    technical_weight: float
    allocation_weight: float
    candidate_date_policy: str
    max_component_lag_days: int
    allow_stale_technical: bool
    by_region: bool
    signals_dir: str
    last_screen: str
    run_type: str


@dataclass
class OptimizePortfolioConfig(StepConfig):
    as_of: str | None
    candidates: str
    output: str
    method: str
    max_weight: float | None
    min_weight: float
    region: str | None
    old_portfolio: str | None
    benchmark_active_limit: float
    country_margin: float
    sector_margin: float
    max_turnover: float | None
    transaction_cost: float
    country_tilt_strength: float
    sector_tilt_strength: float
    run_type: str


@dataclass
class RunBacktestConfig(StepConfig):
    profile: str
    screen: str | None
    returns: str | None
    user: str | None
    inspect_only: bool
    bench: str | None
    metric: list[str] | None
    start_date: str | None
    percentile: float | None
    ptf_name: str | None
    output_dir: str | None
    max_weight: float | None
    sector_neutral: bool
    top: bool
    bottom: bool
    batch: bool
    run_type: str
    record_experiment: bool
    hypothesis_id: str
    experiment_name: str
    parent_run_id: str | None
    effective_trial_count: int | None
    experiment_root: str | None


@dataclass
class GenerateReportConfig(StepConfig):
    output: str
    step: list[str] | None
    run_type: str


@dataclass(frozen=True)
class PipelineControls:
    skip_refresh_data: bool
    refresh_supplemental_data: bool
    refresh_regime: bool
    refresh_ml: bool
    skip_refresh_sector: bool
    skip_refresh_country_model: bool
    skip_refresh_technical: bool
    skip_export_signals: bool
    skip_refresh_small_cap: bool
    skip_build_candidates: bool
    skip_optimize_portfolio: bool
    skip_backtest: bool
    skip_report: bool
    refresh_factor_recommendation: bool


@dataclass(frozen=True)
class PipelineExperimentConfig:
    hypothesis_id: str
    name: str
    parent_run_id: str | None
    effective_trial_count: int | None
    root: str | None
    trial_family: str


@dataclass
class PipelineRunConfig:
    """Resolved configuration for one pipeline execution."""

    as_of: str | None
    run_type: str
    freshness_window_days: int
    reuse_manifest: str | None
    model_release_ids: tuple[str, ...]
    controls: PipelineControls
    experiment: PipelineExperimentConfig
    refresh_data: RefreshDataConfig
    refresh_supplemental: RefreshSupplementalConfig
    refresh_regime: RefreshRegimeConfig
    refresh_sector: RefreshSectorConfig
    refresh_country_model: RefreshCountryConfig
    refresh_ml: RefreshMLConfig
    refresh_technical: RefreshTechnicalConfig
    export_signals: ExportSignalsConfig
    refresh_small_cap: RefreshSmallCapConfig
    refresh_factor_recommendation: RefreshFactorRecommendationConfig
    build_candidates: BuildCandidatesConfig
    optimize_portfolio: OptimizePortfolioConfig
    run_backtest: RunBacktestConfig
    generate_report: GenerateReportConfig
    cli_parameters: dict[str, Any]

    @property
    def candidates_output(self) -> str:
        return self.build_candidates.output

    @property
    def portfolio_output(self) -> str:
        return self.optimize_portfolio.output

    @property
    def report_output(self) -> str:
        return self.generate_report.output

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "PipelineRunConfig":
        """Adapt parser output once; all downstream code receives typed configs."""

        values = vars(args).copy()

        def get(name: str, default: Any = None) -> Any:
            return getattr(args, name, default)

        run_type = str(get("run_type", "production"))
        as_of = get("as_of")
        raw_model_release_ids = get("model_release_id", ()) or ()
        if isinstance(raw_model_release_ids, str):
            raw_model_release_ids = (raw_model_release_ids,)
        model_release_ids = tuple(str(item) for item in raw_model_release_ids)
        hypothesis_id = get("hypothesis_id") or "production-pipeline"
        experiment_name = get("experiment_name") or "TP production pipeline"
        technical_patterns = str(
            get(
                "technical_patterns_output",
                TP_ROOT / "03_technical_analysis" / "output" / "patterns.parquet",
            )
        )
        candidates_output = str(
            get("candidates_output", CANDIDATES_DIR / "latest_candidates.parquet")
        )
        portfolio_output = str(
            get(
                "portfolio_output",
                PORTFOLIOS_DIR / "latest_target_weights.parquet",
            )
        )
        report_output = str(
            get("report_output", REPORTS_DIR / "latest_pipeline_report.md")
        )
        experiment_root = get("experiment_root")
        effective_trial_count = get("effective_trial_count")

        controls = PipelineControls(
            skip_refresh_data=bool(get("skip_refresh_data", False)),
            refresh_supplemental_data=bool(get("refresh_supplemental_data", False)),
            refresh_regime=bool(get("refresh_regime", True)),
            refresh_ml=bool(get("refresh_ml", False)),
            skip_refresh_sector=bool(get("skip_refresh_sector", False)),
            skip_refresh_country_model=bool(get("skip_refresh_country_model", False)),
            skip_refresh_technical=bool(get("skip_refresh_technical", False)),
            skip_export_signals=bool(get("skip_export_signals", False)),
            skip_refresh_small_cap=bool(get("skip_refresh_small_cap", False)),
            skip_build_candidates=bool(get("skip_build_candidates", False)),
            skip_optimize_portfolio=bool(get("skip_optimize_portfolio", False)),
            skip_backtest=bool(get("skip_backtest", False)),
            skip_report=bool(get("skip_report", False)),
            refresh_factor_recommendation=bool(
                get("refresh_factor_recommendation", False)
            ),
        )
        experiment = PipelineExperimentConfig(
            hypothesis_id=hypothesis_id,
            name=experiment_name,
            parent_run_id=get("parent_run_id"),
            effective_trial_count=effective_trial_count,
            root=experiment_root,
            trial_family=str(get("trial_family", "production-pipeline")),
        )
        refresh_data = RefreshDataConfig(
            base_dir=None,
            input_month=get("input_month"),
            screen_excel=None,
            returns_delta=None,
            update_mode=str(get("update_mode", "both")),
            ciq_dir=get("ciq_dir"),
            skip_ciq=bool(get("skip_ciq", False)),
            dry_run=bool(get("dry_run_data", False)),
            inspect_only=bool(get("inspect_only_refresh_data", False)),
            qa_report=None,
            run_type=run_type,
            apply=bool(get("apply", False)),
        )
        if refresh_data.apply:
            values["write_approval"] = "explicit_cli_apply"
        elif bool(get("skip_refresh_data", False)):
            values["write_approval"] = "not_required_skip_refresh_data"
        elif refresh_data.dry_run or refresh_data.inspect_only:
            values["write_approval"] = "not_required_non_writing_mode"
        else:
            values["write_approval"] = "blocked_missing_explicit_cli_apply"
        supplemental_config = str(
            get("supplemental_config", Path(__file__).with_name("supplemental_sources.json"))
        )
        supplemental_security_map = str(
            get(
                "supplemental_security_map",
                TP_ROOT
                / "00_screen"
                / "supplemental"
                / "identifiers"
                / "security_identifiers.csv",
            )
        )
        refresh_supplemental = RefreshSupplementalConfig(
            source=get("supplemental_source"),
            from_date=str(get("supplemental_from_date", "2000-01-01")),
            to_date=get("supplemental_to_date"),
            config=supplemental_config,
            security_map=supplemental_security_map,
            max_jobs=get("supplemental_max_jobs"),
            timeout_seconds=int(get("supplemental_timeout_seconds", 30)),
            resume=bool(get("supplemental_resume", False)),
            dry_run=bool(get("supplemental_dry_run", False)),
            inspect_only=bool(get("inspect_only_supplemental", False)),
            promote_to_canonical=False,
            run_type=run_type,
        )
        refresh_regime = RefreshRegimeConfig(
            regime_output=str(SIGNALS_DIR / "regime_risk_budget.parquet"),
            run_type=run_type,
        )
        refresh_sector = RefreshSectorConfig(
            screen=str(get("sector_screen", SCREEN_AGGREGATE_PATH)),
            returns=str(get("sector_returns", RETURNS_PATH)),
            mapping=str(get("sector_mapping") or FACTSET_ICB_MAPPING_PATH),
            us_output_dir=str(
                get(
                    "sector_us_output_dir",
                    TP_ROOT / "13_sector_score_model" / "outputs_fs_sector_default",
                )
            ),
            eu_output_dir=str(
                get(
                    "sector_eu_output_dir",
                    TP_ROOT / "13_sector_score_model" / "outputs_eu",
                )
            ),
            legacy_us_output_dir=str(
                get(
                    "sector_legacy_us_output_dir",
                    TP_ROOT / "13_sector_score_model" / "outputs",
                )
            ),
            start_date=str(get("sector_start_date", "2010-01-01")),
            score_column=str(get("sector_score_column", "score_final")),
            top_n=int(get("sector_top_n", 3)),
            bottom_n=int(get("sector_bottom_n", 3)),
            inspect_only=bool(get("inspect_only_sector", False)),
            run_type=run_type,
        )
        refresh_country_model = RefreshCountryConfig(
            workbook=str(
                get(
                    "country_workbook",
                    TP_ROOT / "00_screen" / "production_inputs" / "modele_pays.xlsb",
                )
            ),
            database_output=str(
                get(
                    "country_database",
                    TP_ROOT / "14_country_model" / "data" / "country_model_database.parquet",
                )
            ),
            output_dir=str(TP_ROOT / "14_country_model" / "outputs"),
            signal_output=str(
                get("country_output", SIGNALS_DIR / "country_model_signals.parquet")
            ),
            all_history=bool(get("all_history_signals", False)),
            use_existing_database=bool(get("use_existing_country_database", False)),
            inspect_only=bool(get("inspect_only_country_model", False)),
            run_type=run_type,
        )
        refresh_ml = RefreshMLConfig(
            date=get("ml_date"),
            from_date=get("ml_from_date"),
            to_date=get("ml_to_date"),
            universe=get("ml_universe"),
            inspect_only=bool(get("inspect_only_ml", False)),
            timeout_seconds=int(get("ml_timeout_seconds", 7200)),
            run_type=run_type,
        )
        refresh_technical = RefreshTechnicalConfig(
            returns=str(RETURNS_PATH),
            screen=str(SCREEN_AGGREGATE_PATH),
            output=technical_patterns,
            max_lag_days=int(get("technical_max_lag_days", 31)),
            timeout_seconds=int(get("technical_timeout_seconds", 1800)),
            inspect_only=bool(get("inspect_only_technical", False)),
            run_type=run_type,
        )
        export_signals = ExportSignalsConfig(
            as_of=as_of,
            all_history=bool(get("all_history_signals", False)),
            skip_ml=False,
            skip_technical=False,
            skip_regime=controls.refresh_regime,
            skip_country=bool(get("skip_country", False)),
            regime_oos=bool(get("regime_oos", False)),
            region=get("regime_region"),
            patterns=technical_patterns,
            returns=str(RETURNS_PATH),
            ml_output=str(SIGNALS_DIR / "ml_signals.parquet"),
            technical_output=str(SIGNALS_DIR / "technical_signals.parquet"),
            regime_output=str(SIGNALS_DIR / "regime_risk_budget.parquet"),
            country_output=str(
                get(
                    "country_output",
                    SIGNALS_DIR / "country_model_signals.parquet",
                )
            ),
            country_workbook=str(
                get(
                    "country_workbook",
                    TP_ROOT / "00_screen" / "production_inputs" / "modele_pays.xlsb",
                )
            ),
            country_database=str(
                get(
                    "country_database",
                    TP_ROOT / "14_country_model" / "data" / "country_model_database.parquet",
                )
            ),
            run_type=run_type,
        )
        small_cap_config = str(
            get(
                "small_cap_config",
                TP_ROOT
                / "15_small_cap_model"
                / "config"
                / "eu_small_validated_qvm.json",
            )
        )
        refresh_small_cap = RefreshSmallCapConfig(
            as_of=as_of,
            screen=str(SCREEN_AGGREGATE_PATH),
            config=small_cap_config,
            output_dir=str(get("small_cap_output_dir", TP_ROOT / "15_small_cap_model" / "outputs")),
            signal_output=str(
                get(
                    "small_cap_signal_output",
                    SIGNALS_DIR / "small_cap_model_signals.parquet",
                )
            ),
            all_history=bool(get("all_history_signals", False)),
            inspect_only=bool(get("inspect_only_small_cap", False)),
            min_coverage=float(get("small_cap_min_coverage", 0.5)),
            run_type=run_type,
        )
        factor_recommendation_root = TP_ROOT / "16_factor_recommendation_model"
        factor_recommendation_config = RefreshFactorRecommendationConfig(
            inspect_only=bool(
                get(
                    "factor_recommendation_inspect_only",
                    get("inspect_only_factor_recommendation", False),
                )
            ),
            as_of=get("factor_recommendation_as_of", as_of),
            screen=str(
                get(
                    "factor_recommendation_screen",
                    get("factor_screen", SCREEN_AGGREGATE_PATH),
                )
            ),
            returns=str(
                get(
                    "factor_recommendation_returns",
                    get("factor_returns", RETURNS_PATH),
                )
            ),
            universe_config=str(
                get(
                    "factor_recommendation_universe_config",
                    factor_recommendation_root
                    / "config"
                    / "region_universes_v1.json",
                )
            ),
            factor_config=str(
                get(
                    "factor_recommendation_factor_config",
                    factor_recommendation_root
                    / "config"
                    / "factor_definitions_v1.json",
                )
            ),
            model_config=str(
                get(
                    "factor_recommendation_model_config",
                    factor_recommendation_root / "config" / "model_v1.json",
                )
            ),
            output_dir=str(
                get(
                    "factor_recommendation_output_dir",
                    factor_recommendation_root / "outputs",
                )
            ),
            signal_output=str(
                get(
                    "factor_recommendation_signal_output",
                    SIGNALS_DIR / "factor_exposure_snapshot_signals.parquet",
                )
            ),
            all_history=bool(get("factor_recommendation_all_history", False)),
            use_frozen_model=bool(
                get("factor_recommendation_use_frozen_model", False)
            ),
            minimum_coverage=float(
                get("factor_recommendation_minimum_coverage", 0.8)
            ),
            run_type=run_type,
        )
        build_candidates = BuildCandidatesConfig(
            as_of=as_of,
            output=candidates_output,
            top_n=get("top_n"),
            top_pct=float(get("top_pct", 0.10)),
            ml_weight=float(get("ml_weight", 0.70)),
            technical_weight=float(get("technical_weight", 0.30)),
            allocation_weight=float(get("allocation_weight", 0.20)),
            candidate_date_policy=str(get("candidate_date_policy", "max_component")),
            max_component_lag_days=int(get("candidate_max_component_lag_days", 31)),
            allow_stale_technical=bool(get("allow_stale_technical", False)),
            by_region=bool(get("by_region", False)),
            signals_dir=str(SIGNALS_DIR),
            last_screen=str(LAST_SCREEN_PATH),
            run_type=run_type,
        )
        optimize_portfolio = OptimizePortfolioConfig(
            as_of=as_of,
            candidates=candidates_output,
            output=portfolio_output,
            method=str(get("optimizer_method", "constrained")),
            max_weight=get("max_weight", 0.05),
            min_weight=float(get("min_weight", 0.0)),
            region=get("portfolio_region"),
            old_portfolio=get("old_portfolio"),
            benchmark_active_limit=float(get("benchmark_active_limit", 0.03)),
            country_margin=float(get("country_margin", 0.05)),
            sector_margin=float(get("sector_margin", 0.04)),
            max_turnover=get("max_turnover"),
            transaction_cost=float(get("transaction_cost", 0.001)),
            country_tilt_strength=float(get("country_tilt_strength", 0.15)),
            sector_tilt_strength=float(get("sector_tilt_strength", 0.10)),
            run_type=run_type,
        )
        run_backtest = RunBacktestConfig(
            profile=str(get("backtest_profile", "default")),
            screen=None,
            returns=None,
            user=get("backtest_user"),
            inspect_only=bool(get("inspect_only_backtest", False)),
            bench=get("bench"),
            metric=get("metric"),
            start_date=get("start_date"),
            percentile=get("percentile"),
            ptf_name=get("ptf_name"),
            output_dir=get("backtest_output_dir"),
            max_weight=get("backtest_max_weight"),
            sector_neutral=bool(get("sector_neutral", False)),
            top=bool(get("top", False)),
            bottom=bool(get("bottom", False)),
            batch=bool(get("batch", False)),
            run_type=run_type,
            record_experiment=True,
            hypothesis_id=f"{hypothesis_id}-backtest",
            experiment_name=f"{experiment_name} backtest",
            parent_run_id=None,
            effective_trial_count=effective_trial_count,
            experiment_root=experiment_root,
        )
        generate_report = GenerateReportConfig(
            output=report_output,
            step=None,
            run_type=run_type,
        )
        return cls(
            as_of=as_of,
            run_type=run_type,
            freshness_window_days=int(get("freshness_window_days", 31)),
            reuse_manifest=get("reuse_manifest"),
            model_release_ids=model_release_ids,
            controls=controls,
            experiment=experiment,
            refresh_data=refresh_data,
            refresh_supplemental=refresh_supplemental,
            refresh_regime=refresh_regime,
            refresh_sector=refresh_sector,
            refresh_country_model=refresh_country_model,
            refresh_ml=refresh_ml,
            refresh_technical=refresh_technical,
            export_signals=export_signals,
            refresh_small_cap=refresh_small_cap,
            refresh_factor_recommendation=factor_recommendation_config,
            build_candidates=build_candidates,
            optimize_portfolio=optimize_portfolio,
            run_backtest=run_backtest,
            generate_report=generate_report,
            cli_parameters=values,
        )

"""Typed step registry for the TP production pipeline."""

from __future__ import annotations

import argparse
from argparse import Namespace
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from tp_core.data_sources import LAST_SCREEN_PATH, RETURNS_PATH, SCREEN_AGGREGATE_PATH, TP_ROOT

from .build_candidates import DEFAULT_OUTPUT as DEFAULT_CANDIDATES, run_build_candidates
from .common import REPORTS_DIR
from .export_signals import run_export_signals
from .generate_report import run_generate_report
from .optimize_portfolio import DEFAULT_OUTPUT as DEFAULT_PORTFOLIO, run_optimize_portfolio
from .refresh_data import run_refresh_data
from .refresh_ml import run_refresh_ml
from .refresh_regime import run_refresh_regime
from .refresh_small_cap import DEFAULT_CONFIG as DEFAULT_SMALL_CAP_CONFIG
from .refresh_small_cap import DEFAULT_OUTPUT_DIR as DEFAULT_SMALL_CAP_OUTPUT_DIR
from .refresh_small_cap import DEFAULT_SIGNAL_OUTPUT as DEFAULT_SMALL_CAP_SIGNAL_OUTPUT
from .refresh_small_cap import run_refresh_small_cap
from .refresh_supplemental_data import (
    DEFAULT_CONFIG as DEFAULT_SUPPLEMENTAL_CONFIG,
    DEFAULT_SECURITY_MAP as DEFAULT_SUPPLEMENTAL_SECURITY_MAP,
)
from .refresh_supplemental_data import run_refresh_supplemental_data
from .refresh_technical import DEFAULT_PATTERNS as DEFAULT_TECHNICAL_PATTERNS
from .refresh_technical import run_refresh_technical
from .run_backtest import run_backtest_step


@dataclass
class PipelineContext:
    """Resolved pipeline configuration and mutable execution state."""

    args: argparse.Namespace
    run_type: str
    candidates_output: str
    portfolio_output: str
    report_output: str
    technical_patterns_output: str
    child_manifests: list[str] = field(default_factory=list)
    regime_refreshed: bool = False
    experiment_parent_run_id: str | None = None

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "PipelineContext":
        return cls(
            args=args,
            run_type=getattr(args, "run_type", "production"),
            candidates_output=getattr(args, "candidates_output", str(DEFAULT_CANDIDATES)),
            portfolio_output=getattr(args, "portfolio_output", str(DEFAULT_PORTFOLIO)),
            report_output=getattr(
                args,
                "report_output",
                str(REPORTS_DIR / "latest_pipeline_report.md"),
            ),
            technical_patterns_output=getattr(
                args,
                "technical_patterns_output",
                str(DEFAULT_TECHNICAL_PATTERNS),
            ),
        )

    def record(self, manifest: str | Path) -> None:
        self.child_manifests.append(str(manifest))


@dataclass(frozen=True)
class PipelineStep:
    """One ordered, conditionally enabled pipeline operation."""

    name: str
    enabled: Callable[[PipelineContext], bool]
    execute: Callable[[PipelineContext], Path]


def _refresh_data(context: PipelineContext) -> Path:
    args = context.args
    return run_refresh_data(
        Namespace(
            base_dir=None,
            input_month=args.input_month,
            screen_excel=None,
            returns_delta=None,
            update_mode=args.update_mode,
            ciq_dir=args.ciq_dir,
            skip_ciq=args.skip_ciq,
            dry_run=args.dry_run_data,
            inspect_only=args.inspect_only_refresh_data,
            qa_report=None,
            run_type=context.run_type,
        )
    )


def _refresh_supplemental(context: PipelineContext) -> Path:
    args = context.args
    return run_refresh_supplemental_data(
        Namespace(
            source=getattr(args, "supplemental_source", None),
            from_date=getattr(args, "supplemental_from_date", "2000-01-01"),
            to_date=getattr(args, "supplemental_to_date", None),
            config=getattr(args, "supplemental_config", str(DEFAULT_SUPPLEMENTAL_CONFIG)),
            security_map=getattr(
                args,
                "supplemental_security_map",
                str(DEFAULT_SUPPLEMENTAL_SECURITY_MAP),
            ),
            max_jobs=getattr(args, "supplemental_max_jobs", None),
            timeout_seconds=getattr(args, "supplemental_timeout_seconds", 30),
            resume=getattr(args, "supplemental_resume", False),
            dry_run=getattr(args, "supplemental_dry_run", False),
            inspect_only=getattr(args, "inspect_only_supplemental", False),
            promote_to_canonical=False,
            run_type=context.run_type,
        )
    )


def _refresh_regime(context: PipelineContext) -> Path:
    output = TP_ROOT / "04_signals" / "regime_risk_budget.parquet"
    result = run_refresh_regime(
        Namespace(regime_output=str(output), run_type=context.run_type)
    )
    context.regime_refreshed = True
    return result


def _refresh_ml(context: PipelineContext) -> Path:
    args = context.args
    return run_refresh_ml(
        Namespace(
            date=getattr(args, "ml_date", None),
            from_date=getattr(args, "ml_from_date", None),
            to_date=getattr(args, "ml_to_date", None),
            universe=getattr(args, "ml_universe", None),
            inspect_only=getattr(args, "inspect_only_ml", False),
            timeout_seconds=getattr(args, "ml_timeout_seconds", 7200),
            run_type=context.run_type,
        )
    )


def _refresh_technical(context: PipelineContext) -> Path:
    args = context.args
    return run_refresh_technical(
        Namespace(
            returns=str(RETURNS_PATH),
            screen=str(SCREEN_AGGREGATE_PATH),
            output=context.technical_patterns_output,
            max_lag_days=getattr(args, "technical_max_lag_days", 31),
            timeout_seconds=getattr(args, "technical_timeout_seconds", 1800),
            inspect_only=getattr(args, "inspect_only_technical", False),
            run_type=context.run_type,
        )
    )


def _export_signals(context: PipelineContext) -> Path:
    args = context.args
    return run_export_signals(
        Namespace(
            as_of=args.as_of,
            all_history=args.all_history_signals,
            skip_ml=False,
            skip_technical=False,
            skip_regime=context.regime_refreshed,
            skip_country=getattr(args, "skip_country", False),
            regime_oos=args.regime_oos,
            region=args.regime_region,
            patterns=context.technical_patterns_output,
            returns=str(RETURNS_PATH),
            ml_output=str(TP_ROOT / "04_signals" / "ml_signals.parquet"),
            technical_output=str(TP_ROOT / "04_signals" / "technical_signals.parquet"),
            regime_output=str(TP_ROOT / "04_signals" / "regime_risk_budget.parquet"),
            country_output=getattr(
                args,
                "country_output",
                str(TP_ROOT / "04_signals" / "country_model_signals.parquet"),
            ),
            country_workbook=getattr(
                args,
                "country_workbook",
                str(TP_ROOT / "00_screen" / "production_inputs" / "modele_pays.xlsb"),
            ),
            country_database=getattr(
                args,
                "country_database",
                str(
                    TP_ROOT
                    / "14_country_model"
                    / "data"
                    / "country_model_database.parquet"
                ),
            ),
            run_type=context.run_type,
        )
    )


def _refresh_small_cap(context: PipelineContext) -> Path:
    args = context.args
    return run_refresh_small_cap(
        Namespace(
            as_of=args.as_of,
            screen=str(SCREEN_AGGREGATE_PATH),
            config=str(DEFAULT_SMALL_CAP_CONFIG),
            output_dir=getattr(
                args,
                "small_cap_output_dir",
                str(DEFAULT_SMALL_CAP_OUTPUT_DIR),
            ),
            signal_output=getattr(
                args,
                "small_cap_signal_output",
                str(DEFAULT_SMALL_CAP_SIGNAL_OUTPUT),
            ),
            all_history=args.all_history_signals,
            inspect_only=getattr(args, "inspect_only_small_cap", False),
            min_coverage=getattr(args, "small_cap_min_coverage", 0.5),
            run_type=context.run_type,
        )
    )


def _build_candidates(context: PipelineContext) -> Path:
    args = context.args
    return run_build_candidates(
        Namespace(
            as_of=args.as_of,
            output=context.candidates_output,
            top_n=args.top_n,
            top_pct=args.top_pct,
            ml_weight=args.ml_weight,
            technical_weight=args.technical_weight,
            allocation_weight=getattr(args, "allocation_weight", 0.2),
            candidate_date_policy=getattr(args, "candidate_date_policy", "max_component"),
            max_component_lag_days=getattr(
                args,
                "candidate_max_component_lag_days",
                31,
            ),
            allow_stale_technical=getattr(args, "allow_stale_technical", False),
            by_region=args.by_region,
            signals_dir=str(TP_ROOT / "04_signals"),
            last_screen=str(LAST_SCREEN_PATH),
            run_type=context.run_type,
        )
    )


def _optimize_portfolio(context: PipelineContext) -> Path:
    args = context.args
    return run_optimize_portfolio(
        Namespace(
            as_of=args.as_of,
            candidates=context.candidates_output,
            output=context.portfolio_output,
            method=args.optimizer_method,
            max_weight=args.max_weight,
            min_weight=getattr(args, "min_weight", 0.0),
            region=args.portfolio_region,
            old_portfolio=args.old_portfolio,
            benchmark_active_limit=getattr(args, "benchmark_active_limit", 0.02),
            country_margin=getattr(args, "country_margin", 0.03),
            sector_margin=getattr(args, "sector_margin", 0.03),
            max_turnover=getattr(args, "max_turnover", None),
            transaction_cost=getattr(args, "transaction_cost", 0.0),
            country_tilt_strength=getattr(args, "country_tilt_strength", 0.25),
            sector_tilt_strength=getattr(args, "sector_tilt_strength", 0.2),
            run_type=context.run_type,
        )
    )


def _run_backtest(context: PipelineContext) -> Path:
    args = context.args
    pipeline_hypothesis = getattr(args, "hypothesis_id", None) or "production-pipeline"
    return run_backtest_step(
        Namespace(
            profile=args.backtest_profile,
            screen=None,
            returns=None,
            user=args.backtest_user,
            inspect_only=args.inspect_only_backtest,
            bench=args.bench,
            metric=args.metric,
            start_date=args.start_date,
            percentile=args.percentile,
            ptf_name=args.ptf_name,
            output_dir=args.backtest_output_dir,
            max_weight=args.backtest_max_weight,
            sector_neutral=args.sector_neutral,
            top=args.top,
            bottom=args.bottom,
            batch=args.batch,
            run_type=context.run_type,
            record_experiment=True,
            hypothesis_id=f"{pipeline_hypothesis}-backtest",
            experiment_name=f"{getattr(args, 'experiment_name', None) or 'TP production pipeline'} backtest",
            parent_run_id=context.experiment_parent_run_id,
            effective_trial_count=getattr(args, "effective_trial_count", None),
            experiment_root=getattr(args, "experiment_root", None),
        )
    )


def _generate_report(context: PipelineContext) -> Path:
    return run_generate_report(
        Namespace(
            output=context.report_output,
            step=None,
            run_type=context.run_type,
        )
    )


def pipeline_steps() -> tuple[PipelineStep, ...]:
    """Return the canonical, deterministic production step order."""

    return (
        PipelineStep(
            "refresh_data",
            lambda context: not context.args.skip_refresh_data,
            _refresh_data,
        ),
        PipelineStep(
            "refresh_supplemental_data",
            lambda context: bool(
                getattr(context.args, "refresh_supplemental_data", False)
            ),
            _refresh_supplemental,
        ),
        PipelineStep(
            "refresh_regime",
            lambda context: bool(context.args.refresh_regime)
            and not context.args.skip_export_signals,
            _refresh_regime,
        ),
        PipelineStep(
            "refresh_ml",
            lambda context: bool(getattr(context.args, "refresh_ml", False))
            and not context.args.skip_export_signals,
            _refresh_ml,
        ),
        PipelineStep(
            "refresh_technical",
            lambda context: not context.args.skip_export_signals
            and not getattr(context.args, "skip_refresh_technical", False),
            _refresh_technical,
        ),
        PipelineStep(
            "export_signals",
            lambda context: not context.args.skip_export_signals,
            _export_signals,
        ),
        PipelineStep(
            "refresh_small_cap",
            lambda context: not getattr(context.args, "skip_refresh_small_cap", False),
            _refresh_small_cap,
        ),
        PipelineStep(
            "build_candidates",
            lambda context: not context.args.skip_build_candidates,
            _build_candidates,
        ),
        PipelineStep(
            "optimize_portfolio",
            lambda context: not context.args.skip_optimize_portfolio,
            _optimize_portfolio,
        ),
        PipelineStep(
            "run_backtest",
            lambda context: not context.args.skip_backtest,
            _run_backtest,
        ),
        PipelineStep(
            "generate_report",
            lambda context: not context.args.skip_report,
            _generate_report,
        ),
    )


def execute_pipeline_steps(context: PipelineContext) -> list[str]:
    """Execute enabled steps and return their manifest paths."""

    for step in pipeline_steps():
        if step.enabled(context):
            context.record(step.execute(context))
    return context.child_manifests

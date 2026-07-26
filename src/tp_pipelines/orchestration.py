"""Typed, dependency-aware orchestration for the TP production pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .build_candidates import run_build_candidates
from .configs import PipelineRunConfig
from .dag import PipelineDAG, PipelineStep
from .export_signals import run_export_signals
from .generate_report import run_generate_report
from .optimize_portfolio import run_optimize_portfolio
from .refresh_data import run_refresh_data
from .refresh_ml import run_refresh_ml
from .refresh_regime import run_refresh_regime
from .refresh_small_cap import run_refresh_small_cap
from .refresh_supplemental_data import run_refresh_supplemental_data
from .refresh_technical import run_refresh_technical
from .run_backtest import run_backtest_step


@dataclass
class PipelineContext:
    """Resolved pipeline configuration and mutable execution state."""

    config: PipelineRunConfig
    child_manifests: list[str] = field(default_factory=list)
    regime_refreshed: bool = False
    experiment_parent_run_id: str | None = None

    @classmethod
    def from_args(cls, args: object) -> "PipelineContext":
        """Compatibility adapter for callers still passing parser output."""

        if isinstance(args, PipelineRunConfig):
            return cls(config=args)
        return cls(config=PipelineRunConfig.from_namespace(args))

    @property
    def run_type(self) -> str:
        return self.config.run_type

    @property
    def candidates_output(self) -> str:
        return self.config.candidates_output

    @property
    def portfolio_output(self) -> str:
        return self.config.portfolio_output

    @property
    def report_output(self) -> str:
        return self.config.report_output

    @property
    def technical_patterns_output(self) -> str:
        return self.config.refresh_technical.output

    def record(self, manifest: str | Path) -> None:
        self.child_manifests.append(str(manifest))


def _refresh_data(context: PipelineContext) -> Path:
    return run_refresh_data(context.config.refresh_data)


def _refresh_supplemental(context: PipelineContext) -> Path:
    return run_refresh_supplemental_data(context.config.refresh_supplemental)


def _refresh_regime(context: PipelineContext) -> Path:
    result = run_refresh_regime(context.config.refresh_regime)
    context.regime_refreshed = True
    return result


def _refresh_ml(context: PipelineContext) -> Path:
    return run_refresh_ml(context.config.refresh_ml)


def _refresh_technical(context: PipelineContext) -> Path:
    return run_refresh_technical(context.config.refresh_technical)


def _export_signals(context: PipelineContext) -> Path:
    context.config.export_signals.skip_regime = context.regime_refreshed
    return run_export_signals(context.config.export_signals)


def _refresh_small_cap(context: PipelineContext) -> Path:
    return run_refresh_small_cap(context.config.refresh_small_cap)


def _build_candidates(context: PipelineContext) -> Path:
    return run_build_candidates(context.config.build_candidates)


def _optimize_portfolio(context: PipelineContext) -> Path:
    return run_optimize_portfolio(context.config.optimize_portfolio)


def _run_backtest(context: PipelineContext) -> Path:
    config = context.config.run_backtest
    config.parent_run_id = context.experiment_parent_run_id
    return run_backtest_step(config)


def _generate_report(context: PipelineContext) -> Path:
    return run_generate_report(context.config.generate_report)


def pipeline_dag() -> PipelineDAG:
    """Return the validated production dependency graph."""

    return PipelineDAG(
        (
        PipelineStep(
            "refresh_data",
            (),
            lambda context: not context.config.controls.skip_refresh_data,
            _refresh_data,
        ),
        PipelineStep(
            "refresh_supplemental_data",
            ("refresh_data",),
            lambda context: context.config.controls.refresh_supplemental_data,
            _refresh_supplemental,
        ),
        PipelineStep(
            "refresh_regime",
            ("refresh_data",),
            lambda context: context.config.controls.refresh_regime
            and not context.config.controls.skip_export_signals,
            _refresh_regime,
        ),
        PipelineStep(
            "refresh_ml",
            ("refresh_data",),
            lambda context: context.config.controls.refresh_ml
            and not context.config.controls.skip_export_signals,
            _refresh_ml,
        ),
        PipelineStep(
            "refresh_technical",
            ("refresh_data",),
            lambda context: not context.config.controls.skip_export_signals
            and not context.config.controls.skip_refresh_technical,
            _refresh_technical,
        ),
        PipelineStep(
            "export_signals",
            ("refresh_regime", "refresh_ml", "refresh_technical"),
            lambda context: not context.config.controls.skip_export_signals,
            _export_signals,
        ),
        PipelineStep(
            "refresh_small_cap",
            ("refresh_data",),
            lambda context: not context.config.controls.skip_refresh_small_cap,
            _refresh_small_cap,
        ),
        PipelineStep(
            "build_candidates",
            ("export_signals", "refresh_small_cap"),
            lambda context: not context.config.controls.skip_build_candidates,
            _build_candidates,
        ),
        PipelineStep(
            "optimize_portfolio",
            ("build_candidates",),
            lambda context: not context.config.controls.skip_optimize_portfolio,
            _optimize_portfolio,
        ),
        PipelineStep(
            "run_backtest",
            ("optimize_portfolio",),
            lambda context: not context.config.controls.skip_backtest,
            _run_backtest,
        ),
        PipelineStep(
            "generate_report",
            ("run_backtest",),
            lambda context: not context.config.controls.skip_report,
            _generate_report,
        ),
        )
    )


def pipeline_steps() -> tuple[PipelineStep, ...]:
    """Compatibility accessor returning deterministic topological order."""

    return pipeline_dag().ordered_steps()


def execute_pipeline_steps(context: PipelineContext) -> list[str]:
    """Execute enabled steps and return their manifest paths."""

    for step in pipeline_dag().ordered_steps():
        if step.enabled(context):
            context.record(step.execute(context))
    return context.child_manifests

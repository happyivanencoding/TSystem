"""Typed, dependency-aware orchestration for the TP production pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .configs import PipelineRunConfig
from .dag import PipelineDAG, PipelineStep
from .lineage import (
    load_reuse_mapping,
    new_production_run_id,
    validate_reuse_manifest,
)


@dataclass
class PipelineContext:
    """Resolved pipeline configuration and mutable execution state."""

    config: PipelineRunConfig
    child_manifests: list[str] = field(default_factory=list)
    regime_refreshed: bool = False
    country_model_refreshed: bool = False
    experiment_parent_run_id: str | None = None
    production_run_id: str = field(default_factory=new_production_run_id)
    step_states: dict[str, str] = field(default_factory=dict)
    step_manifests: dict[str, str] = field(default_factory=dict)
    explicit_reuse_manifests: dict[str, dict[str, object]] = field(default_factory=dict)
    reuse_mapping: dict[str, dict[str, object]] = field(default_factory=dict)
    reuse_decisions: list[dict[str, object]] = field(default_factory=list)

    @classmethod
    def from_args(cls, args: object) -> "PipelineContext":
        """Compatibility adapter for callers still passing parser output."""

        if isinstance(args, PipelineRunConfig):
            config = args
        else:
            config = PipelineRunConfig.from_namespace(args)
        return cls(config=config, reuse_mapping=load_reuse_mapping(config.reuse_manifest))

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

    def record(self, step: str, manifest: str | Path) -> None:
        path = str(manifest)
        self.child_manifests.append(path)
        self.step_manifests[step] = path
        self.step_states[step] = "produced_this_run"

    def mark(self, step: str, state: str) -> None:
        self.step_states[step] = state

    def parent_manifests_for(self, step: PipelineStep) -> list[str]:
        return [
            self.step_manifests[dependency]
            for dependency in step.dependencies
            if dependency in self.step_manifests
        ]

    def prepare_step(self, step: PipelineStep) -> None:
        config_names = {
            "refresh_data": "refresh_data",
            "refresh_supplemental_data": "refresh_supplemental",
            "refresh_regime": "refresh_regime",
            "refresh_sector_model": "refresh_sector",
            "refresh_country_model": "refresh_country_model",
            "refresh_ml": "refresh_ml",
            "refresh_technical": "refresh_technical",
            "export_signals": "export_signals",
            "refresh_factor_recommendation": "refresh_factor_recommendation",
            "refresh_small_cap": "refresh_small_cap",
            "build_candidates": "build_candidates",
            "optimize_portfolio": "optimize_portfolio",
            "run_backtest": "run_backtest",
            "generate_report": "generate_report",
        }
        step_config = getattr(self.config, config_names[step.name])
        setattr(step_config, "production_run_id", self.production_run_id)
        setattr(step_config, "data_release_id", self.config.cli_parameters.get("data_release_id"))
        setattr(step_config, "catalog_release_id", self.config.cli_parameters.get("catalog_release_id"))
        setattr(step_config, "model_release_ids", list(self.config.model_release_ids))
        setattr(step_config, "parent_manifests", self.parent_manifests_for(step))
        setattr(
            step_config,
            "reuse_decisions",
            list(self.reuse_decisions),
        )
        setattr(step_config, "write_approval", self.config.cli_parameters.get("write_approval"))

    def reuse_for(self, step: str) -> dict[str, object] | None:
        entry = self.reuse_mapping.get(step)
        if entry is None:
            return None
        details = validate_reuse_manifest(
            str(entry["manifest"]),
            run_type=self.run_type,
            as_of=self.config.as_of,
            allowed_lag_days=self.config.freshness_window_days,
        )
        details["reason"] = str(entry.get("reason") or "explicit reuse")
        return details

    def record_reuse(self, step: str, details: dict[str, object]) -> None:
        path = str(details["manifest_path"])
        self.step_states[step] = "explicitly_reused"
        self.step_manifests[step] = path
        self.explicit_reuse_manifests[step] = details
        self.reuse_decisions.append(
            {
                "step": step,
                "manifest": path,
                "reason": details.get("reason", "explicit reuse"),
                "source_production_run_id": details.get("production_run_id"),
                "data_date": details.get("data_date"),
            }
        )


def run_refresh_supplemental_data(config):
    """Lazy seam retained for orchestration tests and injected implementations."""

    from .refresh_supplemental_data import run_refresh_supplemental_data as implementation

    return implementation(config)


def run_refresh_regime(config):
    from .refresh_regime import run_refresh_regime as implementation

    return implementation(config)


def run_refresh_sector_model(config):
    from .refresh_sector_model import run_refresh_sector_model as implementation

    return implementation(config)


def run_refresh_country_model(config):
    from .refresh_country_model import run_refresh_country_model as implementation

    return implementation(config)


def run_export_signals(config):
    from .export_signals import run_export_signals as implementation

    return implementation(config)


def run_refresh_factor_recommendation(config):
    """Lazy seam for the isolated research-only factor recommendation step."""

    from .refresh_factor_recommendation import (
        run_refresh_factor_recommendation as implementation,
    )

    return implementation(config)


def run_backtest_step(config):
    from .run_backtest import run_backtest_step as implementation

    return implementation(config)


def _refresh_data(context: PipelineContext) -> Path:
    from .refresh_data import run_refresh_data

    return run_refresh_data(context.config.refresh_data)


def _refresh_supplemental(context: PipelineContext) -> Path:
    return run_refresh_supplemental_data(context.config.refresh_supplemental)


def _refresh_regime(context: PipelineContext) -> Path:
    result = run_refresh_regime(context.config.refresh_regime)
    context.regime_refreshed = True
    return result


def _refresh_sector_model(context: PipelineContext) -> Path:
    return run_refresh_sector_model(context.config.refresh_sector)


def _refresh_country_model(context: PipelineContext) -> Path:
    result = run_refresh_country_model(context.config.refresh_country_model)
    if not context.config.refresh_country_model.inspect_only:
        context.country_model_refreshed = True
    return result


def _refresh_ml(context: PipelineContext) -> Path:
    from .refresh_ml import run_refresh_ml

    return run_refresh_ml(context.config.refresh_ml)


def _refresh_technical(context: PipelineContext) -> Path:
    from .refresh_technical import run_refresh_technical

    return run_refresh_technical(context.config.refresh_technical)


def _export_signals(context: PipelineContext) -> Path:
    states = context.step_states
    context.config.export_signals.skip_ml = (
        context.config.export_signals.skip_ml or states.get("refresh_ml") == "disabled"
    )
    context.config.export_signals.skip_technical = (
        context.config.export_signals.skip_technical
        or states.get("refresh_technical") == "disabled"
    )
    context.config.export_signals.skip_regime = context.regime_refreshed
    context.config.export_signals.skip_regime = (
        context.config.export_signals.skip_regime
        or states.get("refresh_regime") == "disabled"
    )
    context.config.export_signals.skip_country = (
        context.config.export_signals.skip_country
        or context.country_model_refreshed
        or states.get("refresh_country_model") == "disabled"
    )
    return run_export_signals(context.config.export_signals)


def _refresh_small_cap(context: PipelineContext) -> Path:
    from .refresh_small_cap import run_refresh_small_cap

    return run_refresh_small_cap(context.config.refresh_small_cap)


def _refresh_factor_recommendation(context: PipelineContext) -> Path:
    return run_refresh_factor_recommendation(
        context.config.refresh_factor_recommendation
    )


def _build_candidates(context: PipelineContext) -> Path:
    from .build_candidates import run_build_candidates

    return run_build_candidates(context.config.build_candidates)


def _optimize_portfolio(context: PipelineContext) -> Path:
    from .optimize_portfolio import run_optimize_portfolio

    return run_optimize_portfolio(context.config.optimize_portfolio)


def _run_backtest(context: PipelineContext) -> Path:
    config = context.config.run_backtest
    config.parent_run_id = context.experiment_parent_run_id
    return run_backtest_step(config)


def _generate_report(context: PipelineContext) -> Path:
    from .generate_report import run_generate_report

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
            "refresh_sector_model",
            ("refresh_data",),
            lambda context: not context.config.controls.skip_refresh_sector,
            _refresh_sector_model,
        ),
        PipelineStep(
            "refresh_country_model",
            ("refresh_data",),
            lambda context: not context.config.controls.skip_refresh_country_model,
            _refresh_country_model,
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
            ("refresh_regime", "refresh_ml", "refresh_technical", "refresh_country_model"),
            lambda context: not context.config.controls.skip_export_signals,
            _export_signals,
        ),
        PipelineStep(
            "refresh_factor_recommendation",
            ("refresh_data",),
            lambda context: bool(
                getattr(context.config.controls, "refresh_factor_recommendation", False)
            ),
            _refresh_factor_recommendation,
        ),
        PipelineStep(
            "refresh_small_cap",
            ("refresh_data",),
            lambda context: not context.config.controls.skip_refresh_small_cap,
            _refresh_small_cap,
        ),
        PipelineStep(
            "build_candidates",
            ("export_signals", "refresh_small_cap", "refresh_sector_model"),
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
    """Execute steps only after dependencies are produced or explicitly reused."""

    failure: BaseException | None = None
    for step in pipeline_dag().ordered_steps():
        try:
            reuse = context.reuse_for(step.name)
            if reuse is not None:
                context.record_reuse(step.name, reuse)
                continue
            if not step.enabled(context):
                context.mark(step.name, "disabled")
                continue
            blocked = [
                dependency
                for dependency in step.dependencies
                if context.step_states.get(dependency)
                not in {"produced_this_run", "explicitly_reused"}
                and not (
                    step.name == "export_signals"
                    and context.step_states.get(dependency) == "disabled"
                )
            ]
            if blocked:
                context.mark(step.name, "blocked_by_dependency")
                continue
            context.prepare_step(step)
            context.record(step.name, step.execute(context))
        except BaseException as exc:
            context.mark(step.name, "failed")
            if failure is None:
                failure = exc
    if failure is not None:
        raise failure
    return context.child_manifests

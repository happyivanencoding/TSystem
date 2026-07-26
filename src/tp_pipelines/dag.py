"""Dependency-aware registry for TP pipeline steps."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .configs import PipelineRunConfig


class PipelineExecutionContext(Protocol):
    """Minimum contract consumed by registered steps."""

    config: "PipelineRunConfig"

    def record(self, manifest: str | Path) -> None: ...


@dataclass(frozen=True)
class PipelineStep:
    name: str
    dependencies: tuple[str, ...]
    enabled: Callable[[PipelineExecutionContext], bool]
    execute: Callable[[PipelineExecutionContext], Path]


@dataclass(frozen=True)
class PipelineDAG:
    """Validated DAG with deterministic registration-order tie breaking."""

    steps: tuple[PipelineStep, ...]

    def __post_init__(self) -> None:
        names = [step.name for step in self.steps]
        if len(names) != len(set(names)):
            raise ValueError("pipeline step names must be unique")
        known = set(names)
        for step in self.steps:
            missing = set(step.dependencies) - known
            if missing:
                raise ValueError(
                    f"pipeline step {step.name!r} has unknown dependencies: {sorted(missing)}"
                )
        self.ordered_steps()

    def ordered_steps(self) -> tuple[PipelineStep, ...]:
        by_name = {step.name: step for step in self.steps}
        pending = {step.name: set(step.dependencies) for step in self.steps}
        ordered: list[PipelineStep] = []
        while pending:
            ready = [
                step.name
                for step in self.steps
                if step.name in pending and not pending[step.name]
            ]
            if not ready:
                raise ValueError(f"pipeline dependency cycle: {sorted(pending)}")
            for name in ready:
                ordered.append(by_name[name])
                del pending[name]
                for dependencies in pending.values():
                    dependencies.discard(name)
        return tuple(ordered)

    def dependencies_for(self, name: str) -> tuple[str, ...]:
        for step in self.steps:
            if step.name == name:
                return step.dependencies
        raise KeyError(name)

    def names(self) -> tuple[str, ...]:
        return tuple(step.name for step in self.ordered_steps())

"""Public orchestration contracts for TP production pipelines."""

from .configs import PipelineRunConfig, StepConfig
from .dag import PipelineDAG, PipelineExecutionContext, PipelineStep


def __getattr__(name: str):
    if name in {"PipelineContext", "pipeline_dag"}:
        from .orchestration import PipelineContext, pipeline_dag

        return {"PipelineContext": PipelineContext, "pipeline_dag": pipeline_dag}[name]
    raise AttributeError(name)

__all__ = [
    "PipelineContext",
    "PipelineDAG",
    "PipelineExecutionContext",
    "PipelineRunConfig",
    "PipelineStep",
    "StepConfig",
    "pipeline_dag",
]

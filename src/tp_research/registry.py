"""Validated configuration registry for reproducible TP research workflows."""

from __future__ import annotations

import importlib
import json
import os
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH
from tp_core.security_nav_engine import NAV_ENGINE_ID, NAV_ENGINE_VERSION
from tp_core.workspace import CONFIG_ROOT, RESEARCH_RUNS_DIR
from tp_experiments.artifacts import (
    ExperimentArtifactPolicy,
    compact_experiment_holdings,
    experiment_artifact_environment,
)
from tp_experiments import ExperimentRecorder, ExperimentSpec
from tp_portfolio import OPTIMIZER_ID, OPTIMIZER_VERSION
from tp_research.runtime import RESEARCH_SIGNAL_ID, RESEARCH_SIGNAL_VERSION

REGISTRY_SCHEMA_VERSION = 1
HYPOTHESIS_STATUSES = {
    "draft",
    "research",
    "validated",
    "promoted",
    "rejected",
    "retired",
}
DEFAULT_REGISTRY_DIR = CONFIG_ROOT / "research" / "hypotheses"


@dataclass(frozen=True)
class ResearchDefinition:
    path: Path
    payload: Mapping[str, Any]

    @property
    def hypothesis_id(self) -> str:
        return str(self.payload["hypothesis_id"])

    @property
    def runner(self) -> Mapping[str, Any]:
        return self.payload["runner"]

    def to_spec(self) -> ExperimentSpec:
        return ExperimentSpec(
            hypothesis_id=self.hypothesis_id,
            name=str(self.payload["name"]),
            universe=self.payload.get("universe"),
            sample_start=self.payload.get("sample_start"),
            sample_end=self.payload.get("sample_end"),
            pit_cutoff=self.payload.get("pit_cutoff"),
            cost_assumptions=dict(self.payload.get("cost_assumptions") or {}),
            trial_family=str(self.payload.get("trial_family") or self.hypothesis_id),
            effective_trial_count=self.payload.get("effective_trial_count"),
            component_versions={
                "engine": f"{NAV_ENGINE_ID}:{NAV_ENGINE_VERSION}",
                "signal": f"{RESEARCH_SIGNAL_ID}:{RESEARCH_SIGNAL_VERSION}",
                "optimizer": f"{OPTIMIZER_ID}:{OPTIMIZER_VERSION}",
                **dict(self.payload.get("component_versions") or {}),
            },
            tags=tuple(self.payload.get("tags") or ("research",)),
        )


class HypothesisRegistry:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or DEFAULT_REGISTRY_DIR)

    def load(self, hypothesis_id: str) -> ResearchDefinition:
        path = self.root / f"{hypothesis_id}.json"
        if not path.is_file():
            raise FileNotFoundError(f"研究定义不存在：{path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self._validate(payload, path)
        return ResearchDefinition(path=path.resolve(), payload=payload)

    def list(self) -> list[ResearchDefinition]:
        definitions = []
        for path in sorted(self.root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            self._validate(payload, path)
            definitions.append(ResearchDefinition(path=path.resolve(), payload=payload))
        return definitions

    @staticmethod
    def _validate(payload: Mapping[str, Any], path: Path) -> None:
        required = {"schema_version", "hypothesis_id", "name", "statement", "status", "runner"}
        missing = required - set(payload)
        if missing:
            raise ValueError(f"{path} 缺少字段：{sorted(missing)}")
        if payload["schema_version"] != REGISTRY_SCHEMA_VERSION:
            raise ValueError(f"{path} schema_version 不受支持")
        if payload["status"] not in HYPOTHESIS_STATUSES:
            raise ValueError(f"{path} status 不合法：{payload['status']}")
        runner = payload["runner"]
        if not isinstance(runner, Mapping):
            raise ValueError(f"{path} runner 必须是对象")
        module = str(runner.get("module") or "")
        if not module.startswith("tp_research.workflows."):
            raise ValueError(f"{path} runner.module 必须位于 tp_research.workflows")
        if str(runner.get("callable") or "main") != "main":
            raise ValueError(f"{path} 只允许公共 main 入口")
        ExperimentArtifactPolicy.from_definition(payload)


def _has_option(arguments: list[str], option: str) -> bool:
    return option in arguments or any(value.startswith(f"{option}=") for value in arguments)


def run_definition(
    definition: ResearchDefinition,
    *,
    arguments: Iterable[str] = (),
    root: str | Path = RESEARCH_RUNS_DIR,
    parent_run_id: str | None = None,
) -> Path:
    """Execute one allow-listed package entry point and write a Run Card v3."""

    supplied = list(arguments)
    if supplied[:1] == ["--"]:
        supplied = supplied[1:]
    defaults = list(definition.runner.get("default_args") or ())
    combined = defaults + supplied
    if _has_option(combined, "--output-dir"):
        raise ValueError("--output-dir 由研究运行器管理，不能覆盖")
    missing = [
        option
        for option in definition.runner.get("required_options") or ()
        if not _has_option(combined, str(option))
    ]
    if missing:
        raise ValueError(f"缺少研究参数：{missing}")

    artifact_policy = ExperimentArtifactPolicy.from_definition(definition.payload)
    recorder = ExperimentRecorder(root=root)
    run = recorder.start_run(
        definition.to_spec(),
        parameters={
            "arguments": combined,
            "artifact_policy": artifact_policy.to_dict(),
        },
        parent_run_id=parent_run_id,
        config=definition.payload,
        config_path=definition.path,
        run_kind="research",
    )
    run.log_inputs({"hypothesis_definition": definition.path}, hash_content=True)
    run.log_inputs(
        {
            "screen_aggregate": SCREEN_AGGREGATE_PATH,
            "returns": RETURNS_PATH,
        }
    )
    results_dir = run.run_dir / "results"
    module = importlib.import_module(str(definition.runner["module"]))
    function = getattr(module, "main")
    previous = os.environ.get("TP_RESEARCH_RECORDER_DISABLED")
    os.environ["TP_RESEARCH_RECORDER_DISABLED"] = "1"
    started = time.perf_counter()
    try:
        with experiment_artifact_environment(artifact_policy):
            result = function([*combined, "--output-dir", str(results_dir)])
        exit_code = result if isinstance(result, int) else 0
        compacted_holdings = compact_experiment_holdings(
            results_dir,
            policy=artifact_policy,
        )
        run.log_metrics(
            {
                "duration_seconds": round(time.perf_counter() - started, 3),
                "exit_code": exit_code,
                "holdings_files_compacted": len(compacted_holdings),
            }
        )
        run.log_provenance(
            {
                "artifact_policy": artifact_policy.to_dict(),
                "compacted_holdings": [
                    str(path.resolve()) for path in compacted_holdings
                ],
            }
        )
        run.log_artifacts({"results": results_dir})
        if exit_code:
            run.set_decision(
                "reject",
                reason=f"Workflow returned non-zero exit code {exit_code}.",
                decided_by="system",
            )
            run.complete(status="failed")
        else:
            run.set_decision(
                "review_required",
                reason="Configured research completed; promotion requires gate review.",
                decided_by="system",
            )
            run.complete()
    except BaseException as error:
        if run.status == "running":
            run.log_artifacts({"results": results_dir})
            run.fail(error)
        raise
    finally:
        if previous is None:
            os.environ.pop("TP_RESEARCH_RECORDER_DISABLED", None)
        else:
            os.environ["TP_RESEARCH_RECORDER_DISABLED"] = previous
    return run.path


__all__ = [
    "DEFAULT_REGISTRY_DIR",
    "HYPOTHESIS_STATUSES",
    "HypothesisRegistry",
    "ResearchDefinition",
    "run_definition",
]

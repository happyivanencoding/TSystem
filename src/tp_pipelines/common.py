"""共享的 pipeline manifest、路径和校验工具。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from tp_core.data_sources import TP_ROOT
from tp_core.security_nav_engine import NAV_ENGINE_ID, NAV_ENGINE_VERSION
from tp_core.workspace import (
    CANDIDATES_DIR,
    PIPELINE_MANIFESTS_DIR,
    PIPELINE_RUNS_DIR,
    PORTFOLIOS_DIR,
    REPORTS_DIR,
)
from tp_experiments import ExperimentRecorder, ExperimentSpec, RunRecorder
from tp_portfolio import OPTIMIZER_ID, OPTIMIZER_VERSION

RUN_TYPES = {"production", "smoke", "inspect"}


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def validation(name: str, ok: bool, message: str = "", details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": "passed" if ok else "failed",
        "message": message,
        "details": dict(details or {}),
    }


def _safe_stat(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def parquet_profile(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    profile: dict[str, Any] = {"path": str(target), "exists": target.exists()}
    if not target.exists() or not target.is_file():
        return profile
    profile.update(_safe_stat(target))
    try:
        import pyarrow.parquet as pq

        metadata = pq.ParquetFile(target).metadata
        profile.update(
            {
                "format": "parquet",
                "rows": int(metadata.num_rows),
                "columns": int(metadata.num_columns),
                "row_groups": int(metadata.num_row_groups),
            }
        )
    except Exception as exc:  # pragma: no cover - best effort manifest detail
        profile["parquet_profile_error"] = str(exc)
    return profile


def path_profile(path: str | Path, *, parquet: bool = False) -> dict[str, Any]:
    target = Path(path)
    if parquet or target.suffix.lower() == ".parquet":
        return parquet_profile(target)

    profile: dict[str, Any] = {"path": str(target), "exists": target.exists()}
    if not target.exists():
        return profile
    if target.is_file():
        profile.update({"type": "file", **_safe_stat(target)})
        return profile

    children = list(target.iterdir())
    profile.update(
        {
            "type": "directory",
            "child_count": len(children),
            "file_count": sum(1 for child in children if child.is_file()),
            "dir_count": sum(1 for child in children if child.is_dir()),
        }
    )
    return profile


def summarize_frame(frame: pd.DataFrame, *, date_column: str = "Date") -> dict[str, Any]:
    summary: dict[str, Any] = {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "column_names": list(map(str, frame.columns[:80])),
    }
    if date_column in frame.columns:
        dates = pd.to_datetime(frame[date_column], errors="coerce").dropna()
        summary["date_min"] = dates.min().date().isoformat() if not dates.empty else None
        summary["date_max"] = dates.max().date().isoformat() if not dates.empty else None
        summary["date_count"] = int(dates.nunique()) if not dates.empty else 0
    return summary


def latest_on_or_before(frame: pd.DataFrame, as_of: str | None, *, date_column: str = "Date") -> pd.Timestamp:
    dates = pd.to_datetime(frame[date_column], errors="coerce").dropna()
    if dates.empty:
        raise ValueError(f"{date_column} 没有可用日期")
    if as_of:
        cutoff = pd.Timestamp(as_of)
        dates = dates[dates <= cutoff]
        if dates.empty:
            raise ValueError(f"找不到 {as_of} 之前的可用日期")
    return pd.Timestamp(dates.max())


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    temp_path.replace(path)


@dataclass
class StepManifest:
    step: str
    parameters: dict[str, Any]
    started_at: str = field(default_factory=iso_now)
    started_timer: float = field(default_factory=time.perf_counter)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    validations: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    record_experiment: bool = True
    run_type: str = field(init=False)
    experiment: RunRecorder | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        run_type = str(self.parameters.get("run_type") or "production")
        if run_type not in RUN_TYPES:
            raise ValueError(f"run_type 必须是 {sorted(RUN_TYPES)} 之一")
        self.run_type = run_type
        if self.record_experiment and not self.parameters.get(
            "_experiment_managed_externally", False
        ):
            cutoff = (
                self.parameters.get("as_of")
                or self.parameters.get("to_date")
                or self.parameters.get("date")
                or "latest-canonical-input"
            )
            hypothesis_id = str(
                self.parameters.get("hypothesis_id") or f"pipeline-{self.step}"
            )
            parent_run_id = (
                self.parameters.get("parent_run_id")
                or os.environ.get("TP_PARENT_EXPERIMENT_RUN_ID")
                or None
            )
            self.experiment = ExperimentRecorder(
                root=self.parameters.get("experiment_root") or None
            ).start_run(
                ExperimentSpec(
                    hypothesis_id=hypothesis_id,
                    name=str(
                        self.parameters.get("experiment_name")
                        or f"Pipeline step: {self.step}"
                    ),
                    universe=str(
                        self.parameters.get("region")
                        or self.parameters.get("universe")
                        or self.parameters.get("bench")
                        or "all-supported"
                    ),
                    sample_start=self.parameters.get("start_date"),
                    sample_end=str(cutoff),
                    pit_cutoff=str(cutoff),
                    cost_assumptions={
                        "transaction_cost": self.parameters.get(
                            "transaction_cost", 0.0
                        ),
                        "max_turnover": self.parameters.get("max_turnover"),
                    },
                    trial_family=str(
                        self.parameters.get("trial_family") or self.step
                    ),
                    effective_trial_count=int(
                        self.parameters.get("effective_trial_count") or 1
                    ),
                    component_versions={
                        "engine": f"{NAV_ENGINE_ID}:{NAV_ENGINE_VERSION}",
                        "signal": "tp.pipeline.signal-contract:1.0.0",
                        "optimizer": f"{OPTIMIZER_ID}:{OPTIMIZER_VERSION}",
                    },
                    tags=("pipeline-step", self.step, self.run_type),
                ),
                parameters=self.parameters,
                parent_run_id=str(parent_run_id) if parent_run_id else None,
                run_kind="production" if self.run_type == "production" else "research",
                production_run={
                    "production_run_id": self.parameters.get("production_run_id"),
                    "data_release_id": self.parameters.get("data_release_id"),
                    "model_release_ids": list(self.parameters.get("model_release_ids") or ()),
                    "parent_step_manifests": list(
                        self.parameters.get("parent_manifests") or ()
                    ),
                    "reuse_decisions": list(self.parameters.get("reuse_decisions") or ()),
                    "write_approval": dict(self.parameters.get("write_approval") or {}),
                    "rollback_target": self.parameters.get("rollback_target"),
                },
            )

    def add_validation(self, name: str, ok: bool, message: str = "", details: Mapping[str, Any] | None = None) -> None:
        self.validations.append(validation(name, ok, message, details))

    def write(self, status: str, *, error: BaseException | None = None) -> Path:
        finished_at = iso_now()
        payload: dict[str, Any] = {
            "step": self.step,
            "status": status,
            "started_at": self.started_at,
            "finished_at": finished_at,
            "duration_seconds": round(time.perf_counter() - self.started_timer, 3),
            "run_type": self.run_type,
            "run_kind": "production" if self.run_type == "production" else "research",
            "production_run_id": self.parameters.get("production_run_id"),
            "parent_manifests": list(self.parameters.get("parent_manifests") or ()),
            "data_release_id": self.parameters.get("data_release_id"),
            "model_release_ids": list(self.parameters.get("model_release_ids") or ()),
            "parameters": self.parameters,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "validations": self.validations,
            "details": self.details,
            "idempotency": {
                "policy": "标准产物使用固定 latest 路径覆盖写入；每次运行另写时间戳 manifest 保留审计证据。",
                "no_duplicate_rows_expected": True,
            },
        }
        if error is not None:
            payload["error"] = {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            }
        manifest_dir = PIPELINE_MANIFESTS_DIR / self.step
        manifest_dir.mkdir(parents=True, exist_ok=True)
        suffix = "" if self.run_type == "production" else f"_{self.run_type}"
        manifest_path = manifest_dir / f"{self.step}{suffix}_{timestamp()}.json"
        latest_path = manifest_dir / f"{self.step}{suffix}_latest.json"
        atomic_write_json(manifest_path, payload)
        atomic_write_json(latest_path, payload)
        self._finalize_experiment(
            status=status,
            error=error,
            manifest_path=manifest_path,
            duration_seconds=payload["duration_seconds"],
        )
        return manifest_path

    @staticmethod
    def _profile_paths(profiles: Mapping[str, Any]) -> dict[str, Path]:
        paths: dict[str, Path] = {}
        for name, profile in profiles.items():
            if not isinstance(profile, Mapping):
                continue
            value = profile.get("path")
            if value:
                paths[str(name)] = Path(str(value))
        return paths

    def _finalize_experiment(
        self,
        *,
        status: str,
        error: BaseException | None,
        manifest_path: Path,
        duration_seconds: float,
    ) -> None:
        experiment = self.experiment
        if experiment is None or experiment.status != "running":
            return
        input_paths = self._profile_paths(self.inputs)
        if input_paths:
            experiment.log_inputs(input_paths)
        artifacts = self._profile_paths(self.outputs)
        artifacts["step_manifest"] = manifest_path
        experiment.log_artifacts(artifacts)
        experiment.log_metrics(
            {
                "duration_seconds": duration_seconds,
                "validation_count": len(self.validations),
                "validation_failures": sum(
                    item.get("status") == "failed" for item in self.validations
                ),
            }
        )
        if status == "success" and error is None:
            experiment.set_decision(
                "review_required",
                reason="Pipeline step completed; promotion requires control review.",
                decided_by="system",
            )
            experiment.complete()
            return
        failure = error or RuntimeError(f"pipeline step finished with status={status}")
        experiment.fail(failure)


def run_python_module(module: str, args: Iterable[str] = ()) -> dict[str, Any]:
    command = [sys.executable, "-m", module, *list(args)]
    completed = subprocess.run(command, cwd=TP_ROOT, text=True, capture_output=True, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-8000:],
        "stderr": completed.stderr[-8000:],
    }


def run_python_script(script: str | Path, args: Iterable[str] = ()) -> dict[str, Any]:
    command = [sys.executable, str(script), *list(args)]
    completed = subprocess.run(command, cwd=TP_ROOT, text=True, capture_output=True, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-8000:],
        "stderr": completed.stderr[-8000:],
    }

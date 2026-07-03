"""共享的 pipeline manifest、路径和校验工具。"""

from __future__ import annotations

import json
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


PIPELINE_RUNS_DIR = TP_ROOT / "10_pipeline_runs"
PIPELINE_MANIFESTS_DIR = PIPELINE_RUNS_DIR / "manifests"
CANDIDATES_DIR = TP_ROOT / "05_candidates"
PORTFOLIOS_DIR = TP_ROOT / "06_portfolios"
REPORTS_DIR = TP_ROOT / "09_reports"


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
        manifest_path = manifest_dir / f"{self.step}_{timestamp()}.json"
        latest_path = manifest_dir / f"{self.step}_latest.json"
        atomic_write_json(manifest_path, payload)
        atomic_write_json(latest_path, payload)
        return manifest_path


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

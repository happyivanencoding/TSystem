"""Persistent, auditable experiment records for TP research and production runs."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tp_core.data_sources import TP_ROOT


EXPERIMENT_SCHEMA_VERSION = 1
FINAL_STATUSES = {"success", "failed", "cancelled"}
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_identifier(value: str, *, field_name: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(
            f"{field_name} must use only letters, numbers, dots, underscores, or dashes"
        )
    return value


def _content_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_path(path: str | Path, *, hash_content: bool = False) -> dict[str, Any]:
    """Return a stable file fingerprint without reading large files unless requested."""

    target = Path(path).resolve()
    result: dict[str, Any] = {"path": str(target), "exists": target.exists()}
    if not target.exists():
        result["fingerprint"] = _canonical_digest(result)
        return result

    stat = target.stat()
    result.update(
        {
            "kind": "directory" if target.is_dir() else "file",
            "size": stat.st_size,
            "modified_at_ns": stat.st_mtime_ns,
        }
    )
    if target.is_file() and hash_content:
        result["sha256"] = _content_digest(target)
    result["fingerprint"] = _canonical_digest(result)
    return result


def _git_version(repo_root: Path) -> dict[str, Any]:
    def run(*args: str) -> str | None:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        value = result.stdout.strip()
        return value or None

    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(run("status", "--porcelain")),
    }


@dataclass(frozen=True)
class ExperimentSpec:
    """Stable research intent shared by one or more concrete runs."""

    hypothesis_id: str
    name: str
    universe: str | None = None
    sample_start: str | None = None
    sample_end: str | None = None
    pit_cutoff: str | None = None
    cost_assumptions: Mapping[str, Any] = field(default_factory=dict)
    effective_trial_count: int | None = None
    component_versions: Mapping[str, str] = field(default_factory=dict)
    tags: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _validate_identifier(self.hypothesis_id, field_name="hypothesis_id")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if self.effective_trial_count is not None and self.effective_trial_count < 1:
            raise ValueError("effective_trial_count must be at least 1")


class ExperimentRecorder:
    """Create run records beneath a queryable experiment directory."""

    def __init__(self, root: str | Path | None = None, *, repo_root: str | Path = TP_ROOT):
        self.root = Path(root or (TP_ROOT / "10_pipeline_runs" / "experiments"))
        self.repo_root = Path(repo_root)

    def start_run(
        self,
        spec: ExperimentSpec,
        *,
        parameters: Mapping[str, Any] | None = None,
        parent_run_id: str | None = None,
        run_id: str | None = None,
    ) -> "RunRecorder":
        if parent_run_id is not None:
            _validate_identifier(parent_run_id, field_name="parent_run_id")
        if run_id is not None:
            _validate_identifier(run_id, field_name="run_id")
        return RunRecorder(
            recorder=self,
            spec=spec,
            parameters=dict(parameters or {}),
            parent_run_id=parent_run_id,
            run_id=run_id,
        )

    def query_runs(
        self,
        *,
        hypothesis_id: str | None = None,
        status: str | None = None,
        tags: Sequence[str] = (),
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Read final and in-flight run cards using stable filters."""

        if hypothesis_id is not None:
            _validate_identifier(hypothesis_id, field_name="hypothesis_id")
            candidates = (self.root / hypothesis_id).glob("*/run.json")
        else:
            candidates = self.root.glob("*/*/run.json")
        required_tags = set(tags)
        records: list[dict[str, Any]] = []
        for path in candidates:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if status is not None and record.get("run", {}).get("status") != status:
                continue
            record_tags = set(record.get("hypothesis", {}).get("tags") or ())
            if not required_tags.issubset(record_tags):
                continue
            record["record_path"] = str(path.resolve())
            records.append(record)
        records.sort(
            key=lambda item: (
                str(item.get("run", {}).get("started_at") or ""),
                str(item.get("run", {}).get("run_id") or ""),
            ),
            reverse=True,
        )
        if limit is not None:
            if limit < 0:
                raise ValueError("limit must be non-negative")
            return records[:limit]
        return records

    def latest_run(self, hypothesis_id: str) -> dict[str, Any] | None:
        """Return the newest readable run card for one hypothesis."""

        records = self.query_runs(hypothesis_id=hypothesis_id, limit=1)
        return records[0] if records else None


class RunRecorder:
    """Mutable writer for one run; use as a context manager for failure capture."""

    def __init__(
        self,
        *,
        recorder: ExperimentRecorder,
        spec: ExperimentSpec,
        parameters: Mapping[str, Any],
        parent_run_id: str | None,
        run_id: str | None,
    ):
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.recorder = recorder
        self.spec = spec
        self.run_id = run_id or f"{timestamp}-{uuid.uuid4().hex[:8]}"
        self.experiment_dir = recorder.root / spec.hypothesis_id
        self.run_dir = self.experiment_dir / self.run_id
        self.path = self.run_dir / "run.json"
        self._record: dict[str, Any] = {
            "schema_version": EXPERIMENT_SCHEMA_VERSION,
            "hypothesis": asdict(spec),
            "run": {
                "run_id": self.run_id,
                "parent_run_id": parent_run_id,
                "status": "running",
                "started_at": _utc_now(),
                "finished_at": None,
            },
            "code": _git_version(recorder.repo_root),
            "parameters": dict(parameters),
            "inputs": {},
            "metrics": {},
            "artifacts": {},
            "decision": None,
            "error": None,
        }
        self._write()

    @property
    def status(self) -> str:
        return str(self._record["run"]["status"])

    def _write(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(self._record)
        payload["record_fingerprint"] = _canonical_digest(self._record)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        if self.status in FINAL_STATUSES:
            latest_path = self.experiment_dir / "latest.json"
            latest_temporary = latest_path.with_suffix(".json.tmp")
            latest_temporary.write_text(
                json.dumps(
                    {
                        "hypothesis_id": self.spec.hypothesis_id,
                        "run_id": self.run_id,
                        "status": self.status,
                        "finished_at": self._record["run"]["finished_at"],
                        "record_path": str(self.path.resolve()),
                        "record_fingerprint": payload["record_fingerprint"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            latest_temporary.replace(latest_path)

    def log_inputs(
        self,
        paths: Mapping[str, str | Path],
        *,
        hash_content: bool = False,
    ) -> "RunRecorder":
        self._ensure_running()
        self._record["inputs"].update(
            {
                name: fingerprint_path(path, hash_content=hash_content)
                for name, path in paths.items()
            }
        )
        self._write()
        return self

    def log_metrics(self, metrics: Mapping[str, Any]) -> "RunRecorder":
        self._ensure_running()
        self._record["metrics"].update(dict(metrics))
        self._write()
        return self

    def log_artifacts(self, artifacts: Mapping[str, str | Path]) -> "RunRecorder":
        self._ensure_running()
        self._record["artifacts"].update(
            {name: fingerprint_path(path) for name, path in artifacts.items()}
        )
        self._write()
        return self

    def set_decision(
        self,
        status: str,
        *,
        reason: str,
        decided_by: str = "human",
    ) -> "RunRecorder":
        self._ensure_running()
        self._record["decision"] = {
            "status": status,
            "reason": reason,
            "decided_by": decided_by,
            "decided_at": _utc_now(),
        }
        self._write()
        return self

    def complete(self, *, status: str = "success") -> Path:
        if status not in FINAL_STATUSES:
            raise ValueError(f"invalid final status: {status}")
        self._ensure_running()
        self._record["run"].update({"status": status, "finished_at": _utc_now()})
        self._write()
        return self.path

    def fail(self, error: BaseException) -> Path:
        self._ensure_running()
        self._record["error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
        return self.complete(status="failed")

    def _ensure_running(self) -> None:
        if self.status != "running":
            raise RuntimeError(f"run {self.run_id} is already {self.status}")

    def __enter__(self) -> "RunRecorder":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc is None:
            if self.status == "running":
                self.complete()
            return False
        if self.status == "running":
            self.fail(exc)
        return False

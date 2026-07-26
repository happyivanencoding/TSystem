"""Pure formatting and job view-model construction for the system dashboard."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


def relative_path(path: str | Path | None, *, root: Path) -> str:
    if not path:
        return ""
    resolved = Path(path)
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


def format_bytes(value: Any) -> str:
    if value in (None, ""):
        return ""
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return ""


def format_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


def format_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return pd.Timestamp(value).date().isoformat()
    except Exception:
        return str(value)


def format_number(value: Any, digits: int = 4) -> str:
    if value is None or (isinstance(value, str) and value == ""):
        return ""
    try:
        if pd.isna(value):
            return ""
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def format_pct(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except Exception:
        return str(value)


def status_label(status: str | None) -> str:
    if status == "success":
        return "OK"
    if status == "failed":
        return "FAIL"
    if status:
        return status.upper()
    return "N/A"


def status_class(status: str | None) -> str:
    if status == "success":
        return "tp-chip-success"
    if status == "failed":
        return "tp-chip-failed"
    if status:
        return "tp-chip-warning"
    return "tp-chip-muted"


@dataclass(frozen=True)
class JobViewModelContext:
    launch_dir: Path
    relpath: Callable[[str | Path | None], str]
    log_tail: Callable[..., str]
    launch_evidence: Callable[[str], tuple[Path | None, dict[str, Any] | None]]
    evidence_status: Callable[..., str]
    pid_is_running: Callable[[Any], bool]


def job_payload_from_record(
    payload: dict[str, Any] | None,
    *,
    context: JobViewModelContext,
) -> dict[str, str]:
    """Convert a persisted worker record into the stable dashboard job contract."""

    if not payload:
        return {
            "job_id": "",
            "step": "暂无启动任务",
            "status": "idle",
            "status_label": "IDLE",
            "phase": "submitted",
            "pid": "",
            "started_at": "",
            "manifest_status": "N/A",
            "manifest": "",
            "log_path": context.relpath(context.launch_dir),
            "log_tail": "",
            "backend": "",
            "queue_name": "",
            "queued_at": "",
            "status_updated_at": "",
            "finished_at": "",
            "returncode": "",
            "error": "",
        }
    step = str(payload.get("step", ""))
    pid = payload.get("pid", "")
    started_at = str(payload.get("started_at", ""))
    record_status = str(payload.get("status", ""))
    job_meta = {
        "backend": str(payload.get("backend") or ""),
        "queue_name": str(payload.get("queue_name") or ""),
        "queued_at": str(payload.get("queued_at") or ""),
        "status_updated_at": str(payload.get("status_updated_at") or ""),
        "finished_at": str(payload.get("finished_at") or ""),
        "returncode": str(
            payload.get("returncode")
            if payload.get("returncode") is not None
            else ""
        ),
        "error": str(payload.get("error") or ""),
    }
    log_path = Path(str(payload.get("log_path", "")))
    if record_status == "queued":
        return {
            "job_id": str(payload.get("job_id") or ""),
            "step": step,
            "status": "queued",
            "status_label": "QUEUED",
            "phase": "submitted",
            "pid": "",
            "started_at": started_at,
            "manifest_status": "N/A",
            "manifest": "",
            "log_path": context.relpath(log_path),
            "log_tail": context.log_tail(log_path, limit=360),
            **job_meta,
        }

    running = context.pid_is_running(pid)
    evidence_path, evidence_payload = context.launch_evidence(step)
    manifest_status = context.evidence_status(
        evidence_path,
        evidence_payload,
        started_at,
        running,
    )
    if record_status == "failed":
        status, label = "failed", "FAILED"
    elif running:
        status, label = "running", "RUNNING"
    elif manifest_status == "OK":
        status, label = "completed", "COMPLETED"
    elif manifest_status == "FAIL":
        status, label = "failed", "FAILED"
    else:
        status, label = "evidence_waiting", "EVIDENCE WAITING"
    phase = {
        "running": "running",
        "completed": "done",
        "failed": "done",
        "evidence_waiting": "evidence",
    }.get(status, "submitted")
    record_path = payload.get("record_path") or payload.get("_record_file") or ""
    job_id = str(
        payload.get("job_id")
        or (Path(str(record_path)).stem if record_path else "")
    )
    return {
        "job_id": job_id,
        "step": step,
        "status": status,
        "status_label": label,
        "phase": phase,
        "pid": str(pid or ""),
        "started_at": started_at,
        "manifest_status": manifest_status,
        "manifest": context.relpath(evidence_path),
        "log_path": context.relpath(log_path),
        "log_tail": context.log_tail(log_path, limit=360),
        **job_meta,
    }


__all__ = [
    "JobViewModelContext",
    "format_bytes",
    "format_date",
    "format_int",
    "format_number",
    "format_pct",
    "job_payload_from_record",
    "relative_path",
    "status_class",
    "status_label",
]

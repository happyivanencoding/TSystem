"""Background job records and process launcher for the system dashboard."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

PopenFactory = Callable[..., Any]
QUEUE_NAME = "tp_dashboard_local"

_JOB_QUEUE: queue.Queue[dict[str, Any]] = queue.Queue()
_WORKER_LOCK = threading.Lock()
_WORKER_THREAD: threading.Thread | None = None


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _job_id(step: str, now: datetime) -> str:
    stamp = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]
    safe_step = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in step).strip("_")
    return f"{safe_step or 'launch'}_{stamp}"


def _latest_points_to(latest_record_path: Path, job_id: str) -> bool:
    latest = _read_json(latest_record_path)
    return not latest or latest.get("job_id") == job_id


def _write_record(
    record: dict[str, Any],
    record_path: Path,
    latest_record_path: Path,
    *,
    update_latest: bool = True,
) -> None:
    text = json.dumps(record, ensure_ascii=False, indent=2)
    record_path.write_text(text, encoding="utf-8")
    if update_latest:
        latest_record_path.write_text(text, encoding="utf-8")


def _write_worker_record(record: dict[str, Any], record_path: Path, latest_record_path: Path) -> None:
    _write_record(
        record,
        record_path,
        latest_record_path,
        update_latest=_latest_points_to(latest_record_path, str(record.get("job_id") or "")),
    )


def _worker_id() -> str:
    return f"{os.getpid()}-{threading.get_ident()}"


def _lock_path(record_path: Path) -> Path:
    return record_path.with_suffix(record_path.suffix + ".lock")


def _claim_queued_record(record_path: Path, latest_record_path: Path, worker_id: str) -> Path | None:
    lock_path = _lock_path(record_path)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    except OSError:
        return None
    try:
        claimed_at = datetime.now().isoformat(timespec="seconds")
        with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
            lock_file.write(json.dumps({"worker_id": worker_id, "claimed_at": claimed_at}, ensure_ascii=False))
        record = _read_json(record_path) or {}
        if record.get("status") != "queued":
            _release_claim(lock_path)
            return None
        record.update(
            {
                "status": "running",
                "worker_id": worker_id,
                "claimed_at": claimed_at,
                "status_updated_at": claimed_at,
            }
        )
        _write_worker_record(record, record_path, latest_record_path)
        return lock_path
    except Exception:
        _release_claim(lock_path)
        return None


def _release_claim(lock_path: Path | None) -> None:
    if not lock_path:
        return
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _ensure_worker() -> None:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD and _WORKER_THREAD.is_alive():
            return
        _WORKER_THREAD = threading.Thread(target=_worker_loop, name="tp-dashboard-job-worker", daemon=True)
        _WORKER_THREAD.start()


def _worker_loop() -> None:
    while True:
        item = _JOB_QUEUE.get()
        try:
            _run_queued_job(**item)
        finally:
            _JOB_QUEUE.task_done()


def _run_queued_job(
    *,
    command_list: list[str],
    root: Path,
    record_path: Path,
    latest_record_path: Path,
    log_path: Path,
    popen_factory: PopenFactory,
    creationflags: int,
    claim_lock: Path | None = None,
) -> None:
    record = _read_json(record_path) or {}
    try:
        record.update(
            {
                "status": "running",
                "status_updated_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        _write_worker_record(record, record_path, latest_record_path)
        with log_path.open("a", encoding="utf-8") as log:
            process = popen_factory(
                command_list,
                cwd=root,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creationflags,
            )
            record["pid"] = process.pid
            record["status_updated_at"] = datetime.now().isoformat(timespec="seconds")
            _write_worker_record(record, record_path, latest_record_path)
            wait = getattr(process, "wait", None)
            if callable(wait):
                returncode = wait()
                record.update(
                    {
                        "status": "completed" if returncode == 0 else "failed",
                        "returncode": returncode,
                        "finished_at": datetime.now().isoformat(timespec="seconds"),
                        "status_updated_at": datetime.now().isoformat(timespec="seconds"),
                    }
                )
                _write_worker_record(record, record_path, latest_record_path)
    except Exception as exc:
        record.update(
            {
                "status": "failed",
                "error": str(exc),
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "status_updated_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        _write_worker_record(record, record_path, latest_record_path)
    finally:
        _release_claim(claim_lock)


def _queued_record_paths(launch_dir: Path) -> list[Path]:
    if not launch_dir.exists():
        return []
    paths: list[Path] = []
    for path in sorted(launch_dir.glob("*.json"), key=lambda item: item.stat().st_mtime):
        if path.name == "launch_latest.json":
            continue
        payload = _read_json(path)
        if payload and payload.get("status") == "queued":
            paths.append(path)
    return paths


def _record_paths(launch_dir: Path) -> list[Path]:
    if not launch_dir.exists():
        return []
    return sorted(
        (path for path in launch_dir.glob("*.json") if path.name != "launch_latest.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def queue_status(launch_dir: Path, *, limit: int = 8) -> dict[str, Any]:
    counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "other": 0}
    recent: list[dict[str, Any]] = []
    for path in _record_paths(launch_dir):
        payload = _read_json(path) or {}
        status = str(payload.get("status") or "other")
        counts[status if status in counts else "other"] += 1
        if len(recent) >= limit:
            continue
        recent.append(
            {
                "job_id": str(payload.get("job_id") or path.stem),
                "status": status,
                "step": str(payload.get("step") or ""),
                "updated_at": str(payload.get("status_updated_at") or payload.get("queued_at") or ""),
                "backend": str(payload.get("backend") or ""),
                "queue_name": str(payload.get("queue_name") or QUEUE_NAME),
                "log_path": str(payload.get("log_path") or ""),
            }
        )
    latest = latest_launch_record(launch_dir) or {}
    return {
        "queue_name": QUEUE_NAME,
        "launch_dir": str(launch_dir),
        "thread_worker_alive": bool(_WORKER_THREAD and _WORKER_THREAD.is_alive()),
        "in_memory_pending": _JOB_QUEUE.qsize(),
        "total_records": sum(counts.values()),
        "latest_job_id": str(latest.get("job_id") or ""),
        "counts": counts,
        "recent": recent,
    }


def run_queued_jobs_once(
    launch_dir: Path,
    root: Path,
    *,
    popen_factory: PopenFactory | None = None,
    creationflags: int | None = None,
    limit: int | None = None,
) -> int:
    if creationflags is None:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    count = 0
    worker_id = _worker_id()
    for record_path in _queued_record_paths(launch_dir):
        if limit is not None and count >= limit:
            break
        latest_record_path = launch_dir / "launch_latest.json"
        claim_lock = _claim_queued_record(record_path, latest_record_path, worker_id)
        if claim_lock is None:
            continue
        record = _read_json(record_path) or {}
        command_list = [str(item) for item in record.get("command") or []]
        log_path = Path(str(record.get("log_path") or record_path.with_suffix(".log")))
        if command_list:
            _run_queued_job(
                command_list=command_list,
                root=root,
                record_path=record_path,
                latest_record_path=latest_record_path,
                log_path=log_path,
                popen_factory=popen_factory or subprocess.Popen,
                creationflags=creationflags,
                claim_lock=claim_lock,
            )
        else:
            record.update(
                {
                    "status": "failed",
                    "error": "queued job has no command",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "status_updated_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            _write_worker_record(record, record_path, latest_record_path)
            _release_claim(claim_lock)
        count += 1
    return count


def run_worker(
    launch_dir: Path,
    root: Path,
    *,
    interval_seconds: float = 2.0,
    once: bool = False,
    limit: int | None = None,
) -> int:
    total = 0
    while True:
        remaining = None if limit is None else max(limit - total, 0)
        if remaining == 0:
            return total
        total += run_queued_jobs_once(launch_dir, root, limit=remaining)
        if once:
            return total
        time.sleep(max(interval_seconds, 0.2))


def latest_launch_record(launch_dir: Path) -> dict[str, Any] | None:
    latest_path = launch_dir / "launch_latest.json"
    if latest_path.exists():
        payload = _read_json(latest_path)
        if payload:
            payload["_record_file"] = str(latest_path)
            return payload
    if not launch_dir.exists():
        return None
    paths = sorted(launch_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in paths:
        payload = _read_json(path)
        if payload:
            payload["_record_file"] = str(path)
            return payload
    return None


def launch_record_by_job_id(job_id: str, launch_dir: Path) -> dict[str, Any] | None:
    if not job_id:
        return None
    try:
        launch_root = launch_dir.resolve(strict=False)
        record_path = (launch_dir / f"{job_id}.json").resolve(strict=False)
        if launch_root not in (record_path, *record_path.parents):
            return None
    except Exception:
        return None
    if not record_path.exists():
        return None
    payload = _read_json(record_path)
    if not payload:
        return None
    payload["_record_file"] = str(record_path)
    return payload


def launch_job(
    command: Sequence[str],
    step: str,
    launch_dir: Path,
    root: Path,
    *,
    popen_factory: PopenFactory | None = None,
    creationflags: int | None = None,
) -> dict[str, Any]:
    launch_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    started_at = now.isoformat(timespec="seconds")
    job_id = _job_id(step, now)
    log_path = launch_dir / f"{job_id}.log"
    record_path = launch_dir / f"{job_id}.json"
    latest_record_path = launch_dir / "launch_latest.json"
    popen = popen_factory or subprocess.Popen
    if creationflags is None:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    command_list = [str(item) for item in command]
    with log_path.open("w", encoding="utf-8") as log:
        process = popen(
            command_list,
            cwd=root,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creationflags,
        )
    record = {
        "job_id": job_id,
        "status": "running",
        "status_updated_at": datetime.now().isoformat(timespec="seconds"),
        "started_at": started_at,
        "step": step,
        "pid": process.pid,
        "command": command_list,
        "log_path": str(log_path),
        "record_path": str(record_path),
        "backend": "local_subprocess",
        "queue_name": "",
    }
    _write_record(record, record_path, latest_record_path)
    return record


def submit_job(
    command: Sequence[str],
    step: str,
    launch_dir: Path,
    root: Path,
    *,
    popen_factory: PopenFactory | None = None,
    creationflags: int | None = None,
) -> dict[str, Any]:
    launch_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    queued_at = now.isoformat(timespec="seconds")
    job_id = _job_id(step, now)
    log_path = launch_dir / f"{job_id}.log"
    record_path = launch_dir / f"{job_id}.json"
    latest_record_path = launch_dir / "launch_latest.json"
    if creationflags is None:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    command_list = [str(item) for item in command]
    log_path.touch()
    record = {
        "job_id": job_id,
        "status": "queued",
        "status_updated_at": queued_at,
        "queued_at": queued_at,
        "started_at": queued_at,
        "step": step,
        "pid": "",
        "command": command_list,
        "log_path": str(log_path),
        "record_path": str(record_path),
        "backend": "local_thread_queue",
        "queue_name": QUEUE_NAME,
    }
    _write_record(record, record_path, latest_record_path)
    _ensure_worker()
    _JOB_QUEUE.put(
        {
            "command_list": command_list,
            "root": root,
            "record_path": record_path,
            "latest_record_path": latest_record_path,
            "log_path": log_path,
            "popen_factory": popen_factory or subprocess.Popen,
            "creationflags": creationflags,
        }
    )
    return record

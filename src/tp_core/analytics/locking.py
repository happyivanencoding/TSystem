"""Small cross-process file lock for single-writer catalog publication."""

from __future__ import annotations

import time
from pathlib import Path
from typing import IO, Self


class FileLock:
    """Acquire an advisory lock on one byte of a lock file."""

    def __init__(self, path: str | Path, *, timeout: float = 30.0, poll_interval: float = 0.05) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._handle: IO[bytes] | None = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+b")
        if self._handle.seek(0, 2) == 0:
            self._handle.write(b"\0")
            self._handle.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                _try_lock(self._handle)
                return self
            except (BlockingIOError, OSError) as exc:
                if time.monotonic() >= deadline:
                    self._handle.close()
                    self._handle = None
                    raise TimeoutError(f"timed out acquiring lock: {self.path}") from exc
                time.sleep(self.poll_interval)

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        if self._handle is None:
            return
        try:
            _unlock(self._handle)
        finally:
            self._handle.close()
            self._handle = None


def _try_lock(handle: IO[bytes]) -> None:
    handle.seek(0)
    try:
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except ImportError:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]


def _unlock(handle: IO[bytes]) -> None:
    handle.seek(0)
    try:
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except ImportError:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


__all__ = ["FileLock"]

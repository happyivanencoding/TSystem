"""Filesystem repository used by the system dashboard."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


class DashboardRepository(Protocol):
    def read_json(self, path: Path) -> dict[str, Any] | None: ...

    def latest_manifest(self, step: str) -> dict[str, Any] | None: ...

    def latest_qa_json(self, pattern: str) -> dict[str, Any] | None: ...

    def read_config(self) -> dict[str, Any]: ...

    def write_config(self, values: Mapping[str, Any]) -> dict[str, Any]: ...

    def read_frame(self, path: Path) -> pd.DataFrame | None: ...


@lru_cache(maxsize=48)
def _cached_parquet(path_text: str, mtime_ns: int) -> pd.DataFrame:
    del mtime_ns
    return pd.read_parquet(path_text)


@dataclass(frozen=True)
class SystemDashboardRepository:
    config_path: Path
    defaults: Mapping[str, Any]
    qa_dir: Path
    manifest_dir: Path

    def read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def latest_manifest(self, step: str) -> dict[str, Any] | None:
        return self.read_json(self.manifest_dir / step / f"{step}_latest.json")

    def latest_qa_json(self, pattern: str) -> dict[str, Any] | None:
        matches = sorted(
            self.qa_dir.glob(pattern),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for path in matches:
            payload = self.read_json(path)
            if payload is not None:
                return {**payload, "_path": str(path)}
        return None

    def read_config(self) -> dict[str, Any]:
        payload = self.read_json(self.config_path) or {}
        raw_values = payload.get("values")
        values = raw_values if isinstance(raw_values, dict) else payload
        config = dict(self.defaults)
        for key in self.defaults:
            if key in values:
                config[key] = values[key]
        return config

    def write_config(self, values: Mapping[str, Any]) -> dict[str, Any]:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        clean_values = {
            key: values.get(key, default)
            for key, default in self.defaults.items()
        }
        payload = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "values": clean_values,
        }
        self.config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    def read_frame(self, path: Path) -> pd.DataFrame | None:
        if not path.exists() or path.suffix.lower() != ".parquet":
            return None
        try:
            return _cached_parquet(str(path), path.stat().st_mtime_ns)
        except Exception:
            return None


__all__ = [
    "DashboardRepository",
    "SystemDashboardRepository",
]

"""Read-only repository and bounded read-path policy for the system dashboard."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import duckdb
import pandas as pd
import pyarrow as pa

from tp_core.analytics.config import DuckDBConfig
from tp_core.analytics.connection import connect
from tp_core.analytics.repositories import MartRepository
from tp_core.data_sources import TP_ROOT

MAX_DASHBOARD_ARTIFACT_FALLBACK_BYTES = 80 * 1024 * 1024
MAX_DASHBOARD_MART_ROWS = 25_000
EXTERNAL_DASHBOARD_ARTIFACT_NAMES = frozenset(
    {
        "regime_risk_budget.parquet",
        "regime_eu.parquet",
        "regime_us.parquet",
        "regime_oos_eu.parquet",
        "regime_oos_us.parquet",
        "sector_panel.parquet",
        "sector_scores_panel.parquet",
        "factor_recommendation_panel.parquet",
        "factor_recommendation_history.parquet",
        "factor_recommendation_signals.parquet",
    }
)


class DashboardRepository(Protocol):
    def read_json(self, path: Path) -> dict[str, Any] | None: ...

    def latest_manifest(self, step: str) -> dict[str, Any] | None: ...

    def latest_qa_json(self, pattern: str) -> dict[str, Any] | None: ...

    def read_config(self) -> dict[str, Any]: ...

    def write_config(self, values: Mapping[str, Any]) -> dict[str, Any]: ...

    def read_frame(
        self,
        path: Path,
        *,
        purpose: str = "latest",
        query_params: Mapping[str, Any] | None = None,
    ) -> pd.DataFrame | None: ...


@dataclass(frozen=True)
class MartRoute:
    name: str
    where: str | None = None
    parameters: tuple[Any, ...] = ()


@dataclass(frozen=True)
class CatalogIdentity:
    database_path: Path
    release_id: str


@lru_cache(maxsize=48)
def _cached_parquet(path_text: str, release_id: str, query_key: tuple[tuple[str, str], ...]) -> pd.DataFrame:
    """Cache an explicitly allowlisted fallback by logical release and query."""

    del release_id, query_key
    return pd.read_parquet(path_text)


@lru_cache(maxsize=32)
def _cached_mart_frame(
    database_path_text: str,
    release_id: str,
    mart_name: str,
    where: str | None,
    parameters: tuple[Any, ...],
    query_key: tuple[tuple[str, str], ...],
    limit: int,
) -> pd.DataFrame:
    """Read one immutable mart release through a read-only DuckDB connection."""

    del query_key
    database_path = Path(database_path_text)
    config = DuckDBConfig.from_env(read_only=True, database_path=database_path)
    with connect(config) as connection:
        frame = MartRepository(connection).query(
            mart_name,
            where=where,
            parameters=parameters,
            limit=limit,
        )
    frame.attrs["catalog_release_id"] = release_id
    return frame


@dataclass(frozen=True)
class SystemDashboardRepository:
    config_path: Path
    defaults: Mapping[str, Any]
    qa_dir: Path
    manifest_dir: Path
    data_root: Path = TP_ROOT

    def read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
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
            "saved_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "values": clean_values,
        }
        self.config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    def read_frame(
        self,
        path: Path,
        *,
        purpose: str = "latest",
        query_params: Mapping[str, Any] | None = None,
    ) -> pd.DataFrame | None:
        """Read a dashboard frame mart-first, with a bounded artifact fallback."""

        target = Path(path)
        if target.suffix.lower() != ".parquet":
            return None
        query_key = _query_key(purpose, query_params)
        route = mart_route_for_path(target, purpose=purpose)
        identity = self.catalog_identity()
        if route is not None and identity is not None:
            frame: pd.DataFrame | None = None
            try:
                frame = _cached_mart_frame(
                    str(identity.database_path),
                    identity.release_id,
                    route.name,
                    route.where,
                    route.parameters,
                    query_key,
                    MAX_DASHBOARD_MART_ROWS,
                )
            except (KeyError, OSError, TypeError, ValueError, duckdb.Error):
                frame = None
            if frame is not None and not frame.empty:
                return frame
        if not self._artifact_fallback_allowed(target):
            return None
        release_id = _artifact_release_id(target)
        try:
            return _cached_parquet(str(target), release_id, query_key)
        except (ImportError, KeyError, OSError, TypeError, ValueError, pa.ArrowException):
            return None

    def catalog_identity(self) -> CatalogIdentity | None:
        """Resolve the current immutable release without activating anything."""

        config = DuckDBConfig.from_env(read_only=True)
        pointer_payload = self.read_json(config.latest_pointer)
        pointer_seen = pointer_payload is not None
        candidate: Path | None = None
        release_id: str | None = None
        if pointer_payload:
            raw_path = pointer_payload.get("database_path")
            if raw_path:
                candidate = Path(str(raw_path))
                if not candidate.is_absolute():
                    candidate = config.latest_pointer.parent / candidate
                release_id = str(pointer_payload.get("release_id") or "") or None
        if pointer_seen and (candidate is None or not candidate.exists()):
            return None
        if not pointer_seen:
            candidate = config.database_path if config.database_path.exists() else None
        if candidate is None:
            return None
        candidate = candidate.resolve()
        if release_id is None:
            release_id = _catalog_release_id(candidate) or _artifact_release_id(candidate)
        return CatalogIdentity(candidate, release_id)

    def read_path_audit(self, path: Path, *, purpose: str = "latest") -> dict[str, Any]:
        """Return the policy decision used by ``read_frame`` for audit reports."""

        target = Path(path)
        route = mart_route_for_path(target, purpose=purpose)
        identity = self.catalog_identity()
        size = target.stat().st_size if target.exists() else 0
        fallback_allowed = self._artifact_fallback_allowed(target)
        if route is not None and identity is not None:
            route_status = "mart-first with bounded artifact fallback"
            mart_available = "yes"
        elif route is not None:
            route_status = "artifact fallback pending catalog release"
            mart_available = "expected"
        else:
            route_status = "artifact-backed detail on demand"
            mart_available = "no"
        return {
            "route": route_status,
            "mart": route.name if route else "",
            "mart_available": mart_available,
            "catalog_release_id": identity.release_id if identity else "",
            "source_path": str(target),
            "file_size": size,
            "bounded_fallback": bool(fallback_allowed),
            "fallback_reason": "" if fallback_allowed else "not allowlisted or exceeds size bound",
        }

    def _artifact_fallback_allowed(self, path: Path) -> bool:
        if not path.exists() or path.stat().st_size > MAX_DASHBOARD_ARTIFACT_FALLBACK_BYTES:
            return False
        target = path.resolve()
        roots = (
            self.data_root / "00_screen",
            self.data_root / "artifacts" / "signals",
            self.data_root / "artifacts" / "candidates",
            self.data_root / "artifacts" / "portfolios",
            self.data_root / "artifacts" / "research" / "runs" / "historical",
            self.data_root / "03_regime_model",
            self.data_root / "13_sector_score_model",
            self.data_root / "14_country_model",
            self.data_root / "15_small_cap_model",
            self.data_root / "16_factor_recommendation_model",
        )
        if any(_is_relative_to(target, root.resolve()) for root in roots):
            return True
        return target.name.lower() in {
            "last_des.parquet",
            "last_news_3months.parquet",
            *EXTERNAL_DASHBOARD_ARTIFACT_NAMES,
        }


def mart_route_for_path(path: Path, *, purpose: str = "latest") -> MartRoute | None:
    """Map only latest dashboard paths to bounded DuckDB marts."""

    if purpose != "latest":
        return None
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    if name in {"screen_aggregate.parquet", "last_screen.parquet"}:
        return MartRoute("company_master_latest")
    if "signals" in parts and name == "regime_risk_budget.parquet":
        return MartRoute("latest_regime")
    if "signals" in parts and name == "country_model_signals.parquet":
        return MartRoute("latest_country_scores")
    if "signals" in parts and name in {
        "ml_signals.parquet",
        "technical_signals.parquet",
        "small_cap_model_signals.parquet",
    }:
        keyword = "ml" if name.startswith("ml") else "technical" if name.startswith("technical") else "small"
        return MartRoute(
            "latest_signals",
            where="lower(coalesce(\"signal_family\", '')) LIKE ? OR lower(coalesce(\"source_project\", '')) LIKE ?",
            parameters=(f"%{keyword}%", f"%{keyword}%"),
        )
    if "signals" in parts and name in {
        "factor_exposure_snapshot_signals.parquet",
        "factor_recommendation_forecast_signals.parquet",
    }:
        return MartRoute("latest_factor_recommendation")
    if name == "latest_candidates.parquet":
        return MartRoute("latest_candidates")
    if name == "latest_target_weights.parquet":
        return MartRoute("latest_portfolio")
    return None


def _catalog_release_id(database_path: Path) -> str | None:
    config = DuckDBConfig.from_env(read_only=True, database_path=database_path)
    try:
        with connect(config) as connection:
            row = connection.execute(
                "SELECT release_id FROM meta.catalog_releases ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
    except (KeyError, OSError, ValueError, duckdb.Error):
        return None
    return str(row[0]) if row and row[0] else None


def _artifact_release_id(path: Path) -> str:
    stat = path.stat()
    return f"artifact:{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"


def _query_key(purpose: str, query_params: Mapping[str, Any] | None) -> tuple[tuple[str, str], ...]:
    values = {"purpose": purpose}
    if query_params:
        values.update({str(key): str(value) for key, value in query_params.items()})
    return tuple(sorted(values.items()))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


__all__ = [
    "MAX_DASHBOARD_ARTIFACT_FALLBACK_BYTES",
    "DashboardRepository",
    "SystemDashboardRepository",
    "mart_route_for_path",
]

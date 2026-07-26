"""Effective artifact policy shared by TP experiment runners."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
from typing import Any, Iterator, Mapping

import pandas as pd

SAVE_PLOTS_ENV = "TP_EXPERIMENT_SAVE_PLOTS"
HOLDINGS_MODE_ENV = "TP_EXPERIMENT_HOLDINGS_MODE"
MINIMAL_HOLDING_COLUMNS = ("Date", "Weight", "ISIN")
HOLDINGS_MODES = {"minimal", "full"}

_TRUE_VALUES = {"1", "true", "yes", "on"}
_HOLDING_NAME = re.compile(
    r"^(?:sec_list(?:_.*)?|security_list(?:_.*)?|holdings?)$",
    re.IGNORECASE,
)
_COLUMN_ALIASES = {
    "Date": ("date", "time", "timestamp", "datetime"),
    "Weight": ("weight", "target_weight", "portfolio_weight"),
    "ISIN": ("isin",),
}


@dataclass(frozen=True)
class ExperimentArtifactPolicy:
    """Auditable effective defaults for one configured experiment."""

    save_plots: bool = False
    holdings_mode: str = "minimal"

    @classmethod
    def from_definition(
        cls,
        payload: Mapping[str, Any] | None,
    ) -> "ExperimentArtifactPolicy":
        configured = (payload or {}).get("artifact_policy") or {}
        if not isinstance(configured, Mapping):
            raise ValueError("artifact_policy 必须是对象")
        unknown = set(configured) - {"save_plots", "holdings_mode"}
        if unknown:
            raise ValueError(f"artifact_policy 包含未知字段：{sorted(unknown)}")
        save_plots = configured.get("save_plots", False)
        if not isinstance(save_plots, bool):
            raise ValueError("artifact_policy.save_plots 必须是布尔值")
        holdings_mode = str(configured.get("holdings_mode", "minimal"))
        if holdings_mode not in HOLDINGS_MODES:
            raise ValueError(
                "artifact_policy.holdings_mode 必须是 minimal 或 full"
            )
        return cls(save_plots=save_plots, holdings_mode=holdings_mode)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def experiment_plots_enabled() -> bool:
    """Return whether the active experiment should persist Plot artifacts."""

    return os.environ.get(SAVE_PLOTS_ENV, "0").strip().lower() in _TRUE_VALUES


def experiment_holdings_mode() -> str:
    """Return the active holdings detail level for direct experiment runs."""

    value = os.environ.get(HOLDINGS_MODE_ENV, "minimal").strip().lower()
    return value if value in HOLDINGS_MODES else "minimal"


def _minimal_holdings_frame(dataframe: pd.DataFrame | None) -> pd.DataFrame:
    if dataframe is None:
        return pd.DataFrame(columns=MINIMAL_HOLDING_COLUMNS)
    normalized = {
        str(column).strip().casefold(): column for column in dataframe.columns
    }
    selected: dict[str, Any] = {}
    missing: list[str] = []
    for canonical, aliases in _COLUMN_ALIASES.items():
        source = next(
            (
                normalized.get(alias.casefold())
                for alias in aliases
                if alias.casefold() in normalized
            ),
            None,
        )
        if source is None:
            missing.append(canonical)
        else:
            selected[canonical] = source
    if missing:
        raise ValueError(f"holdings 缺少最小字段：{missing}")
    return dataframe[
        [selected[column] for column in MINIMAL_HOLDING_COLUMNS]
    ].rename(
        columns={
            selected[column]: column for column in MINIMAL_HOLDING_COLUMNS
        }
    )


def holdings_for_storage(
    dataframe: pd.DataFrame | None,
    *,
    mode: str | None = None,
) -> pd.DataFrame:
    """Keep only reproducible identifiers and weights unless full mode is active."""

    effective_mode = mode or experiment_holdings_mode()
    if effective_mode not in HOLDINGS_MODES:
        raise ValueError("holdings mode 必须是 minimal 或 full")
    if dataframe is not None and effective_mode == "full":
        return dataframe.copy()
    return _minimal_holdings_frame(dataframe)


@contextmanager
def experiment_artifact_environment(
    policy: ExperimentArtifactPolicy,
) -> Iterator[None]:
    """Expose one effective policy to package workflows and restore the caller state."""

    previous = {
        SAVE_PLOTS_ENV: os.environ.get(SAVE_PLOTS_ENV),
        HOLDINGS_MODE_ENV: os.environ.get(HOLDINGS_MODE_ENV),
    }
    os.environ[SAVE_PLOTS_ENV] = "1" if policy.save_plots else "0"
    os.environ[HOLDINGS_MODE_ENV] = policy.holdings_mode
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def compact_experiment_holdings(
    root: str | Path,
    *,
    policy: ExperimentArtifactPolicy,
) -> list[Path]:
    """Apply the holdings policy recursively to completed experiment results."""

    target_root = Path(root)
    if policy.holdings_mode == "full" or not target_root.exists():
        return []
    candidates = sorted(
        path
        for path in target_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".parquet", ".csv", ".xlsx"}
        and _HOLDING_NAME.fullmatch(path.stem)
    )
    compacted: list[Path] = []
    for path in candidates:
        suffix = path.suffix.lower()
        if suffix == ".parquet":
            frame = pd.read_parquet(path)
        elif suffix == ".csv":
            frame = pd.read_csv(path)
        else:
            frame = pd.read_excel(path)
        minimal = _minimal_holdings_frame(frame)
        if suffix == ".parquet":
            minimal.to_parquet(path, index=False)
        elif suffix == ".csv":
            minimal.to_csv(path, index=False)
        else:
            minimal.to_excel(path, index=False)
        compacted.append(path)
    return compacted


__all__ = [
    "HOLDINGS_MODE_ENV",
    "MINIMAL_HOLDING_COLUMNS",
    "ExperimentArtifactPolicy",
    "SAVE_PLOTS_ENV",
    "compact_experiment_holdings",
    "experiment_artifact_environment",
    "experiment_holdings_mode",
    "experiment_plots_enabled",
    "holdings_for_storage",
]

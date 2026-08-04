"""风格因子定义与横截面得分计算。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from .config import DEFAULT_FACTOR_DEFINITIONS_PATH


@dataclass(frozen=True)
class FactorDefinition:
    name: str
    label: str
    source_columns: tuple[str, ...]
    direction: int = 1
    score_scale: float = 10.0
    transform: str = "identity"
    min_count: int = 1
    description: str = ""

    def __post_init__(self) -> None:
        if self.direction not in (-1, 1):
            raise ValueError("factor direction must be -1 or 1")
        if self.score_scale <= 0:
            raise ValueError("score_scale must be positive")
        if self.min_count < 1:
            raise ValueError("min_count must be >= 1")


def _as_sources(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, Mapping):
        raw = raw.get("columns", raw.get("column", []))
    values: list[str] = []
    for item in raw or []:
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, Mapping):
            column = item.get("column")
            if column:
                values.append(str(column))
            values.extend(str(alias) for alias in item.get("aliases", []))
    return tuple(dict.fromkeys(values))


def parse_factor_definitions(payload: Mapping[str, Any]) -> tuple[FactorDefinition, ...]:
    raw_factors = payload.get("factors", payload)
    items = raw_factors.items() if isinstance(raw_factors, Mapping) else enumerate(raw_factors)
    definitions: list[FactorDefinition] = []
    for key, raw in items:
        if not isinstance(raw, Mapping):
            raise TypeError(f"factor definition {key!r} must be an object")
        name = str(raw.get("name", key)).strip()
        sources = _as_sources(raw.get("source_columns", raw.get("sources", [])))
        if not name or not sources:
            raise ValueError(f"factor definition {key!r} needs name and source_columns")
        definitions.append(
            FactorDefinition(
                name=name,
                label=str(raw.get("label", name)),
                source_columns=sources,
                direction=int(raw.get("direction", 1)),
                score_scale=float(raw.get("score_scale", payload.get("score_scale", 10.0))),
                transform=str(raw.get("transform", "identity")),
                min_count=int(raw.get("min_count", 1)),
                description=str(raw.get("description", "")),
            )
        )
    return tuple(definitions)


def load_factor_definitions(
    path: str | Path = DEFAULT_FACTOR_DEFINITIONS_PATH,
) -> tuple[FactorDefinition, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_factor_definitions(payload)


def factor_definition_map(
    definitions: Iterable[FactorDefinition] | None = None,
) -> dict[str, FactorDefinition]:
    definitions = tuple(definitions or load_factor_definitions())
    return {definition.name: definition for definition in definitions}


def _resolve_source(frame: pd.DataFrame, source: str) -> pd.Series | None:
    if source in frame.columns:
        return pd.to_numeric(frame[source], errors="coerce")
    normalized = {str(column).strip().lower(): column for column in frame.columns}
    column = normalized.get(source.strip().lower())
    if column is None:
        return None
    return pd.to_numeric(frame[column], errors="coerce")


def compute_factor_scores(
    frame: pd.DataFrame,
    definitions: Iterable[FactorDefinition] | None = None,
    *,
    include_alias_columns: bool = True,
) -> pd.DataFrame:
    """按定义计算分数；缺少字段时返回 NA，不用未来字段或补零伪造覆盖率。"""

    out = frame.copy()
    for definition in tuple(definitions or load_factor_definitions()):
        values: list[pd.Series] = []
        for source in definition.source_columns:
            series = _resolve_source(out, source)
            if series is None:
                continue
            if definition.direction < 0:
                if definition.transform == "reverse_score":
                    series = definition.score_scale - series
                else:
                    series = -series
            values.append(series)
        if not values:
            score = pd.Series(np.nan, index=out.index, dtype=float)
        else:
            score_frame = pd.concat(values, axis=1)
            score = score_frame.mean(axis=1, skipna=True)
            score[score_frame.notna().sum(axis=1) < definition.min_count] = np.nan
        out[definition.name] = score.astype(float)
        if include_alias_columns:
            out[f"factor__{definition.name}"] = out[definition.name]
    return out


def factor_score_columns(
    definitions: Iterable[FactorDefinition] | None = None,
) -> tuple[str, ...]:
    return tuple(definition.name for definition in tuple(definitions or load_factor_definitions()))


__all__ = [
    "FactorDefinition",
    "compute_factor_scores",
    "factor_definition_map",
    "factor_score_columns",
    "load_factor_definitions",
    "parse_factor_definitions",
]

"""PIT 区域 universe 定义与选择。

ASIA 不是一个可直接映射的 canonical benchmark：它固定由 JAPAN(NIKKEI)
和 ASIA_EX_JAPAN(MSCI EM 正权重 + 国家 allowlist) 两个组件组成。因此
ASIA 聚合结果始终标记为 research_only / benchmark_unapproved。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .config import DEFAULT_REGION_UNIVERSES_PATH
from .contracts import DATE_COLUMN, ID_COLUMN, Region, UniverseSelection, normalize_region


@dataclass(frozen=True)
class UniverseComponent:
    name: str
    benchmark: str
    weight_column: str
    positive_weight: bool = True
    country_column: str | None = None
    country_allowlist: tuple[str, ...] = ()
    exclude_countries: tuple[str, ...] = ()
    pit_boundary_note: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "UniverseComponent":
        return cls(
            name=str(payload["name"]),
            benchmark=str(payload.get("benchmark", payload["name"])),
            weight_column=str(payload["weight_column"]),
            positive_weight=bool(payload.get("positive_weight", True)),
            country_column=(
                str(payload["country_column"]) if payload.get("country_column") else None
            ),
            country_allowlist=tuple(str(item) for item in payload.get("country_allowlist", [])),
            exclude_countries=tuple(str(item) for item in payload.get("exclude_countries", [])),
            pit_boundary_note=str(payload.get("pit_boundary_note", "")),
        )


@dataclass(frozen=True)
class RegionUniverse:
    name: str
    components: tuple[UniverseComponent, ...]
    display_name: str = ""
    aggregation_weights: Mapping[str, float] = None  # type: ignore[assignment]
    currency_basis: str = "local_currency"
    minimum_monthly_constituents: int = 1
    minimum_weight_coverage: float = 0.0
    history_start: str | None = None
    production_eligible: bool = True
    approval_status: str = "approved"
    aliases: tuple[str, ...] = ()
    research_only: bool = False
    benchmark_approved: bool = True
    aggregation_policy: str = "single_component"
    description: str = ""

    @property
    def component_aggregation_weights(self) -> Mapping[str, float]:
        """兼容 Prompt 术语的只读别名。"""

        return self.aggregation_weights

    def __post_init__(self) -> None:
        if not self.components:
            raise ValueError(f"{self.name} must define at least one universe component")
        if self.aggregation_weights is None:
            object.__setattr__(
                self,
                "aggregation_weights",
                {component.name: 1.0 / len(self.components) for component in self.components},
            )
        if self.minimum_monthly_constituents < 1:
            raise ValueError("minimum_monthly_constituents must be >= 1")
        if not 0 <= self.minimum_weight_coverage <= 1:
            raise ValueError("minimum_weight_coverage must be in [0, 1]")
        if set(self.aggregation_weights) != {component.name for component in self.components}:
            raise ValueError(f"{self.name} aggregation_weights must cover every component")
        if abs(sum(float(value) for value in self.aggregation_weights.values()) - 1.0) > 1e-9:
            raise ValueError(f"{self.name} aggregation_weights must sum to 1")
        if self.name == Region.ASIA.value and (
            not self.research_only or self.benchmark_approved
        ):
            raise ValueError("ASIA must be research_only and benchmark_unapproved")
        if self.name == Region.ASIA.value:
            expected = {"JAPAN": 0.5, "ASIA_EX_JAPAN": 0.5}
            if dict(self.aggregation_weights) != expected:
                raise ValueError("ASIA component aggregation weights are fixed at 0.5/0.5")
            if self.production_eligible or self.approval_status != "research_only_benchmark_unapproved":
                raise ValueError("ASIA must remain research-ineligible and benchmark-unapproved")


def parse_region_universes(payload: Mapping[str, Any]) -> dict[str, RegionUniverse]:
    raw_regions = payload.get("regions", payload)
    result: dict[str, RegionUniverse] = {}
    for key, raw in raw_regions.items():
        if not isinstance(raw, Mapping):
            raise TypeError(f"region {key!r} must be an object")
        name = normalize_region(str(raw.get("name", key)))
        components = tuple(
            UniverseComponent.from_dict(item) for item in raw.get("components", [])
        )
        result[name] = RegionUniverse(
            name=name,
            components=components,
            display_name=str(raw.get("display_name", name)),
            aggregation_weights={
                str(component): float(weight)
                for component, weight in dict(
                    raw.get("component_aggregation_weights", raw.get("aggregation_weights", {}))
                ).items()
            }
            or None,
            currency_basis=str(raw.get("currency_basis", "local_currency")),
            minimum_monthly_constituents=int(raw.get("minimum_monthly_constituents", 1)),
            minimum_weight_coverage=float(raw.get("minimum_weight_coverage", 0.0)),
            history_start=(str(raw["history_start"]) if raw.get("history_start") else None),
            production_eligible=bool(raw.get("production_eligible", True)),
            approval_status=str(raw.get("approval_status", "approved")),
            aliases=tuple(str(alias) for alias in raw.get("aliases", [])),
            research_only=bool(raw.get("research_only", False)),
            benchmark_approved=bool(raw.get("benchmark_approved", True)),
            aggregation_policy=str(raw.get("aggregation_policy", "single_component")),
            description=str(raw.get("description", "")),
        )
    return result


def load_region_universes(
    path: str | Path = DEFAULT_REGION_UNIVERSES_PATH,
) -> dict[str, RegionUniverse]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_region_universes(payload)


def _ensure_screen(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if ID_COLUMN not in out.columns and out.index.name == ID_COLUMN:
        out = out.reset_index()
    if DATE_COLUMN not in out.columns:
        raise KeyError(f"screen must contain {DATE_COLUMN}")
    out[DATE_COLUMN] = pd.to_datetime(out[DATE_COLUMN], errors="coerce")
    if out[DATE_COLUMN].isna().any():
        raise ValueError("screen contains invalid Date values")
    return out


def _component_mask(screen: pd.DataFrame, component: UniverseComponent) -> pd.Series:
    if component.weight_column not in screen.columns:
        raise KeyError(
            f"{component.name} requires canonical weight column {component.weight_column!r}"
        )
    weight = pd.to_numeric(screen[component.weight_column], errors="coerce").fillna(0.0)
    mask = weight.gt(0) if component.positive_weight else weight.ne(0)
    if component.country_allowlist:
        if not component.country_column or component.country_column not in screen.columns:
            raise KeyError(
                f"{component.name} requires country column {component.country_column!r}"
            )
        mask &= screen[component.country_column].astype("string").isin(
            list(component.country_allowlist)
        )
    if component.exclude_countries:
        if not component.country_column or component.country_column not in screen.columns:
            raise KeyError(
                f"{component.name} requires country column {component.country_column!r}"
            )
        mask &= ~screen[component.country_column].astype("string").isin(
            list(component.exclude_countries)
        )
    return mask


def select_universe(
    screen: pd.DataFrame,
    region: str | Region,
    *,
    date: pd.Timestamp | str | None = None,
    definitions: Mapping[str, RegionUniverse] | None = None,
) -> UniverseSelection:
    """根据当期 PIT 权重和 allowlist 选择证券，不回填今天的成分。"""

    region_name = normalize_region(region)
    regions = dict(definitions or load_region_universes())
    if region_name not in regions:
        raise KeyError(f"unknown factor recommendation region: {region_name}")
    spec = regions[region_name]
    source = _ensure_screen(screen)
    if date is not None:
        selected_date = pd.Timestamp(date)
        source = source.loc[source[DATE_COLUMN].eq(selected_date)].copy()
    rows: list[pd.DataFrame] = []
    for component in spec.components:
        mask = _component_mask(source, component)
        part = source.loc[mask].copy()
        if part.empty:
            continue
        part["universe_component"] = component.name
        part["universe_benchmark"] = component.benchmark
        part["universe_weight"] = pd.to_numeric(
            part[component.weight_column], errors="coerce"
        )
        part["component_aggregation_weight"] = float(
            spec.aggregation_weights.get(component.name, 1.0 / len(spec.components))
        )
        rows.append(part)
    if rows:
        selected = pd.concat(rows, ignore_index=True)
        dedupe_keys = [column for column in (ID_COLUMN, DATE_COLUMN) if column in selected.columns]
        if dedupe_keys:
            selected = selected.drop_duplicates(dedupe_keys, keep="first")
    else:
        selected = source.iloc[0:0].copy()
        selected["universe_component"] = pd.Series(index=selected.index, dtype="string")
        selected["universe_benchmark"] = pd.Series(index=selected.index, dtype="string")
        selected["universe_weight"] = pd.Series(index=selected.index, dtype=float)
    return UniverseSelection(
        frame=selected.reset_index(drop=True),
        region=region_name,
        research_only=spec.research_only,
        benchmark_approved=spec.benchmark_approved,
        components=tuple(component.name for component in spec.components),
        notes=(spec.description,) if spec.description else (),
    )


def region_mask(
    screen: pd.DataFrame,
    region: str | Region,
    *,
    definitions: Mapping[str, RegionUniverse] | None = None,
) -> pd.Series:
    """返回与输入 index 对齐的区域 mask。"""

    source = _ensure_screen(screen)
    selection = select_universe(source, region, definitions=definitions)
    keys = set(
        zip(
            selection.frame.get(ID_COLUMN, pd.Series(dtype=object)).astype(str),
            selection.frame[DATE_COLUMN].astype(str),
        )
    )
    return pd.Series(
        [
            (str(identifier), str(current_date)) in keys
            for identifier, current_date in zip(
                source.get(ID_COLUMN, source.index).astype(str), source[DATE_COLUMN]
            )
        ],
        index=source.index,
        dtype=bool,
    )


__all__ = [
    "RegionUniverse",
    "UniverseComponent",
    "load_region_universes",
    "parse_region_universes",
    "region_mask",
    "select_universe",
]

"""研究 runner 使用的 canonical input loader。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH
from tp_core.io import read_returns, read_screen_aggregate

from .config import FactorRecommendationConfig, load_runtime_config
from .factor_definitions import FactorDefinition, load_factor_definitions
from .universe import RegionUniverse, UniverseComponent, load_region_universes


@dataclass(frozen=True)
class ResearchInputs:
    """loader 的 typed 返回值。"""

    screen: pd.DataFrame
    returns: pd.DataFrame
    universe: Mapping[str, RegionUniverse]
    factors: tuple[FactorDefinition, ...]
    model: FactorRecommendationConfig
    components: Mapping[str, tuple[UniverseComponent, ...]]


def load_research_inputs(
    *,
    screen_path: str | Path = SCREEN_AGGREGATE_PATH,
    returns_path: str | Path = RETURNS_PATH,
    factor_definitions_path: str | Path | None = None,
    region_universes_path: str | Path | None = None,
    screen_columns: Iterable[str] | None = None,
    return_columns: Iterable[str] | None = None,
    date_from: str | pd.Timestamp | None = None,
    date_to: str | pd.Timestamp | None = None,
    engine: str | None = None,
) -> ResearchInputs:
    """读取 canonical 输入并装配版本化配置。

    ``screen_columns``/``return_columns`` 可用于 inspect 或轻量 runner；默认
    读取完整 canonical 数据。此函数没有任何写路径，也不修改 DataFrame 输入。
    """

    config = load_runtime_config(
        factor_definitions_path=factor_definitions_path,
        region_universes_path=region_universes_path,
    )
    factors = load_factor_definitions(config.factor_definitions_path)
    universe = load_region_universes(config.region_universes_path)
    if screen_columns is None:
        requested = {"Date", "Company SEDOL"}
        for factor in factors:
            requested.update(factor.source_columns)
        for spec in universe.values():
            for component in spec.components:
                requested.add(component.weight_column)
                if component.country_column:
                    requested.add(component.country_column)
        try:
            import pyarrow.parquet as pq

            available = set(pq.ParquetFile(Path(screen_path)).schema.names)
            screen_columns = sorted(requested.intersection(available))
        except (ImportError, KeyError, OSError, ValueError):
            # The canonical reader remains the fallback when a parquet schema
            # inspector is unavailable; no synthetic or copied data is used.
            screen_columns = None
    screen = read_screen_aggregate(
        Path(screen_path),
        columns=screen_columns,
        date_from=_coerce_date(date_from),
        date_to=_coerce_date(date_to),
        engine=engine,
    )
    returns = read_returns(
        Path(returns_path),
        columns=return_columns,
        date_from=_coerce_date(date_from),
        date_to=_coerce_date(date_to),
        engine=engine,
    )
    components = {name: tuple(spec.components) for name, spec in universe.items()}
    return ResearchInputs(
        screen=screen,
        returns=returns,
        universe=universe,
        factors=factors,
        model=config,
        components=components,
    )


def _coerce_date(value: str | pd.Timestamp | None) -> pd.Timestamp | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"invalid date value: {value!r}")
    return pd.Timestamp(parsed)


__all__ = ["ResearchInputs", "load_research_inputs"]

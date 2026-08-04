"""官方 factor sleeve adapter。

本模块是新包唯一的 official sleeve 入口，严格调用
``tp_core.backtesting.OfficialPortfolioBacktest``。它不实现本地 NAV 计算，
也不提供名为 ``nav_from_weights`` 的替代路径。ASIA 聚合只返回组件结果，
因为该聚合定义没有官方 benchmark approval。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import pandas as pd

from .contracts import DATE_COLUMN, Region, normalize_region
from .factor_definitions import FactorDefinition, compute_factor_scores, load_factor_definitions
from .universe import RegionUniverse, load_region_universes, select_universe


OfficialFactory = Callable[..., Any]


@dataclass(frozen=True)
class OfficialSleeveResult:
    """官方 adapter 的结果，不在包内重算 NAV。"""

    region: str
    factor: str
    benchmark: str | None
    nav: Any = None
    weights: Any = None
    component: str | None = None
    research_only: bool = False
    benchmark_approved: bool = True
    adapter_id: str = "tp_core.backtesting.OfficialPortfolioBacktest"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    component_results: tuple["OfficialSleeveResult", ...] = ()


def _default_factory() -> OfficialFactory:
    # Lazy import keeps synthetic feature/model tests independent of optional backtest deps.
    from tp_core.backtesting import OfficialPortfolioBacktest

    return OfficialPortfolioBacktest


def _metric_column(
    screen: pd.DataFrame,
    factor: str,
    definitions: tuple[FactorDefinition, ...],
) -> tuple[pd.DataFrame, str]:
    """确保 official constructor 看到的是一个可排名的列。"""

    if factor in screen.columns:
        return screen, factor
    scored = compute_factor_scores(screen, definitions)
    if factor in scored.columns:
        return scored, factor
    raise KeyError(f"factor {factor!r} has no canonical or defined score column")


class OfficialSleeveAdapter:
    """TP official backtest 的唯一 adapter。"""

    adapter_id = "tp_core.backtesting.OfficialPortfolioBacktest"

    def __init__(self, factory: OfficialFactory | None = None) -> None:
        self._factory = factory

    @property
    def factory(self) -> OfficialFactory:
        return self._factory or _default_factory()

    def run(
        self,
        *,
        screen: pd.DataFrame,
        returns: pd.DataFrame,
        benchmark: str,
        factor: str,
        region: str | Region,
        component: str | None = None,
        top: bool = True,
        percentile: float = 0.2,
        start_date: pd.Timestamp | str | None = None,
        screen_date: pd.Timestamp | str | None = None,
        ptf_name: str | None = None,
        definitions: tuple[FactorDefinition, ...] | None = None,
        **official_kwargs: Any,
    ) -> OfficialSleeveResult:
        """构建并运行一个官方 sleeve。"""

        if not 0 < percentile <= 0.5:
            raise ValueError("percentile must be in (0, 0.5]")
        definitions = definitions or load_factor_definitions()
        prepared, metric = _metric_column(screen, factor, definitions)
        if "ISIN" in prepared.columns:
            prepared = prepared.set_index("ISIN", drop=True)
        kwargs = {
            "screen": prepared,
            "returns": returns,
            "bench": benchmark,
            "percentile": percentile,
            "metrics": metric,
            "ptf_name": ptf_name or f"FR_{normalize_region(region)}_{factor}",
            "Top": bool(top),
            "copy_inputs": True,
        }
        kwargs.update(official_kwargs)
        engine = self.factory(**kwargs)
        if screen_date is not None:
            date = pd.Timestamp(screen_date)
            monthly = prepared.loc[
                pd.to_datetime(prepared[DATE_COLUMN], errors="coerce").eq(date)
            ].copy()
            if monthly.empty:
                raise ValueError(f"no screen rows for official screen_date={date.date()}")
            security_list, exclusions = engine.build_monthly_security_list(
                screen_agg_monthly=monthly
            )
            nav, weights = engine.run_portfolio_nav(sec_list=security_list)
            run_metadata = {
                "mode": "monthly",
                "screen_date": date.isoformat(),
                "exclusion_rows": int(len(exclusions)) if hasattr(exclusions, "__len__") else None,
            }
        else:
            if start_date is None:
                start_date = pd.to_datetime(prepared[DATE_COLUMN], errors="coerce").min()
            engine.build_historical_security_lists(
                start_date=pd.Timestamp(start_date).to_pydatetime(),
                screen_start_date=None,
                fill_method="copy",
            )
            nav, weights = engine.run_portfolio_nav(sec_list=engine.sec_list_historical)
            run_metadata = {
                "mode": "historical",
                "start_date": pd.Timestamp(start_date).isoformat(),
            }
        return OfficialSleeveResult(
            region=normalize_region(region),
            factor=factor,
            benchmark=benchmark,
            nav=nav,
            weights=weights,
            component=component,
            adapter_id=self.adapter_id,
            metadata=run_metadata,
        )


def _component_screen(
    screen: pd.DataFrame,
    region: str,
    component: str,
    universe_definitions: Mapping[str, RegionUniverse] | None,
) -> pd.DataFrame:
    selection = select_universe(screen, region, definitions=universe_definitions)
    return selection.frame.loc[selection.frame["universe_component"].eq(component)].copy()


def run_official_sleeve(
    *,
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    region: str | Region,
    factor: str,
    top: bool = True,
    percentile: float = 0.2,
    screen_date: pd.Timestamp | str | None = None,
    start_date: pd.Timestamp | str | None = None,
    adapter: OfficialSleeveAdapter | None = None,
    definitions: tuple[FactorDefinition, ...] | None = None,
    universe_definitions: Mapping[str, RegionUniverse] | None = None,
    **official_kwargs: Any,
) -> OfficialSleeveResult:
    """运行单一官方区域或 ASIA 的两个官方组件。"""

    region_name = normalize_region(region)
    regions = dict(universe_definitions or load_region_universes())
    if region_name not in regions:
        raise KeyError(f"unknown region: {region_name}")
    spec = regions[region_name]
    adapter = adapter or OfficialSleeveAdapter()
    definitions = definitions or load_factor_definitions()
    if not spec.research_only:
        component = spec.components[0]
        return adapter.run(
            screen=screen,
            returns=returns,
            benchmark=component.benchmark,
            factor=factor,
            region=region_name,
            component=component.name,
            top=top,
            percentile=percentile,
            start_date=start_date,
            screen_date=screen_date,
            definitions=definitions,
            **official_kwargs,
        )
    if spec.benchmark_approved:
        raise ValueError("research-only aggregate cannot be benchmark approved")
    component_results: list[OfficialSleeveResult] = []
    for component in spec.components:
        component_frame = _component_screen(
            screen, region_name, component.name, universe_definitions
        )
        if component_frame.empty:
            raise ValueError(f"ASIA component {component.name} has no eligible rows")
        if "ISIN" in component_frame.columns:
            component_frame = component_frame.set_index("ISIN", drop=True)
        component_results.append(
            adapter.run(
                screen=component_frame,
                returns=returns,
                benchmark=component.benchmark,
                factor=factor,
                region=region_name,
                component=component.name,
                top=top,
                percentile=percentile,
                start_date=start_date,
                screen_date=screen_date,
                definitions=definitions,
                **official_kwargs,
            )
        )
    return OfficialSleeveResult(
        region=region_name,
        factor=factor,
        benchmark=None,
        component=None,
        research_only=True,
        benchmark_approved=False,
        adapter_id=adapter.adapter_id,
        metadata={
            "aggregation": "research_only_component_results",
            "component_names": [result.component for result in component_results],
            "aggregate_nav": None,
        },
        component_results=tuple(component_results),
    )


__all__ = ["OfficialSleeveAdapter", "OfficialSleeveResult", "run_official_sleeve"]

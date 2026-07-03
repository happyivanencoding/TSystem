"""Compatibility wrapper for dash-mantine-components.

The app is written for dash-mantine-components 0.14, while some local
Anaconda environments still provide 0.12. This module keeps smoke imports and
local startup usable by mapping common 0.14 component names/props to 0.12.
"""
from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

import dash_mantine_components as _dmc
from dash import html


_ALIASES: dict[str, Callable[..., Any] | str] = {
    "AppShellHeader": html.Header,
    "AppShellMain": html.Main,
    "Box": html.Div,
    "GridCol": "Col",
}

_RENAMED_PROPS = {
    "gap": "spacing",
    "justify": "position",
}

_DISCARDED_PROPS = {
    "forceColorScheme",
    "hiddenFrom",
    "transitionDuration",
    "transitionTimingFunction",
    "visibleFrom",
    "withBorder",
    "withOverlay",
}

_PROBE_KWARGS = {
    "AccordionItem": {"value": "probe"},
    "Anchor": {"href": "#"},
    "AppShell": {"children": []},
    "Pagination": {"total": 1},
    "SegmentedControl": {"data": []},
}


@lru_cache(maxsize=None)
def _allowed_props(name: str) -> set[str]:
    component = _resolve_component(name)
    if component is None:
        return set()
    try:
        instance = component(**_PROBE_KWARGS.get(name, {}))
    except TypeError:
        return set()
    return set(getattr(instance, "_prop_names", []) or [])


def _resolve_component(name: str) -> Callable[..., Any] | None:
    target = _ALIASES.get(name, name)
    if isinstance(target, str):
        return getattr(_dmc, target, None)
    if callable(target):
        return target
    return getattr(_dmc, name, None)


def _coerce_kwargs(name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    allowed = _allowed_props(name)
    coerced = dict(kwargs)

    for old_name, new_name in _RENAMED_PROPS.items():
        if old_name in coerced and new_name not in coerced:
            coerced[new_name] = coerced.pop(old_name)

    for prop in _DISCARDED_PROPS:
        coerced.pop(prop, None)

    if "wrap" in coerced:
        coerced.pop("wrap")

    if allowed:
        coerced = {key: value for key, value in coerced.items() if key in allowed}

    return coerced


def __getattr__(name: str) -> Any:
    component = _resolve_component(name)
    if component is None:
        return getattr(_dmc, name)

    def factory(*args: Any, **kwargs: Any) -> Any:
        return component(*args, **_coerce_kwargs(name, kwargs))

    factory.__name__ = name
    return factory


def __dir__() -> list[str]:
    return sorted(set(dir(_dmc)) | set(_ALIASES))

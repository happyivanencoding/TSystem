"""Cache LRU en mémoire pour figures Plotly (tiroirs Composition / ICB)."""
from __future__ import annotations

from collections import OrderedDict

import plotly.graph_objects as go

_MAX_KEYS: int = 12


class PlotlyFigureLRU:
    """Stocke des ``figure`` sérialisées (dict) avec éviction FIFO."""

    def __init__(self, max_keys: int = _MAX_KEYS) -> None:
        self._max = max_keys
        self._data: OrderedDict[str, dict] = OrderedDict()

    def get(self, key: str) -> dict | None:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def set(self, key: str, fig: go.Figure) -> None:
        payload = fig.to_plotly_json()
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = payload
        while len(self._data) > self._max:
            self._data.popitem(last=False)


_ptf_cache = PlotlyFigureLRU()
_ind_cache = PlotlyFigureLRU()

# Figure + titre (graphique métrique)
_ptf_metric_bundle: OrderedDict[str, tuple[dict, str]] = OrderedDict()
_ind_metric_bundle: OrderedDict[str, tuple[dict, str]] = OrderedDict()
_MAX_BUNDLE = _MAX_KEYS


def _bundle_get(d: OrderedDict[str, tuple[dict, str]], key: str) -> tuple[dict, str] | None:
    if key not in d:
        return None
    d.move_to_end(key)
    return d[key]


def _bundle_set(d: OrderedDict[str, tuple[dict, str]], key: str, fig: go.Figure, title: str) -> None:
    d[key] = (fig.to_plotly_json(), title)
    d.move_to_end(key)
    while len(d) > _MAX_BUNDLE:
        d.popitem(last=False)


def ptf_factor_cache_key(isin: str, bench: str) -> str:
    return f"f|{isin}|{bench}"


def ptf_metric_cache_key(isin: str, bench: str, metric: str | None) -> str:
    return f"m|{isin}|{bench}|{metric or ''}"


def ind_factor_cache_key(isin: str, bench: str, sector: str) -> str:
    return f"f|{isin}|{bench}|{sector}"


def ind_metric_cache_key(isin: str, bench: str, sector: str, metric: str | None) -> str:
    return f"m|{isin}|{bench}|{sector}|{metric or ''}"


def get_ptf_factor_dict(key: str) -> dict | None:
    return _ptf_cache.get(key)


def set_ptf_factor(key: str, fig: go.Figure) -> None:
    _ptf_cache.set(key, fig)


def get_ptf_metric_bundle(key: str) -> tuple[dict, str] | None:
    return _bundle_get(_ptf_metric_bundle, key)


def set_ptf_metric_bundle(key: str, fig: go.Figure, title: str) -> None:
    _bundle_set(_ptf_metric_bundle, key, fig, title)


def get_ind_factor_dict(key: str) -> dict | None:
    return _ind_cache.get(key)


def set_ind_factor(key: str, fig: go.Figure) -> None:
    _ind_cache.set(key, fig)


def get_ind_metric_bundle(key: str) -> tuple[dict, str] | None:
    return _bundle_get(_ind_metric_bundle, key)


def set_ind_metric_bundle(key: str, fig: go.Figure, title: str) -> None:
    _bundle_set(_ind_metric_bundle, key, fig, title)

"""Filter panel shown on the home page (country / sector / search)."""
from __future__ import annotations

from typing import Iterable

from src.ui import dmc_compat as dmc
from dash import html


def render_filter_panel(countries: Iterable[str], sectors: Iterable[str]) -> html.Div:
    return html.Div(
        className="filter-panel",
        children=dmc.Stack(
            gap="md",
            children=[
                dmc.Text("Filtres", fw=700, size="md", c="#111827"),
                dmc.TextInput(
                    id="filter-query",
                    label="Recherche",
                    placeholder="Nom ou ISIN…",
                    leftSection=None,
                    size="sm",
                ),
                dmc.MultiSelect(
                    id="filter-countries",
                    label="Pays",
                    placeholder="Tous les pays",
                    data=[{"value": c, "label": c.title()} for c in countries],
                    searchable=True,
                    clearable=True,
                    size="sm",
                    maxDropdownHeight=280,
                ),
                dmc.MultiSelect(
                    id="filter-sectors",
                    label="Secteur",
                    placeholder="Tous les secteurs",
                    data=[{"value": s, "label": s} for s in sectors],
                    searchable=True,
                    clearable=True,
                    size="sm",
                    maxDropdownHeight=280,
                ),
                dmc.Button(
                    "Réinitialiser",
                    id="filter-reset",
                    variant="subtle",
                    color="gray",
                    size="sm",
                ),
                dmc.Divider(),
                dmc.Text(id="filter-count", size="xs", c="#6B7280"),
            ],
        ),
    )

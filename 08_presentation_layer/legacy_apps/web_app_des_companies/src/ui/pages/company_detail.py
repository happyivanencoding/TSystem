"""Company detail page: DES description + NEWS timeline for a single ISIN."""
from __future__ import annotations

import dash
from src.ui import dmc_compat as dmc
from dash import html
from src.ui.icon import DashIconify

from src.data.repository import get_repository
from src.ui.components.description_panel import render_description_panel
from src.ui.components.news_timeline import render_news_timeline

dash.register_page(__name__, path_template="/company/<isin>", name="Entreprise")


def _not_found(isin: str) -> html.Div:
    return html.Div(
        dmc.Paper(
            withBorder=True,
            radius="md",
            p="xl",
            children=dmc.Stack(
                align="center",
                gap="sm",
                children=[
                    dmc.Text("Entreprise introuvable", fw=600, size="lg"),
                    dmc.Text(
                        f"Aucune donnée pour l'ISIN « {isin} ».",
                        c="#6B7280",
                        size="sm",
                    ),
                    dmc.Anchor("Retour au catalogue", href="/", size="sm"),
                ],
            ),
        )
    )


def layout(isin: str | None = None, **_kwargs) -> html.Div:
    repo = get_repository()

    if not isin:
        return _not_found("")

    identity = repo.get_identity(isin)
    if identity is None:
        return _not_found(isin)

    description_row = repo.get_description(isin)
    news_df = repo.get_news(isin)

    header = dmc.Paper(
        withBorder=True,
        radius="md",
        p="xl",
        children=[
            dmc.Anchor(
                dmc.Group(
                    gap=4,
                    children=[
                        DashIconify(icon="mdi:chevron-left", width=16),
                        dmc.Text("Catalogue", size="sm"),
                    ],
                ),
                href="/",
                underline=False,
                c="#1E40AF",
            ),
            dmc.Space(h=12),
            dmc.Group(
                justify="space-between",
                align="flex-start",
                children=[
                    dmc.Stack(
                        gap=4,
                        children=[
                            dmc.Text(identity.name, size="xl", fw=700, c="#111827"),
                            dmc.Text(
                                identity.isin,
                                size="sm",
                                c="#6B7280",
                                style={"fontFamily": "monospace"},
                            ),
                        ],
                    ),
                    dmc.Group(
                        gap="xs",
                        children=[
                            dmc.Badge(
                                identity.country.title() if identity.country else "—",
                                color="blue",
                                variant="light",
                                size="lg",
                            ),
                            dmc.Badge(
                                identity.sector or "—",
                                color="teal",
                                variant="light",
                                size="lg",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )

    return html.Div(
        className="page-company-detail",
        children=[
            header,
            dmc.Space(h=20),
            dmc.Grid(
                gutter="xl",
                children=[
                    dmc.GridCol(
                        span={"base": 12, "md": 9},
                        children=render_description_panel(description_row),
                    ),
                    dmc.GridCol(
                        span={"base": 12, "md": 3},
                        children=render_news_timeline(news_df),
                    ),
                ],
            ),
        ],
    )

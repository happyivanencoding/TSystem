"""Home page: company catalog with filters and paginated card grid."""
from __future__ import annotations

import dash
from presentation_layer.company_browser.ui import dmc_compat as dmc
from dash import dcc, html

from presentation_layer.company_browser.data.repository import get_repository
from presentation_layer.company_browser.ui.components.filter_panel import render_filter_panel

dash.register_page(__name__, path="/", name="Entreprises")


def layout() -> html.Div:
    repo = get_repository()
    return html.Div(
        className="page-entreprises",
        children=[
            dcc.Store(id="home-page-index", data=1),
            dmc.Space(h=28),
            dmc.Grid(
                gutter="xl",
                children=[
                    dmc.GridCol(
                        span={"base": 12, "md": 3},
                        children=render_filter_panel(
                            countries=repo.list_countries(),
                            sectors=repo.list_sectors(),
                        ),
                    ),
                    dmc.GridCol(
                        span={"base": 12, "md": 9},
                        children=[
                            dmc.Stack(
                                gap="xl",
                                children=[
                                    dmc.Group(
                                        justify="space-between",
                                        align="center",
                                        children=[
                                            dmc.Text(
                                                "Catalogue des entreprises",
                                                size="xl",
                                                fw=700,
                                                c="#111827",
                                            ),
                                            dmc.Text(
                                                id="home-result-summary",
                                                size="sm",
                                                c="#6B7280",
                                            ),
                                        ],
                                    ),
                                    html.Div(id="home-cards-grid"),
                                    dmc.Center(
                                        dmc.Pagination(
                                            id="home-pagination",
                                            total=1,
                                            value=1,
                                            siblings=1,
                                            withEdges=True,
                                        ),
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ]
    )

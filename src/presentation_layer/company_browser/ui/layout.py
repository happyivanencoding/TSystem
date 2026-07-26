"""Coquille de l’app : MantineProvider + AppShell (en-tête fixe, contenu principal, tiroir mobile)."""
from __future__ import annotations

import dash
from presentation_layer.company_browser.ui import dmc_compat as dmc
from dash import dcc, html

from presentation_layer.company_browser.ui.components.app_header import build_app_header_content
from presentation_layer.company_browser.ui.theme import MANTINE_THEME


def build_layout() -> dmc.MantineProvider:
    """Racine du layout, enveloppe MantineProvider (thème clair)."""
    header, mobile_drawer = build_app_header_content()
    return dmc.MantineProvider(
        theme=MANTINE_THEME,
        forceColorScheme="light",
        children=html.Div(
            className="app-root",
            children=[
                dcc.Location(id="_url", refresh=False),
                dcc.Store(id="_scroll_reset_sink", data=0),
                dcc.Store(id="app-nav-open-store", data=False),
                dcc.Store(id="app-nav-anim", data=0),
                dmc.AppShell(
                    header={"height": 80, "offset": False},
                    padding=0,
                    withBorder=True,
                    transitionDuration=220,
                    transitionTimingFunction="cubic-bezier(0.16, 1, 0.3, 1)",
                    zIndex=300,
                    className="app-shell-root",
                    children=[
                        header,
                        dmc.AppShellMain(
                            p=0,
                            className="app-shell-main-outer",
                            children=html.Div(
                                id="app-page-wrap",
                                className="app-main app-page-wrap app-page-flip-0",
                                children=[dash.page_container],
                            ),
                        ),
                    ],
                ),
                mobile_drawer,
            ],
        ),
    )

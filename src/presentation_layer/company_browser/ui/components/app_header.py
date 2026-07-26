"""En-tête fixe + navigation principale (AppShell Header) : pilule sur desktop, tiroir replié sur mobile."""
from __future__ import annotations

from presentation_layer.company_browser.ui import dmc_compat as dmc
from dash import html
from presentation_layer.company_browser.ui.icon import DashIconify

from presentation_layer.company_browser import settings


def build_app_header_content() -> tuple[dmc.AppShellHeader, dmc.Drawer]:
    """Contenu de l’en-tête + tiroir latéral partagé avec le burger, assemblé au niveau du layout."""
    brand = dmc.Anchor(
        href="/",
        underline=False,
        children=dmc.Group(
            gap="sm",
            align="center",
            wrap="nowrap",
            children=[
                DashIconify(
                    icon="mdi:chart-bubble",
                    width=26,
                    color="#1E40AF",
                ),
                dmc.Stack(
                    gap=0,
                    style={"minWidth": 0},
                    children=[
                        dmc.Text(
                            settings.APP_TITLE,
                            fw=700,
                            size="md",
                            c="#111827",
                            className="app-brand-title",
                        ),
                        dmc.Text(
                            settings.APP_SUBTITLE,
                            size="xs",
                            c="#6B7280",
                            className="app-brand-subtitle",
                        ),
                    ],
                ),
            ],
        ),
    )

    def _pill_item(nav_id: str, label: str, href: str) -> dmc.NavLink:
        return dmc.NavLink(
            id=nav_id,
            href=href,
            label=label,
            h=38,
            px="lg",
            className="app-nav-pill__link",
        )

    pill_desktop = dmc.Group(
        wrap="nowrap",
        gap=4,
        align="center",
        visibleFrom="sm",
        justify="center",
        className="app-nav-pill",
        grow=True,
        children=[
            _pill_item("app-nav-entreprises-d", "Entreprises", "/"),
            _pill_item("app-nav-indice-d", "Composition indice", "/indice"),
            _pill_item("app-nav-icb-d", "Analyse sectorielle ICB", "/analyse-icb"),
        ],
    )

    def _stack_item(nav_id: str, label: str, href: str) -> dmc.NavLink:
        return dmc.NavLink(
            id=nav_id,
            href=href,
            label=label,
            w="100%",
            className="app-nav-mobile__link",
        )

    mobile_burger = dmc.Box(
        hiddenFrom="sm",
        children=dmc.Burger(
            id="app-nav-burger",
            size="md",
            opened=False,
        ),
    )

    header = dmc.AppShellHeader(
        className="app-shell-header-bar",
        p=0,
        style={"minHeight": 80},
        children=dmc.Group(
            h=80,
            align="center",
            justify="space-between",
            wrap="nowrap",
            gap="md",
            px="md",
            w="100%",
            children=[brand, pill_desktop, dmc.Group(w=44, justify="end", children=[mobile_burger])],
        ),
    )

    drawer = dmc.Drawer(
        id="app-nav-drawer",
        position="right",
        size="md",
        title="Navigation",
        padding="md",
        withOverlay=True,
        withCloseButton=True,
        closeOnClickOutside=True,
        zIndex=400,
        opened=False,
        trapFocus=True,
        children=dmc.Stack(
            gap="xs",
            children=[
                dmc.Divider(label="Vues", labelPosition="left"),
                _stack_item("app-nav-entreprises-m", "Entreprises", "/"),
                _stack_item("app-nav-indice-m", "Composition indice", "/indice"),
                _stack_item("app-nav-icb-m", "Analyse sectorielle ICB", "/analyse-icb"),
            ],
        ),
    )

    return header, drawer

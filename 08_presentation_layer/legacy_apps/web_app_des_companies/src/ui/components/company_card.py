"""Single company card used in the home page grid."""
from __future__ import annotations

from src.ui import dmc_compat as dmc
from dash import html

from config import settings
from src.services.text import summarize_markdown


def render_company_card(
    isin: str,
    name: str,
    country: str,
    sector: str,
    description_markdown: str | None,
) -> html.A:
    """Return a clickable card linking to the company detail page."""
    preview = summarize_markdown(description_markdown, settings.CARD_SUMMARY_CHARS)

    return html.A(
        href=f"/company/{isin}",
        className="card-link",
        children=dmc.Card(
            className="company-card",
            padding="lg",
            radius="md",
            withBorder=False,
            children=[
                dmc.Stack(
                    gap="xs",
                    children=[
                        dmc.Group(
                            justify="space-between",
                            align="flex-start",
                            children=[
                                dmc.Text(
                                    name or "—",
                                    fw=600,
                                    size="md",
                                    c="#111827",
                                    lineClamp=2,
                                ),
                                dmc.Badge(
                                    country.title() if country else "—",
                                    color="blue",
                                    variant="light",
                                    radius="sm",
                                    size="sm",
                                ),
                            ],
                        ),
                        dmc.Text(
                            isin,
                            size="xs",
                            c="#6B7280",
                            style={"fontFamily": "monospace"},
                        ),
                        dmc.Badge(
                            sector or "—",
                            color="teal",
                            variant="light",
                            radius="sm",
                            size="xs",
                            style={"alignSelf": "flex-start"},
                        ),
                        dmc.Text(
                            preview,
                            size="sm",
                            c="#374151",
                            style={"marginTop": "6px"},
                            lineClamp=4,
                        ),
                    ],
                ),
            ],
        ),
    )

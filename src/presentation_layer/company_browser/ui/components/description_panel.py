"""Description panel rendered on the company detail page."""
from __future__ import annotations

from presentation_layer.company_browser.ui import dmc_compat as dmc
import pandas as pd
from dash import dcc, html

from presentation_layer.company_browser.data.schemas import COL_BODY, COL_DATE
from presentation_layer.company_browser.services.markdown_format import format_markdown_body


def render_description_panel(row: pd.Series | None) -> dmc.Paper:
    """Render the DES panel or a placeholder when no description is available."""
    if row is None:
        return dmc.Paper(
            withBorder=True,
            radius="md",
            p="xl",
            children=dmc.Text(
                "Aucune description disponible pour cette entreprise.",
                c="#6B7280",
            ),
        )

    body = format_markdown_body(row.get(COL_BODY) or "")
    date = row.get(COL_DATE)
    date_str = pd.to_datetime(date).strftime("%d %B %Y") if pd.notna(date) else ""

    return dmc.Paper(
        withBorder=True,
        radius="md",
        p="xl",
        children=[
            dmc.Group(
                justify="space-between",
                align="center",
                children=[
                    dmc.Text("Description", className="section-heading"),
                    dmc.Text(date_str, size="xs", c="#6B7280"),
                ],
            ),
            dmc.Space(h=8),
            # Native overflow (reliable); Mantine ScrollArea + maxHeight alone often clips without scroll.
            html.Div(
                className="markdown-scroll-region markdown-scroll-region--des",
                children=html.Div(
                    className="markdown-prose",
                    children=dcc.Markdown(
                        body,
                        className="markdown-body",
                        dangerously_allow_html=True,
                    ),
                ),
            ),
        ],
    )

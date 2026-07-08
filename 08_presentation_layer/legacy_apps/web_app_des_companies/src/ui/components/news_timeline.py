"""News timeline panel shown on the company detail page."""
from __future__ import annotations

from src.ui import dmc_compat as dmc
import pandas as pd
from dash import dcc, html

from src.data.schemas import COL_BODY, COL_DATE, COL_TITLE
from src.services.markdown_format import format_markdown_body


def _format_title(raw: str | None, date: pd.Timestamp | None) -> str:
    """Fallback title if data is missing."""
    if raw:
        return str(raw)
    if date is not None and pd.notna(date):
        return date.strftime("%d %B %Y")
    return "Actualité"


def render_news_timeline(news_df: pd.DataFrame) -> dmc.Paper:
    if news_df is None or news_df.empty:
        return dmc.Paper(
            withBorder=True,
            radius="md",
            p="xl",
            children=[
                dmc.Text("Actualités", className="section-heading"),
                dmc.Space(h=8),
                dmc.Text(
                    "Aucune actualité disponible sur les 3 derniers mois.",
                    c="#6B7280",
                ),
            ],
        )

    items = []
    for _, row in news_df.iterrows():
        date = row.get(COL_DATE)
        date_str = pd.to_datetime(date).strftime("%d %b %Y") if pd.notna(date) else ""
        title = _format_title(row.get(COL_TITLE), date)
        body = format_markdown_body(row.get(COL_BODY) or "")

        items.append(
            html.Div(
                className="news-item",
                children=[
                    html.Div(date_str, className="news-date"),
                    html.Div(title, className="news-title"),
                    dmc.Accordion(
                        variant="separated",
                        radius="sm",
                        chevronPosition="right",
                        children=dmc.AccordionItem(
                            value=f"news-{row.name}",
                            children=[
                                dmc.AccordionControl(
                                    dmc.Text("Lire l'analyse", size="sm", c="#1E40AF"),
                                ),
                                dmc.AccordionPanel(
                                    html.Div(
                                        className="markdown-scroll-region markdown-scroll-region--news",
                                        children=html.Div(
                                            className="markdown-prose",
                                            children=dcc.Markdown(
                                                body,
                                                className="markdown-body",
                                                dangerously_allow_html=True,
                                            ),
                                        ),
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            )
        )

    return dmc.Paper(
        withBorder=True,
        radius="md",
        p="xl",
        children=[
            dmc.Group(
                justify="space-between",
                align="center",
                children=[
                    dmc.Text("Actualités (3 mois)", className="section-heading"),
                    dmc.Badge(
                        f"{len(news_df)} analyses",
                        color="blue",
                        variant="light",
                        size="sm",
                    ),
                ],
            ),
            dmc.Space(h=12),
            html.Div(items),
        ],
    )

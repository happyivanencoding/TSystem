"""Callbacks for the home page: filters -> cards grid + pagination."""
from __future__ import annotations

from presentation_layer.company_browser.ui import dmc_compat as dmc
import pandas as pd
from dash import Input, Output, State, callback, ctx, html, no_update

from presentation_layer.company_browser import settings
from presentation_layer.company_browser.data.repository import get_repository
from presentation_layer.company_browser.data.schemas import (
    COL_BODY,
    COL_COUNTRY,
    COL_ISIN,
    COL_NAME,
    COL_SECTOR,
)
from presentation_layer.company_browser.services.filters import apply_filters, paginate, total_pages
from presentation_layer.company_browser.ui.components.company_card import render_company_card


def _enrich_with_latest_description(catalog: pd.DataFrame) -> pd.DataFrame:
    """Joint le catalogue avec le dernier DES (précalculé dans CompanyRepository)."""
    return catalog.merge(
        get_repository().latest_des_preview(), on=COL_ISIN, how="left"
    )


@callback(
    Output("home-cards-grid", "children"),
    Output("home-pagination", "total"),
    Output("home-pagination", "value"),
    Output("home-result-summary", "children"),
    Output("filter-count", "children"),
    Input("filter-query", "value"),
    Input("filter-countries", "value"),
    Input("filter-sectors", "value"),
    Input("home-pagination", "value"),
    Input("filter-reset", "n_clicks"),
    State("home-pagination", "value"),
    prevent_initial_call=False,
)
def update_grid(query, countries, sectors, page_value, _reset_clicks, _current_page):
    repo = get_repository()
    catalog = repo.companies_df()

    # When a filter input changes, reset pagination to page 1.
    triggered = ctx.triggered_id
    if triggered in {"filter-query", "filter-countries", "filter-sectors", "filter-reset"}:
        page = 1
    else:
        page = page_value or 1

    if triggered == "filter-reset":
        query, countries, sectors = None, None, None

    filtered = apply_filters(
        catalog,
        countries=countries or None,
        sectors=sectors or None,
        query=query,
    )

    total_items = len(filtered)
    pages = total_pages(total_items, settings.CARDS_PER_PAGE)
    page = min(page, pages)

    page_df = paginate(filtered, page=page, page_size=settings.CARDS_PER_PAGE)
    page_df = _enrich_with_latest_description(page_df)

    if page_df.empty:
        cards_children = dmc.Paper(
            withBorder=True,
            radius="md",
            p="xl",
            children=dmc.Text(
                "Aucune entreprise ne correspond à ces filtres.",
                c="#6B7280",
            ),
        )
    else:
        cards = [
            dmc.GridCol(
                span={"base": 12, "sm": 6, "lg": 4},
                children=render_company_card(
                    isin=row[COL_ISIN],
                    name=row[COL_NAME],
                    country=row[COL_COUNTRY],
                    sector=row[COL_SECTOR],
                    description_markdown=row.get(COL_BODY),
                ),
            )
            for _, row in page_df.iterrows()
        ]
        cards_children = dmc.Grid(gutter="md", children=cards)

    summary = f"{total_items} entreprises • page {page} / {pages}"
    filter_count = f"{total_items} résultat(s)"
    return cards_children, pages, page, summary, filter_count


@callback(
    Output("filter-query", "value"),
    Output("filter-countries", "value"),
    Output("filter-sectors", "value"),
    Input("filter-reset", "n_clicks"),
    prevent_initial_call=True,
)
def reset_filters(_n_clicks):
    """Clear all filter inputs when the reset button is clicked."""
    return "", [], []

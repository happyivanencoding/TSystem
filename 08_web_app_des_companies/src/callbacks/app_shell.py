"""Actif de la nav principale, tiroir mobile, transition entre vues du contenu principal."""
from __future__ import annotations

from dash import Input, Output, State, callback
from dash.exceptions import PreventUpdate


@callback(
    Output("app-nav-entreprises-d", "active"),
    Output("app-nav-indice-d", "active"),
    Output("app-nav-icb-d", "active"),
    Output("app-nav-entreprises-m", "active"),
    Output("app-nav-indice-m", "active"),
    Output("app-nav-icb-m", "active"),
    Input("_url", "pathname"),
)
def _set_main_nav_active(pathname: str | None) -> tuple:
    p = (pathname or "/").strip() or "/"
    entreprises = p == "/" or p.startswith("/company")
    indice = p == "/indice" or p.startswith("/indice/")
    icb = p == "/analyse-icb" or p.startswith("/analyse-icb/")
    return (entreprises, indice, icb, entreprises, indice, icb)


@callback(
    Output("app-nav-open-store", "data"),
    Input("app-nav-burger", "n_clicks"),
    State("app-nav-open-store", "data"),
    prevent_initial_call=True,
)
def _toggle_burger(n_clicks, open_):
    if not n_clicks:
        raise PreventUpdate
    return not bool(open_)


@callback(
    Output("app-nav-open-store", "data", allow_duplicate=True),
    Input("_url", "pathname"),
    State("app-nav-open-store", "data"),
    prevent_initial_call=True,
)
def _close_drawer_on_nav(_pathname, open_):
    if open_:
        return False
    raise PreventUpdate


# Clic sur fond / fermer : certains environnements renvoient opened du Drawer ; aligner le Store
@callback(
    Output("app-nav-open-store", "data", allow_duplicate=True),
    Input("app-nav-drawer", "opened"),
    State("app-nav-open-store", "data"),
    prevent_initial_call=True,
)
def _store_follow_drawer_opened(opened, st):
    if opened is None:
        raise PreventUpdate
    b_open = bool(opened)
    if b_open is bool(st):
        raise PreventUpdate
    return b_open


@callback(
    Output("app-nav-drawer", "opened"),
    Output("app-nav-burger", "opened"),
    Input("app-nav-open-store", "data"),
)
def _sync_drawer_burger_menu(open_):
    o = bool(open_)
    return o, o


@callback(
    Output("app-page-wrap", "className"),
    Output("app-nav-anim", "data"),
    Input("_url", "pathname"),
    State("app-nav-anim", "data"),
    prevent_initial_call=True,
)
def _page_enter_flip(_pathname, flip):
    f = 0 if flip is None else int(flip) % 2
    nxt = 1 - f
    return f"app-main app-page-wrap app-page-flip-{nxt}", nxt

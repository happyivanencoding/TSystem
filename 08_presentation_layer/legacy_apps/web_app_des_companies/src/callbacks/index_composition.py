"""Callbacks page PTF / bench (remplace l’ancien mode indice+metric)."""
from __future__ import annotations

from collections import OrderedDict

import plotly.graph_objects as go
import pandas as pd
from dash import Input, Output, State, callback, clientside_callback, dcc, html, no_update, callback_context
from src.ui import dmc_compat as dmc

from config.settings import (
    FACTOR_TRACES,
    MULTIFACTOR_BASE_COLUMNS,
    PTF_DEFAULT_DATE_MODE,
)
from src.data.index_screen_repository import get_index_screen_repository
from src.data.ptf_column_groups import (
    FACTOR_SCORE_COLUMNS,
    filter_groups_for_ciq,
)
from src.data.schemas_ciq import (
    CIQ_COL_DATE,
    CIQ_COL_ICB_SUPERSECTOR,
    CIQ_COL_ISIN,
    CIQ_COL_NAME,
    WEIGHT_IN_PREFIX,
)
from src.data.ptf_repository import get_ptf_repository
from src.data.schemas_ptf import PTF_COL_ISIN, PTF_COL_WEIGHT
from src.services.ptf_table import merge_ptf_ciq
from src.services.peer_fan import peer_fan_timeseries
from src.data.repository import get_repository
from src.ui.components.description_panel import render_description_panel
from src.ui.components.news_timeline import render_news_timeline
from src.services.drawer_figure_cache import (
    get_ptf_factor_dict,
    set_ptf_factor,
)

_GRAY = "rgba(120,120,120,0.2)"
_ACCENT = "#0F766E"
_BLUE = "#1E40AF"

# Libellés produit -> colonnes CIQ（config.FACTOR_TRACES）；Value = Dividend Avg Percentile
_FACTOR_TRACE_SPEC = FACTOR_TRACES
_COL_MULTIFACTOR = "Multi Avg Percentile"
_BASE_COLS_SYNTH_MULTIFACTOR = MULTIFACTOR_BASE_COLUMNS
_FACTOR_TRACE_COLORS: tuple[str, ...] = (
    "#0F766E",
    "#1D4ED8",
    "#C026D3",
    "#D97706",
    "#DC2626",
    "#4F46E5",
    "#059669",
)

_MAX_PTF_DETAIL = 20
_ptf_detail_cache: OrderedDict[str, tuple] = OrderedDict()


def _ptf_detail_cache_get(isin: str) -> tuple | None:
    if isin not in _ptf_detail_cache:
        return None
    _ptf_detail_cache.move_to_end(isin)
    return _ptf_detail_cache[isin]


def _ptf_detail_cache_set(isin: str, desc, news_df) -> None:
    news_c = news_df.copy() if hasattr(news_df, "copy") else news_df
    _ptf_detail_cache[isin] = (desc, news_c)
    while len(_ptf_detail_cache) > _MAX_PTF_DETAIL:
        _ptf_detail_cache.popitem(last=False)


def _synthetic_multifactor_at_row(row: pd.Series) -> float:
    """Moyenne des 5 bases (ML exclu) ; MOM ramené à l’échelle ~0–10 comme sur le tracé."""
    vals: list[float] = []
    for c in _BASE_COLS_SYNTH_MULTIFACTOR:
        if c not in row.index:
            continue
        v = row[c]
        if v is not None and not (isinstance(v, float) and pd.isna(v)):
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if c == "MOM Score":
                fv = fv / 10.0
            vals.append(fv)
    # Au moins 2 bases : avec l’ancien seuil à 3, beaucoup de dates CIQ restaient NaN → pas de trace MultiFactor.
    if len(vals) < 2:
        return float("nan")
    return sum(vals) / len(vals)


def build_company_factor_history_figure(H: pd.DataFrame, isin: str) -> go.Figure:
    """Une seule figure : historique facteurs de la société (sans peers). ``H`` = historique bench."""
    fig = go.Figure()
    if H.empty or not isin:
        fig.update_layout(title="Aucune donnée", height=240, template="plotly_white")
        return fig
    sub = H.loc[H[CIQ_COL_ISIN].astype(str).str.strip() == str(isin).strip()].copy()
    if sub.empty:
        fig.update_layout(
            title="Historique des facteurs",
            annotations=[
                dict(
                    text="ISIN absent de l'historique bench",
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                )
            ],
            height=320,
            template="plotly_white",
        )
        return fig
    sub[CIQ_COL_DATE] = pd.to_datetime(sub[CIQ_COL_DATE], errors="coerce")
    sub = sub.dropna(subset=[CIQ_COL_DATE])
    need_cols = {
        c
        for _, c in _FACTOR_TRACE_SPEC
    } | {_COL_MULTIFACTOR}
    need_cols = {c for c in need_cols if c in sub.columns}
    if not need_cols:
        fig.update_layout(
            title="Historique des facteurs",
            annotations=[
                dict(
                    text="Aucune colonne facteur dans les données",
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                )
            ],
            height=320,
            template="plotly_white",
        )
        return fig
    agg = sub.groupby(CIQ_COL_DATE, sort=True)[sorted(need_cols)].mean()
    color_i = 0
    for label, col in _FACTOR_TRACE_SPEC:
        if col not in agg.columns:
            continue
        ser = agg[col].dropna()
        if ser.empty:
            continue
        color = _FACTOR_TRACE_COLORS[color_i % len(_FACTOR_TRACE_COLORS)]
        color_i += 1
        # Affichage seul : MOM Score source ~0–100 → tracé ~0–10 (données agrégées inchangées ailleurs).
        y_plot = (ser / 10.0).values if label == "Momentum" else ser.values
        fig.add_trace(
            go.Scattergl(
                x=ser.index,
                y=y_plot,
                mode="lines",
                name=label,
                line={"color": color, "width": 2},
            )
        )
    mf_added = False
    if _COL_MULTIFACTOR in agg.columns:
        ser_m = agg[_COL_MULTIFACTOR].dropna()
        if not ser_m.empty:
            color = _FACTOR_TRACE_COLORS[color_i % len(_FACTOR_TRACE_COLORS)]
            color_i += 1
            fig.add_trace(
                go.Scattergl(
                    x=ser_m.index,
                    y=ser_m.values,
                    mode="lines",
                    name="MultiFactor",
                    line={"color": color, "width": 2.5},
                )
            )
            mf_added = True
    if not mf_added:
        synth = agg.apply(_synthetic_multifactor_at_row, axis=1).dropna()
        if not synth.empty:
            color = _FACTOR_TRACE_COLORS[color_i % len(_FACTOR_TRACE_COLORS)]
            color_i += 1
            fig.add_trace(
                go.Scattergl(
                    x=synth.index,
                    y=synth.values,
                    mode="lines",
                    name="MultiFactor",
                    line={"color": color, "width": 2.5},
                )
            )
    if not fig.data:
        fig.update_layout(title="Historique des facteurs", height=320, template="plotly_white")
        return fig
    fig.update_layout(
        title="Historique des facteurs",
        template="plotly_white",
        height=440,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=24, t=72, b=48),
        xaxis_title="Date",
        yaxis_title="Score",
    )
    fig.update_yaxes(tickformat=".2f", hoverformat=".2f")
    return fig


def build_peer_metric_figure(
    H: pd.DataFrame, isin: str, active_m: str | None
) -> tuple[go.Figure, str]:
    """Graphique métrique hors facteurs + titre affiché."""
    empty_m = go.Figure()
    mtitle = "Autre indicateur (cliquez une cellule hors facteurs dans le tableau)"
    if (
        active_m
        and active_m in H.columns
        and active_m not in FACTOR_SCORE_COLUMNS
        and active_m not in ("isin", "name", "ptf_w", CIQ_COL_ISIN, CIQ_COL_NAME)
    ):
        mtitle = f"Historique : {active_m}"
        figm = go.Figure()
        anc, peers, err = peer_fan_timeseries(H, isin, active_m)
        for _pid, ser in peers.items():
            figm.add_trace(
                go.Scattergl(
                    x=ser.index,
                    y=ser.values,
                    mode="lines",
                    line={"color": _GRAY, "width": 1},
                    showlegend=False,
                )
            )
        if anc is not None and len(anc) > 0:
            figm.add_trace(
                go.Scatter(
                    x=anc.index,
                    y=anc.values,
                    mode="lines+markers",
                    name=isin,
                    line={"color": _BLUE, "width": 2.2},
                )
            )
        if err:
            figm.update_layout(title=err, height=320)
        else:
            figm.update_layout(
                template="plotly_white",
                height=400,
                xaxis_title="Date",
                yaxis_title=active_m,
                margin=dict(l=50, r=20, t=20, b=40),
            )
            figm.update_yaxes(tickformat=".2f", hoverformat=".2f")
        return figm, mtitle
    figm = empty_m
    figm.update_layout(
        title="Sélectionnez une colonne (hors 7 facteurs) dans le tableau",
        height=200,
    )
    return figm, mtitle


_MAX_MM = 40
_mm_ptf_fig: OrderedDict[str, dict] = OrderedDict()
_mm_ind_fig: OrderedDict[str, dict] = OrderedDict()


def _mm_cache_get(d: OrderedDict[str, dict], key: str) -> dict | None:
    if key not in d:
        return None
    d.move_to_end(key)
    return d[key]


def _mm_cache_set(d: OrderedDict[str, dict], key: str, fig: go.Figure) -> None:
    d[key] = fig.to_plotly_json()
    d.move_to_end(key)
    while len(d) > _MAX_MM:
        d.popitem(last=False)


def _drawer_metric_col_ok(col: str, av: set[str], df: pd.DataFrame) -> bool:
    if not col or col not in av or col not in df.columns:
        return False
    if col in ("isin", "name", "ptf_w", CIQ_COL_ISIN, CIQ_COL_NAME):
        return False
    if _is_bench_weight_col(col):
        return False
    if col in FACTOR_SCORE_COLUMNS:
        return False
    if not pd.api.types.is_numeric_dtype(df[col]):
        return False
    return True


def build_drawer_metric_multiselect_data(av: set[str], df: pd.DataFrame) -> list[dict]:
    """Liste plate ``{value, label}`` — même contrat que les autres MultiSelect du projet.

    Le format imbriqué ``{group, items}`` n’est pas rendu correctement par dmc 0.14 / Mantine 7
    côté client (menu vide) ; le groupe est préfixé dans le libellé.
    """
    groups = filter_groups_for_ciq(av)
    out: list[dict] = []
    for g in groups:
        for lab, c in g.entries:
            if not _drawer_metric_col_ok(c, av, df):
                continue
            out.append({"value": c, "label": f"{g.label} — {lab}"})
    return out


def history_bench_sector_slice(H: pd.DataFrame, sector: str | None) -> pd.DataFrame:
    """ICB : restreint l’historique au super-secteur courant (comparaison gris)."""
    if H.empty or not sector:
        return H
    scol = CIQ_COL_ICB_SUPERSECTOR
    if scol not in H.columns:
        return H
    s = str(sector).strip()
    return H.loc[H[scol].astype(str).str.strip() == s].copy()


def _fmt(d: str | None) -> str:
    if d is None:
        return ""
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def _round2(v) -> float | None:
    """Valeur numérique : 2 décimales (affichage)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _weight_to_pct2(v) -> float | None:
    """Poids 0–1 → pourcentage numérique (×100), 2 décimales."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return round(float(v) * 100.0, 2)
    except (TypeError, ValueError):
        return None


def _is_bench_weight_col(cid: str) -> bool:
    return isinstance(cid, str) and cid.startswith(WEIGHT_IN_PREFIX)


def _format_dash_datatable_header_label(col_name: str) -> str:
    """Insère des coupures (espaces ou \\n) dans les libellés longs pour ~2 lignes d’en-tête (CSS)."""
    if len(col_name) <= 12:
        return col_name
    if " " in col_name or "_" in col_name:
        words = [w for w in col_name.replace("_", " ").split(" ") if w]
        if len(words) > 1:
            mid = len(words) // 2
            return " ".join(words[:mid]) + " \n" + " ".join(words[mid:])
        return col_name[:12] + " " + col_name[12:]
    return col_name[:12] + " " + col_name[12:]


@callback(
    Output("ptf-date", "data"),
    Output("ptf-date", "value"),
    Input("ptf-bench", "value"),
)
def _ptf_bench_dates(bench: str | None):
    if not bench:
        return [], None
    r = get_index_screen_repository()
    ds = r.available_dates_for_index(bench)
    data = [{"value": _fmt(x), "label": _fmt(x)} for x in ds]
    v = None
    if data:
        v = data[-1]["value"] if PTF_DEFAULT_DATE_MODE == "latest" else data[0]["value"]
    return data, v


@callback(
    Output("ptf-cols", "value", allow_duplicate=True),
    Input("ptf-add-group", "value"),
    State("ptf-cols", "value"),
    State("ptf-bench", "value"),
    prevent_initial_call=True,
)
def _ptf_append_group(grp: str | None, cur: list | None, bench: str | None):
    if not grp or cur is None:
        return no_update
    r = get_index_screen_repository()
    av = set(r.df.columns)
    groups = filter_groups_for_ciq(av)
    g = next((x for x in groups if x.id == grp), None)
    if not g:
        return no_update
    add = [c for _, c in g.entries if c in av]
    if bench and bench in av and bench not in add:
        pass
    nxt = list(dict.fromkeys([*cur, *add]))
    return nxt


@callback(
    Output("ptf-table", "data"),
    Output("ptf-table", "columns"),
    Input("ptf-name", "value"),
    Input("ptf-bench", "value"),
    Input("ptf-date", "value"),
    Input("ptf-cols", "value"),
)
def _ptf_table(ptf: str | None, bench: str | None, date: str | None, cols: list | None):
    if not ptf or not bench or not date or not cols:
        return [], []
    prepo = get_ptf_repository()
    idx = get_index_screen_repository()
    asof = pd.Timestamp(date)
    hold = prepo.holdings_asof(ptf, asof)
    if hold.empty:
        return [], []
    ciq = idx.df
    ciq_d = ciq[ciq[CIQ_COL_DATE] == asof]
    extra = [c for c in cols if c in ciq.columns]
    merged = merge_ptf_ciq(hold, ciq_d, extra, ciq_full=ciq)
    disp = ["isin", "name", "ptf_w"] + [c for c in extra if c not in ("isin", "name")]
    disp = [x for i, x in enumerate(disp) if x not in disp[:i]]
    for c in extra:
        if c not in merged.columns and c in idx.df.columns:
            pass
    rows = []
    for _, r in merged.iterrows():
        row: dict = {
            "isin": r.get("isin", ""),
            "name": r.get("name", "") if pd.notna(r.get("name")) else "",
            "ptf_w": _weight_to_pct2(r.get("ptf_w", None)),
        }
        for c in extra:
            v = r.get(c, None) if c in merged.columns else None
            if v is not None and pd.isna(v):
                v = None
            if _is_bench_weight_col(c):
                row[c] = _weight_to_pct2(v)
            else:
                row[c] = _round2(v) if v is not None else None
        rows.append(row)
    table_cols: list[dict] = [
        {"name": "ISIN", "id": "isin"},
        {"name": "Nom", "id": "name"},
        {
            "name": "Poids PTF (%)",
            "id": "ptf_w",
            "type": "numeric",
            "format": {"specifier": ",.2f"},
        },
    ]
    for c in extra:
        if c in ("isin", "name", "ptf_w"):
            continue
        col_def: dict = {
            "id": c,
            "type": "numeric",
            "format": {"specifier": ",.2f"},
        }
        col_name = f"{c} (%)" if _is_bench_weight_col(c) else c
        col_def["name"] = _format_dash_datatable_header_label(col_name)
        table_cols.append(col_def)
    return rows, table_cols


@callback(
    Output("ptf-desc-wrap", "children"),
    Output("ptf-news-wrap", "children"),
    Input("ptf-selected-isin", "data"),
)
def _ptf_detail_panel(isin: str | None):
    """Description + actualités (cache session Python par ISIN)."""
    if not isin:
        return (
            dmc.Text(
                "Cochez une ligne du tableau (sélection à gauche) pour charger description, actualités et graphiques.",
                c="#6B7280",
            ),
            dmc.Text("—", c="#6B7280"),
        )
    hit = _ptf_detail_cache_get(isin)
    if hit is None:
        repo = get_repository()
        desc = repo.get_description(isin)
        news = repo.get_news(isin)
        _ptf_detail_cache_set(isin, desc, news)
    else:
        desc, news = hit
    desc_c = (
        render_description_panel(desc) if desc is not None else dmc.Paper("—")
    )
    news_c = render_news_timeline(news)
    return desc_c, news_c


@callback(
    Output("ptf-graph-factors", "figure"),
    Input("ptf-selected-isin", "data"),
    Input("ptf-bench", "value"),
)
def _ptf_factor_graphs(isin: str | None, bench: str | None):
    empty = go.Figure()
    if not isin or not bench:
        return empty
    ridx = get_index_screen_repository()
    if bench not in ridx.df.columns:
        return empty
    key = f"sf3|{isin}|{bench}"
    hit = get_ptf_factor_dict(key)
    if hit is not None:
        return hit
    H = ridx.history_for_index(bench)
    if H.empty:
        return empty
    fig = build_company_factor_history_figure(H, isin)
    set_ptf_factor(key, fig)
    return fig


def _peer_metric_fig_ptf(isin: str, bench: str, col: str, H: pd.DataFrame) -> go.Figure:
    k = f"mm|ptf|{isin}|{bench}|{col}"
    hit = _mm_cache_get(_mm_ptf_fig, k)
    if hit is not None:
        return hit
    fig, _t = build_peer_metric_figure(H, isin, col)
    if fig.data:
        fig.update_layout(title=col)
    _mm_cache_set(_mm_ptf_fig, k, fig)
    return fig


@callback(
    Output("ptf-metric-charts-wrap", "children"),
    Input("ptf-selected-isin", "data"),
    Input("ptf-metric-multiselect", "value"),
    Input("ptf-bench", "value"),
)
def _ptf_metric_charts_wrap(isin: str | None, metrics: list | None, bench: str | None):
    if not isin or not bench or not metrics:
        return []
    ridx = get_index_screen_repository()
    if bench not in ridx.df.columns:
        return []
    H = ridx.history_for_index(bench)
    if H.empty:
        return []
    order = list(dict.fromkeys(str(m) for m in metrics if m))
    blocks: list = []
    for col in order:
        if col not in H.columns or col in FACTOR_SCORE_COLUMNS:
            continue
        fig = _peer_metric_fig_ptf(str(isin).strip(), bench, col, H)
        blocks.append(
            html.Div(
                dcc.Graph(figure=fig, config={"displaylogo": False}, style={"height": "380px"}),
                style={"marginBottom": "20px"},
            )
        )
    return blocks


def _row_index_for_isin(data: list | None, isin_s: str) -> list[int]:
    if not data or not isin_s:
        return []
    for i, r in enumerate(data):
        if r.get("isin") is not None and str(r.get("isin")).strip() == isin_s:
            return [i]
    return []


@callback(
    Output("ptf-selected-isin", "data"),
    Output("ptf-table", "selected_rows"),
    Input("ptf-table", "data"),
    Input("ptf-table", "active_cell"),
    State("ptf-selected-isin", "data"),
)
def _ptf_data_or_cell(
    data: list | None,
    cell: dict | None,
    cur_isin: str | None,
):
    """ISIN + ligne cochée ; clic cellule ne pilote plus les graphiques métriques."""
    if not callback_context.triggered:
        return no_update, no_update
    prop_id = callback_context.triggered[0]["prop_id"]

    if prop_id == "ptf-table.data":
        if not data:
            return None, []
        valid = {str(r.get("isin")) for r in data if r.get("isin")}
        if cur_isin and str(cur_isin).strip() in valid:
            isin_s = str(cur_isin).strip()
            return isin_s, _row_index_for_isin(data, isin_s)
        return None, []

    if not data:
        return no_update, no_update

    if prop_id == "ptf-table.active_cell" and cell:
        r = cell.get("row")
        if r is None or r >= len(data):
            return no_update, no_update
        row = data[r]
        isin = row.get("isin")
        if not isin:
            return no_update, no_update
        isin_s = str(isin).strip()
        return isin_s, [r]

    return no_update, no_update


@callback(
    Output("ptf-selected-isin", "data", allow_duplicate=True),
    Input("ptf-table", "selected_rows"),
    State("ptf-table", "data"),
    State("ptf-selected-isin", "data"),
    prevent_initial_call=True,
)
def _ptf_checkbox_row(
    selected_rows: list | None,
    data: list | None,
    cur_isin: str | None,
):
    """Coche ligne : changement d’ISIN uniquement (pas de métrique tableau)."""
    if not data or not selected_rows:
        return no_update
    r = int(selected_rows[0])
    if r < 0 or r >= len(data):
        return no_update
    isin = data[r].get("isin")
    if not isin:
        return no_update
    isin_s = str(isin).strip()
    if isin_s == str(cur_isin or "").strip():
        return no_update
    return isin_s


@callback(
    Output("ptf-drawer-open", "data"),
    # Pas d’Input sur ptf-selected-isin : restauration de session au retour d’onglet déclencherait à tort ; ouvrir seulement au clic tableau / boutons
    Input("ptf-table", "active_cell"),
    Input("ptf-table", "selected_rows"),
    Input("ptf-drawer-backdrop", "n_clicks"),
    Input("ptf-drawer-close", "n_clicks"),
    Input("ptf-drawer-reopen", "n_clicks"),
    State("ptf-table", "data"),
    State("ptf-selected-isin", "data"),
    prevent_initial_call=True,
)
def _ptf_drawer_open(
    cell,
    selected_rows,
    _nb,
    _nc,
    _nr,
    data,
    isin,
):
    if not callback_context.triggered:
        return no_update
    prop_id = str(callback_context.triggered[0]["prop_id"])
    if prop_id in ("ptf-drawer-backdrop.n_clicks", "ptf-drawer-close.n_clicks"):
        return False
    if prop_id == "ptf-drawer-reopen.n_clicks":
        return bool(isin)

    def _row_has_isin(r: int) -> bool:
        if not data or r < 0 or r >= len(data):
            return False
        return bool(data[r].get("isin"))

    if prop_id == "ptf-table.active_cell":
        if not cell or not isinstance(cell, dict):
            return no_update
        r = cell.get("row")
        if r is not None and isinstance(r, (int, float)) and _row_has_isin(int(r)):
            return True
        return no_update

    if prop_id == "ptf-table.selected_rows":
        # Remplissage de données seul sur selected_rows : souvent pas d’active_cell, ne pas ouvrir
        if not cell or not isinstance(cell, dict) or not data or not selected_rows:
            return no_update
        rsel = int(selected_rows[0])
        if int(cell.get("row", -1)) != rsel or not _row_has_isin(rsel):
            return no_update
        return True

    return no_update


@callback(
    Output("ptf-drawer-overlay", "className"),
    Input("ptf-drawer-open", "data"),
)
def _ptf_drawer_overlay_class(open_):
    base = "drawer-overlay"
    return f"{base} drawer-overlay--open" if open_ else base


@callback(
    Output("ptf-drawer-fab-wrap", "style"),
    Input("ptf-drawer-open", "data"),
    Input("ptf-selected-isin", "data"),
)
def _ptf_drawer_fab_style(open_, isin):
    show = bool(isin) and not open_
    return {"display": "block" if show else "none"}


@callback(
    Output("ptf-drawer-seg", "value"),
    Input("ptf-selected-isin", "data"),
    Input("ptf-drawer-reopen", "n_clicks"),
)
def _ptf_drawer_seg_reset(isin, _nr):
    """Réinitialise l’onglet ; pas d’Input sur la value du seg (évite cycle tab ↔ seg)."""
    return "Description"


def drawer_tab_key(seg_value: str | None) -> str:
    """Libellés du SegmentedControl drawer → clés panneau internes description|factors."""
    if seg_value == "Facteurs & indicateurs":
        return "factors"
    return "description"


@callback(
    Output("ptf-panel-description", "className"),
    Output("ptf-panel-factors", "className"),
    Input("ptf-drawer-seg", "value"),
)
def _ptf_drawer_panels(tab):
    t = drawer_tab_key(tab)

    def one(k: str) -> str:
        b = "drawer-tab-panel"
        return f"{b} drawer-tab-panel--active" if t == k else b

    return one("description"), one("factors")


@callback(
    Output("ptf-drawer-header", "children"),
    Input("ptf-selected-isin", "data"),
    State("ptf-table", "data"),
)
def _ptf_drawer_header(isin, data):
    if not isin:
        return dmc.Text("—", size="sm", c="dimmed")
    name = str(isin)
    if data:
        for r in data:
            if str(r.get("isin", "")).strip() == str(isin).strip():
                nm = r.get("name")
                if nm:
                    name = str(nm)
                break
    return dmc.Stack(
        gap=4,
        children=[
            dmc.Text(name, fw=700, size="lg", lineClamp=3),
            dmc.Text(str(isin), size="xs", c="dimmed", ff="monospace"),
        ],
    )


# Tiroir ouvert : bloquer le scroll du body ; fermé : rétablir (changement de page : scroll_lock réinitialise)
clientside_callback(
    """
    function(open) {
        document.body.style.overflow = open ? 'hidden' : '';
        return 0;
    }
    """,
    Output("ptf-drawer-scroll-helper", "data"),
    Input("ptf-drawer-open", "data"),
)

"""Page portefeuille (PTF) + bench + tableau CIQ + détail entreprise + graphiques fan."""
from __future__ import annotations

import dash
from src.ui import dmc_compat as dmc
from dash import dcc, html
from dash.dash_table import DataTable

from config.settings import (
    DEFAULT_BENCHMARK,
    PTF_DEFAULT_DATE_MODE,
    PTF_DEFAULT_VISIBLE_COLUMNS,
    PTF_TABLE_PAGE_SIZE,
)
from src.data.index_screen_repository import get_index_screen_repository
from src.callbacks.index_composition import build_drawer_metric_multiselect_data
from src.data.ptf_column_groups import default_summary_column_names, filter_groups_for_ciq
from src.data.ptf_repository import get_ptf_repository
from src.data.schemas_ciq import (
    CIQ_COL_FACTSET_ECONOMY,
    CIQ_COL_FACTSET_IND,
    CIQ_COL_ICB_SUPERSECTOR,
)

dash.register_page(__name__, path="/indice", name="Composition indice")


def _fmt_date(ts) -> str:
    try:
        return ts.strftime("%Y-%m-%d")
    except Exception:
        return str(ts)


def layout() -> html.Div:
    idx = get_index_screen_repository()
    ptf_repo = get_ptf_repository()
    av = set(idx.df.columns)
    indices = idx.list_indices()
    index_data = [{"value": ic.column, "label": ic.label} for ic in indices]
    default_bench = (
        DEFAULT_BENCHMARK
        if DEFAULT_BENCHMARK and any(ic.column == DEFAULT_BENCHMARK for ic in indices)
        else (indices[0].column if indices else None)
    )
    dates_l: list[str] = []
    if default_bench:
        dates_l = [_fmt_date(d) for d in idx.available_dates_for_index(default_bench)]
    default_date = None
    if dates_l:
        default_date = dates_l[-1] if PTF_DEFAULT_DATE_MODE == "latest" else dates_l[0]

    ptf_names = ptf_repo.list_ptf_names()
    default_ptf = ptf_names[0] if ptf_names else None

    bench_s = default_bench or ""
    if PTF_DEFAULT_VISIBLE_COLUMNS:
        dcols: list[str] = []
        if bench_s in av:
            dcols.append(bench_s)
        for c in PTF_DEFAULT_VISIBLE_COLUMNS:
            if c in av and c not in dcols:
                dcols.append(c)
    else:
        dcols = default_summary_column_names(av, bench_s)
    groups = filter_groups_for_ciq(av)
    col_options: list[dict] = []
    for g in groups:
        for lab, c in g.entries:
            col_options.append({"label": f"{g.label} — {lab}", "value": c})
    group_add_opts = [{"value": g.id, "label": g.label} for g in groups]
    metric_drawer_data = build_drawer_metric_multiselect_data(av, idx.df)

    return html.Div(
        className="page-ptf-index",
        children=[
            # session：navigation hors page puis retour sans perdre filtres / société sélectionnée
            dcc.Store(id="ptf-selected-isin", data=None, storage_type="session"),
            dcc.Store(id="ptf-drawer-open", data=False),
            dcc.Store(id="ptf-drawer-scroll-helper", data=0),
            dmc.Text(
                "Portefeuille & comparaison sectorielle (bench)",
                size="xl",
                fw=700,
                c="#111827",
            ),
            dmc.Text(
                "Filtres PTF / bench / date, colonnes CIQ, puis détail par ligne (tiroir). "
                "Même logique de colonnes que l’analyse sectorielle ICB pour comparer.",
                size="sm",
                c="#4B5563",
            ),
            dmc.Space(h=10),
            dmc.Paper(
                withBorder=True,
                radius="md",
                p="md",
                children=dmc.Stack(
                    gap="sm",
                    children=[
                        dmc.SimpleGrid(
                            cols={"base": 1, "sm": 2, "lg": 4},
                            spacing="md",
                            children=[
                                dmc.Select(
                                    id="ptf-name",
                                    label="Portefeuille (PTF)",
                                    data=[{"value": n, "label": n} for n in ptf_names],
                                    value=default_ptf,
                                    searchable=True,
                                    clearable=False,
                                    persistence=True,
                                    persistence_type="session",
                                ),
                                dmc.Select(
                                    id="ptf-bench",
                                    label="Benchmark (pondération)",
                                    data=index_data,
                                    value=default_bench,
                                    searchable=True,
                                    clearable=False,
                                    persistence=True,
                                    persistence_type="session",
                                ),
                                dmc.Select(
                                    id="ptf-date",
                                    label="Date",
                                    data=[{"value": d, "label": d} for d in dates_l],
                                    value=default_date,
                                    searchable=True,
                                    clearable=False,
                                    persistence=True,
                                    persistence_type="session",
                                ),
                                dmc.Select(
                                    id="ptf-add-group",
                                    label="Ajouter un groupe de colonnes",
                                    data=group_add_opts,
                                    value=None,
                                    clearable=True,
                                    placeholder="Choisir…",
                                    persistence=True,
                                    persistence_type="session",
                                ),
                            ],
                        ),
                        dmc.MultiSelect(
                            id="ptf-cols",
                            label="Colonnes affichées (résumé par défaut)",
                            data=col_options,
                            value=dcols,
                            searchable=True,
                            clearable=True,
                            nothingFoundMessage="Aucune colonne",
                            persistence=True,
                            persistence_type="session",
                        ),
                        dmc.Text(
                            "Pairs (gris) : même bench, secteur = code « Benchmark ICB Supersector » "
                            f"mappé (libellé ICB dans {CIQ_COL_ICB_SUPERSECTOR}) si dispo, sinon "
                            f"{CIQ_COL_FACTSET_IND}, sinon {CIQ_COL_FACTSET_ECONOMY} ; "
                            "région : West Europe / North America / Mid East & autres (Others). "
                            f"Jusqu'à 80 courbes pairs. ",
                            size="xs",
                            c="#6B7280",
                        ),
                    ],
                ),
            ),
            dmc.Space(h=12),
            dmc.Text(
                "Sélectionnez une ligne (case à gauche) : un panneau latéral s’ouvre avec description, actualités et graphiques. "
                "Fiche dédiée : `/company/<ISIN>`.",
                size="xs",
                c="#6B7280",
            ),
            dmc.Space(h=8),
            dmc.Paper(
                withBorder=True,
                radius="md",
                p="md",
                children=html.Div(
                    className="ptf-table-outer",
                    children=dcc.Loading(
                        type="default",
                        children=DataTable(
                            id="ptf-table",
                            data=[],
                            columns=[],
                            page_size=PTF_TABLE_PAGE_SIZE,
                            row_selectable="single",
                            selected_rows=[],
                            active_cell=None,
                            cell_selectable=True,
                            sort_action="native",
                            fill_width=False,
                            # Styles injectés au périmètre du tableau ; ciblent .dash-spreadsheet, etc.
                            css=[
                                {
                                    "selector": ".dash-table-container",
                                    "rule": "max-width: 100% !important; min-width: 0 !important; box-sizing: border-box;",
                                },
                            ],
                            style_table={
                                "overflowX": "auto",
                                "maxWidth": "100%",
                                "minWidth": 0,
                            },
                            style_cell={
                                "textAlign": "left",
                                "padding": "6px 10px",
                                "fontSize": "13px",
                                "whiteSpace": "nowrap",
                            },
                            style_header={
                                "fontWeight": 600,
                                "backgroundColor": "#F3F4F6",
                                "verticalAlign": "bottom",
                            },
                        ),
                    ),
                    # Avec .ptf-table-outer / #ptf-table dans styles.css : pas de barre horizontale sur toute la coquille
                    style={
                        "maxWidth": "100%",
                        "minWidth": 0,
                        "overflowX": "auto",
                        "maxHeight": "480px",
                        "overflowY": "auto",
                    },
                ),
            ),
            html.Div(
                id="ptf-drawer-overlay",
                className="drawer-overlay",
                children=[
                    html.Button(
                        id="ptf-drawer-backdrop",
                        className="drawer-backdrop",
                        n_clicks=0,
                        type="button",
                        title="Fermer",
                        **{"aria-label": "Fermer le panneau"},
                    ),
                    html.Div(
                        className="drawer-panel",
                        children=[
                            html.Div(
                                className="drawer-panel-header",
                                children=[
                                    html.Div(
                                        id="ptf-drawer-header",
                                        style={"flex": 1, "minWidth": 0},
                                    ),
                                    html.Button(
                                        "×",
                                        id="ptf-drawer-close",
                                        className="drawer-close",
                                        n_clicks=0,
                                        type="button",
                                        title="Fermer",
                                        **{"aria-label": "Fermer"},
                                    ),
                                ],
                            ),
                            html.Div(
                                className="drawer-seg-wrap",
                                children=dmc.SegmentedControl(
                                    id="ptf-drawer-seg",
                                    value="Description",
                                    data=["Description", "Facteurs & indicateurs"],
                                    fullWidth=True,
                                ),
                            ),
                            html.Div(
                                className="drawer-panel-body",
                                children=[
                                    html.Div(
                                        id="ptf-panel-description",
                                        className="drawer-tab-panel drawer-tab-panel--active",
                                        children=[
                                            dmc.Grid(
                                                gutter="md",
                                                align="flex-start",
                                                children=[
                                                    dmc.GridCol(
                                                        span={"base": 12, "md": 8},
                                                        children=[
                                                            dcc.Loading(
                                                                type="circle",
                                                                delay_show=200,
                                                                color="#1E40AF",
                                                                children=html.Div(
                                                                    id="ptf-desc-wrap"
                                                                ),
                                                            ),
                                                        ],
                                                    ),
                                                    dmc.GridCol(
                                                        span={"base": 12, "md": 4},
                                                        children=[
                                                            dcc.Loading(
                                                                type="circle",
                                                                delay_show=200,
                                                                color="#1E40AF",
                                                                children=html.Div(
                                                                    id="ptf-news-wrap"
                                                                ),
                                                            ),
                                                        ],
                                                    ),
                                                ],
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        id="ptf-panel-factors",
                                        className="drawer-tab-panel",
                                        children=[
                                            dmc.Text("Facteurs & indicateurs", size="md", fw=700),
                                            dmc.Space(h=6),
                                            dmc.Grid(
                                                gutter="md",
                                                align="flex-start",
                                                children=[
                                                    dmc.GridCol(
                                                        span={"base": 12, "md": 8},
                                                        children=[
                                                            dmc.Text(
                                                                "Historique des facteurs (société sélectionnée)",
                                                                size="sm",
                                                                fw=600,
                                                            ),
                                                            dmc.Space(h=8),
                                                            dcc.Loading(
                                                                type="circle",
                                                                delay_show=200,
                                                                color="#1E40AF",
                                                                children=dcc.Graph(
                                                                    id="ptf-graph-factors",
                                                                    config={"displaylogo": False},
                                                                    style={"minHeight": "400px"},
                                                                ),
                                                            ),
                                                            dmc.Space(h=16),
                                                            html.Div(
                                                                id="ptf-metric-charts-wrap"
                                                            ),
                                                        ],
                                                    ),
                                                    dmc.GridCol(
                                                        span={"base": 12, "md": 4},
                                                        children=[
                                                            dmc.Text(
                                                                "Indicateurs détaillés (pairs même bench / secteur / région)",
                                                                size="sm",
                                                                fw=600,
                                                            ),
                                                            dmc.Space(h=6),
                                                            dmc.MultiSelect(
                                                                id="ptf-metric-multiselect",
                                                                label="Métriques à afficher (par groupe CIQ)",
                                                                data=metric_drawer_data,
                                                                value=[],
                                                                searchable=True,
                                                                clearable=True,
                                                                nothingFoundMessage="Aucune métrique",
                                                                comboboxProps={"zIndex": 5000},
                                                            ),
                                                        ],
                                                    ),
                                                ],
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                id="ptf-drawer-fab-wrap",
                className="drawer-fab-wrap",
                style={"display": "none"},
                children=[
                    dmc.Button(
                        "Voir la fiche",
                        id="ptf-drawer-reopen",
                        variant="filled",
                        size="sm",
                    ),
                ],
            ),
        ],
    )

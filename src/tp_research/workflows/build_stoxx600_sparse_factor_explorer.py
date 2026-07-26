"""Build a self-contained STOXX Europe 600 sparse-factor explorer."""

from __future__ import annotations
from tp_research.runtime import recorded_workflow

import argparse
from html import escape
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from tp_core.workspace import BACKTEST_RUNS_DIR, REPORTS_DIR

RUN_DIR = (
    BACKTEST_RUNS_DIR
    / "ad_hoc"
    / "stoxx600_sparse_lag_extension_20260723"
)
LAG6_RUN_DIR = (
    BACKTEST_RUNS_DIR
    / "ad_hoc"
    / "stoxx600_relative_lag6_20260723"
)
DEFAULT_OUTPUT = REPORTS_DIR / "stoxx600-factor-explorer.html"
DEFAULT_SOURCE = (
    REPORTS_DIR
    / "factor_explorer_sources"
    / "stoxx600-factor-explorer.html"
)

DISPLAY_NAMES = {
    "stoxx600_momentum_eps_revision_ratio_score": "EPS Revision Ratio",
    "stoxx600_momentum_pmom_12m1m_score": "PMOM 12M1M",
    "stoxx600_reldelta_quality_oper_margin_lag3_score": (
        "Oper Margin directional_delta lag3"
    ),
    "stoxx600_reldelta_quality_oper_margin_lag6_score": (
        "Oper Margin directional_delta lag6"
    ),
    "stoxx600_reldelta_quality_oper_margin_lag12_score": (
        "Oper Margin directional_delta lag12"
    ),
    "stoxx600_reldelta_value_earns_yield_fy1_lag1_score": (
        "Earns Yield FY1 directional_delta lag1"
    ),
    "stoxx600_reldelta_value_earns_yield_fy1_lag6_score": (
        "Earns Yield FY1 directional_delta lag6"
    ),
    "stoxx600_reldelta_value_earns_yield_fy1_lag12_score": (
        "Earns Yield FY1 directional_delta lag12"
    ),
    "stoxx600_reldelta_quality_netdebt_to_ebitda_exfin_lag3_score": (
        "NetDebt to EBITDA exFIN directional_delta lag3"
    ),
    "stoxx600_reldelta_quality_netdebt_to_ebitda_exfin_lag6_score": (
        "NetDebt to EBITDA exFIN directional_delta lag6"
    ),
    "stoxx600_reldelta_quality_netdebt_to_ebitda_exfin_lag12_score": (
        "NetDebt to EBITDA exFIN directional_delta lag12"
    ),
    "stoxx600_growth_gross_income_growth_fy1_score": "Gross Income Growth FY1",
    "stoxx600_dividend_dps_1y_growth_ntm_score": "DPS 1Y Growth NTM",
    "stoxx600_sparse_core3_equal": (
        "Core: EPS Revision Ratio + PMOM 12M1M + "
        "Oper Margin directional_delta lag3"
    ),
    "stoxx600_core3_plus_earnings_yield_improvement": (
        "Core + Earns Yield FY1 directional_delta lag1 (25%)"
    ),
    "stoxx600_core3_plus_deleveraging": (
        "Core + NetDebt to EBITDA exFIN directional_delta lag3 (25%)"
    ),
    "stoxx600_core3_plus_growth": "Core + Gross Income Growth FY1 (25%)",
    "stoxx600_core3_plus_dividend": "Core + DPS 1Y Growth NTM (25%)",
}

ECONOMIC_NOTES = {
    "stoxx600_momentum_eps_revision_ratio_score": (
        "分析师盈利预期的方向与扩散，代表显式预期更新。"
    ),
    "stoxx600_momentum_pmom_12m1m_score": (
        "价格对分散信息的综合确认；需警惕恐慌后急速反弹中的动量崩塌。"
    ),
    "stoxx600_reldelta_quality_oper_margin_lag3_score": (
        "经营实绩正在改善，可能来自定价、成本纪律、产品组合或产能利用率。"
    ),
    "stoxx600_reldelta_value_earns_yield_fy1_lag1_score": (
        "远期盈利相对价格正在改善，区别于静态便宜标签。"
    ),
    "stoxx600_reldelta_quality_netdebt_to_ebitda_exfin_lag3_score": (
        "资产负债表缓冲正在增强，但覆盖率仅略高于 admission 门槛。"
    ),
    "stoxx600_growth_gross_income_growth_fy1_score": (
        "增长预期为正，但单腿与组合中的增量证据弱于 core。"
    ),
    "stoxx600_dividend_dps_1y_growth_ntm_score": (
        "股息增长提供现金分配确认，历史上更像分散化而非严格协同。"
    ),
}

SLEEVE_NAMES = {
    "e1": "Earns Yield FY1 directional_delta lag1",
    "e6": "Earns Yield FY1 directional_delta lag6",
    "e12": "Earns Yield FY1 directional_delta lag12",
    "d3": "NetDebt to EBITDA exFIN directional_delta lag3",
    "d6": "NetDebt to EBITDA exFIN directional_delta lag6",
    "d12": "NetDebt to EBITDA exFIN directional_delta lag12",
    "growth": "Gross Income Growth FY1",
    "dividend": "DPS 1Y Growth NTM",
}
QUALITY_NAMES = {
    "q3": "Oper Margin directional_delta lag3",
    "q6": "Oper Margin directional_delta lag6",
    "q12": "Oper Margin directional_delta lag12",
}

CLASS_NAMES = {
    "strict_synergy": "严格协同",
    "additive_or_diversifying": "加法 / 分散化",
    "no_synergy_support": "不支持协同",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-copy", type=Path, default=DEFAULT_SOURCE)
    return parser.parse_args()


def read_nav(path_text: str) -> pd.Series:
    path = Path(path_text)
    frame = (
        pd.read_parquet(path)
        if path.suffix.lower() == ".parquet"
        else pd.read_csv(path)
    )
    if "Date" not in frame.columns and (
        frame.index.name == "Date"
        or isinstance(frame.index, pd.DatetimeIndex)
    ):
        frame = frame.reset_index()
    date_col = "Date" if "Date" in frame.columns else frame.columns[0]
    nav_col = "nav" if "nav" in frame.columns else frame.columns[-1]
    output = frame[[date_col, nav_col]].copy()
    output[date_col] = pd.to_datetime(output[date_col], errors="coerce")
    output[nav_col] = pd.to_numeric(output[nav_col], errors="coerce")
    output = (
        output.dropna()
        .drop_duplicates(date_col, keep="last")
        .sort_values(date_col)
    )
    return output.set_index(date_col)[nav_col].astype(float)


def monthly_nav_payload(
    metric: str,
    results: pd.DataFrame,
) -> list[dict[str, object]]:
    rows = results.loc[
        results["metric"].eq(metric) & results["status"].eq("success")
    ]
    top = rows.loc[rows["side"].eq("Top")]
    worst = rows.loc[rows["side"].eq("Worst")]
    if top.empty or worst.empty:
        return []
    top_row = top.iloc[-1]
    worst_row = worst.iloc[-1]
    nav = pd.concat(
        {
            "top": read_nav(str(top_row["perf_ptf"])),
            "worst": read_nav(str(worst_row["perf_ptf"])),
            "benchmark": read_nav(str(top_row["perf_bench"])),
        },
        axis=1,
        join="inner",
    ).dropna()
    if nav.empty:
        return []
    nav = nav.div(nav.iloc[0]).mul(100.0)
    monthly = nav.groupby(nav.index.to_period("M")).tail(1)
    monthly = pd.concat([nav.iloc[[0]], monthly, nav.iloc[[-1]]])
    monthly = monthly[~monthly.index.duplicated(keep="last")].sort_index()
    return [
        {
            "date": date.strftime("%Y-%m-%d"),
            "top": round(float(row["top"]), 4),
            "worst": round(float(row["worst"]), 4),
            "benchmark": round(float(row["benchmark"]), 4),
        }
        for date, row in monthly.iterrows()
    ]


def json_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_value(item) for item in value]
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if pd.isna(value):
        return None
    return value


def percent(value: object, digits: int = 2) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "—" if pd.isna(numeric) else f"{float(numeric) * 100:.{digits}f}%"


def number(value: object, digits: int = 2) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "—" if pd.isna(numeric) else f"{float(numeric):.{digits}f}"


def bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def table_rows(
    frame: pd.DataFrame,
    columns: Iterable[tuple[str, str]],
    *,
    row_class=None,
) -> str:
    output = []
    for _, row in frame.iterrows():
        css = f' class="{escape(row_class(row))}"' if row_class else ""
        cells = "".join(
            f"<td>{formatter(row.get(column))}</td>"
            for column, formatter in columns
        )
        output.append(f"<tr{css}>{cells}</tr>")
    return "\n".join(output)


def build_chart_markup(
    nav: list[dict[str, object]],
    *,
    width: int = 1040,
    height: int = 390,
) -> str:
    if not nav:
        return (
            '<text x="50%" y="50%" text-anchor="middle" '
            'fill="#68737d">没有可显示的净值路径</text>'
        )
    margin = {"top": 20, "right": 24, "bottom": 42, "left": 58}
    plot_width = width - margin["left"] - margin["right"]
    plot_height = height - margin["top"] - margin["bottom"]
    values = [
        float(row[key])
        for row in nav
        for key in ("top", "worst", "benchmark")
    ]
    minimum = min(values)
    maximum = max(values)
    padding = max((maximum - minimum) * 0.08, 4.0)
    low = minimum - padding
    high = maximum + padding

    def x(index: int) -> float:
        return margin["left"] + index / max(len(nav) - 1, 1) * plot_width

    def y(value: float) -> float:
        return margin["top"] + (high - value) / max(high - low, 1) * plot_height

    elements: list[str] = []
    for index in range(5):
        value = low + (high - low) * index / 4
        yy = y(value)
        elements.append(
            f'<line x1="{margin["left"]}" y1="{yy:.2f}" '
            f'x2="{width - margin["right"]}" y2="{yy:.2f}" '
            'stroke="#e3e7e9" stroke-width="1"/>'
        )
        elements.append(
            f'<text x="{margin["left"] - 9}" y="{yy + 4:.2f}" '
            'text-anchor="end" fill="#6a747e" font-size="11">'
            f"{value:.0f}</text>"
        )
    tick_indexes = sorted(
        set(
            [
                0,
                (len(nav) - 1) // 3,
                (len(nav) - 1) * 2 // 3,
                len(nav) - 1,
            ]
        )
    )
    for index in tick_indexes:
        anchor = (
            "start"
            if index == 0
            else "end"
            if index == len(nav) - 1
            else "middle"
        )
        elements.append(
            f'<text x="{x(index):.2f}" y="{height - 12}" '
            f'text-anchor="{anchor}" fill="#6a747e" font-size="11">'
            f'{escape(str(nav[index]["date"])[:4])}</text>'
        )
    for key, color, stroke_width in (
        ("top", "#087b63", 2.8),
        ("worst", "#b14f45", 2.2),
        ("benchmark", "#316fa1", 2.2),
    ):
        points = " ".join(
            f'{x(index):.2f},{y(float(row[key])):.2f}'
            for index, row in enumerate(nav)
        )
        elements.append(
            f'<polyline data-series="{key}" points="{points}" '
            f'fill="none" stroke="{color}" stroke-width="{stroke_width}" '
            'stroke-linejoin="round" stroke-linecap="round"/>'
        )
    return "".join(elements)


def build_payload(run_dir: Path) -> dict[str, object]:
    registry = pd.read_csv(run_dir / "candidate_registry.csv")
    results = pd.read_csv(run_dir / "official_run_results.csv", low_memory=False)
    summary = pd.read_csv(run_dir / "performance_summary.csv", low_memory=False)
    validation = pd.read_csv(run_dir / "official_validation_gate.csv")
    architecture = pd.read_csv(run_dir / "architecture_gate_results.csv")
    regime = pd.read_csv(run_dir / "architecture_regime_metrics.csv")
    synergy = pd.read_csv(run_dir / "synergy_evidence.csv")
    cost = pd.read_csv(run_dir / "architecture_cost_sensitivity.csv")
    dsr = pd.read_csv(run_dir / "full_ledger_deflated_sharpe.csv")
    rolling = pd.read_csv(run_dir / "architecture_rolling_robustness.csv")
    break_tests = pd.read_csv(run_dir / "break_2020_tests.csv")
    drift = pd.read_csv(run_dir / "missing_month_drift_check.csv")
    audit = json.loads(
        (run_dir / "data_audit_summary.json").read_text(encoding="utf-8")
    )
    overfit = json.loads(
        (run_dir / "overfit_diagnostics.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    lag_comparison = pd.read_csv(
        LAG6_RUN_DIR / "lag6_vs_lag1_lag3_lag12.csv"
    )

    singles = validation.loc[
        validation["candidate_type"].eq("single")
    ].copy()
    label_map = registry.set_index("metric")["label"].astype(str).to_dict()
    display_map = {
        metric: DISPLAY_NAMES.get(metric, label)
        for metric, label in label_map.items()
    }
    singles["display_name"] = singles["metric"].map(display_map)
    architecture["display_name"] = architecture["metric"].map(display_map)
    architecture["pass_gate"] = architecture["pass_gate"].map(bool_value)
    synergy["display_name"] = (
        synergy["quality_key"].map(QUALITY_NAMES)
        + " + "
        + synergy["sleeve_key"].map(SLEEVE_NAMES)
    )
    synergy["class_name"] = synergy["classification"].map(CLASS_NAMES)
    synergy["class_name"] = synergy["class_name"].fillna("证据不完整")
    regime["display_name"] = regime["metric"].map(display_map)
    cost["display_name"] = cost["metric"].map(display_map)
    dsr = dsr.loc[
        dsr["metric"].isin(architecture["metric"])
    ].copy()
    dsr["display_name"] = dsr["metric"].map(display_map)
    rolling["display_name"] = rolling["metric"].map(display_map)
    break_tests["display_name"] = break_tests["metric"].map(display_map)

    requested_chart_metrics = [
        *singles["metric"].astype(str).tolist(),
        *architecture["metric"].astype(str).tolist(),
    ]
    summary_top = (
        summary.loc[
            summary["side"].eq("Top") & summary["status"].eq("success")
        ]
        .drop_duplicates("metric", keep="last")
        .set_index("metric")
    )
    charts: dict[str, object] = {}
    for metric in requested_chart_metrics:
        if metric not in summary_top.index:
            continue
        nav = monthly_nav_payload(metric, results)
        if not nav:
            continue
        gate_row = validation.loc[validation["metric"].eq(metric)]
        if gate_row.empty:
            gate_row = architecture.loc[architecture["metric"].eq(metric)]
        row = gate_row.iloc[-1]
        top_row = summary_top.loc[metric]
        charts[metric] = {
            "metric": metric,
            "name": display_map.get(metric, metric),
            "type": (
                "architecture"
                if metric in set(architecture["metric"])
                else "single"
            ),
            "coverage": row.get("coverage"),
            "activeCagr": top_row.get("ratio_cagr"),
            "topWorst": top_row.get("top_worst_ratio_return"),
            "robustScore": top_row.get("robust_score"),
            "turnover": top_row.get("avg_turnover"),
            "passGate": bool_value(row.get("pass_gate")),
            "note": ECONOMIC_NOTES.get(
                metric,
                "固定低自由度架构；详细证据见对应研究页签。",
            ),
            "nav": nav,
        }

    return {
        "registry": registry,
        "singles": singles,
        "architecture": architecture,
        "regime": regime,
        "synergy": synergy,
        "cost": cost,
        "dsr": dsr,
        "rolling": rolling,
        "break": break_tests,
        "lag_comparison": lag_comparison,
        "drift": drift.iloc[0].to_dict(),
        "audit": audit,
        "overfit": overfit,
        "manifest": manifest,
        "charts": charts,
    }


def build_html(payload: dict[str, object]) -> str:
    singles = payload["singles"]
    architecture = payload["architecture"]
    regime = payload["regime"]
    synergy = payload["synergy"]
    cost = payload["cost"]
    dsr = payload["dsr"]
    rolling = payload["rolling"]
    break_tests = payload["break"]
    lag_comparison = payload["lag_comparison"]
    drift = payload["drift"]
    audit = payload["audit"]
    overfit = payload["overfit"]
    manifest = payload["manifest"]
    charts = payload["charts"]

    assert isinstance(singles, pd.DataFrame)
    assert isinstance(architecture, pd.DataFrame)
    assert isinstance(regime, pd.DataFrame)
    assert isinstance(synergy, pd.DataFrame)
    assert isinstance(cost, pd.DataFrame)
    assert isinstance(dsr, pd.DataFrame)
    assert isinstance(rolling, pd.DataFrame)
    assert isinstance(break_tests, pd.DataFrame)
    assert isinstance(lag_comparison, pd.DataFrame)
    assert isinstance(drift, dict)
    assert isinstance(audit, dict)
    assert isinstance(overfit, dict)
    assert isinstance(manifest, dict)
    assert isinstance(charts, dict)

    default_metric = "stoxx600_sx_full_q3_e1"
    default_chart = charts[default_metric]
    default_nav = default_chart["nav"]
    chart_markup = build_chart_markup(default_nav)
    chart_options = "\n".join(
        (
            f'<option value="{escape(metric)}"'
            f'{" selected" if metric == default_metric else ""}>'
            f'{escape(str(item["name"]))}</option>'
        )
        for metric, item in charts.items()
    )

    single_rows = table_rows(
        singles.sort_values("robust_score", ascending=False),
        [
            ("display_name", lambda value: f"<strong>{escape(str(value))}</strong>"),
            ("coverage", percent),
            ("ratio_cagr", percent),
            ("top_worst_ratio_return", number),
            ("robust_score", number),
            ("avg_turnover", percent),
            (
                "pass_gate",
                lambda value: (
                    '<span class="status pass">通过</span>'
                    if bool_value(value)
                    else '<span class="status fail">未通过</span>'
                ),
            ),
        ],
    )
    architecture_rows = table_rows(
        architecture.sort_values("robust_score", ascending=False),
        [
            ("display_name", lambda value: f"<strong>{escape(str(value))}</strong>"),
            ("coverage", percent),
            ("ratio_cagr", percent),
            ("top_worst_ratio_return", number),
            ("robust_score", number),
            ("avg_turnover", percent),
            (
                "pass_gate",
                lambda value: (
                    '<span class="status pass">通过</span>'
                    if bool_value(value)
                    else '<span class="status fail">Coverage 阻塞</span>'
                ),
            ),
        ],
        row_class=lambda row: "blocked" if not bool_value(row["pass_gate"]) else "",
    )
    synergy_rows = table_rows(
        synergy,
        [
            ("display_name", lambda value: f"<strong>{escape(str(value))}</strong>"),
            (
                "pair_gate_passes",
                lambda value: (
                    "—"
                    if pd.isna(pd.to_numeric(value, errors="coerce"))
                    else f"{int(float(value))} / 3"
                ),
            ),
            ("full_ratio_cagr", percent),
            ("core_ratio_cagr", percent),
            ("full_robust_score", number),
            ("max_loo_robust_score", number),
            (
                "class_name",
                lambda value: (
                    '<span class="status synergy">严格协同</span>'
                    if value == "严格协同"
                    else f'<span class="status neutral">{escape(str(value))}</span>'
                ),
            ),
        ],
    )
    lag_rows = table_rows(
        lag_comparison.loc[
            lag_comparison["pass_gate_lag6"].map(bool_value)
        ].sort_values("robust_score_lag6", ascending=False),
        [
            ("raw_column", lambda value: f"<strong>{escape(str(value))}</strong>"),
            ("transform", lambda value: f"<code>{escape(str(value))}</code>"),
            ("robust_score_lag1", number),
            ("robust_score_lag3", number),
            ("robust_score_lag6", number),
            ("robust_score_lag12", number),
            ("best_robust_lag", lambda value: escape(str(value))),
        ],
    )
    cost_rows = table_rows(
        cost.sort_values("net_active_cagr_20bps", ascending=False),
        [
            ("display_name", lambda value: f"<strong>{escape(str(value))}</strong>"),
            ("gross_active_cagr", percent),
            ("annualized_one_way_turnover", percent),
            ("net_active_cagr_10bps", percent),
            ("net_active_cagr_20bps", percent),
            ("net_active_cagr_40bps", percent),
        ],
    )
    dsr_rows = table_rows(
        dsr.sort_values("deflated_sharpe_probability", ascending=False),
        [
            ("display_name", lambda value: f"<strong>{escape(str(value))}</strong>"),
            ("annualized_sharpe", number),
            (
                "trial_count",
                lambda value: str(int(float(value))),
            ),
            ("deflated_sharpe_probability", percent),
        ],
    )
    rolling_pivot = rolling.pivot(
        index=["metric", "display_name"],
        columns="window",
        values=["min_active_cagr", "positive_fraction"],
    ).reset_index()
    rolling_pivot.columns = [
        "_".join(str(item) for item in column if item).rstrip("_")
        if isinstance(column, tuple)
        else str(column)
        for column in rolling_pivot.columns
    ]
    rolling_rows = table_rows(
        rolling_pivot,
        [
            ("display_name", lambda value: f"<strong>{escape(str(value))}</strong>"),
            ("min_active_cagr_3y", percent),
            ("positive_fraction_3y", percent),
            ("min_active_cagr_5y", percent),
            ("positive_fraction_5y", percent),
        ],
    )
    break_rows = table_rows(
        break_tests.sort_values("post_minus_pre"),
        [
            ("display_name", lambda value: f"<strong>{escape(str(value))}</strong>"),
            ("pre_2020_annualized_active_mean", percent),
            ("post_2020_annualized_active_mean", percent),
            ("post_minus_pre", percent),
            (
                "difference_supported_95pct",
                lambda value: (
                    '<span class="status fail">支持断裂</span>'
                    if bool_value(value)
                    else '<span class="status neutral">未支持</span>'
                ),
            ),
            (
                "sign_flip",
                lambda value: "是" if bool_value(value) else "否",
            ),
        ],
    )

    regime_metrics = architecture.loc[
        architecture["pass_gate"], ["metric", "display_name"]
    ]
    regime_table = regime.merge(regime_metrics, on="metric", suffixes=("", "_a"))
    regime_table["display_name"] = regime_table["display_name_a"]
    regime_rows = table_rows(
        regime_table.sort_values(["label_zh", "active_cagr"], ascending=[True, False]),
        [
            ("label_zh", lambda value: escape(str(value))),
            ("display_name", lambda value: f"<strong>{escape(str(value))}</strong>"),
            ("active_cagr", percent),
            ("top_worst_cagr", percent),
            ("active_max_drawdown", percent),
            ("cost_adjusted_active_cagr", percent),
        ],
    )

    evidence_json = json.dumps(
        json_value(
            {
                "charts": charts,
                "regime": regime_table[
                    [
                        "metric",
                        "display_name",
                        "regime_id",
                        "label_zh",
                        "active_cagr",
                        "top_worst_cagr",
                    ]
                ].to_dict(orient="records"),
            }
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")

    architecture_pbo = overfit["architecture"]
    full_pbo = overfit["full_ledger"]
    engine = f'{manifest["engine_id"]} {manifest["engine_version"]}'
    passed_architectures = int(architecture["pass_gate"].sum())
    passed_singles = int(singles["pass_gate"].map(bool_value).sum())
    strict_count = int(synergy["classification"].eq("strict_synergy").sum())
    candidate_count = int(manifest["candidate_count"])
    terminal_count = int(manifest["terminal_official_runs"])
    expected_count = int(manifest["expected_official_runs"])

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>STOXX Europe 600 稀疏因子研究浏览器</title>
  <style>
    :root {{
      --ink:#17232d; --muted:#66727c; --line:#dce3e6; --soft:#f4f6f5;
      --green:#087b63; --green-soft:#e7f3ef; --red:#b14f45; --red-soft:#f8ece9;
      --blue:#316fa1; --blue-soft:#eaf1f7; --amber:#9a6d13; --amber-soft:#f7f1e3;
      --white:#fff;
    }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{
      margin:0; color:var(--ink); background:var(--white);
      font-family:Inter, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      font-size:14px; line-height:1.55; letter-spacing:0;
    }}
    button, select {{ font:inherit; letter-spacing:0; }}
    header {{
      border-top:4px solid var(--green); border-bottom:1px solid var(--line);
      padding:28px 0 24px; background:#fff;
    }}
    .wrap {{ width:min(1240px, calc(100% - 40px)); margin:0 auto; }}
    .eyebrow {{ color:var(--green); font-size:12px; font-weight:700; text-transform:uppercase; }}
    h1 {{ font-size:clamp(26px, 3vw, 42px); line-height:1.12; margin:8px 0 10px; }}
    h2 {{ font-size:22px; margin:0 0 8px; }}
    h3 {{ font-size:15px; margin:0 0 6px; }}
    p {{ margin:0 0 10px; }}
    .lede {{ max-width:900px; color:var(--muted); font-size:16px; }}
    .header-meta {{ display:flex; flex-wrap:wrap; gap:18px; margin-top:16px; color:var(--muted); font-size:12px; }}
    .metric-strip {{
      display:grid; grid-template-columns:repeat(6, minmax(0,1fr));
      border-bottom:1px solid var(--line);
    }}
    .metric {{
      min-height:106px; padding:20px; border-right:1px solid var(--line);
      background:#fff;
    }}
    .metric:last-child {{ border-right:0; }}
    .metric strong {{ display:block; font-size:24px; line-height:1.1; margin-bottom:7px; }}
    .metric span {{ color:var(--muted); font-size:12px; }}
    nav {{
      position:sticky; top:0; z-index:10; border-bottom:1px solid var(--line);
      background:rgba(255,255,255,.97); padding:10px 0;
    }}
    .tabs {{ display:flex; gap:4px; overflow-x:auto; }}
    .tab {{
      border:1px solid transparent; background:transparent; color:var(--muted);
      padding:8px 12px; border-radius:6px; white-space:nowrap; cursor:pointer;
    }}
    .tab:hover {{ background:var(--soft); color:var(--ink); }}
    .tab.active {{ border-color:#bed8cf; color:var(--green); background:var(--green-soft); font-weight:700; }}
    main {{ min-height:620px; }}
    .panel {{ padding:30px 0 44px; border-bottom:1px solid var(--line); }}
    .enhanced .panel[hidden] {{ display:none; }}
    .section-head {{
      display:flex; justify-content:space-between; align-items:end; gap:20px;
      margin-bottom:20px;
    }}
    .section-head p {{ color:var(--muted); max-width:780px; }}
    .conclusion-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }}
    .conclusion {{
      border:1px solid var(--line); border-radius:7px; padding:16px; min-height:158px;
    }}
    .conclusion strong {{ color:var(--green); display:block; margin-bottom:7px; }}
    .conclusion.warning strong {{ color:var(--amber); }}
    .conclusion.risk strong {{ color:var(--red); }}
    .chart-toolbar {{
      display:flex; justify-content:space-between; gap:18px; align-items:end;
      border-top:1px solid var(--line); margin-top:26px; padding-top:20px;
    }}
    label {{ display:block; color:var(--muted); font-size:12px; margin-bottom:5px; }}
    select {{
      width:min(460px, 100%); border:1px solid #bdc8cd; border-radius:6px;
      padding:9px 34px 9px 10px; background:#fff; color:var(--ink);
    }}
    .chart-title {{ font-weight:700; font-size:17px; }}
    .chart-meta {{ color:var(--muted); font-size:12px; margin-top:3px; }}
    .chart-note {{ color:var(--muted); margin-top:8px; }}
    .chart-shell {{
      margin-top:14px; border:1px solid var(--line); border-radius:7px;
      padding:12px 12px 4px; overflow:hidden; background:#fff;
    }}
    svg {{ display:block; width:100%; height:390px; }}
    .legend {{ display:flex; gap:18px; padding:0 8px 8px; color:var(--muted); font-size:12px; }}
    .legend i {{ width:11px; height:3px; display:inline-block; margin:0 5px 3px 0; }}
    .table-wrap {{ width:100%; overflow:auto; border:1px solid var(--line); border-radius:7px; }}
    table {{ width:100%; border-collapse:collapse; min-width:820px; }}
    th, td {{ border-bottom:1px solid var(--line); padding:10px 12px; text-align:right; vertical-align:top; }}
    th {{ background:var(--soft); color:#56626c; font-size:11px; text-transform:uppercase; position:sticky; top:0; }}
    th:first-child, td:first-child {{ text-align:left; }}
    tbody tr:last-child td {{ border-bottom:0; }}
    tbody tr:hover {{ background:#fafbfa; }}
    tr.blocked {{ background:#fcf7f5; color:#76544e; }}
    .status {{ display:inline-block; border-radius:999px; padding:2px 8px; font-size:11px; font-weight:700; white-space:nowrap; }}
    .status.pass {{ color:var(--green); background:var(--green-soft); }}
    .status.fail {{ color:var(--red); background:var(--red-soft); }}
    .status.synergy {{ color:#215d87; background:var(--blue-soft); }}
    .status.neutral {{ color:#626d75; background:#edf0f1; }}
    .split {{ display:grid; grid-template-columns:1.15fr .85fr; gap:26px; align-items:start; }}
    .audit-list {{ border-top:1px solid var(--line); }}
    .audit-row {{ display:grid; grid-template-columns:190px 1fr; gap:20px; padding:11px 0; border-bottom:1px solid var(--line); }}
    .audit-row span:first-child {{ color:var(--muted); }}
    .callout {{ border-left:4px solid var(--blue); background:var(--blue-soft); padding:15px 17px; margin:18px 0; }}
    .callout.warning {{ border-left-color:var(--amber); background:var(--amber-soft); }}
    .callout.risk {{ border-left-color:var(--red); background:var(--red-soft); }}
    .pbo-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:22px; }}
    .pbo {{ border:1px solid var(--line); border-radius:7px; padding:18px; }}
    .pbo strong {{ font-size:28px; display:block; margin-bottom:5px; }}
    .pbo span {{ color:var(--muted); }}
    footer {{ padding:28px 0 40px; color:var(--muted); font-size:12px; }}
    code {{
      font-family:"Cascadia Code", Consolas, monospace; font-size:.92em;
      overflow-wrap:anywhere; word-break:break-word;
    }}
    @media (max-width:900px) {{
      .metric-strip {{ grid-template-columns:repeat(3,minmax(0,1fr)); }}
      .metric:nth-child(3) {{ border-right:0; }}
      .metric:nth-child(-n+3) {{ border-bottom:1px solid var(--line); }}
      .conclusion-grid {{ grid-template-columns:1fr 1fr; }}
      .split, .pbo-grid {{ grid-template-columns:1fr; }}
      .chart-toolbar, .section-head {{ align-items:start; flex-direction:column; }}
    }}
    @media (max-width:560px) {{
      .wrap {{ width:min(100% - 24px, 1240px); }}
      header {{ padding:22px 0 18px; }}
      .metric-strip {{ grid-template-columns:1fr 1fr; }}
      .metric {{ border-bottom:1px solid var(--line); }}
      .metric:nth-child(2n) {{ border-right:0; }}
      .conclusion-grid {{ grid-template-columns:1fr; }}
      .audit-row {{ grid-template-columns:1fr; gap:3px; }}
      svg {{ height:300px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <div class="eyebrow">TP Quant Research · Official Top/Worst Evidence</div>
      <h1>STOXX Europe 600 稀疏因子研究浏览器</h1>
      <p class="lede">从 159 项预注册证据中比较 lag3/6/12 的互斥经营改善定义与八种 sleeve。页面完整呈现原文变量名、raw gate、pair、leave-one-out、六阶段、成本和过拟合诊断。</p>
      <div class="header-meta">
        <span>研究日：2026-07-23</span>
        <span>官方收益截至：2026-07-02</span>
        <span>引擎：{escape(engine)}</span>
        <span>Benchmark：STOXX Europe 600</span>
      </div>
    </div>
  </header>

  <section class="wrap metric-strip" aria-label="研究摘要">
    <div class="metric"><strong>{candidate_count}</strong><span>预注册证据指标</span></div>
    <div class="metric"><strong>{terminal_count} / {expected_count}</strong><span>Official sides 有终态</span></div>
    <div class="metric"><strong>{passed_singles} / {len(singles)}</strong><span>底层单变量通过 gate</span></div>
    <div class="metric"><strong>{passed_architectures} / {len(architecture)}</strong><span>架构通过绝对 gate</span></div>
    <div class="metric"><strong>{strict_count}</strong><span>完整证据 strict synergy</span></div>
    <div class="metric"><strong>{architecture_pbo["pbo"]:.1%}</strong><span>架构择赢家 PBO</span></div>
  </section>

  <nav>
    <div class="wrap tabs" role="tablist" aria-label="研究视图">
      <button class="tab active" data-tab="overview" type="button">总览</button>
      <button class="tab" data-tab="singles" type="button">单变量</button>
      <button class="tab" data-tab="architecture" type="button">Core / Sleeve</button>
      <button class="tab" data-tab="synergy" type="button">协同证据</button>
      <button class="tab" data-tab="regimes" type="button">分时期</button>
      <button class="tab" data-tab="robustness" type="button">稳健性与审计</button>
    </div>
  </nav>

  <main>
    <section class="panel" data-panel="overview">
      <div class="wrap">
        <div class="section-head">
          <div>
            <h2>结论先行</h2>
            <p>q3 core 仍是首选；q6 是较弱的跨阶段替代；q12 必须由 growth 或 dividend 确认。动态选择组合冠军的历史排名不稳定。</p>
          </div>
        </div>
        <div class="conclusion-grid">
          <article class="conclusion">
            <strong>静态 Core</strong>
            <code>EPS Revision Ratio + PMOM 12M1M + Oper Margin directional_delta lag3</code>，主动 CAGR 5.54%，六个阶段主动与 Top/Worst 均为正。
          </article>
          <article class="conclusion">
            <strong>5 组 Strict Synergy</strong>
            q3+earnings-yield lag1 仍最强；q6 与 earnings-yield/growth、q12 与 growth/dividend 也通过完整 singles、pairs、full 与 LOO。
          </article>
          <article class="conclusion warning">
            <strong>成本改变排序</strong>
            20 bps 单边成本后，前五架构净主动 CAGR 收敛到约 4.58%–4.69%。
          </article>
          <article class="conclusion risk">
            <strong>不做动态择赢家</strong>
            12 架构 CSCV PBO 72.62%，说明相近架构的样本内外排名容易互换。
          </article>
        </div>

        <div class="chart-toolbar">
          <div>
            <label for="candidate-select">查看官方 Top / Worst 净值</label>
            <select id="candidate-select">{chart_options}</select>
          </div>
          <div>
            <div class="chart-title" id="chart-title">{escape(str(default_chart["name"]))}</div>
            <div class="chart-meta" id="chart-meta">Coverage {percent(default_chart["coverage"])} · 主动 CAGR {percent(default_chart["activeCagr"])} · Robust {number(default_chart["robustScore"])}</div>
          </div>
        </div>
        <p class="chart-note" id="chart-note">{escape(str(default_chart["note"]))}</p>
        <div class="chart-shell">
          <svg id="nav-chart" viewBox="0 0 1040 390" role="img" aria-label="Top、Worst 与 Benchmark 净值">
            {chart_markup}
          </svg>
          <div class="legend">
            <span><i style="background:#087b63"></i>Top</span>
            <span><i style="background:#b14f45"></i>Worst</span>
            <span><i style="background:#316fa1"></i>Benchmark</span>
          </div>
        </div>
      </div>
    </section>

    <section class="panel" data-panel="singles">
      <div class="wrap">
        <div class="section-head">
          <div><h2>单变量证据</h2><p>每个变量先独立 official Top/Worst，再决定是否允许进入组合。缺失值保持 NaN。</p></div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>单变量</th><th>Coverage</th><th>主动 CAGR</th><th>Top/Worst 累计比率</th><th>Robust</th><th>月均单边换手</th><th>Gate</th></tr></thead>
            <tbody>{single_rows}</tbody>
          </table>
        </div>
        <div class="callout">最强单变量是 <code>Oper Margin directional_delta lag3</code>。lag6 仍跨六段为正但强度下降；lag12 单腿只在 4/6 阶段为正。<code>Earns Yield FY1</code> 只有 lag1 通过，lag6/12 失败。</div>
        <h3 style="margin-top:26px">lag1 / lag3 / lag6 / lag12 对照</h3>
        <p style="color:var(--muted)">仅列出通过 lag6 gate 的变量。Best lag 是离散试验的描述性结果，不授权连续参数寻优。</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Raw variable</th><th>Transform</th><th>lag1 Robust</th><th>lag3 Robust</th><th>lag6 Robust</th><th>lag12 Robust</th><th>Best lag</th></tr></thead>
            <tbody>{lag_rows}</tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="panel" data-panel="architecture">
      <div class="wrap">
        <div class="section-head">
          <div><h2>Core 与固定 Sleeve</h2><p>三个互斥 quality-lag core 与 24 个 core+sleeve 架构全部展示。含失败 earnings-yield lag6/12 或 deleveraging lag6/12 的组合被 gate 阻塞。</p></div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>架构</th><th>Coverage</th><th>主动 CAGR</th><th>Top/Worst 累计比率</th><th>Robust</th><th>月均单边换手</th><th>Gate</th></tr></thead>
            <tbody>{architecture_rows}</tbody>
          </table>
        </div>
        <h3 style="margin-top:26px">交易成本敏感性</h3>
        <p style="color:var(--muted)">透明近似：月均单边换手 × 12 × bps。</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>架构</th><th>Gross</th><th>年化单边换手</th><th>10 bps 后</th><th>20 bps 后</th><th>40 bps 后</th></tr></thead>
            <tbody>{cost_rows}</tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="panel" data-panel="synergy">
      <div class="wrap">
        <div class="section-head">
          <div><h2>完整协同证据</h2><p>没有 singles、pair、subset 和 leave-one-out 的完整链条，不允许声称 synergy。</p></div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Quality + Sleeve</th><th>Pair gates</th><th>Full 主动 CAGR</th><th>Core 主动 CAGR</th><th>Full Robust</th><th>最强 LOO Robust</th><th>分类</th></tr></thead>
            <tbody>{synergy_rows}</tbody>
          </table>
        </div>
        <div class="split" style="margin-top:24px">
          <div>
            <h3>为什么不同 lag 需要不同确认</h3>
            <p>q3 与 earnings-yield lag1 连接最新经营事实与估值方向；q6 与 growth 区分效率改善和收缩型降本；q12 单腿较弱，只有 forward growth 或 dividend 同时确认时才获得完整增量证据。</p>
          </div>
          <div class="callout warning" style="margin:0">
            证据不完整的 12 个组合都含未通过 raw gate 的 sleeve。页面保留它们，但不会从经济故事自动推导 synergy。
          </div>
        </div>
      </div>
    </section>

    <section class="panel" data-panel="regimes">
      <div class="wrap">
        <div class="section-head">
          <div><h2>六个经济阶段</h2><p>12 个 gate-passed 架构中，11 个在 6/6 阶段主动 CAGR 为正；q12 core 在通胀、能源与加息阶段为负。</p></div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>阶段</th><th>架构</th><th>主动 CAGR</th><th>Top/Worst CAGR</th><th>主动最大回撤</th><th>20 bps 成本后</th></tr></thead>
            <tbody>{regime_rows}</tbody>
          </table>
        </div>
        <div class="callout">2020 是广泛变量库的显著重排点，但 9 个 gate-passed 稀疏 singles 与 12 个架构没有被 block bootstrap 支持存在均值断裂。另一个 lag6 变量 <code>EV To EBITDA NTM directional_delta lag6</code> 则出现受支持的正转负，说明断点存在与少数机制穿越断点可以同时成立。</div>
      </div>
    </section>

    <section class="panel" data-panel="robustness">
      <div class="wrap">
        <div class="section-head">
          <div><h2>过拟合、滚动窗口与数据审计</h2><p>DSR/PBO/LORO 只能降低历史过拟合嫌疑，不能把 2026-07 之前的历史变成真正未来样本。</p></div>
        </div>
        <div class="pbo-grid">
          <div class="pbo"><strong>{full_pbo["pbo"]:.2%}</strong><span>91 项完整 NAV evidence 的 CSCV PBO</span></div>
          <div class="pbo"><strong>{architecture_pbo["pbo"]:.2%}</strong><span>12 个 gate-passed 架构中择样本内赢家的 CSCV PBO</span></div>
        </div>
        <div class="callout risk">高架构 PBO 是“动态挑赢家”的警报，不是未来亏损概率。现有证据支持固定 core / sleeve，不支持频繁轮换。</div>

        <h3>Deflated Sharpe（多重试验惩罚按 159 个预注册 trials）</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>架构</th><th>年化 Sharpe</th><th>Trial count</th><th>DSR probability</th></tr></thead>
            <tbody>{dsr_rows}</tbody>
          </table>
        </div>

        <h3 style="margin-top:26px">滚动窗口最差值</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>架构</th><th>3Y 最差主动 CAGR</th><th>3Y 正值比例</th><th>5Y 最差主动 CAGR</th><th>5Y 正值比例</th></tr></thead>
            <tbody>{rolling_rows}</tbody>
          </table>
        </div>

        <h3 style="margin-top:26px">2020 前后均值检验</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>变量 / 架构</th><th>2020 前</th><th>2020 后</th><th>差值</th><th>Block bootstrap 95%</th><th>方向翻转</th></tr></thead>
            <tbody>{break_rows}</tbody>
          </table>
        </div>

        <div class="split" style="margin-top:28px">
          <div>
            <h3>2009-11 缺失月份</h3>
            <div class="audit-list">
              <div class="audit-row"><span>执行规则</span><strong>不调仓，上一期持仓按实际收益漂移</strong></div>
              <div class="audit-row"><span>持仓集合</span><strong>{int(drift["prior_holdings"])} → {int(drift["drift_holdings"])}，完全相同</strong></div>
              <div class="audit-row"><span>权重变化</span><strong>{int(drift["changed_weight_count"])} 只证券发生变化</strong></div>
              <div class="audit-row"><span>归一化</span><strong>前后权重和均为 1，验证通过</strong></div>
            </div>
          </div>
          <div>
            <h3>数据契约</h3>
            <div class="audit-list">
              <div class="audit-row"><span>Benchmark 快照</span><strong>{audit["benchmark_rebalance_snapshots"]} 个，{audit["benchmark_start"][:10]} 至 {audit["benchmark_end"][:10]}</strong></div>
              <div class="audit-row"><span>日收益覆盖</span><strong>{audit["active_security_day_coverage"]:.4%}</strong></div>
              <div class="audit-row"><span>证券主键</span><strong>(ISIN, Date)；收益以 SEDOL 连接</strong></div>
              <div class="audit-row"><span>未验证风险</span><strong>财务字段缺逐行 publication timestamp</strong></div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </main>

  <footer>
    <div class="wrap">
      <p>所有结论来自已完成的 official exact Top/Worst 路径。页面无外部脚本、无网络请求；JavaScript 仅增强页签与曲线切换，禁用后全部研究区块仍可阅读。</p>
      <p>研究目录：<code>{escape(str(RUN_DIR))}</code></p>
    </div>
  </footer>

  <script id="research-data" type="application/json">{evidence_json}</script>
  <script>
    document.documentElement.classList.add('enhanced');
    const report = JSON.parse(document.getElementById('research-data').textContent);
    const tabs = [...document.querySelectorAll('[data-tab]')];
    const panels = [...document.querySelectorAll('[data-panel]')];
    const pct = value => value == null ? '—' : `${{(Number(value) * 100).toFixed(2)}}%`;
    const num = value => value == null ? '—' : Number(value).toFixed(2);

    function activateTab(name) {{
      tabs.forEach(tab => tab.classList.toggle('active', tab.dataset.tab === name));
      panels.forEach(panel => panel.hidden = panel.dataset.panel !== name);
      window.scrollTo({{top: document.querySelector('nav').offsetTop, behavior:'smooth'}});
    }}
    tabs.forEach(tab => tab.addEventListener('click', () => activateTab(tab.dataset.tab)));
    panels.forEach(panel => panel.hidden = panel.dataset.panel !== 'overview');

    function chartMarkup(data) {{
      if (!data.length) return '<text x="50%" y="50%" text-anchor="middle" fill="#68737d">没有可显示的净值路径</text>';
      const width=1040, height=390, margin={{top:20,right:24,bottom:42,left:58}};
      const plotW=width-margin.left-margin.right, plotH=height-margin.top-margin.bottom;
      const values=data.flatMap(row=>[row.top,row.worst,row.benchmark]).filter(Number.isFinite);
      const min=Math.min(...values), max=Math.max(...values), pad=Math.max((max-min)*.08,4);
      const low=min-pad, high=max+pad;
      const x=index=>margin.left+index/Math.max(data.length-1,1)*plotW;
      const y=value=>margin.top+(high-value)/Math.max(high-low,1)*plotH;
      let html='';
      for(let i=0;i<5;i++) {{
        const value=low+(high-low)*i/4, yy=y(value);
        html+=`<line x1="${{margin.left}}" y1="${{yy}}" x2="${{width-margin.right}}" y2="${{yy}}" stroke="#e3e7e9"/>`;
        html+=`<text x="${{margin.left-9}}" y="${{yy+4}}" text-anchor="end" fill="#6a747e" font-size="11">${{value.toFixed(0)}}</text>`;
      }}
      const ticks=[0,Math.floor((data.length-1)/3),Math.floor((data.length-1)*2/3),data.length-1];
      [...new Set(ticks)].forEach(index=>{{
        const anchor=index===0?'start':index===data.length-1?'end':'middle';
        html+=`<text x="${{x(index)}}" y="${{height-12}}" text-anchor="${{anchor}}" fill="#6a747e" font-size="11">${{data[index].date.slice(0,4)}}</text>`;
      }});
      [['top','#087b63',2.8],['worst','#b14f45',2.2],['benchmark','#316fa1',2.2]].forEach(([key,color,stroke])=>{{
        const points=data.map((row,index)=>`${{x(index).toFixed(2)}},${{y(row[key]).toFixed(2)}}`).join(' ');
        html+=`<polyline data-series="${{key}}" points="${{points}}" fill="none" stroke="${{color}}" stroke-width="${{stroke}}" stroke-linejoin="round" stroke-linecap="round"/>`;
      }});
      return html;
    }}

    function renderCandidate(metric) {{
      const item=report.charts[metric];
      if(!item) return;
      document.getElementById('chart-title').textContent=item.name;
      document.getElementById('chart-meta').textContent=`Coverage ${{pct(item.coverage)}} · 主动 CAGR ${{pct(item.activeCagr)}} · Robust ${{num(item.robustScore)}}`;
      document.getElementById('chart-note').textContent=item.note;
      document.getElementById('nav-chart').innerHTML=chartMarkup(item.nav);
    }}
    document.getElementById('candidate-select').addEventListener('change', event => renderCandidate(event.target.value));
  </script>
</body>
</html>
"""


@recorded_workflow
def main() -> int:
    args = parse_args()
    payload = build_payload(args.run_dir.resolve())
    html = build_html(payload)
    for path in (args.output.resolve(), args.source_copy.resolve()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "complete",
                "output": str(args.output.resolve()),
                "source_copy": str(args.source_copy.resolve()),
                "bytes": len(html.encode("utf-8")),
                "chart_count": len(payload["charts"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

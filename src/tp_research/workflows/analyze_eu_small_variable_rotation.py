"""Analyze EU Small raw-variable efficacy, pair synergy, and period rotations."""

from __future__ import annotations
from tp_experiments.artifacts import experiment_plots_enabled
from tp_research.runtime import recorded_workflow

import argparse
import json
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


from tp_research.paths import SCRIPT_DIR
from tp_research.paths import BACKTEST_ROOT
from tp_research.paths import TP_ROOT
AD_HOC_ROOT = BACKTEST_ROOT / "runs" / "ad_hoc"

from tp_research.workflows import run_eu_small_multifactor_research as base  # noqa: E402
from tp_research.workflows import run_eu_small_validated_gate_research as gate_runner  # noqa: E402


DEFAULT_RAW_RUN_DIR = AD_HOC_ROOT / "eu_small_multifactor_20260707_085611"
DEFAULT_VALIDATED_RUN_DIR = AD_HOC_ROOT / "eu_small_validated_gate_20260708_official"

PERIODS = [
    ("2005-2007", "Pre-GFC credit expansion", "2005-03-31", "2007-12-31"),
    ("2008-2012", "GFC and euro sovereign crisis", "2008-01-01", "2012-12-31"),
    ("2013-2016", "ECB low-rate/QE transition", "2013-01-01", "2016-12-31"),
    ("2017-2019", "Late-cycle low-rate expansion", "2017-01-01", "2019-12-31"),
    ("2020-2021", "COVID shock and policy rebound", "2020-01-01", "2021-12-31"),
    ("2022-2023", "Inflation, energy and rate shock", "2022-01-01", "2023-12-31"),
    ("2024-2026", "Disinflation and policy normalization", "2024-01-01", "2026-06-30"),
]


ECONOMIC_NOTES = {
    "quality": "质量变量衡量小盘公司是否已经有真实盈利能力和资产负债表韧性；在融资条件收紧或增长稀缺时，市场更愿意给可验证现金流和低财务风险溢价。",
    "value": "价值变量衡量现金流/盈利相对价格是否便宜；在小盘股里，廉价但能产生现金的公司通常反映过度折价、流动性折价或周期悲观定价。",
    "momentum": "动量和盈利修正变量捕捉信息扩散和预期上修；小盘覆盖度低、研究员反应慢，价格趋势和 EPS revision 更容易延续。",
    "dividend": "股息变量在欧洲小盘更像资本纪律和现金回报信号，但单独使用容易混入高派息压力或低增长陷阱。",
    "growth": "增长变量只有 EPS FY1 通过 gate，说明市场奖励的是已经落到盈利预期的增长，而不是销售/收入扩张本身。",
    "lowvol": "低波变量的 Worst 端有避雷价值，但 Top/Benchmark ratio CAGR 没过 gate；在欧洲小盘中，低波更像防守过滤器而不是独立 alpha 来源。",
}

PERIOD_NOTES = {
    "2005-2007": (
        "危机前信用扩张和风险偏好较强，欧洲小盘更愿意奖励盈利预期改善和价格趋势延续。"
        "本期领先的是 Quality + Momentum、QVM 和 momentum family，说明市场不是单纯买便宜，"
        "而是买“盈利/预期正在被验证”的小盘公司。"
    ),
    "2008-2012": (
        "金融危机和欧债危机阶段，融资可得性和资产负债表风险成为核心约束。"
        "Quality、ROE、利润率、低杠杆与 dividend+quality 组合领先，说明小盘股中最重要的是活下来、"
        "保持盈利和不被再融资风险吞噬。"
    ),
    "2013-2016": (
        "ECB 低利率和 QE 过渡期让风险资产估值修复，但欧洲增长仍不强。"
        "PFCF 与 value/momentum、growth/value 的组合靠前，说明市场奖励现金流便宜，同时需要趋势或增长确认，"
        "单纯销售增长仍不是优势。"
    ),
    "2017-2019": (
        "低利率后周期扩张阶段，盈利质量重新成为主线。"
        "Oper Margin、ROE、Quality family 和 PMOM+margin 组合领先，说明此时市场看重经营杠杆和盈利韧性，"
        "而不是高 beta 或低波。"
    ),
    "2020-2021": (
        "COVID 冲击和政策反弹阶段，最强的是 EPS NTM 3M Growth、EPS Revision Ratio、NetDebt/EBITDA 与 revision+quality。"
        "这符合疫情后预期快速重估：市场先奖励盈利预期上修，同时避开财务杠杆过高的小盘公司。"
    ),
    "2022-2023": (
        "通胀、能源和加息冲击使现金流折现率上升。"
        "本期明显转向 PFCF、Dividend Yield、Quality+Value 和 Dividend+Quality：市场奖励即时现金流、估值安全边际和资本纪律，"
        "对长久期成长和脆弱资产负债表更苛刻。"
    ),
    "2024-2026": (
        "通胀回落与政策正常化阶段，动量重新有效，但仍需要股息或价值确认。"
        "Dividend Yield + PMOM、EPS Revision + PFCF、validated QVM 和 no-growth 组合领先，说明市场偏好现金回报、趋势确认和便宜现金流，"
        "对纯 growth 仍保持谨慎。"
    ),
}

EXTERNAL_REFERENCES = [
    {
        "title": "ECB key interest rates",
        "url": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/key_ecb_interest_rates/html/index.en.html",
        "use": "利率周期与 2022-2026 政策正常化背景。",
    },
    {
        "title": "ECB Pandemic Emergency Purchase Programme",
        "url": "https://www.ecb.europa.eu/mopo/implement/pepp/html/index.en.html",
        "use": "2020-2021 疫情政策支持与风险资产反弹背景。",
    },
    {
        "title": "ECB APP early assessment",
        "url": "https://www.ecb.europa.eu/pub/pdf/scpwps/ecbwp1956.en.pdf",
        "use": "2015 后 QE/低利率对资产估值和融资环境的解释。",
    },
    {
        "title": "Eurostat inflation in the euro area",
        "url": "https://ec.europa.eu/eurostat/statistics-explained/index.php?title=Inflation_in_the_euro_area",
        "use": "2021-2023 通胀与能源冲击、2024-2026 通胀回落背景。",
    },
    {
        "title": "Fama and French, A five-factor asset pricing model",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2287202",
        "use": "value/profitability 对截面收益的理论框架。",
    },
    {
        "title": "Novy-Marx, The Other Side of Value",
        "url": "https://www.nber.org/papers/w15940",
        "use": "profitability 与 value 互补的经济解释。",
    },
    {
        "title": "Jegadeesh and Titman, Returns to Buying Winners and Selling Losers",
        "url": "https://ideas.repec.org/a/bla/jfinan/v48y1993i1p65-91.html",
        "use": "momentum / 信息扩散的文献基础。",
    },
    {
        "title": "Asness, Moskowitz and Pedersen, Value and Momentum Everywhere",
        "url": "https://www.aqr.com/Insights/Research/Journal-Article/Value-and-Momentum-Everywhere",
        "use": "value 与 momentum 的互补和跨资产共性。",
    },
]


def load_gate(validated_run_dir: Path) -> pd.DataFrame:
    gate = pd.read_csv(validated_run_dir / "raw_validation_gate.csv")
    gate["pass_gate"] = gate["pass_gate"].astype(bool)
    return gate


def build_pair_screen(raw_run_dir: Path, gate: pd.DataFrame, output_dir: Path) -> tuple[pd.DataFrame, list[base.ModelSpec], pd.DataFrame]:
    screen = pd.read_parquet(raw_run_dir / "eu_small_multifactor_screen.parquet")
    passing = gate[gate["pass_gate"]].sort_values(["raw_family", "robust_score"], ascending=[True, False]).reset_index(drop=True)
    raw_lookup = passing.set_index("metric").to_dict(orient="index")
    pair_specs: list[base.ModelSpec] = []
    pair_rows: list[dict[str, Any]] = []
    for idx, (left, right) in enumerate(combinations(passing["metric"].tolist(), 2), start=1):
        column = f"eu_small_pair_{idx:03d}"
        screen[column] = base.average_scores(screen, [left, right], min_count=2)
        left_info = raw_lookup[left]
        right_info = raw_lookup[right]
        components = {left: 0.5, right: 0.5}
        label = f"{left_info['label']} + {right_info['label']}"
        family_pair = "+".join(sorted({str(left_info["raw_family"]), str(right_info["raw_family"])}))
        pair_specs.append(
            base.ModelSpec(
                column=column,
                label=label,
                family=f"pair_{family_pair}",
                components=components,
                note="equal-weight pair of raw variables that passed the official raw gate; min_count=2",
            )
        )
        pair_rows.append(
            {
                "metric": column,
                "left_metric": left,
                "right_metric": right,
                "left_label": left_info["label"],
                "right_label": right_info["label"],
                "left_family": left_info["raw_family"],
                "right_family": right_info["raw_family"],
                "family_pair": family_pair,
                "left_robust_score": left_info["robust_score"],
                "right_robust_score": right_info["robust_score"],
                "left_ratio_cagr": left_info["ratio_cagr"],
                "right_ratio_cagr": right_info["ratio_cagr"],
            }
        )
    pair_map = pd.DataFrame(pair_rows)
    screen_path = output_dir / "eu_small_variable_pair_screen.parquet"
    screen.to_parquet(screen_path, index=False)
    pair_map.to_csv(output_dir / "pair_definitions.csv", index=False, encoding="utf-8-sig")
    (output_dir / "metric_definitions.json").write_text(
        json.dumps([spec.__dict__ for spec in pair_specs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return screen, pair_specs, pair_map


def _nav_window(nav: pd.Series, start: str, end: str) -> pd.Series:
    if nav.empty:
        return nav
    idx = pd.to_datetime(nav.index, errors="coerce")
    window = nav[(idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))].dropna()
    return window


def _window_stats(nav: pd.Series, start: str, end: str) -> dict[str, float | bool]:
    window = _nav_window(nav, start, end)
    if len(window) < 2 or not np.isfinite(window.iloc[0]) or window.iloc[0] == 0:
        return {"valid": False, "return": np.nan, "cagr": np.nan, "max_drawdown": np.nan}
    years = max((pd.Timestamp(window.index[-1]) - pd.Timestamp(window.index[0])).days / 365.25, 1 / 12)
    total = float(window.iloc[-1] / window.iloc[0] - 1.0)
    cagr = float((window.iloc[-1] / window.iloc[0]) ** (1.0 / years) - 1.0)
    mdd = float((window / window.cummax() - 1.0).min())
    return {"valid": True, "return": total, "cagr": cagr, "max_drawdown": mdd}


def period_rows(run_results: pd.DataFrame, metric_meta: pd.DataFrame, source: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    successes = run_results[run_results["status"].eq("success")].copy()
    meta = metric_meta.set_index("metric").to_dict(orient="index") if not metric_meta.empty else {}
    for metric, group in successes.groupby("metric", observed=True):
        top = group[group["side"].eq("Top")]
        worst = group[group["side"].eq("Worst")]
        if top.empty or worst.empty:
            continue
        top_row = top.iloc[0]
        worst_row = worst.iloc[0]
        top_nav = base.read_nav(str(top_row.get("perf_ptf", "")))
        bench_nav = base.read_nav(str(top_row.get("perf_bench", "")))
        worst_nav = base.read_nav(str(worst_row.get("perf_ptf", "")))
        for period, period_label, start, end in PERIODS:
            top_stats = _window_stats(top_nav, start, end)
            bench_stats = _window_stats(bench_nav, start, end)
            worst_stats = _window_stats(worst_nav, start, end)
            ratio_stats = {"valid": False, "return": np.nan, "cagr": np.nan, "max_drawdown": np.nan}
            tw_stats = {"valid": False, "return": np.nan, "cagr": np.nan, "max_drawdown": np.nan}
            aligned_tb = pd.concat(
                [_nav_window(top_nav, start, end).rename("top"), _nav_window(bench_nav, start, end).rename("bench")],
                axis=1,
            ).dropna()
            if len(aligned_tb) >= 2 and aligned_tb["bench"].iloc[0] != 0:
                ratio_stats = _window_stats(aligned_tb["top"] / aligned_tb["bench"], start, end)
            aligned_tw = pd.concat(
                [_nav_window(top_nav, start, end).rename("top"), _nav_window(worst_nav, start, end).rename("worst")],
                axis=1,
            ).dropna()
            if len(aligned_tw) >= 2 and aligned_tw["worst"].iloc[0] != 0:
                tw_stats = _window_stats(aligned_tw["top"] / aligned_tw["worst"], start, end)
            period_robust = (
                np.nan_to_num(ratio_stats["cagr"], nan=0.0)
                + 0.5 * np.nan_to_num(tw_stats["return"], nan=0.0)
                - 2.0 * abs(np.nan_to_num(ratio_stats["max_drawdown"], nan=0.0))
            )
            rows.append(
                {
                    "source": source,
                    "metric": metric,
                    "period": period,
                    "period_label": period_label,
                    "start": start,
                    "end": end,
                    "top_return": top_stats["return"],
                    "top_cagr": top_stats["cagr"],
                    "benchmark_cagr": bench_stats["cagr"],
                    "worst_cagr": worst_stats["cagr"],
                    "ratio_return": ratio_stats["return"],
                    "ratio_cagr": ratio_stats["cagr"],
                    "ratio_max_drawdown": ratio_stats["max_drawdown"],
                    "top_worst_return": tw_stats["return"],
                    "top_worst_cagr": tw_stats["cagr"],
                    "period_robust_score": float(period_robust),
                    **meta.get(metric, {}),
                }
            )
    return pd.DataFrame(rows)


def _fmt_pct(value: Any, digits: int = 1) -> str:
    try:
        if pd.isna(value):
            return ""
        return f"{float(value) * 100:.{digits}f}%"
    except Exception:
        return str(value)


def _short_metric_label(row: pd.Series) -> str:
    for key in ("label", "pair_label", "metric"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return str(row.get("metric", ""))


def write_plotly(period_stats: pd.DataFrame, pair_summary: pd.DataFrame, output_dir: Path) -> list[str]:
    if not experiment_plots_enabled():
        return []
    try:
        import plotly.express as px
    except Exception:
        return []
    plot_dir = output_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    top_period = (
        period_stats[period_stats["source"].isin(["raw", "pair", "validated"])]
        .sort_values(["period", "period_robust_score"], ascending=[True, False])
        .groupby("period", as_index=False, observed=True)
        .head(12)
    )
    if not top_period.empty:
        fig = px.bar(
            top_period,
            x="metric",
            y="period_robust_score",
            color="source",
            facet_col="period",
            facet_col_wrap=2,
            hover_data=["ratio_cagr", "top_worst_return", "ratio_max_drawdown"],
            title="EU Small variable and pair rotation by period",
        )
        path = plot_dir / "period_rotation_top_metrics.html"
        fig.write_html(path)
        paths.append(str(path))
    if not pair_summary.empty and "synergy_score" in pair_summary.columns:
        top_pairs = pair_summary.sort_values("synergy_score", ascending=False).head(30)
        fig = px.bar(
            top_pairs,
            x="metric",
            y="synergy_score",
            color="family_pair",
            hover_data=["left_label", "right_label", "robust_score", "ratio_cagr", "top_worst_ratio_return"],
            title="Raw-variable pair synergy score",
        )
        path = plot_dir / "pair_synergy_top30.html"
        fig.write_html(path)
        paths.append(str(path))
    return paths


def write_report(
    *,
    output_dir: Path,
    gate: pd.DataFrame,
    raw_summary: pd.DataFrame,
    pair_summary: pd.DataFrame,
    validated_summary: pd.DataFrame,
    period_stats: pd.DataFrame,
    plot_paths: list[str],
    sources: list[str],
) -> Path:
    passed = gate[gate["pass_gate"]].copy()
    raw_top = raw_summary[(raw_summary["status"].eq("success")) & (raw_summary["side"].eq("Top"))].copy()
    raw_top = raw_top[raw_top["family"].astype("string").str.startswith("raw_", na=False)]
    raw_top = raw_top.merge(gate[["metric", "raw_family", "pass_gate", "failure_reasons"]], on="metric", how="left")
    effective_raw = raw_top[raw_top["pass_gate"].fillna(False)].sort_values("robust_score", ascending=False)
    rejected_raw = raw_top[~raw_top["pass_gate"].fillna(False)].sort_values("robust_score", ascending=False)
    pair_top = pair_summary.sort_values("synergy_score", ascending=False).copy()
    validated_top = validated_summary[(validated_summary["status"].eq("success")) & (validated_summary["side"].eq("Top"))].sort_values("robust_score", ascending=False)

    family_table = passed.groupby("raw_family", observed=True).agg(
        passed_variables=("metric", "count"),
        avg_robust=("robust_score", "mean"),
        avg_ratio_cagr=("ratio_cagr", "mean"),
    ).reset_index()

    lines = [
        "# 欧洲小盘股 raw variable 有效性、协同效应与时期 rotation 研究报告",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- Universe / Benchmark: `MSCI EUR SMALL`，`Weight in MSCI EUR SMALL > 0`。",
        "- raw 变量证据: 47 个 raw score 全部使用 official Top/Worst。",
        "- 协同证据: 12 个通过 raw gate 的变量两两组合，共 66 个 pair，全部使用 official Top/Worst。",
        "- 时期分析: 不重新拟合信号，直接从 official NAV 切分时期，属于 official run 的期间归因。",
        "- gate: coverage >= 75%，Top/Benchmark ratio CAGR > 0，Top/Worst ratio return > 0，robust score > 0。",
        "",
        "## 1. 全时期结论摘要",
        "",
        "### 1.1 单个变量：真正适应欧洲小盘市场的是什么？",
        "",
        base.frame_to_markdown(
            effective_raw[
                [
                    "metric",
                    "label",
                    "raw_family",
                    "coverage",
                    "ratio_cagr",
                    "top_worst_ratio_return",
                    "ratio_max_drawdown",
                    "rolling_3y_min_ratio_cagr",
                    "annual_active_hit_rate",
                    "robust_score",
                ]
            ],
            max_rows=30,
        ),
        "",
        "经济解释：",
        "",
    ]
    for family in ["quality", "value", "momentum", "dividend", "growth", "lowvol"]:
        lines.append(f"- **{family}**：{ECONOMIC_NOTES[family]}")

    lines.extend(
        [
            "",
            "### 1.2 Family 层面的证据",
            "",
            base.frame_to_markdown(family_table, max_rows=20),
            "",
            "解释：Quality、Value、Momentum 是最可复用的三条主线。Dividend 有有效变量，但更像现金纪律/收益率补充；Growth 只有 EPS FY1 过关，说明市场奖励可落地的盈利增长，而不是销售或 CIQ 长期增长字段。LowVol 没有进入 validated family。",
            "",
            "### 1.3 变量组合：哪些 pair 有协同？",
            "",
            base.frame_to_markdown(
                pair_top[
                    [
                        "metric",
                        "left_label",
                        "right_label",
                        "family_pair",
                        "coverage",
                        "ratio_cagr",
                        "top_worst_ratio_return",
                        "ratio_max_drawdown",
                        "robust_score",
                        "synergy_score",
                    ]
                ],
                max_rows=25,
            ),
            "",
            "协同判定不是看名字是否好听，而是看 pair 的 robust score 是否超过两个单变量中更强的一边，并且 Top/Benchmark 与 Top/Worst 同时为正。正 synergy 的组合，本质是把“便宜、赚钱、趋势/预期上修”三种不同误定价来源叠加在同一批公司上。",
            "",
            "### 1.4 变量组：validated family/subset 的全时期结果",
            "",
            base.frame_to_markdown(
                validated_top[
                    [
                        "metric",
                        "family",
                        "coverage",
                        "ratio_cagr",
                        "top_worst_ratio_return",
                        "ratio_max_drawdown",
                        "rolling_3y_min_ratio_cagr",
                        "annual_active_hit_rate",
                        "robust_score",
                    ]
                ],
                max_rows=25,
            ),
            "",
            "全时期最稳的是 `eu_small_validated_qvm`，也就是 Quality 40% + Value 30% + Momentum 30%。它不是最高 beta 的进攻模型，而是把小盘股里最容易被错杀的“盈利质量 + 现金流估值 + 预期/价格确认”叠在一起。",
            "",
            "## 2. 被拒绝变量也重要：为什么有些直觉上合理的变量没过关？",
            "",
            base.frame_to_markdown(
                rejected_raw[
                    [
                        "metric",
                        "label",
                        "family",
                        "role",
                        "coverage",
                        "ratio_cagr",
                        "top_worst_ratio_return",
                        "robust_score",
                        "failure_reasons",
                    ]
                ].sort_values(["family", "failure_reasons", "robust_score"], ascending=[True, True, False]),
                max_rows=80,
            ),
            "",
            "- CIQ 长期增长字段没有因为来源被排除，而是同一套 gate 下没有通过：覆盖率低，且 Top/Benchmark 与 Top/Worst 证据弱。",
            "- 低波变量没有通过默认 gate：`Daily Vol 60J/90J` 有一定 Top/Worst 分化，但 Top/Benchmark ratio CAGR 没转正，所以更适合作为风险过滤候选，不应被称为独立 alpha。",
            "- 传统估值倍数如 PB、PE、EV/Sales 在欧洲小盘里容易买到价值陷阱；真正有效的是 PFCF 和 earnings yield 这类更接近现金/盈利回报的指标。",
            "",
            "## 3. 分时期 rotation：哪些变量或变量组在不同市场阶段占优？",
            "",
        ]
    )

    for period, period_label, _, _ in PERIODS:
        subset = period_stats[period_stats["period"].eq(period)].sort_values("period_robust_score", ascending=False)
        lines.extend(
            [
                f"### {period}：{period_label}",
                "",
                base.frame_to_markdown(
                    subset[
                        [
                            "source",
                            "metric",
                            "label",
                            "family",
                            "ratio_cagr",
                            "ratio_max_drawdown",
                            "top_worst_return",
                            "period_robust_score",
                        ]
                    ],
                    max_rows=15,
                ),
                "",
            ]
        )
        lines.append(f"阶段解释：{PERIOD_NOTES.get(period, '')}")
        lines.append("")

    lines.extend(
        [
            "## 4. 宏观与文献解释框架",
            "",
            "- 2008 危机后，欧洲小盘的估值折价只有在盈利质量确认时才更可靠；这和 Fama-French 五因子框架中 profitability 与 value 对截面收益的共同解释是一致的。",
            "- 盈利能力/质量有独立信息。Novy-Marx 的 gross profitability 研究指出，盈利能力能与价值互补，这也解释了为什么 Quality + Value 的组合比单纯低估值更稳。",
            "- Momentum 与 revision 在小盘股里尤其重要，因为覆盖不足导致信息扩散慢；Jegadeesh-Titman 的相对强弱证据和我们这里的 PMOM/EPS revision 结果方向一致。",
            "- Value 与 Momentum 的互补来自不同风险来源：value 更像便宜资产的再定价，momentum/revision 更像信息扩散和盈利预期确认。Asness/Moskowitz/Pedersen 也发现 value 与 momentum 在不同资产中具备共同结构且彼此互补。",
            "- ECB 的政策周期帮助解释 rotation：2020-2021 的政策支持和 reopening 有利于 beta/预期修复；2022-2023 的通胀、能源和加息冲击提高了对质量、现金流和估值安全边际的要求。",
            "",
            "外部参考资料：",
            "",
        ]
    )
    lines.extend([f"- [{item['title']}]({item['url']})：{item['use']}" for item in EXTERNAL_REFERENCES])
    lines.extend(
        [
            "",
            "## 5. 投资含义",
            "",
            "1. 欧洲小盘的主模型应以 Quality + Value + Momentum 为核心，不应机械引入 LowVol。",
            "2. 单变量中最值得长期跟踪的是 ROE avg FY0、PFCF LTM、EPS Revision Ratio、Oper Margin、DVD Yield FY1、PMOM 12M1M、NetDebt to EBITDA exFIN。",
            "3. Growth 只能保留 EPS FY1 这种盈利落地变量；销售增长、gross income growth 和 CIQ 长期增长字段不应进入默认 family。",
            "4. Dividend 是辅助，不是主轴；股息收益率有效，但 payout pressure 单独反而失败，说明要避免高派息陷阱。",
            "5. 协同组合最有经济意义的是“盈利质量 + 现金流便宜 + 预期上修/价格确认”，这也是当前 `eu_small_validated_qvm` 的核心。",
            "",
            "## 6. 证据文件",
            "",
        ]
    )
    for path in plot_paths:
        lines.append(f"- Plotly: `{path}`")
    for source in sources:
        lines.append(f"- Source: {source}")
    report_path = output_dir / "eu_small_variable_rotation_research_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze EU Small raw variables, pair synergy, and rotations.")
    parser.add_argument("--raw-run-dir", default=str(DEFAULT_RAW_RUN_DIR))
    parser.add_argument("--validated-run-dir", default=str(DEFAULT_VALIDATED_RUN_DIR))
    parser.add_argument("--returns", default=str(base.DEFAULT_RETURNS))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    return parser


@recorded_workflow
def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    raw_run_dir = Path(args.raw_run_dir)
    validated_run_dir = Path(args.validated_run_dir)
    output_dir = Path(args.output_dir) if args.output_dir else AD_HOC_ROOT / f"eu_small_variable_rotation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir.mkdir(parents=True, exist_ok=True)

    gate = load_gate(validated_run_dir)
    screen, pair_specs, pair_map = build_pair_screen(raw_run_dir, gate, output_dir)
    research_screen_path = output_dir / "eu_small_variable_pair_screen.parquet"
    metric_diag = base.metric_diagnostics(screen, pair_specs, [])
    metric_diag.to_csv(output_dir / "metric_diagnostics.csv", index=False)

    returns_path = Path(args.returns)
    returns = base.load_tabular_file(returns_path)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index()

    existing_results_path = output_dir / "official_run_results.csv"
    run_results = pd.DataFrame()
    if args.report_only and existing_results_path.exists():
        run_results = pd.read_csv(existing_results_path)
    elif not args.report_only:
        existing_results = pd.read_csv(existing_results_path) if args.resume and existing_results_path.exists() else None
        try:
            run_root_name = output_dir.resolve().relative_to((BACKTEST_ROOT / "runs").resolve()).as_posix()
        except ValueError:
            run_root_name = f"ad_hoc/{base.slugify(output_dir.name)}"
        run_results = gate_runner.run_official_backtests_incremental(
            screen=screen,
            returns=returns,
            screen_path=research_screen_path,
            returns_path=returns_path,
            run_root_name=run_root_name,
            metrics=[spec.column for spec in pair_specs],
            max_runs=args.max_runs,
            results_path=existing_results_path,
            existing_results=existing_results,
        )
    run_results.to_csv(existing_results_path, index=False)

    pair_summary = base.summarize_runs(run_results, metric_diag)
    pair_top = pair_summary[(pair_summary["status"].eq("success")) & (pair_summary["side"].eq("Top"))].copy()
    pair_top = pair_top.merge(pair_map, on="metric", how="left")
    pair_top["max_leg_robust"] = pair_top[["left_robust_score", "right_robust_score"]].max(axis=1)
    pair_top["synergy_score"] = pair_top["robust_score"] - pair_top["max_leg_robust"]
    pair_top.to_csv(output_dir / "pair_synergy_summary.csv", index=False, encoding="utf-8-sig")
    pair_summary.to_csv(output_dir / "performance_summary.csv", index=False)

    raw_run_results = pd.read_csv(raw_run_dir / "official_run_results.csv")
    raw_summary = pd.read_csv(raw_run_dir / "performance_summary.csv")
    validated_run_results = pd.read_csv(validated_run_dir / "official_run_results.csv")
    validated_summary = pd.read_csv(validated_run_dir / "performance_summary.csv")

    raw_meta = raw_summary[raw_summary["side"].eq("Top")][["metric", "label", "family", "role", "coverage", "robust_score"]].drop_duplicates("metric")
    pair_meta = pair_top[
        ["metric", "label", "family", "coverage", "robust_score", "left_label", "right_label", "family_pair", "synergy_score"]
    ].drop_duplicates("metric")
    validated_meta = validated_summary[validated_summary["side"].eq("Top")][["metric", "label", "family", "coverage", "robust_score"]].drop_duplicates("metric")
    period_stats = pd.concat(
        [
            period_rows(raw_run_results, raw_meta, "raw"),
            period_rows(run_results, pair_meta, "pair"),
            period_rows(validated_run_results, validated_meta, "validated"),
        ],
        ignore_index=True,
    )
    period_stats.to_csv(output_dir / "period_rotation_stats.csv", index=False, encoding="utf-8-sig")
    plot_paths = write_plotly(period_stats, pair_top, output_dir)

    report_path = write_report(
        output_dir=output_dir,
        gate=gate,
        raw_summary=raw_summary,
        pair_summary=pair_top,
        validated_summary=validated_summary,
        period_stats=period_stats,
        plot_paths=plot_paths,
        sources=[
            str(raw_run_dir / "performance_summary.csv"),
            str(validated_run_dir / "performance_summary.csv"),
            str(output_dir / "pair_synergy_summary.csv"),
            str(output_dir / "period_rotation_stats.csv"),
        ],
    )
    manifest = {
        "output_dir": str(output_dir),
        "raw_run_dir": str(raw_run_dir),
        "validated_run_dir": str(validated_run_dir),
        "research_screen": str(research_screen_path),
        "pair_count": int(len(pair_specs)),
        "expected_run_count": int(len(pair_specs) * 2),
        "run_count": int(len(run_results)),
        "success_count": int(run_results["status"].eq("success").sum()) if not run_results.empty else 0,
        "report": str(report_path),
        "plot_paths": plot_paths,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

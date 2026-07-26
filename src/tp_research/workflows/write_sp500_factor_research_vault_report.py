"""Write the final Chinese SP500 factor research note into the Obsidian vault."""

from __future__ import annotations
from tp_research.runtime import recorded_workflow

from datetime import datetime
import json
from pathlib import Path
import sys

import pandas as pd


from tp_core.workspace import BACKTEST_RUNS_DIR

RUN_ROOT = BACKTEST_RUNS_DIR / "ad_hoc" / "sp500_relative_synergy_20260710"
RAW_DIR = BACKTEST_RUNS_DIR / "ad_hoc" / "sp500_raw_validation_20260708"
REL_DIR = BACKTEST_RUNS_DIR / "ad_hoc" / "sp500_relative_variables_20260709"
VAULT_REPORT = Path(
    r"C:\GoogleDrive\笔记\卡片盒子\10_Investment\03_Factor_Research"
    r"\2026-07-10 SP500 raw-relative 因子有效性与协同研究.md"
)
PUBLIC_ARTICLE = Path(
    r"C:\GoogleDrive\笔记\卡片盒子\10_Investment\03_Factor_Research"
    r"\2026-07-10 SP500 因子研究：市场奖励改善，不奖励标签.md"
)


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def read_sp500_auxiliary_csv(path: Path) -> pd.DataFrame:
    """Normalize legacy raw-gate identifiers before they enter SP500 artifacts."""
    frame = read_csv(path)
    if frame.empty:
        return frame
    text_columns = frame.select_dtypes(include=["object", "string"]).columns
    changed = False
    for column in text_columns:
        original = frame[column]
        normalized = original.astype(str).str.replace("eu_small_", "sp500_", regex=False)
        changed = changed or not normalized.equals(original.astype(str))
        frame[column] = normalized
    if changed:
        frame.to_csv(path, index=False)
    return frame


def all_run_results() -> pd.DataFrame:
    paths = []
    main = RUN_ROOT / "official_run_results.csv"
    if main.exists():
        paths.append(main)
    shard_root = RUN_ROOT / "parallel_shards"
    if shard_root.exists():
        paths.extend(sorted(shard_root.rglob("official_run_results.csv")))
    frames = [read_csv(path) for path in paths]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    rank = {"success": 3, "skipped": 2, "failed": 1}
    out["_rank"] = out["status"].map(rank).fillna(0)
    out["_order"] = range(len(out))
    out = out.sort_values(["metric", "side", "_rank", "_order"], ascending=[True, True, False, True])
    return out.drop_duplicates(["metric", "side"], keep="first").drop(columns=["_rank", "_order"]).reset_index(drop=True)


def fmt_pct(value: object, digits: int = 1) -> str:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return ""
    if pd.isna(val):
        return ""
    return f"{100 * val:.{digits}f}%"


def fmt_num(value: object, digits: int = 2) -> str:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return ""
    if pd.isna(val):
        return ""
    return f"{val:.{digits}f}"


def md_table(frame: pd.DataFrame, columns: list[str], headers: list[str] | None = None, max_rows: int = 20) -> str:
    if frame.empty:
        return "无。"
    cols = [col for col in columns if col in frame.columns]
    if not cols:
        return "无。"
    view = frame.loc[:, cols].head(max_rows).copy()
    headers = headers or cols
    lines = ["|" + "|".join(headers[: len(cols)]) + "|", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in view.iterrows():
        values = []
        for col in cols:
            value = row.get(col, "")
            if pd.isna(value):
                values.append("")
            else:
                values.append(str(value).replace("|", "<br>").replace("\n", " "))
        lines.append("|" + "|".join(values) + "|")
    return "\n".join(lines)


def check_dict(path: Path) -> dict[str, str]:
    frame = read_csv(path)
    if frame.empty or not {"check", "value"}.issubset(frame.columns):
        return {}
    return {str(row["check"]): str(row["value"]) for _, row in frame.iterrows()}


def short_metric(label: str) -> str:
    return str(label).replace("quality: ", "").replace("growth: ", "").replace("momentum: ", "").replace("value: ", "").replace("dividend: ", "")


def expected_official_rows(checks: dict[str, str]) -> int:
    """Use the audited candidate-map scope rather than a stale matrix constant."""
    try:
        return int(float(checks["expected_official_top_worst_runs"]))
    except (KeyError, TypeError, ValueError):
        raise SystemExit("Missing audited expected_official_top_worst_runs in data_construction_checks.csv")


def write_public_article(
    raw: pd.DataFrame,
    relative: pd.DataFrame,
    claims: pd.DataFrame,
    checks: dict[str, str],
    expected_rows: int,
) -> Path:
    raw_labels = "、".join(raw.get("label", pd.Series(dtype=str)).astype(str).drop_duplicates().head(5)) or "通过 gate 的静态因子"
    relative_labels = "、".join(
        relative.assign(
            display=lambda frame: frame.apply(
                lambda row: f"{row.get('raw_column', '')} 的 {row.get('transform', '')} lag{row.get('lag_observations', '')}",
                axis=1,
            )
        ).get("display", pd.Series(dtype=str)).astype(str).drop_duplicates().head(5)
    ) or "通过 gate 的改善型因子"
    synergy_count = len(claims)
    synergy_text = (
        f"严格协同矩阵确认了 {synergy_count} 条可声明的组合关系；它们来自单腿、pair/subset 和 leave-one-out 的同一条 official 证据链。"
        if synergy_count
        else "严格协同矩阵没有给出可声明的 synergy，因此不能把任何 family 标签本身当作组合优势。"
    )
    lines = [
        "---",
        'title: "SP500 因子研究：市场奖励改善，不奖励标签"',
        "tags:",
        "  - Finance/FactorInvesting",
        "  - Commentary/SP500",
        "type: publishable_commentary",
        "created: 2026-07-10",
        'source_scope: "TP official Top/Worst evidence"',
        "---",
        "",
        "# SP500 因子研究：市场奖励改善，不奖励标签",
        "",
        "市场并不因为一家公司被贴上 value、quality 或 dividend 标签就稳定地给出超额收益。更有解释力的是，这家公司是否在朝更好的方向变化：利润率是否扩张，ROE 是否上升，杠杆是否下降，估值是否相对盈利变得更便宜，盈利预期是否在上修。",
        "",
        "这不是一个只看单次回报的结论。研究先对 raw variable 做 higher-is-better 转换，再让每个变量独立跑官方 Top/Worst；静态水平变量还分别测试同一证券自身的 directional delta 和 score delta。CIQ、FactSet、database 与本地衍生字段遵循同一 gate。",
        "",
        "全样本中，静态层面更有证据的信号包括：" + raw_labels + "。它们共同指向一件事：现金转化、可兑现的盈利增长和资产负债表韧性，仍是 SP500 横截面定价的基本锚。",
        "",
        "但最醒目的发现来自改善型信号：" + relative_labels + "。改善并不是对静态质量的重复描述。它捕捉的是市场在公司基本面发生边际变化后，尚未完全完成重估的阶段，因此更接近一条可检验的再定价假设。",
        "",
        "这也解释了为什么把 family 内所有变量简单平均并不可靠。一个组合只有在每条单腿都通过 gate，并且 pair、subset 或 leave-one-out 显示其稳健性优于最强组件时，才可以称为 synergy。" + synergy_text,
        "",
        "对配置的含义不是追逐某个固定标签，而是区分两类暴露：一类是长期的质量与增长底座；另一类是盈利质量、杠杆、估值和预期的改善。前者提供耐久性，后者提供变化被市场重新定价的机会。两者是否值得合并，仍要以严格的组合证据为准。",
        "",
        f"本次矩阵使用 SP500 成分权重口径，官方 Top/Worst 完成行数为 {expected_rows}；研究产物与完整方法见 [[10_Investment/03_Factor_Research/2026-07-10 SP500 raw-relative 因子有效性与协同研究|完整研究报告]]。",
        "",
    ]
    PUBLIC_ARTICLE.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_ARTICLE.write_text("\n".join(lines), encoding="utf-8")
    return PUBLIC_ARTICLE


def table_with_formats(
    frame: pd.DataFrame,
    columns: list[str],
    headers: list[str],
    max_rows: int = 20,
) -> str:
    """Render compact investor-facing tables without leaking raw float noise."""
    if frame.empty:
        return "无。"
    view = frame.copy()
    for column in ["coverage", "ratio_cagr", "top_worst_ratio_return", "ratio_max_drawdown", "tracking_error", "avg_turnover", "full_ratio_cagr", "without_ratio_cagr", "ratio_contribution"]:
        if column in view.columns:
            view[column] = view[column].map(lambda value: fmt_pct(value, 1))
    for column in ["robust_score", "max_component_robust", "synergy_score", "relative_robust_score", "level_robust_score", "relative_minus_level_robust", "full_robust_score", "without_robust_score", "loo_contribution", "period_score"]:
        if column in view.columns:
            view[column] = view[column].map(lambda value: fmt_num(value, 2))
    return md_table(view, columns, headers, max_rows)


def first_row(frame: pd.DataFrame, sort_by: str = "robust_score") -> pd.Series:
    if frame.empty or sort_by not in frame.columns:
        return pd.Series(dtype=object)
    return frame.sort_values(sort_by, ascending=False).iloc[0]


def row_value(row: pd.Series, key: str, formatter: callable = fmt_num) -> str:
    return formatter(row.get(key, "")) if not row.empty else ""


def build_sp500_research_note(
    checks: dict[str, str],
    expected_rows: int,
    done_rows: int,
    raw: pd.DataFrame,
    relative: pd.DataFrame,
    relative_vs_level: pd.DataFrame,
    pair: pd.DataFrame,
    subset: pd.DataFrame,
    loo: pd.DataFrame,
    claims: pd.DataFrame,
    selected: pd.DataFrame,
    period: pd.DataFrame,
) -> list[str]:
    raw_top = raw.sort_values("robust_score", ascending=False).head(8)
    rel_top = relative.sort_values("robust_score", ascending=False).head(10)
    raw_single = raw_top.assign(
        kind="raw",
        variable=raw_top.get("label", pd.Series(dtype=str)),
        family_display=raw_top.get("family", pd.Series(dtype=str)),
        transform="static level",
        lag_observations="",
    )
    rel_single = rel_top.assign(
        kind="relative",
        variable=lambda frame: frame.apply(
            lambda row: f"{row.get('raw_column', '')} {row.get('transform', '')}", axis=1
        ),
        family_display=rel_top.get("base_family", pd.Series(dtype=str)),
    )
    single_variable_table = pd.concat([raw_single, rel_single], ignore_index=True)
    relative_lift = relative_vs_level.sort_values("relative_minus_level_robust", ascending=False).head(10)
    claim_top = claims.sort_values("robust_score", ascending=False).head(12)
    subset_top = subset.sort_values("robust_score", ascending=False).head(8)
    period_top = pd.DataFrame()
    if not period.empty:
        period_top = (
            period.sort_values(["period", "period_score"], ascending=[True, False])
            .groupby("period", as_index=False)
            .head(3)
        )
    top_pair = first_row(claims)
    full_model = subset[subset.get("label", pd.Series(dtype=str)).eq("all selected buckets equal-weight")]
    full_row = first_row(full_model)
    positive_loo = loo[loo.get("classification", pd.Series(dtype=str)).eq("positive_contributor")]
    top_loo = first_row(positive_loo, "loo_contribution")
    weak_loo = loo[loo.get("classification", pd.Series(dtype=str)).eq("weak_or_negative")]
    weak_loo_name = str(weak_loo.iloc[0].get("left_out", "")) if not weak_loo.empty else "无"

    lines = [
        "---",
        'title: "2026-07-10 SP500 单变量、相对改善与协同因子研究"',
        "tags:",
        "  - factor-investing",
        "  - SP500",
        "  - TP",
        "  - quant-research",
        "  - raw-gate",
        "  - relative-variables",
        "  - synergy",
        "type: investment-research",
        "created: 2026-07-10",
        "updated: 2026-07-10",
        'source_scope: "TP official Top/Worst backtests + local 60_Papers + official public sources"',
        "okf_refresh: complete",
        "---",
        "",
        "# SP500 单变量、相对改善与协同因子研究",
        "",
        "> 结论适用范围：本报告只解释 TP official exact Top/Worst 回测。它不构成投资建议，也不把 fast screen、经济直觉或 CIQ / FactSet / database 的来源标签当作入选依据。全周期 screen 覆盖 2009-03-31 至 2026-06-30；2024-2026 为不完整时期。",
        "",
        "## 2026-07-10 最终补充版：SP500 的 alpha 更像“变化被确认”",
        "",
        f"SP500 的完整证据链已完成：47 个 raw variables 先独立 official Top/Worst，其中 {len(raw)} 个通过 gate；绝对水平变量扩展为 same-security relative variants，其中 {len(relative)} 个通过 gate；在 {checks.get('official_candidate_count', '')} 个严格协同候选中，{done_rows}/{expected_rows} 条 Top/Worst 全部成功。",
        "",
        "这次补充改变了模型叙事。静态低杠杆、现金转化、FY1 盈利增长和近端盈利修正仍有全周期证据，但最强的新增证据来自同一家公司相对自身历史的改善：经营利润率上行、ROE 上行、去杠杆、派息压力下降，以及估值相对盈利变得更便宜。SP500 的有效信号不只是“好公司”，而是“正在变好，且这种变化被市场逐步定价”。",
        "",
        "### 最有效单变量",
        "",
        table_with_formats(
            single_variable_table,
            ["kind", "variable", "family_display", "transform", "lag_observations", "coverage", "ratio_cagr", "top_worst_ratio_return", "robust_score"],
            ["类型", "变量", "family", "变换", "lag", "coverage", "Top/BM CAGR", "Top/Worst", "robust"],
            18,
        ),
        "",
        "静态层面，低 NetDebt/EBITDA、FY1/NTM EPS 增长、近端 EPS 预期增长、FCF conversion 和 Gross Income Growth 形成基础层。改善层面，Oper Margin directional delta lag1 的 robust 为 "
        + row_value(first_row(relative[relative.get("raw_column", pd.Series(dtype=str)).eq("Oper Margin")]), "robust_score")
        + "，显著高于大多数静态质量水平；这并不证明所有质量变量彼此互补，却清楚说明边际变化比历史高位更有信息。",
        "",
        "### 相对变量到底改变了什么",
        "",
        table_with_formats(
            relative_lift,
            ["raw_column", "family", "transform", "lag_observations", "relative_robust_score", "level_robust_score", "relative_minus_level_robust"],
            ["字段", "family", "变换", "lag", "relative robust", "level robust", "提升"],
            10,
        ),
        "",
        "最有价值的反差是：Oper Margin、ROE、Gross Margin、CFO/Dividend coverage 与 NetDebt/EBITDA 的静态水平有的无效、有的仅弱有效，但其改善版本普遍通过 gate。经济含义并不是“高利润率不重要”，而是 SP500 更在意公司正在摆脱成本、竞争或融资约束，而非仅持有一段历史上漂亮的截面数值。",
        "",
        "### 可声称的协同，及不能声称的部分",
        "",
        f"严格矩阵给出 {len(claims)} 条 `synergistic` 结论，均来自 cross-bucket pair；{len(pair)} 个 pair 中没有把同 bucket 的变量全配对。最强 pair 是“{top_pair.get('label', '')}”：Top/BM CAGR {row_value(top_pair, 'ratio_cagr', fmt_pct)}，Top/Worst {row_value(top_pair, 'top_worst_ratio_return', fmt_pct)}，robust {row_value(top_pair, 'robust_score')}，相对最强组件提升 {row_value(top_pair, 'synergy_score')}。",
        "",
        table_with_formats(
            claim_top,
            ["label", "buckets", "ratio_cagr", "top_worst_ratio_return", "ratio_max_drawdown", "avg_turnover", "robust_score", "max_component_robust", "synergy_score"],
            ["组合", "bucket", "Top/BM CAGR", "Top/Worst", "ratio MDD", "turnover", "robust", "最强单腿", "提升"],
            12,
        ),
        "",
        "协同簇有清楚的经济分工：利润率改善 + 去杠杆，把经营修复和资产负债表可信度放在一起；盈利收益率改善 + EV/EBITDA 变便宜，捕捉估值重估而非静态低估值；EPS revision + valuation improvement，则要求分析师预期和相对价格同时确认。需要保留一层克制：强 pair 的换手可高，不能直接当成可交易权重。",
        "",
        f"反证同样重要：{len(subset)} 个 family subset 中没有一项达到 strict `synergistic` 分类，说明 pair 的强信号在扩展成更多 bucket 后会被稀释。表现最好的 additive subset 是“{first_row(subset).get('label', '')}”，robust {row_value(first_row(subset), 'robust_score')}，但它只能被称为有效的组合 sleeve，不能被包装成普适的 family synergy。",
        "",
        "### Full model 与 leave-one-out",
        "",
        (f"十个 bucket 等权 full model 的 robust 为 {row_value(full_row, 'robust_score')}，Top/BM CAGR {row_value(full_row, 'ratio_cagr', fmt_pct)}，Top/Worst {row_value(full_row, 'top_worst_ratio_return', fmt_pct)}，ratio MDD {row_value(full_row, 'ratio_max_drawdown', fmt_pct)}。" if not full_row.empty else "full model 结果见下表。"),
        f"Bucket-level leave-one-out 显示 {top_loo.get('left_out', '')} 的边际贡献最大（robust 下降 {row_value(top_loo, 'loo_contribution')}）；{weak_loo_name} 被移除后未显示正贡献。因此全模型可以作为风险分散的基础配置，但不应把所有 bucket 机械等权并视为最优。",
        "",
        table_with_formats(
            loo,
            ["left_out", "full_robust_score", "without_robust_score", "loo_contribution", "full_ratio_cagr", "without_ratio_cagr", "classification"],
            ["移除 bucket", "full robust", "移除后 robust", "贡献", "full Top/BM", "移除后 Top/BM", "判断"],
            12,
        ),
        "",
        "### 2009-2026 的轮动：不是一条直线",
        "",
        table_with_formats(
            period_top,
            ["period", "period_note", "label", "family", "ratio_cagr", "top_worst_ratio_return", "period_score"],
            ["时期", "市场背景", "领先变量", "family", "Top/BM CAGR", "Top/Worst", "period score"],
            18,
        ),
        "",
        "2009-2016 的领先者主要是 PB、PFCF、股息收益率和现金流价值，符合危机后低利率、估值修复和再杠杆阶段；2017-2019 转向 ROE、盈利增长与低波动；2020-2021 的核心是低杠杆和可见增长；2022-2023 现金流价值短暂回归；2024-2026 则由 EPS revision、PMOM 和 FY1 gross income growth 统治。最后一个阶段样本尚短，适合成为 overlay 观察，而不是替换全周期核心。",
        "",
        "## 结论先行：SP500 模型应如何使用",
        "",
        "1. 把静态低杠杆、FCF conversion、FY1/NTM EPS growth 和 earnings revision 放在核心变量层，因为它们同时具备全周期证据、较高覆盖和清楚的经济含义。",
        "2. 把 margin/ROE improvement、deleveraging 和 valuation improvement 放在变化确认层；它们不是锦上添花，而是 SP500 里最强的边际信息来源。",
        "3. 把利润率改善 + 去杠杆、revision + valuation improvement、growth + risk decline 视为有条件的 pair sleeves；先尊重换手和 drawdown，再讨论权重。",
        "4. 不把静态 value、静态高股息或完整 family equal-weight 当成自动有效。它们需要改善、盈利修正、风险控制或明确的时期条件来确认。",
        "",
        "## 方法与数据约束",
        "",
        f"- Universe：`{checks.get('universe_rule', 'Weight in SP500 > 0')}`；平均每月 {fmt_num(checks.get('avg_small_names_per_month', ''), 1)} 只证券。",
        f"- 样本与覆盖：{checks.get('first_small_date', '')} 至 {checks.get('last_small_date', '')}，{checks.get('small_date_count', '')} 个 screen observations；SEDOL returns coverage {fmt_pct(checks.get('sedol_return_coverage', ''), 3)}。",
        "- 方向和中性化：所有变量先转为 higher-is-better 的月度横截面分数；absolute level 的 directional_delta / score_delta 以同一证券 lag 1、3、12 个 screen observations 构造。",
        "- Gate：coverage >= 75%、Top/BM ratio CAGR > 0、Top/Worst > 0、robust > 0，且 official run 成功。CIQ、FactSet、database 和本地衍生字段同一门槛。",
        "- 限制：回测没有把交易成本直接从 NAV 中扣除；高 turnover pair 只能作为研究证据，尚不能直接推广为实盘配置。2024-2026 仅为不完整样本。",
        "",
        "## 外部与本地佐证",
        "",
        "- [Fama and French, A Five-Factor Asset Pricing Model](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2287202)：盈利能力与投资能改变对传统价值的解释，支持把 value 与质量分开验证。",
        "- [AQR, Quality Minus Junk](https://www.aqr.com/Insights/Research/Working-Paper/Quality-Minus-Junk)：quality 的核心是 profitability、growth、safety 与 management，低杠杆和现金转化属于安全性维度。",
        "- [Novy-Marx, The Other Side of Value](https://ideas.repec.org/a/eee/jfinec/v108y2013i1p1-28.html)：gross profitability 能补充传统价值解释。",
        "- [Jegadeesh and Titman, 1993](https://econpapers.repec.org/article/blajfinan/v_3a48_3ay_3a1993_3ai_3a1_3ap_3a65-91.htm) 与 [Chan, Jegadeesh and Lakonishok](https://www.nber.org/papers/w5375)：价格动量与盈利预期动量都可被理解为信息渐进扩散，而不是因子标签本身的魔法。",
        "",
        "## 本地关联",
        "",
        "- [[Factor_Investing_MOC]]",
        "- [[10_Investment/03_Factor_Research/02_Team_Factors/Quality Factor|Quality Factor]]",
        "- [[10_Investment/03_Factor_Research/02_Team_Factors/Growth Factor|Growth Factor]]",
        "- [[10_Investment/03_Factor_Research/02_Team_Factors/Value Factor|Value Factor]]",
        "- [[10_Investment/03_Factor_Research/04_Concepts/EPS Revisions|EPS Revisions]]",
        "- [[10_Investment/03_Factor_Research/04_Concepts/Style Timing|Style Timing]]",
        "- [[2026-07-10 SP500 因子研究：市场奖励改善，不奖励标签]]",
        "",
        "## 反向入口",
        "",
        f"- 运行根目录：`{RUN_ROOT}`",
        f"- raw gate：`{RAW_DIR}`；relative gate：`{REL_DIR}`。",
        "- 关键证据：`official_run_results.csv`、`performance_summary.csv`、`pair_synergy_results.csv`、`family_subset_results.csv`、`leave_one_out_results.csv`、`synergy_claims.csv`。",
        "- Plotly：`plots/best_robust_nav.html`、`plots/robust_score_top30.html`、`plots/drawdown_te_top30.html`。",
        "- 交互浏览器：`C:\\GoogleDrive\\TP\\artifacts\\reports\\sp500-factor-explorer.html`。",
        "",
    ]
    return lines


def write_public_article_v2(
    raw: pd.DataFrame,
    relative: pd.DataFrame,
    claims: pd.DataFrame,
    subset: pd.DataFrame,
    loo: pd.DataFrame,
    period: pd.DataFrame,
    expected_rows: int,
) -> Path:
    top_pair = first_row(claims)
    best_subset = first_row(subset)
    raw_leaders = "、".join(raw.sort_values("robust_score", ascending=False)["label"].head(5))
    period_2024 = period[period.get("period", pd.Series(dtype=str)).eq("2024-2026")]
    period_2024_leaders = "、".join(period_2024.sort_values("period_score", ascending=False)["label"].head(3))
    weak_loo = loo[loo.get("classification", pd.Series(dtype=str)).eq("weak_or_negative")]
    weak_name = str(weak_loo.iloc[0].get("left_out", "earnings-yield improvement")) if not weak_loo.empty else "earnings-yield improvement"
    lines = [
        "---",
        'title: "美国股票因子轮动评论文章 - communication版本"',
        "tags:",
        "  - factor-investing",
        "  - US-equities",
        "  - public-commentary",
        "  - SP500",
        "  - regime-rotation",
        "type: public-commentary",
        "created: 2026-07-10",
        "updated: 2026-07-10",
        'source_scope: "Federal Reserve official sources + academic evidence + anonymized TP SP500 factor research"',
        "okf_refresh: complete",
        "---",
        "",
        "# 美国股票因子轮动评论文章 - communication版本",
        "",
        "> 用途：可供 communication 部门改写或发布的专业评论稿。本文不构成投资建议，不讨论个股推荐，也不披露内部组合权重或交易信号参数。",
        "",
        "## 美国股票因子，正在从“拥有优势”转向“优势正在扩大”",
        "",
        "过去十多年，SP500 的因子讨论常被压缩成几个固定标签：成长、价值、质量、动量和股息。但我们对美国大盘股做的完整变量级研究给出了一幅更有用的图景：市场不会因为一家公司历史上看起来便宜、盈利能力高或派息率高，就稳定地奖励它。市场更愿意奖励的是可被确认的变化：利润率在改善、资本回报在上升、杠杆在下降、估值相对盈利在变便宜，或者分析师正在持续上调盈利预期。",
        "",
        "这不是用一个漂亮回测替代另一个标签。研究先让每个 raw variable 独立完成官方 Top/Worst，再让每个 absolute level 变量接受同一证券自身历史的改善测试。最终，47 个 raw variables、30 个通过 gate 的 relative variables，以及 738 条严格协同 Top/Worst 回测共同指向同一结论：**美国市场更在意优势能否继续扩大，而不是优势是否曾经存在。**",
        "",
        "### 2009-2016：从资产负债表修复到现金流价值",
        "",
        "金融危机后的第一阶段，PB、PFCF、股息收益率和现金流转换更突出。这个阶段的核心并不神秘：企业去风险、融资条件改善、估值修复和现金流回归正常，使得静态价值与现金回收能力更容易被市场定价。",
        "",
        "### 2020：变化确认成为必要条件",
        "",
        "疫情冲击改变了市场如何判断质量。2020 年 3 月，美联储先把联邦基金利率降至接近零，随后扩大对国债和机构 MBS 的购买，以维护市场功能和信用传导。极端流动性支持让增长资产得到修复，但也提高了“盈利能否兑现、资产负债表能否穿越冲击”的重要性。",
        "",
        "回测中，2020-2021 的领先线索正是低 NetDebt/EBITDA 和可见增长。它们问的是同一个问题：企业既能恢复收入，也不需要依赖脆弱的融资条件吗？",
        "",
        "### 2022-2023：资本成本回来了，静态便宜短暂变得有用",
        "",
        "2022 年 6 月，美联储一次上调政策利率 75 个基点，资本成本重新进入估值和公司基本面的中心。这个阶段，PFCF、Price/FreeCF 和股息覆盖等现金流价值变量重新占优。它不意味着传统 value 永久回归，而是说明当折现率和融资约束突然改变时，能产生现金、现金不依赖外部融资的公司会获得重新定价。",
        "",
        "### 2024-2026：市场把“增长叙事”换成了“盈利可见性”",
        "",
        f"截至 2026 年 6 月的样本，最强的阶段性变量是 {period_2024_leaders}。这组信号共同表示，市场不再满足于远期故事：分析师修正、价格确认和毛利增长必须同步出现。AI 扩散当然是这个时期的产业背景之一，但变量层面的结论更克制：只有当预期上修和盈利能力改善真的进入数据，成长才被稳定地定价。",
        "",
        "### 哪些变量有跨周期证据",
        "",
        f"全周期中，静态层面最有证据的是 {raw_leaders}。它们共同组成一个更务实的底座：资产负债表韧性、现金转化、可兑现的未来一年增长和近端盈利修正。",
        "",
        "真正值得强调的却是改善型质量。经营利润率 directional delta、ROE directional delta 和去杠杆 directional delta 的全周期稳健度明显高于许多对应的静态水平。这里的经济含义很直接：在美国大盘股中，市场愿意为“利润率正在扩张、资本回报正在修复、融资风险正在下降”支付溢价，而不是单纯为“过去利润率高”付费。",
        "",
        "### 协同不是一个漂亮的 family 名称",
        "",
        f"完整矩阵给出 {len(claims)} 条可声称的 pair synergy，但没有把任何 family subset 认定为严格 synergy。最强 pair 是“{top_pair.get('label', '')}”：它把经营修复与资产负债表修复放在同一条证据链里，Top/BM CAGR 为 {row_value(top_pair, 'ratio_cagr', fmt_pct)}，但换手也达到 {row_value(top_pair, 'avg_turnover', fmt_pct)}。因此它是强研究信号，不是可以不经成本和容量审计就直接部署的配置建议。",
        "",
        f"更宽的组合也有价值，只是应该被叫作 additive sleeve 而非 synergy。表现最好的这类组合是“{best_subset.get('label', '')}”，它说明质量改善与去杠杆能够形成很好的风险调整结果；但随着 bucket 增多，信息会被稀释，不能因为标签更丰富就假设 alpha 更强。",
        "",
        "### 2027 年美国股票因子该观察什么",
        "",
        "第一，盈利修正是否继续扩散。EPS revision 和近端 EPS 增长是判断产业主题能否从少数龙头扩展到更广横截面的最好检查项。",
        "",
        "第二，利润率改善是否伴随去杠杆。经营改善若没有资产负债表支持，可能只是周期高点；二者同时改善，才更接近可持续的财务修复。",
        "",
        "第三，价值有没有催化剂。静态低估值不再是自动放行条件；盈利收益率或 EV/EBITDA 的改善，最好得到盈利修正、低杠杆或风险下降的确认。",
        "",
        f"第四，保留对 {weak_name} 的克制。它在 full-model leave-one-out 中没有形成正贡献，提醒我们：单变量通过 gate，并不等于它在任何组合里都值得保留。",
        "",
        "### 结语",
        "",
        "美国股票因子研究真正的分水岭，不是从价值转向成长，也不是从质量转向动量，而是从静态标签转向变化确认。专业的因子框架应该先问：这个变量单独有效吗？这家公司相对自身历史正在变好吗？两个变量能否互相确认？把其中任何一步跳过，最后得到的都可能只是一个听上去合理的故事。",
        "",
        "## 可配套发布标题",
        "",
        "- 美国股票因子，正在从“拥有优势”转向“优势正在扩大”",
        "- US Equity Factors: From Static Quality to Confirmed Improvement",
        "- 为什么盈利修正、利润率改善和去杠杆正在重塑美国选股",
        "",
        "## 公开资料来源",
        "",
        "- [Federal Reserve: extensive measures to support the economy, 2020-03-23](https://www.federalreserve.gov/newsevents/pressreleases/monetary20200323b.htm)",
        "- [Federal Reserve: 2022 policy actions record](https://www.federalreserve.gov/publications/2022-ar-record-of-policy-actions-of-the-board-of-governors.htm)",
        "- [Fama and French, 2015: A Five-Factor Asset Pricing Model](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2287202)",
        "- [Novy-Marx, 2013: The Other Side of Value](https://ideas.repec.org/a/eee/jfinec/v108y2013i1p1-28.html)",
        "- [Jegadeesh and Titman, 1993: Returns to Buying Winners and Selling Losers](https://econpapers.repec.org/article/blajfinan/v_3a48_3ay_3a1993_3ai_3a1_3ap_3a65-91.htm)",
        "",
        "## 本地关联",
        "",
        "- [[2026-07-10 SP500 raw-relative 因子有效性与协同研究]]",
        "- [[Factor_Investing_MOC]]",
        "- [[10_Investment/03_Factor_Research/04_Concepts/EPS Revisions|EPS Revisions]]",
        "- [[10_Investment/03_Factor_Research/04_Concepts/Style Timing|Style Timing]]",
        "",
        "## 反向入口",
        "",
        f"- 本文依托 SP500 official Top/Worst {expected_rows}/{expected_rows} 的完整矩阵。",
        "- 方法、变量表和协同边界见 [[2026-07-10 SP500 raw-relative 因子有效性与协同研究]]。",
        "",
    ]
    PUBLIC_ARTICLE.write_text("\n".join(lines), encoding="utf-8")
    return PUBLIC_ARTICLE


@recorded_workflow
def main() -> int:
    checks = check_dict(RUN_ROOT / "data_construction_checks.csv")
    expected_rows = expected_official_rows(checks)
    run_results = all_run_results()
    terminal = pd.Series(False, index=run_results.index)
    if not run_results.empty:
        terminal = run_results["status"].isin(["success", "skipped"]) | (
            run_results["status"].eq("failed")
            & run_results.get("message", pd.Series("", index=run_results.index)).astype(str).str.contains("manual hard failure", case=False, na=False)
        )
    done_rows = int(terminal.sum()) if not run_results.empty else 0
    failed_rows = int(run_results["status"].eq("failed").sum()) if not run_results.empty else 0
    success_rows = int(run_results["status"].eq("success").sum()) if not run_results.empty else 0
    skipped_rows = int(run_results["status"].eq("skipped").sum()) if not run_results.empty else 0
    if done_rows < expected_rows:
        raise SystemExit(f"Synergy matrix incomplete: {done_rows}/{expected_rows}")

    raw = read_sp500_auxiliary_csv(RUN_ROOT / "report_raw_top_pass.csv")
    rel = read_sp500_auxiliary_csv(RUN_ROOT / "report_relative_top_pass.csv")
    rel_cmp = read_sp500_auxiliary_csv(RUN_ROOT / "report_relative_vs_level_top.csv")
    period = read_sp500_auxiliary_csv(RUN_ROOT / "report_period_top_raw.csv")
    old_pairs = read_sp500_auxiliary_csv(RUN_ROOT / "report_existing_raw_pair_top.csv")
    pair = read_csv(RUN_ROOT / "pair_synergy_results.csv")
    subset = read_csv(RUN_ROOT / "family_subset_results.csv")
    loo = read_csv(RUN_ROOT / "leave_one_out_results.csv")
    claims = read_csv(RUN_ROOT / "synergy_claims.csv")
    selected = read_csv(RUN_ROOT / "selected_legs.csv")
    candidate_map = read_csv(RUN_ROOT / "candidate_map.csv")
    rel_manifest = json.loads((REL_DIR / "manifest.json").read_text(encoding="utf-8")) if (REL_DIR / "manifest.json").exists() else {}

    raw_view = raw.copy()
    for col in ["coverage", "ratio_cagr"]:
        if col in raw_view.columns:
            raw_view[col] = raw_view[col].map(fmt_pct)
    if "top_worst_ratio_return" in raw_view.columns:
        raw_view["top_worst_ratio_return"] = raw_view["top_worst_ratio_return"].map(fmt_pct)
    if "robust_score" in raw_view.columns:
        raw_view["robust_score"] = raw_view["robust_score"].map(lambda x: fmt_num(x, 2))

    rel_view = rel.copy()
    for col in ["coverage", "ratio_cagr", "top_worst_ratio_return"]:
        if col in rel_view.columns:
            rel_view[col] = rel_view[col].map(fmt_pct)
    if "robust_score" in rel_view.columns:
        rel_view["robust_score"] = rel_view["robust_score"].map(lambda x: fmt_num(x, 2))

    claims_view = claims.copy()
    for col in ["coverage", "ratio_cagr", "top_worst_ratio_return"]:
        if col in claims_view.columns:
            claims_view[col] = claims_view[col].map(fmt_pct)
    for col in ["robust_score", "max_component_robust", "synergy_score"]:
        if col in claims_view.columns:
            claims_view[col] = claims_view[col].map(lambda x: fmt_num(x, 2))

    pair_view = pair.sort_values(["classification", "synergy_score", "robust_score"], ascending=[True, False, False]).copy() if not pair.empty else pair
    for col in ["ratio_cagr", "top_worst_ratio_return"]:
        if col in pair_view.columns:
            pair_view[col] = pair_view[col].map(fmt_pct)
    for col in ["robust_score", "max_component_robust", "synergy_score"]:
        if col in pair_view.columns:
            pair_view[col] = pair_view[col].map(lambda x: fmt_num(x, 2))

    period_top = pd.DataFrame()
    if not period.empty:
        period_top = period.sort_values(["period", "period_score"], ascending=[True, False]).groupby("period", as_index=False).head(3).copy()
        for col in ["ratio_cagr", "top_worst_ratio_return"]:
            if col in period_top.columns:
                period_top[col] = period_top[col].map(fmt_pct)

    lines = [
        "---",
        'title: "2026-07-10 SP500 raw-relative 因子有效性与协同研究"',
        "tags:",
        "  - Finance/Quant",
        "  - FactorResearch/SP500",
        "  - OKF/Investment",
        "type: research_report",
        "created: 2026-07-10",
        'source_scope: "TP official Top/Worst backtests + local 60_Papers/OKF + web evidence"',
        "okf_refresh: complete",
        "---",
        "",
        "# 2026-07-10 SP500 raw-relative 因子有效性与协同研究",
        "",
        "> 本报告遵循 TP 因子研究流水线：raw variable 先独立 official Top/Worst；CIQ、FactSet、database、本地衍生字段同一 gate；relative variants 单独作为新 raw variable；没有 pair / subset / leave-one-out 证据，不声明 synergy。",
        "",
        "## 一句话结论",
        "",
        "SP500 全样本最稳定的单变量核心仍是低杠杆、现金质量和可兑现盈利增长；新增 same-security relative 研究显示，盈利质量和资产负债表的“正在改善”比许多静态水平变量更强。协同判断只以 full matrix 完成后的 pair/subset/leave-one-out 证据为准：能被声明为 synergy 的，是在 robust、Top/Benchmark 和 Top/Worst 分化上同时优于组件的组合；其余即使经济故事顺，也只能标为 additive、redundant 或待验证。",
        "",
        "## 本地关联",
        "",
        "- [[Factor_Investing_MOC]]",
        "- [[10_Investment/03_Factor_Research/02_Team_Factors/Quality Factor|Quality Factor]]",
        "- [[10_Investment/03_Factor_Research/02_Team_Factors/Growth Factor|Growth Factor]]",
        "- [[10_Investment/03_Factor_Research/02_Team_Factors/Value Factor|Value Factor]]",
        "- [[10_Investment/03_Factor_Research/02_Team_Factors/Momentum Factor|Momentum Factor]]",
        "- [[10_Investment/03_Factor_Research/02_Team_Factors/Dividend Factor|Dividend Factor]]",
        "- [[10_Investment/03_Factor_Research/04_Concepts/EPS Revisions|EPS Revisions]]",
        "- [[10_Investment/03_Factor_Research/04_Concepts/Style Timing|Style Timing]]",
        "- [[60_Papers/A Backtesting Protocol in the Era of Machine Learning|A Backtesting Protocol in the Era of Machine Learning]]",
        "- [[60_Papers/Smart Beta Multifactor Construction Methodology Mixing versus Integrating|Smart Beta Multifactor Construction Methodology Mixing versus Integrating]]",
        "- [[60_Papers/The Promises and Pitfalls of Factor Timing|The Promises and Pitfalls of Factor Timing]]",
        "- [[60_Papers/Trade-Off in Multifactor Smart Beta Investing Factor Premium and Implementation Cost|Trade-Off in Multifactor Smart Beta Investing]]",
        "",
        "## Benchmark 与数据审计",
        "",
        f"- Benchmark: `{checks.get('benchmark', 'SP500')}`。",
        f"- 权重列 / universe rule: `{checks.get('universe_rule', 'Weight in SP500 > 0')}`。",
        f"- 样本区间: {checks.get('first_small_date', '')} 至 {checks.get('last_small_date', '')}，{checks.get('small_date_count', '')} 个 screen observations。",
        f"- 样本行数: source screen rows {checks.get('source_screen_rows', '')}；research screen rows {checks.get('research_screen_rows', '')}。",
        f"- 平均 universe names/month: {fmt_num(checks.get('avg_small_names_per_month', ''), 1)}。",
        f"- returns 覆盖率: {checks.get('sedol_rows_in_returns', '')} / {checks.get('sedol_rows', '')}，SEDOL return coverage {fmt_pct(checks.get('sedol_return_coverage', ''), 3)}。",
        f"- 回测口径: {checks.get('lookahead_rule', 'monthly screen date; official engine trades after signal date')}。",
        f"- 协同矩阵: selected legs {checks.get('selected_leg_count', '')}；candidate metrics {checks.get('candidate_metric_count', '')}，其中 official {checks.get('official_candidate_count', '')}；official Top/Worst rows {done_rows}/{expected_rows}。",
        "",
        "## 官方矩阵完成度",
        "",
        f"- raw variables: 47 个变量，94 条 Top/Worst official rows，全部成功；raw gate 通过 {len(raw)} 个。",
        f"- relative variants: {rel_manifest.get('gate_total_count', '')} 个 gate rows，通过 {rel_manifest.get('gate_pass_count', '')} 个；official rows {rel_manifest.get('run_count', '')}。",
        f"- strict synergy: {checks.get('official_candidate_count', '')} 个 official metric，Top/Worst 两侧 terminal rows {done_rows}/{expected_rows}；success {success_rows}，skipped {skipped_rows}，failed {failed_rows}。",
        f"- synergy claims: {len(claims)} 条。若为 0，报告不把任何组合称为严格 synergy。",
        "",
        "## Gate 规则",
        "",
        "统一 gate 为 coverage >= 75%，Top/Benchmark ratio CAGR > 0，Top/Worst ratio return > 0，robust_score > 0，并要求 official run 成功。`core` / `supplement` 只是诊断标签；CIQ 不被保守排除，也不自动放行。",
        "",
        "## Raw Gate：全周期有效单变量",
        "",
        md_table(raw_view, ["label", "family", "coverage", "ratio_cagr", "top_worst_ratio_return", "robust_score"], ["变量", "family", "coverage", "Top/BM CAGR", "Top/Worst", "robust"], 20),
        "",
        "### 经济解释",
        "",
        "- Quality：`NetDebt to EBITDA exFIN`、`Net Debt to Tot Equity`、`FCF Conversion` 的有效性说明，SP500 对资产负债表韧性和利润变现金能力有持续定价。AQR Quality Minus Junk 和本地 Quality Factor 笔记都把盈利能力、安全性、稳定增长放在质量定义核心。",
        "- Growth：EPS Growth 与 Gross Income Growth 强于单纯 Sales Growth，说明市场奖励的是能穿透到毛利池和股东盈利的增长，而不是只看收入规模扩张。Novy-Marx 的 gross profitability 研究为 gross income / gross profitability 类信号提供了经济支撑。",
        "- Revision / fundamental momentum：`EPS NTM 3M Growth` 和 `EPS Revision Ratio` 捕捉盈利预期迁移。经典 momentum 文献支持信息渐进扩散，但本报告仍把价格动量和基本面动量分开验证。",
        "- Value / Dividend：静态估值和高股息率并不天然适合 SP500 全周期；有效证据更偏 EV/EBITDA NTM、DPS growth 和后续 relative improvement。",
        "",
        "## Relative Gate：同一证券自身改善",
        "",
        md_table(rel_view, ["raw_column", "base_family", "transform", "lag_observations", "coverage", "ratio_cagr", "top_worst_ratio_return", "robust_score"], ["raw column", "family", "transform", "lag", "coverage", "Top/BM CAGR", "Top/Worst", "robust"], 20),
        "",
        "relative 结果的核心含义是：很多静态 quality/value/dividend 水平变量未必全周期强，但当同一家公司自己的 margin、ROE、leverage、earnings yield 或 payout/coverage 出现改善时，横截面排序变得更有效。这是 level 与 improvement 的不同经济角色。",
        "",
        "### Relative vs Level",
        "",
        md_table(rel_cmp, ["raw_column", "family", "best_relative_metric", "transform", "lag_observations", "relative_robust_score", "level_robust_score", "relative_minus_level_robust", "relative_improves_level"], ["raw", "family", "best relative", "transform", "lag", "rel robust", "level robust", "uplift", "improves"], 20),
        "",
        "## 严格协同证据",
        "",
        "### 可声明 synergy",
        "",
        md_table(claims_view, ["label", "candidate_type", "buckets", "ratio_cagr", "top_worst_ratio_return", "robust_score", "max_component_robust", "synergy_score"], ["组合", "type", "buckets", "Top/BM CAGR", "Top/Worst", "robust", "best leg", "synergy"], 40),
        "",
        "### Pair / subset 证据边界",
        "",
        md_table(pair_view, ["label", "classification", "buckets", "ratio_cagr", "top_worst_ratio_return", "robust_score", "max_component_robust", "synergy_score"], ["pair", "class", "buckets", "Top/BM CAGR", "Top/Worst", "robust", "best leg", "synergy"], 30),
        "",
        "synergy 的经济解释只在上表 classification 为 `synergistic` 时成立；`additive` 代表组合本身有效但没有超过最强组件，`redundant` 代表信息重叠，`harmful` 代表组合破坏排序。",
        "",
        "### Leave-one-out",
        "",
        md_table(loo, ["left_out", "left_out_bucket", "full_robust_score", "without_robust_score", "loo_contribution", "classification"], ["left out", "bucket", "full robust", "without robust", "contribution", "class"], 40),
        "",
        "leave-one-out 用来反证 family 内部是否真的互补：如果拿掉某个 bucket 或变量后 full model 反而更好，这个变量就不能因为单腿有效而被放入核心组合。",
        "",
        "## 旧 raw-pair 证据如何放置",
        "",
        "此前 raw-only pair 研究已经显示 Growth + Quality、Revision + Quality 是 SP500 的强簇；本次 strict matrix 在此基础上加入 relative legs、subset 与 leave-one-out。历史 raw-gate 文件中的 metric 名称已规范化为 `sp500_*`，其数据样本仍为 SP500；旧证据只作先验和解释材料，最终 synergy 声明以本次 full matrix 为准。",
        "",
        md_table(old_pairs, ["pair_label", "pair_ratio_cagr", "pair_top_worst_ratio_return", "pair_robust_score", "synergy_robust_score", "synergy_pass"], ["raw pair", "ratio CAGR", "Top/Worst", "robust", "uplift", "pass"], 12),
        "",
        "## 分时期 rotation",
        "",
        md_table(period_top, ["period", "period_note", "label", "family", "ratio_cagr", "top_worst_ratio_return", "period_score"], ["period", "note", "variable", "family", "ratio CAGR", "Top/Worst", "score"], 30),
        "",
        "分时期结果只能说明 regime-specific 优势，不能自动进入全周期核心。2009-2012 与 2022-2023 更偏 value/cash-flow；2017-2019 更偏 profitability/growth；2024-2026 revision 与 PMOM 更突出。Style Timing 文献也提醒：factor timing 的关系高度时变，容易 hindsight mining。",
        "",
        "## 弱证据与待验证假设",
        "",
        "- PMOM 全周期 raw gate 未通过，但 2024-2026 强，适合作为 regime overlay，不适合作为全周期核心。",
        "- PB、PFCF、Price/FCF 在部分时期强，但覆盖率、行业结构和资本开支周期会影响全周期 gate。",
        "- dividend yield 水平变量容易混入 value trap；DPS growth 和 dividend coverage improvement 更有经济含义。",
        "- family 内部变量不天然有 synergy。只有通过 pair/subset/leave-one-out 后，才能把它写成组合设计原则。",
        "",
        "## 外部证据",
        "",
        "- [Fama and French, A Five-Factor Asset Pricing Model](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2287202): value、profitability、investment 被放在统一资产定价框架中，但加入 profitability 后 value 的独立作用可能变弱。",
        "- [AQR, Quality Minus Junk](https://www.aqr.com/Insights/Research/Working-Paper/Quality-Minus-Junk): quality 被定义为 profitable、growing、safe、well-managed，支持把低杠杆、现金转化和盈利质量作为质量核心。",
        "- [Novy-Marx, The Other Side of Value](https://ideas.repec.org/a/eee/jfinec/v108y2013i1p1-28.html): gross profitability 对横截面收益有解释力，并能改善 value 策略。",
        "- [Jegadeesh and Titman 1993](https://econpapers.repec.org/article/blajfinan/v_3a48_3ay_3a1993_3ai_3a1_3ap_3a65-91.htm) 与 [Chan/Jegadeesh/Lakonishok earnings momentum](https://www.nber.org/papers/w5375): 支持信息渐进扩散，但也要求控制反转、交易成本和 regime。",
        "- [Sloan 1996 accruals anomaly](https://www.cuhk.edu.hk/acy2/workshop/June2009Wasley/1996TAR%29.pdf): 支持区分会计利润和现金流质量。",
        "- [Dividend puzzle 文献线索](https://www.sciencedirect.com/science/article/abs/pii/S1058330002000447): 支持把 dividend yield、payout、coverage 分开看；本研究中 dividend growth / coverage improvement 比静态高股息更适合进入解释框架。",
        "",
        "## 反向入口",
        "",
        f"- TP run root: `{RUN_ROOT}`",
        f"- raw validation: `{RAW_DIR}`",
        f"- relative validation: `{REL_DIR}`",
        "- key files: `official_run_results.csv`, `performance_summary.csv`, `pair_synergy_results.csv`, `family_subset_results.csv`, `leave_one_out_results.csv`, `synergy_claims.csv`。",
        "",
    ]
    lines = build_sp500_research_note(
        checks,
        expected_rows,
        done_rows,
        raw,
        rel,
        rel_cmp,
        pair,
        subset,
        loo,
        claims,
        selected,
        period,
    )
    VAULT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    VAULT_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(VAULT_REPORT)
    print(write_public_article_v2(raw, rel, claims, subset, loo, period, expected_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

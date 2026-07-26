"""Assemble the final EU Small raw/relative/synergy factor research report."""

from __future__ import annotations
from tp_research.runtime import recorded_workflow

import argparse
from datetime import datetime
from pathlib import Path
import shutil

import numpy as np
import pandas as pd


from tp_core.workspace import HISTORICAL_RESEARCH_RUNS_DIR, RESEARCH_RUNS_DIR

AD_HOC_ROOT = HISTORICAL_RESEARCH_RUNS_DIR / "ad_hoc"
DEFAULT_RAW_DIR = AD_HOC_ROOT / "eu_small_validated_gate_20260708_official"
DEFAULT_ROTATION_DIR = AD_HOC_ROOT / "eu_small_variable_rotation_20260708_official"
DEFAULT_RELATIVE_DIR = AD_HOC_ROOT / "eu_small_relative_variables_20260709"
DEFAULT_SYNERGY_DIR = AD_HOC_ROOT / "eu_small_relative_synergy_20260709"
DEFAULT_OUT_DIR = RESEARCH_RUNS_DIR / "ad_hoc" / "eu_small_extended_factor_report_20260709"
DEFAULT_OBSIDIAN_DIR = Path(r"C:\GoogleDrive\笔记\卡片盒子\10_Investment\03_Factor_Research")


LOCAL_SOURCES = [
    {
        "title": "A Backtesting Protocol in the Era of Machine Learning",
        "path": r"C:\GoogleDrive\笔记\卡片盒子\60_Papers\A Backtesting Protocol in the Era of Machine Learning.md",
        "claim": "研究流程需要预先设定 winsorize、样本、变量和 gate，防止事后挑参。",
    },
    {
        "title": "Clairvoyant Value and the Value Effect",
        "path": r"C:\GoogleDrive\笔记\卡片盒子\60_Papers\Clairvoyant Value and the Value Effect.md",
        "claim": "value 的经济含义不是低估值本身，而是市场常对远期成长付出过高价格。",
    },
    {
        "title": "Quality Assurance: Demystifying the Quality Factor in Equities and Bonds",
        "path": r"C:\GoogleDrive\笔记\卡片盒子\60_Papers\Quality Assurance Demystifying the Quality Factor in Equities and Bonds.md",
        "claim": "quality 可由盈利能力、盈利稳定性和低杠杆刻画，组合层面有降低尾部风险的意义。",
    },
    {
        "title": "Fact and Fiction about Low-Risk Investing",
        "path": r"C:\GoogleDrive\笔记\卡片盒子\60_Papers\Fact and Fiction about Low-Risk Investing.md",
        "claim": "low-risk 长期有理论和跨市场证据，但可能在下跌市场阶段为负，不能自动视为独立 alpha。",
    },
    {
        "title": "All Days Are Not Created Equal: Understanding Momentum by Learning to Weight Past Returns",
        "path": r"C:\GoogleDrive\笔记\卡片盒子\60_Papers\All Days Are Not Created Equal Understanding Momentum by Learning to Weight Past Returns.md",
        "claim": "momentum 可解释为重要信息日后的反应不足，和 EPS revision 的信息扩散机制一致。",
    },
    {
        "title": "Diversification Benefits of European Small-Cap Stocks after the Global Financial Crisis and Brexit",
        "path": r"C:\GoogleDrive\笔记\卡片盒子\60_Papers\Diversification Benefits of European Small-Cap Stocks after the Global Financial Crisis and Brexit.md",
        "claim": "欧洲小盘在危机后更受本地融资、相关性上升和 downside co-movement 影响，因此稳健性比最高收益更重要。",
    },
    {
        "title": "Small, Value, or Small/Value?",
        "path": r"C:\GoogleDrive\笔记\卡片盒子\60_Papers\Small, Value, or SmallValue.md",
        "claim": "小盘和价值的交叉暴露可能比孤立 size/value 卫星更有效，支持在小盘内部寻找 value-quality-momentum 交集。",
    },
]

EXTERNAL_SOURCES = [
    {
        "title": "Fama and French: A Five-Factor Asset Pricing Model",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2287202",
        "claim": "size、value、profitability 与 investment 是跨股票横截面解释变量；小盘内部需同时看 value 与 profitability/quality。",
    },
    {
        "title": "Novy-Marx: The Other Side of Value",
        "url": "https://www.nber.org/papers/w15940",
        "claim": "盈利能力与 value 互补，支持 quality/value 交集而不是只买便宜。",
    },
    {
        "title": "Asness, Frazzini and Pedersen: Quality Minus Junk",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2312432",
        "claim": "高质量、低杠杆、稳健盈利可形成跨市场质量溢价，与本研究 quality/deleveraging bucket 对应。",
    },
    {
        "title": "Frazzini and Pedersen: Betting Against Beta",
        "url": "https://www.aqr.com/Insights/Datasets/Betting-Against-Beta-Equity-Factors-Monthly",
        "claim": "low-risk/BAB 的经济机制来自杠杆约束与高 beta 需求，但在风险反弹期可能承压。",
    },
    {
        "title": "Daniel and Moskowitz: Momentum Crashes",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2371227",
        "claim": "momentum 有强均值但会在高波动恐慌后反弹期 crash，因此需要 quality/value 防守过滤。",
    },
    {
        "title": "Arnott and Asness: Surprise! Higher Dividends = Higher Earnings Growth",
        "url": "https://www.aqr.com/Insights/Research/Journal-Article/Surprise-Higher-Dividends-Equal-Higher-Earnings-Growth",
        "claim": "股息/派息并不必然等于低增长，可能反映管理层现金纪律；但单独使用仍需 gate 证据。",
    },
    {
        "title": "Bermejo et al.: Factor investing in the European equity market",
        "url": "https://www.sciencedirect.com/science/article/pii/S2405844021022714",
        "claim": "欧洲市场上 value、profitability、momentum 的组合证据支持本研究的区域解释框架。",
    },
]


def read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def as_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def md(frame: pd.DataFrame, rows: int = 30, cols: list[str] | None = None) -> str:
    if frame.empty:
        return "暂无数据。"
    out = frame.copy()
    if cols is not None:
        out = out[[col for col in cols if col in out.columns]]
    out = out.head(rows)
    try:
        return out.to_markdown(index=False)
    except Exception:
        return out.to_csv(index=False)


def pct(value: object) -> str:
    try:
        return f"{float(value):.2%}"
    except Exception:
        return str(value)


def top_period_table(rotation: pd.DataFrame) -> pd.DataFrame:
    if rotation.empty:
        return pd.DataFrame()
    rows = []
    for period, group in rotation.groupby("period", sort=False):
        work = group[group["source"].isin(["raw", "pair", "validated"])].copy()
        work = work[pd.to_numeric(work["period_robust_score"], errors="coerce").notna()]
        work = work.sort_values(["period_robust_score", "ratio_cagr"], ascending=[False, False]).head(8)
        for _, row in work.iterrows():
            rows.append(
                {
                    "period": period,
                    "period_label": row.get("period_label", ""),
                    "source": row.get("source", ""),
                    "label": row.get("label", ""),
                    "family": row.get("family", ""),
                    "ratio_cagr": row.get("ratio_cagr", np.nan),
                    "top_worst_return": row.get("top_worst_return", np.nan),
                    "period_robust_score": row.get("period_robust_score", np.nan),
                }
            )
    return pd.DataFrame(rows)


def economic_takeaways(raw_pass: pd.DataFrame, rel_pass: pd.DataFrame, synergy_claims: pd.DataFrame) -> list[str]:
    lines = []
    if not raw_pass.empty:
        raw_labels = raw_pass.sort_values("robust_score", ascending=False)["label"].head(6).tolist()
        lines.append("全时期最能适应欧洲小盘的单变量不是一整套 style 标签，而是这些可解释的 raw legs: " + "；".join(map(str, raw_labels)) + "。")
    if not rel_pass.empty:
        rel = rel_pass.sort_values("robust_score", ascending=False).head(6)
        desc = [f"{row.get('raw_column')} {row.get('transform')} lag{row.get('lag_observations')}" for _, row in rel.iterrows()]
        lines.append("same-security relative 里通过 gate 的是边际改善/排名改善，而不是原 level 的自动延伸: " + "；".join(desc) + "。")
    else:
        lines.append("relative gate 若为空，结论应是: 当前市场更奖励横截面 level，而非同一公司自己的短中期改善。")
    if not synergy_claims.empty:
        labels = synergy_claims.get("label", pd.Series(dtype=str)).head(5).astype(str).tolist()
        lines.append("可声明 synergy 的组合必须同时有单腿 gate 与组合 official 证据；本轮可声明项: " + "；".join(labels) + "。")
    else:
        lines.append("若 synergy_claims 为空，只能说 additive/redundant/harmful，不能写 family 内部协同。")
    return lines


def write_report(args: argparse.Namespace) -> Path:
    raw_dir = Path(args.raw_dir)
    rotation_dir = Path(args.rotation_dir)
    relative_dir = Path(args.relative_dir)
    synergy_dir = Path(args.synergy_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_gate = read_csv(raw_dir / "raw_validation_gate.csv")
    raw_summary = read_csv(raw_dir / "performance_summary.csv")
    rotation = read_csv(rotation_dir / "period_rotation_stats.csv")
    raw_pair = read_csv(rotation_dir / "pair_synergy_summary.csv")
    rel_gate = read_csv(relative_dir / "relative_validation_gate.csv")
    rel_summary = read_csv(relative_dir / "performance_summary.csv")
    rel_compare = read_csv(relative_dir / "relative_vs_level_comparison.csv")
    rel_checks = read_csv(relative_dir / "data_construction_checks.csv")
    pair = read_csv(synergy_dir / "pair_synergy_results.csv")
    subset = read_csv(synergy_dir / "family_subset_results.csv")
    loo = read_csv(synergy_dir / "leave_one_out_results.csv")
    claims = read_csv(synergy_dir / "synergy_claims.csv")

    if not raw_gate.empty and not raw_summary.empty:
        raw_extra_cols = ["metric", "ratio_max_drawdown", "rolling_3y_min_ratio_cagr", "annual_active_hit_rate"]
        raw_extra = raw_summary[
            raw_summary.get("side", pd.Series(dtype=str)).eq("Top")
            & raw_summary.get("status", pd.Series(dtype=str)).eq("success")
        ][[col for col in raw_extra_cols if col in raw_summary.columns]].drop_duplicates("metric", keep="last")
        raw_gate = raw_gate.merge(raw_extra, on="metric", how="left")
    if not rel_gate.empty and not rel_summary.empty:
        rel_extra_cols = ["metric", "ratio_max_drawdown", "rolling_3y_min_ratio_cagr", "annual_active_hit_rate"]
        rel_extra = rel_summary[
            rel_summary.get("side", pd.Series(dtype=str)).eq("Top")
            & rel_summary.get("status", pd.Series(dtype=str)).eq("success")
        ][[col for col in rel_extra_cols if col in rel_summary.columns]].drop_duplicates("metric", keep="last")
        rel_gate = rel_gate.merge(rel_extra, on="metric", how="left")

    raw_pass = raw_gate[as_bool(raw_gate["pass_gate"])] if "pass_gate" in raw_gate.columns else pd.DataFrame()
    rel_pass = rel_gate[as_bool(rel_gate["pass_gate"])] if "pass_gate" in rel_gate.columns else pd.DataFrame()
    raw_reject = raw_gate[~as_bool(raw_gate["pass_gate"])] if "pass_gate" in raw_gate.columns else pd.DataFrame()
    raw_fail_by_family = (
        raw_reject.groupby("raw_family").size().reset_index(name="rejected_count").sort_values("rejected_count", ascending=False)
        if not raw_reject.empty and "raw_family" in raw_reject.columns
        else pd.DataFrame()
    )
    period_top = top_period_table(rotation)

    check_map = dict(zip(rel_checks.get("check", []), rel_checks.get("value", [])))
    source_rows = [
        {
            "note": item["title"],
            "local_path": item["path"],
            "url": "",
            "how_used": item["claim"],
        }
        for item in LOCAL_SOURCES
    ]
    source_rows.extend(
        {
            "note": item["title"],
            "local_path": "",
            "url": item["url"],
            "how_used": item["claim"],
        }
        for item in EXTERNAL_SOURCES
    )
    source_table = pd.DataFrame(source_rows)

    lines = [
        "---",
        'title: "欧洲小盘股 raw-relative 协同因子研究最终报告"',
        "tags: [investment, factor-research, europe-small-cap, tp]",
        "type: research_report",
        f"created: {datetime.now().strftime('%Y-%m-%d')}",
        "source_scope: TP official backtests + local paper notes + external paper links",
        "okf_refresh: pending",
        "---",
        "",
        "# 欧洲小盘股 raw-relative 协同因子研究最终报告",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 证据口径: official exact Top/Worst；fast/screening 只作诊断，不进入结论。",
        f"- Universe / Benchmark: `{check_map.get('benchmark', 'MSCI EUR SMALL')}`，规则 `{check_map.get('universe_rule', 'Weight in MSCI EUR SMALL > 0')}`。",
        f"- 样本: {check_map.get('first_small_date', '')} 到 {check_map.get('last_small_date', '')}；月度截面 {check_map.get('small_date_count', '')} 个；平均股票数 {check_map.get('avg_small_names_per_month', '')}。",
        f"- returns 覆盖率: {pct(check_map.get('sedol_return_coverage', np.nan))}。",
        "",
        "## 结论先行",
        "",
    ]
    lines.extend([f"- {item}" for item in economic_takeaways(raw_pass, rel_pass, claims)])
    lines.extend(
        [
            "",
            "## 数据与 Gate 审计",
            "",
            md(rel_checks, 80),
            "",
            "## Raw Variable Gate",
            "",
            f"- raw official gate: {len(raw_gate)} 个变量，{len(raw_pass)} 个通过。",
            "",
            md(
                raw_pass.sort_values("robust_score", ascending=False),
                30,
                ["metric", "label", "raw_family", "role", "source_tag", "coverage", "ratio_cagr", "top_worst_ratio_return", "ratio_max_drawdown", "rolling_3y_min_ratio_cagr", "annual_active_hit_rate", "robust_score"],
            ),
            "",
            "### 被拒变量结构",
            "",
            md(raw_fail_by_family, 20),
            "",
            "## Relative Raw Variable Gate",
            "",
            f"- relative official gate: {len(rel_gate)} 个变量，{len(rel_pass)} 个通过。",
            "",
            md(
                rel_pass.sort_values("robust_score", ascending=False) if not rel_pass.empty else rel_pass,
                40,
                ["metric", "raw_column", "base_family", "transform", "lag_observations", "coverage", "ratio_cagr", "top_worst_ratio_return", "ratio_max_drawdown", "robust_score", "economic_read"],
            ),
            "",
            "### Relative vs Level",
            "",
            md(
                rel_compare.sort_values(["relative_pass_gate", "relative_minus_level_robust"], ascending=[False, False]) if not rel_compare.empty else rel_compare,
                40,
                ["raw_column", "base_family", "best_relative_metric", "relative_pass_gate", "relative_robust_score", "level_pass_gate", "level_robust_score", "relative_minus_level_robust", "relative_ratio_cagr", "level_ratio_cagr"],
            ),
            "",
            "## Raw Pair 证据",
            "",
            "这里保留旧 66 个 raw pair official evidence。pair 可以支持 pair-level synergy，但没有 LOO 时不能升级成 family 内部 synergy。",
            "",
            md(
                raw_pair.sort_values("synergy_score", ascending=False) if not raw_pair.empty else raw_pair,
                30,
                ["metric", "left_label", "right_label", "family_pair", "coverage", "ratio_cagr", "top_worst_ratio_return", "ratio_max_drawdown", "robust_score", "max_leg_robust", "synergy_score"],
            ),
            "",
            "## Relative-Aware Pair / Subset / LOO",
            "",
            "### Pair",
            "",
            md(pair.sort_values(["classification", "synergy_score"], ascending=[True, False]) if not pair.empty else pair, 60),
            "",
            "### Family Subset",
            "",
            md(subset.sort_values(["classification", "synergy_score"], ascending=[True, False]) if not subset.empty else subset, 60),
            "",
            "### Leave-One-Out",
            "",
            md(loo, 60),
            "",
            "### 可声明 Synergy",
            "",
            md(claims, 60),
            "",
            "## 分时期 Rotation",
            "",
            "分时期不是重新拟合信号，而是对 official NAV 做期间归因；因此它说明适配期，不说明当时可事前知道 regime。",
            "",
            md(period_top, 80),
            "",
            "## 经济解释",
            "",
            "- **Value / PFCF / earnings yield**: 小盘股里估值便宜必须靠现金流或盈利支撑；PB、EV/Sales、PE 等静态倍数更容易买到价值陷阱。PFCF 与 earnings yield 通过 gate，说明市场奖励的是可回收现金流，而不是表面低价格。",
            "- **Quality / ROE / operating margin / deleveraging**: 欧洲小盘受融资环境和本地经济波动影响更大，盈利能力与低杠杆降低再融资风险，也解释了 quality 与 value/momentum 的组合稳健性。",
            "- **Momentum / EPS revision / PMOM**: 小盘覆盖度低，信息扩散慢；EPS revision 是分析师预期修正，PMOM 是价格确认，两者属于不同但互补的信息通道。",
            "- **Dividend**: 欧洲市场中股息收益率有现金纪律含义，但派息压力和低增长陷阱需要用 quality/value/momentum 过滤。",
            "- **LowVol**: 低波在 Worst 端有避雷价值，但若 Top/Benchmark ratio CAGR 不过 gate，就只应作为风险过滤或组合约束候选，而不是独立 alpha family。",
            "- **Relative variables**: directional_delta 是边际改善，score_delta 是同行内排名改善。只有 official gate 通过后，才能把“改善”作为有效单腿。",
            "",
            "## 本地关联",
            "",
            "- [[60_Papers/A Backtesting Protocol in the Era of Machine Learning]]",
            "- [[60_Papers/Clairvoyant Value and the Value Effect]]",
            "- [[60_Papers/Quality Assurance Demystifying the Quality Factor in Equities and Bonds]]",
            "- [[60_Papers/Fact and Fiction about Low-Risk Investing]]",
            "- [[60_Papers/All Days Are Not Created Equal Understanding Momentum by Learning to Weight Past Returns]]",
            "- [[60_Papers/Diversification Benefits of European Small-Cap Stocks after the Global Financial Crisis and Brexit]]",
            "- [[60_Papers/Small, Value, or SmallValue]]",
            "",
            "## 外部/本地证据索引",
            "",
            md(source_table, 20),
            "",
            "## 反向入口",
            "",
            "- [[10_Investment/03_Factor_Research]]",
            "- [[60_Papers/index]]",
            "",
            "## 产物路径",
            "",
            f"- raw gate: `{raw_dir}`",
            f"- raw pair / rotation: `{rotation_dir}`",
            f"- relative gate: `{relative_dir}`",
            f"- relative-aware synergy: `{synergy_dir}`",
        ]
    )

    report_path = out_dir / "eu_small_extended_factor_research_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    if args.obsidian:
        obsidian_dir = Path(args.obsidian_dir)
        obsidian_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(report_path, obsidian_dir / report_path.name)
    return report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write final EU small factor research report.")
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--rotation-dir", default=str(DEFAULT_ROTATION_DIR))
    parser.add_argument("--relative-dir", default=str(DEFAULT_RELATIVE_DIR))
    parser.add_argument("--synergy-dir", default=str(DEFAULT_SYNERGY_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--obsidian", action="store_true")
    parser.add_argument("--obsidian-dir", default=str(DEFAULT_OBSIDIAN_DIR))
    return parser


@recorded_workflow
def main() -> int:
    args = build_parser().parse_args()
    report = write_report(args)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

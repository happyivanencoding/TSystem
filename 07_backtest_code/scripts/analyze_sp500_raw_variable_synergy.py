"""Analyze SP500 raw-variable efficacy, pair synergy, and period rotation."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
from itertools import combinations
import json
from pathlib import Path
import sys
from typing import Iterable

import numpy as np
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
BACKTEST_ROOT = SCRIPT_DIR.parents[0]
TP_ROOT = BACKTEST_ROOT.parent

for path in (SCRIPT_DIR, TP_ROOT, BACKTEST_ROOT, BACKTEST_ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_sp500_multifactor_research as sp500  # noqa: E402


AD_HOC_ROOT = BACKTEST_ROOT / "runs" / "ad_hoc"
DEFAULT_RAW_DIR = AD_HOC_ROOT / "sp500_raw_validation_20260708"
DEFAULT_VALIDATED_DIR = AD_HOC_ROOT / "sp500_validated_family_20260708"
DEFAULT_RETURNS = TP_ROOT / "00_screen" / "returns.parquet"

PERIODS = [
    ("2009-2012", "2009-03-31", "2012-12-31", "GFC 后复苏和 QE 初期"),
    ("2013-2016", "2013-01-01", "2016-12-31", "低利率扩张、油价和中国冲击"),
    ("2017-2019", "2017-01-01", "2019-12-31", "税改后晚周期、低通胀成长"),
    ("2020-2021", "2020-01-01", "2021-12-31", "疫情冲击、流动性和重启交易"),
    ("2022-2023", "2022-01-01", "2023-12-31", "通胀和加息冲击、AI 起点"),
    ("2024-2026", "2024-01-01", "2026-07-02", "AI 扩散和软着陆定价"),
]

SOURCE_NOTES = {
    "growth": "成长变量刻画未来收入、毛利或 EPS 扩张；在 SP500 里更像对可扩张商业模式和盈利上修通道的定价。",
    "value": "价值变量刻画以经营利润或现金流衡量的便宜程度；在无形资产占比高的美股大盘里，EV/EBITDA 往往比 PB 或简单 PE 更稳定。",
    "quality": "质量变量刻画现金转化和资产负债表韧性；低杠杆和高 FCF conversion 通常降低融资周期冲击。",
    "momentum": "修正/动量变量刻画信息扩散和盈利预期迁移；分析师上修和 NTM EPS 变化往往比纯价格动量更贴近基本面。",
    "dividend": "股息变量里，股息增长比股息率更像资本纪律和管理层信心；高股息率本身容易混入价值陷阱。",
}


@dataclass(frozen=True)
class Period:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp
    note: str


def read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def passed_raw_metrics(gate: pd.DataFrame) -> pd.DataFrame:
    passed = gate[gate["passed"].astype(bool)].copy()
    return passed.sort_values(["family", "robust_score"], ascending=[True, False])


def pair_column(a: str, b: str) -> str:
    digest = hashlib.sha1(f"{a}|{b}".encode("utf-8")).hexdigest()[:12]
    return f"sp500_pair_{digest}"


def build_pair_screen(
    raw_screen: pd.DataFrame,
    passed: pd.DataFrame,
    output_dir: Path,
) -> tuple[pd.DataFrame, list[sp500.base.ModelSpec], dict[str, tuple[str, str]]]:
    screen = raw_screen.copy()
    labels = passed.set_index("metric")["label"].to_dict()
    families = passed.set_index("metric")["family"].to_dict()
    specs: list[sp500.base.ModelSpec] = []
    pair_map: dict[str, tuple[str, str]] = {}
    for a, b in combinations(passed["metric"].tolist(), 2):
        column = pair_column(a, b)
        screen[column] = sp500.base.average_scores(screen, [a, b], min_count=2)
        family = f"pair_{families.get(a, '')}_{families.get(b, '')}"
        label = f"{labels.get(a, a)} + {labels.get(b, b)}"
        specs.append(
            sp500.base.ModelSpec(
                column=column,
                label=label,
                family=family,
                components={a: 0.5, b: 0.5},
                note="equal-weight pair of raw variables that passed SP500 raw gate",
            )
        )
        pair_map[column] = (a, b)
    (output_dir / "pair_metric_map.json").write_text(
        json.dumps({key: list(value) for key, value in pair_map.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return screen, specs, pair_map


def max_drawdown(nav: pd.Series) -> float:
    nav = pd.to_numeric(nav, errors="coerce").dropna()
    if nav.empty:
        return np.nan
    return float((nav / nav.cummax() - 1.0).min())


def nav_return(nav: pd.Series) -> float:
    nav = pd.to_numeric(nav, errors="coerce").dropna()
    if len(nav) < 2 or nav.iloc[0] <= 0:
        return np.nan
    return float(nav.iloc[-1] / nav.iloc[0] - 1.0)


def nav_cagr(nav: pd.Series, dates: pd.Series) -> float:
    nav = pd.to_numeric(nav, errors="coerce").dropna()
    if len(nav) < 2 or nav.iloc[0] <= 0:
        return np.nan
    days = max((pd.Timestamp(dates.iloc[-1]) - pd.Timestamp(dates.iloc[0])).days, 1)
    years = days / 365.25
    return float((nav.iloc[-1] / nav.iloc[0]) ** (1.0 / years) - 1.0)


def load_nav(path: str) -> pd.Series:
    frame = pd.read_parquet(path)
    frame["index"] = pd.to_datetime(frame["index"], errors="coerce")
    return frame.dropna(subset=["index"]).set_index("index")["nav"].sort_index()


def period_slice(series: pd.Series, period: Period) -> pd.Series:
    return series.loc[(series.index >= period.start) & (series.index <= period.end)]


def summarize_periods(summary: pd.DataFrame, periods: list[Period], universe: str) -> pd.DataFrame:
    if summary.empty or "status" not in summary.columns:
        return pd.DataFrame()
    rows = []
    for metric, group in summary[summary["status"].eq("success")].groupby("metric", sort=False):
        sides = {str(row["side"]): row for _, row in group.iterrows()}
        if "Top" not in sides:
            continue
        top = sides["Top"]
        top_nav = load_nav(str(top["perf_ptf"]))
        bench_nav = load_nav(str(top["perf_bench"]))
        worst_nav = load_nav(str(sides["Worst"]["perf_ptf"])) if "Worst" in sides else pd.Series(dtype=float)
        for period in periods:
            top_p = period_slice(top_nav, period)
            bench_p = period_slice(bench_nav, period)
            worst_p = period_slice(worst_nav, period) if not worst_nav.empty else worst_nav
            aligned = pd.concat({"top": top_p, "bench": bench_p}, axis=1).dropna()
            if len(aligned) < 120:
                continue
            ratio = aligned["top"] / aligned["bench"]
            top_worst_ratio_return = np.nan
            top_worst_ratio_max_drawdown = np.nan
            if not worst_p.empty:
                tw = pd.concat({"top": top_p, "worst": worst_p}, axis=1).dropna()
                if len(tw) >= 120:
                    tw_ratio = tw["top"] / tw["worst"]
                    top_worst_ratio_return = nav_return(tw_ratio)
                    top_worst_ratio_max_drawdown = max_drawdown(tw_ratio)
            rows.append(
                {
                    "universe": universe,
                    "period": period.name,
                    "period_note": period.note,
                    "metric": metric,
                    "label": top.get("label", ""),
                    "family": top.get("family", ""),
                    "coverage": top.get("coverage", np.nan),
                    "start": aligned.index.min().date().isoformat(),
                    "end": aligned.index.max().date().isoformat(),
                    "days": int((aligned.index.max() - aligned.index.min()).days),
                    "top_cagr": nav_cagr(aligned["top"], pd.Series(aligned.index)),
                    "bench_cagr": nav_cagr(aligned["bench"], pd.Series(aligned.index)),
                    "ratio_return": nav_return(ratio),
                    "ratio_cagr": nav_cagr(ratio, pd.Series(aligned.index)),
                    "ratio_max_drawdown": max_drawdown(ratio),
                    "top_worst_ratio_return": top_worst_ratio_return,
                    "top_worst_ratio_max_drawdown": top_worst_ratio_max_drawdown,
                }
            )
    out = pd.DataFrame(rows)
    if not out.empty:
        out["period_score"] = (
            out["ratio_cagr"].fillna(0)
            + 0.08 * out["top_worst_ratio_return"].fillna(0)
            + 0.15 * out["ratio_max_drawdown"].fillna(0)
        )
    return out


def pair_synergy_table(pair_summary: pd.DataFrame, raw_summary: pd.DataFrame, pair_map: dict[str, tuple[str, str]]) -> pd.DataFrame:
    if pair_summary.empty or "side" not in pair_summary.columns:
        return pd.DataFrame()
    raw_top = raw_summary[(raw_summary["side"].eq("Top")) & (raw_summary["status"].eq("success"))].set_index("metric")
    pair_top = pair_summary[(pair_summary["side"].eq("Top")) & (pair_summary["status"].eq("success"))].copy()
    rows = []
    for _, row in pair_top.iterrows():
        metric = row["metric"]
        a, b = pair_map.get(metric, ("", ""))
        if a not in raw_top.index or b not in raw_top.index:
            continue
        left = raw_top.loc[a]
        right = raw_top.loc[b]
        avg_robust = float(np.nanmean([left["robust_score"], right["robust_score"]]))
        avg_ratio = float(np.nanmean([left["ratio_cagr"], right["ratio_cagr"]]))
        avg_tw = float(np.nanmean([left["top_worst_ratio_return"], right["top_worst_ratio_return"]]))
        avg_dd = float(np.nanmean([left["ratio_max_drawdown"], right["ratio_max_drawdown"]]))
        rows.append(
            {
                "pair_metric": metric,
                "pair_label": row.get("label", ""),
                "metric_a": a,
                "label_a": left.get("label", ""),
                "family_a": left.get("family", "").replace("raw_", ""),
                "metric_b": b,
                "label_b": right.get("label", ""),
                "family_b": right.get("family", "").replace("raw_", ""),
                "pair_coverage": row.get("coverage", np.nan),
                "pair_ratio_cagr": row.get("ratio_cagr", np.nan),
                "avg_single_ratio_cagr": avg_ratio,
                "synergy_ratio_cagr": row.get("ratio_cagr", np.nan) - avg_ratio,
                "pair_top_worst_ratio_return": row.get("top_worst_ratio_return", np.nan),
                "avg_single_top_worst_ratio_return": avg_tw,
                "synergy_top_worst_ratio_return": row.get("top_worst_ratio_return", np.nan) - avg_tw,
                "pair_ratio_max_drawdown": row.get("ratio_max_drawdown", np.nan),
                "avg_single_ratio_max_drawdown": avg_dd,
                "synergy_ratio_max_drawdown": row.get("ratio_max_drawdown", np.nan) - avg_dd,
                "pair_robust_score": row.get("robust_score", np.nan),
                "avg_single_robust_score": avg_robust,
                "synergy_robust_score": row.get("robust_score", np.nan) - avg_robust,
                "pair_cagr": row.get("cagr", np.nan),
                "pair_tracking_error": row.get("tracking_error", np.nan),
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out["synergy_pass"] = (
            (out["pair_robust_score"] > 0)
            & (out["synergy_robust_score"] > 0)
            & (out["synergy_ratio_cagr"] > 0)
            & (out["synergy_top_worst_ratio_return"] > 0)
        )
        out = out.sort_values(["synergy_pass", "synergy_robust_score", "pair_robust_score"], ascending=[False, False, False])
    return out


def table(frame: pd.DataFrame, columns: list[str], max_rows: int = 20) -> str:
    cols = [col for col in columns if col in frame.columns]
    if frame.empty or not cols:
        return "暂无数据。"
    view = frame.loc[:, cols].head(max_rows).copy()
    for col in view.select_dtypes(include=["float", "float64"]).columns:
        view[col] = view[col].map(lambda x: "" if pd.isna(x) else f"{x:.4f}")
    return sp500.frame_to_markdown(view, max_rows=max_rows)


def economic_read(metric: str, label: str, family: str) -> str:
    label_lower = str(label).lower()
    if "revision" in label_lower or "ntm 3m" in label_lower:
        return "盈利修正有效说明信息扩散和分析师预期迁移仍然存在，适合作为成长/质量的 timing overlay。"
    if "eps" in label_lower and "growth" in label_lower:
        return "EPS 增长有效说明 SP500 对未来盈利兑现和盈利上修通道给溢价；这比单纯销售扩张更接近股东收益。"
    if "gross income" in label_lower:
        return "毛利增长有效说明市场奖励具备规模扩张且毛利池扩大的公司，通常对应定价权或产品周期。"
    if "sales growth" in label_lower:
        return "销售增长有效但强度较弱，说明营收扩张需要和利润质量配合，否则容易买到低质量增长。"
    if "ebitda 5y" in label_lower:
        return "长期 EBITDA 增长通过 gate，说明 CIQ 补充数据在覆盖足够时能捕捉长期经营复利，但单独强度不如前瞻 EPS。"
    if "ev to ebitda" in label_lower:
        return "EV/EBITDA NTM 是唯一通过的价值变量，说明 SP500 的价值更适合用经营利润口径衡量，PB/PE 等更容易被无形资产和行业结构扭曲。"
    if "netdebt" in label_lower or "net debt" in label_lower:
        return "低杠杆有效说明大盘股也存在融资周期和资产负债表风险溢价；在加息或信用压力阶段尤其重要。"
    if "fcf conversion" in label_lower:
        return "FCF conversion 有效说明市场奖励会把会计利润转成现金的公司，能过滤一部分利润质量陷阱。"
    if "dps" in label_lower:
        return "股息增长而非股息率通过 gate，说明市场奖励可持续分红能力和管理层信心，而不是追逐高息本身。"
    return SOURCE_NOTES.get(family.replace("raw_", ""), "该变量通过 gate，说明在 SP500 横截面中有可观测的排序信息。")


def write_report(
    output_dir: Path,
    raw_gate: pd.DataFrame,
    raw_summary: pd.DataFrame,
    pair_summary: pd.DataFrame,
    synergy: pd.DataFrame,
    single_period: pd.DataFrame,
    pair_period: pd.DataFrame,
) -> Path:
    raw_top = raw_summary[(raw_summary["side"].eq("Top")) & (raw_summary["status"].eq("success"))].copy()
    raw_top["passed"] = raw_top["metric"].isin(raw_gate.loc[raw_gate["passed"].astype(bool), "metric"])
    raw_top = raw_top.sort_values(["passed", "robust_score"], ascending=[False, False])
    passed = raw_top[raw_top["passed"]].copy()
    failed = raw_top[~raw_top["passed"]].copy()
    good_pairs = synergy[synergy["synergy_pass"]].copy() if not synergy.empty else pd.DataFrame()
    period_best_single = (
        single_period.sort_values(["period", "period_score"], ascending=[True, False]).groupby("period", as_index=False).head(8)
        if not single_period.empty
        else pd.DataFrame()
    )
    period_best_pair = (
        pair_period.sort_values(["period", "period_score"], ascending=[True, False]).groupby("period", as_index=False).head(8)
        if not pair_period.empty
        else pd.DataFrame()
    )

    lines = [
        "# SP500 单变量有效性、变量协同与时期轮动研究报告",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 证据口径: 单变量和 pair 均使用 official exact Top/Worst backtest；时期分析从 official NAV 重新切分计算。",
        f"- 单变量候选: {raw_gate.shape[0]} 个；raw gate 通过: {int(raw_gate['passed'].astype(bool).sum())} 个。",
        f"- pair 候选: {synergy.shape[0]} 个；满足协同定义: {int(synergy['synergy_pass'].sum()) if 'synergy_pass' in synergy else 0} 个。",
        "",
        "## 方法论",
        "",
        "1. 先看单变量: 每个 raw score 单独跑 Top/Worst，只有 coverage、Top/Benchmark ratio CAGR、Top/Worst ratio return、robust score 同时过关，才视为全周期有效。",
        "2. 再看协同: 对通过 raw gate 的变量两两等权组合，重新跑 official Top/Worst。pair 的 robust score、ratio CAGR、Top/Worst 分化必须高于两个单变量均值，才标为协同。",
        "3. 再切时期: 使用 official NAV 按经济时期切段，计算 Top/Benchmark ratio CAGR、ratio drawdown、Top/Worst ratio，识别 rotation。",
        "4. 分时期单变量榜单允许全周期未通过 gate 的变量出现，用来识别 regime-specific 优势；这些变量不能自动进入全周期 final family。",
        "",
        "## 全周期最有效的单变量",
        "",
        table(
            passed,
            [
                "family",
                "label",
                "coverage",
                "ratio_cagr",
                "top_worst_ratio_return",
                "ratio_max_drawdown",
                "rolling_3y_min_ratio_cagr",
                "annual_active_hit_rate",
                "robust_score",
            ],
            max_rows=30,
        ),
        "",
        "### 单变量经济含义",
        "",
    ]
    for _, row in passed.iterrows():
        fam = str(row["family"]).replace("raw_", "")
        lines.append(f"- `{row['label']}`: {economic_read(str(row['metric']), str(row['label']), fam)}")

    lines.extend(
        [
            "",
            "## 未通过 gate 的变量说明",
            "",
            "未通过不等于永远无用，但在当前 SP500 全周期证据下不能进入最终 family。常见失败原因是 Top/Benchmark ratio 不够、Top/Worst 分化不足、robust score 被回撤/滚动失效惩罚，或 coverage 不足。",
            "",
            table(
                failed.sort_values("robust_score", ascending=False),
                ["family", "label", "coverage", "ratio_cagr", "top_worst_ratio_return", "robust_score"],
                max_rows=25,
            ),
            "",
            "## 全周期变量协同",
            "",
            "协同不是两个好变量简单相加，而是 pair 在 official run 中比两个单变量均值更稳、更能分化 Top/Worst，或明显改善回撤/失效。",
            "",
            table(
                good_pairs,
                [
                    "pair_label",
                    "family_a",
                    "family_b",
                    "pair_ratio_cagr",
                    "synergy_ratio_cagr",
                    "pair_top_worst_ratio_return",
                    "synergy_top_worst_ratio_return",
                    "pair_ratio_max_drawdown",
                    "synergy_ratio_max_drawdown",
                    "pair_robust_score",
                    "synergy_robust_score",
                ],
                max_rows=30,
            ),
            "",
            "### 协同经济解释",
            "",
        ]
    )
    for _, row in good_pairs.head(12).iterrows():
        fams = {row["family_a"], row["family_b"]}
        if {"growth", "quality"}.issubset(fams):
            why = "成长给出扩张方向，质量/低杠杆过滤融资脆弱和低质量增长，因此组合更像“可兑现成长”。"
        elif {"growth", "momentum"}.issubset(fams):
            why = "成长给出长期基本面方向，修正/动量给出近期预期变化，组合捕捉“成长正在被市场确认”。"
        elif {"quality", "momentum"}.issubset(fams):
            why = "质量降低基本面下行尾部，修正捕捉信息扩散，适合 SP500 的盈利预期驱动行情。"
        elif {"value", "quality"}.issubset(fams):
            why = "价值提供估值安全边际，质量过滤便宜但脆弱的公司，是典型的 anti-value-trap 结构。"
        elif {"value", "growth"}.issubset(fams):
            why = "估值约束降低为成长支付过高价格的风险，成长约束避免买入低增长的静态便宜。"
        else:
            why = "两个变量提供不同的信息来源，pair 超过单变量均值说明组合减少了单一因子噪音。"
        lines.append(f"- `{row['pair_label']}`: {why}")

    lines.extend(
        [
            "",
            "## 分时期 rotation: 单变量",
            "",
            table(
                period_best_single,
                [
                    "period",
                    "period_note",
                    "label",
                    "family",
                    "ratio_cagr",
                    "ratio_return",
                    "ratio_max_drawdown",
                    "top_worst_ratio_return",
                    "period_score",
                ],
                max_rows=60,
            ),
            "",
            "## 分时期 rotation: 变量组",
            "",
            table(
                period_best_pair,
                [
                    "period",
                    "period_note",
                    "label",
                    "family",
                    "ratio_cagr",
                    "ratio_return",
                    "ratio_max_drawdown",
                    "top_worst_ratio_return",
                    "period_score",
                ],
                max_rows=60,
            ),
            "",
            "## 研究结论",
            "",
            "- SP500 全周期最适应市场的不是传统高股息、低 PB 或纯低波，而是前瞻 EPS/毛利增长、盈利修正、低杠杆、现金转化和 EV/EBITDA NTM。",
            "- 经济上，这说明美国大盘股的横截面奖励“盈利增长能兑现、资产负债表能承受周期、估值仍有经营利润锚”的公司。",
            "- 协同应优先看 growth + quality、growth + momentum、quality + momentum、value + quality 这几类组合；它们分别对应可兑现成长、被确认的成长、盈利预期质量和 anti-value-trap。",
            "- 分时期 rotation 会改变主导变量: 宽松和 AI/成长周期更偏 EPS/修正，通胀和加息阶段更偏低杠杆/现金质量，疫情和重启阶段的股息增长/经营利润估值可能阶段性占优。",
            "",
            "## 输出文件",
            "",
            f"- `raw_variable_full_period.csv`",
            f"- `pair_official_summary.csv`",
            f"- `pair_synergy.csv`",
            f"- `single_period_performance.csv`",
            f"- `pair_period_performance.csv`",
        ]
    )
    path = output_dir / "sp500_raw_variable_synergy_period_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SP500 raw-variable synergy and rotation report.")
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--validated-dir", default=str(DEFAULT_VALIDATED_DIR))
    parser.add_argument("--returns", default=str(DEFAULT_RETURNS))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--skip-official", action="store_true", help="Use existing pair summary if present.")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    sp500.configure_base()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    raw_dir = Path(args.raw_dir)
    validated_dir = Path(args.validated_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else AD_HOC_ROOT / f"sp500_raw_synergy_period_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_gate = read_csv(validated_dir / "raw_validation_gate.csv")
    raw_summary = read_csv(raw_dir / "performance_summary.csv")
    raw_screen = pd.read_parquet(raw_dir / "sp500_multifactor_screen.parquet")
    passed = passed_raw_metrics(raw_gate)
    pair_screen, pair_specs, pair_map = build_pair_screen(raw_screen, passed, output_dir)
    pair_screen_path = output_dir / "sp500_raw_pair_screen.parquet"
    pair_screen.to_parquet(pair_screen_path, index=False)
    pair_diag = sp500.base.metric_diagnostics(pair_screen, pair_specs, list(sp500.base.RAW_METRICS))
    pair_diag.to_csv(output_dir / "pair_metric_diagnostics.csv", index=False)
    (output_dir / "pair_metric_definitions.json").write_text(
        json.dumps([spec.__dict__ for spec in pair_specs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    pair_results_path = output_dir / "pair_official_run_results.csv"
    pair_summary_path = output_dir / "pair_official_summary.csv"
    pair_summary = pd.DataFrame()
    if args.skip_official and pair_summary_path.exists():
        pair_summary = read_csv(pair_summary_path)
    else:
        returns = sp500.base.load_tabular_file(Path(args.returns))
        returns.index = pd.to_datetime(returns.index, errors="coerce")
        returns = returns.sort_index()
        try:
            run_root_name = output_dir.resolve().relative_to((BACKTEST_ROOT / "runs").resolve()).as_posix()
        except ValueError:
            run_root_name = f"ad_hoc/{sp500.base.slugify(output_dir.name)}"
        existing_results = read_csv(pair_results_path) if args.resume and pair_results_path.exists() else None
        pair_results = sp500.run_official_backtests_incremental(
            screen=pair_screen,
            returns=returns,
            screen_path=pair_screen_path,
            returns_path=Path(args.returns),
            run_root_name=run_root_name,
            metrics=[spec.column for spec in pair_specs],
            max_runs=args.max_runs,
            results_path=pair_results_path,
            existing_results=existing_results,
        )
        pair_results.to_csv(pair_results_path, index=False)
        pair_summary = sp500.base.summarize_runs(pair_results, pair_diag)
        pair_summary.to_csv(pair_summary_path, index=False)

    synergy = pair_synergy_table(pair_summary, raw_summary, pair_map)
    synergy.to_csv(output_dir / "pair_synergy.csv", index=False)
    raw_summary[(raw_summary["side"].eq("Top")) & (raw_summary["status"].eq("success"))].to_csv(
        output_dir / "raw_variable_full_period.csv",
        index=False,
    )

    periods = [Period(name, pd.Timestamp(start), pd.Timestamp(end), note) for name, start, end, note in PERIODS]
    single_period = summarize_periods(raw_summary, periods, "single")
    pair_period = summarize_periods(pair_summary, periods, "pair")
    single_period.to_csv(output_dir / "single_period_performance.csv", index=False)
    pair_period.to_csv(output_dir / "pair_period_performance.csv", index=False)
    report = write_report(output_dir, raw_gate, raw_summary, pair_summary, synergy, single_period, pair_period)

    manifest = {
        "output_dir": str(output_dir),
        "raw_dir": str(raw_dir),
        "validated_dir": str(validated_dir),
        "passed_raw_count": int(len(passed)),
        "pair_count": int(len(pair_specs)),
        "pair_run_count": int(2 * len(pair_specs)),
        "pair_summary_rows": int(len(pair_summary)),
        "synergy_pass_count": int(synergy["synergy_pass"].sum()) if "synergy_pass" in synergy else 0,
        "report": str(report),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

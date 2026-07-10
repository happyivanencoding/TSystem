"""Build a standalone interactive explorer from official SP500 factor research."""

from __future__ import annotations

import json
import importlib.util
from collections import defaultdict
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "07_backtest_code" / "runs" / "ad_hoc"
SYNERGY_DIR = RUNS / "sp500_relative_synergy_20260710"
RELATIVE_DIR = RUNS / "sp500_relative_variables_20260709"
RAW_DIR = RUNS / "sp500_raw_validation_20260708"
FRAGMENT = (
    ROOT
    / ".codex"
    / "visualizations"
    / "2026"
    / "07"
    / "10"
    / "sp500-factor-explorer"
    / "sp500-factor-explorer.html"
)
STANDALONE = ROOT / "09_reports" / "sp500-factor-explorer.html"
VISUALIZE_RENDERER = Path(
    r"C:\Users\jingx\.codex\plugins\cache\openai-bundled\visualize\1.0.11\skills\visualize\scripts\render.py"
)

PERIODS = [
    ("all", "全样本", "2009-03-31", "2026-06-30"),
    ("2009-2012", "GFC 后复苏与 QE 初期", "2009-03-31", "2012-12-31"),
    ("2013-2016", "低利率扩张、油价与中国冲击", "2013-01-01", "2016-12-31"),
    ("2017-2019", "税改后晚周期、低通胀成长", "2017-01-01", "2019-12-31"),
    ("2020-2021", "疫情冲击、流动性与重启交易", "2020-01-01", "2021-12-31"),
    ("2022-2023", "通胀、加息冲击与 AI 起点", "2022-01-01", "2023-12-31"),
    ("2024-2026", "AI 扩散与软着陆定价", "2024-01-01", "2026-06-30"),
]


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def score_rows(path: Path) -> pd.DataFrame:
    frame = read_csv(path)
    return frame[frame["status"].eq("success") & frame["valid"].astype(str).eq("True")].copy()


def metric_index(frame: pd.DataFrame) -> dict[tuple[str, str], pd.Series]:
    return {
        (str(row.metric), str(row.side)): row
        for row in frame.itertuples(index=False)
    }


def num(value: object, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if pd.notna(parsed) else default


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def number(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


NAV_CACHE: dict[str, pd.DataFrame] = {}


def nav_frame(parquet_path: str) -> pd.DataFrame:
    csv_path = str(parquet_path).replace(".parquet", ".csv")
    if csv_path not in NAV_CACHE:
        raw = pd.read_csv(csv_path)
        raw = raw.iloc[:, :2].copy()
        raw.columns = ["date", "nav"]
        raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
        raw["nav"] = pd.to_numeric(raw["nav"], errors="coerce")
        NAV_CACHE[csv_path] = raw.dropna().sort_values("date")
    return NAV_CACHE[csv_path].copy()


def joined_nav(top: pd.Series, worst: pd.Series) -> pd.DataFrame:
    top_nav = nav_frame(str(top.perf_ptf)).rename(columns={"nav": "top"})
    worst_nav = nav_frame(str(worst.perf_ptf)).rename(columns={"nav": "worst"})
    bench_nav = nav_frame(str(top.perf_bench)).rename(columns={"nav": "bench"})
    merged = top_nav.merge(worst_nav, on="date", how="inner").merge(bench_nav, on="date", how="inner")
    return merged.sort_values("date").dropna()


def period_stats(frame: pd.DataFrame) -> dict[str, dict[str, float | str | None]]:
    result: dict[str, dict[str, float | str | None]] = {}
    for period_id, _, start, end in PERIODS:
        subset = frame[(frame["date"] >= start) & (frame["date"] <= end)].copy()
        if len(subset) < 2:
            continue
        first, last = subset.iloc[0], subset.iloc[-1]
        days = max((last.date - first.date).days, 1)
        active = subset["top"] / subset["bench"]
        top_worst = subset["top"] / subset["worst"]
        active_cagr = (active.iloc[-1] / active.iloc[0]) ** (365.25 / days) - 1
        top_cagr = (last.top / first.top) ** (365.25 / days) - 1
        tw_cagr = (top_worst.iloc[-1] / top_worst.iloc[0]) ** (365.25 / days) - 1
        drawdown = (active / active.cummax() - 1).min()
        result[period_id] = {
            "start": first.date.strftime("%Y-%m-%d"),
            "end": last.date.strftime("%Y-%m-%d"),
            "activeCagr": round(active_cagr, 6),
            "topCagr": round(top_cagr, 6),
            "topWorstCagr": round(tw_cagr, 6),
            "activeDrawdown": round(float(drawdown), 6),
        }
    return result


def monthly_series(frame: pd.DataFrame) -> list[dict[str, float | str]]:
    monthly = frame.set_index("date").resample("ME").last().dropna().reset_index()
    base = monthly.iloc[0]
    return [
        {
            "d": row.date.strftime("%Y-%m-%d"),
            "t": round(float(row.top / base.top * 100), 3),
            "w": round(float(row.worst / base.worst * 100), 3),
            "b": round(float(row.bench / base.bench * 100), 3),
        }
        for row in monthly.itertuples(index=False)
    ]


def load_definitions(path: Path) -> dict[str, dict]:
    definitions = {}
    for item in json.loads(path.read_text(encoding="utf-8")):
        definitions[str(item["column"])] = item.get("components", {})
    return definitions


def enrich_raw_labels() -> tuple[dict[str, dict], dict[str, str]]:
    selected = read_csv(SYNERGY_DIR / "selected_legs.csv")
    raw_meta = {}
    labels = {}
    for row in selected.itertuples(index=False):
        metric = str(row.metric)
        raw_meta[metric] = {
            "label": str(row.label),
            "bucket": str(row.bucket),
            "economic": str(row.economic_role),
            "source": str(row.source_type),
        }
        labels[metric] = str(row.label)
    raw_gate = read_csv(SYNERGY_DIR / "report_raw_top_pass.csv")
    for row in raw_gate.itertuples(index=False):
        metric = str(row.metric)
        labels.setdefault(metric, str(row.label))
    return raw_meta, labels


def expand_weights(
    metric: str,
    definitions: dict[str, dict],
    labels: dict[str, str],
    weight: float = 1.0,
    trail: tuple[str, ...] = (),
) -> list[dict[str, object]]:
    components = definitions.get(metric)
    if not components:
        return [{"metric": metric, "label": labels.get(metric, metric), "weight": weight, "path": " > ".join(trail)}]
    expanded: list[dict[str, object]] = []
    for child, child_weight in components.items():
        child_label = labels.get(child, child.replace("sp500_syn_bucket_", ""))
        expanded.extend(
            expand_weights(
                str(child), definitions, labels, weight * float(child_weight), trail + (child_label,)
            )
        )
    return expanded


def direct_components(metric: str, definitions: dict[str, dict], labels: dict[str, str]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], float] = defaultdict(float)
    for item in expand_weights(metric, definitions, labels):
        grouped[(str(item["metric"]), str(item["path"]))] += float(item["weight"])
    rows = [
        {"metric": key[0], "label": labels.get(key[0], key[0]), "path": key[1], "weight": round(value, 6)}
        for key, value in grouped.items()
    ]
    return sorted(rows, key=lambda row: (-float(row["weight"]), str(row["label"])))


def root_components(metric: str, definitions: dict[str, dict], labels: dict[str, str]) -> list[dict[str, object]]:
    components = definitions.get(metric, {})
    return [
        {"label": labels.get(child, str(child).replace("sp500_syn_bucket_", "")), "weight": round(float(weight), 6)}
        for child, weight in components.items()
    ]


def clean_value(value: object) -> float | str | None:
    """Return JSON-safe scalar values for the analysis layer."""
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return str(value)


def compact_rows(frame: pd.DataFrame, columns: dict[str, str], limit: int | None = None) -> list[dict[str, object]]:
    if limit is not None:
        frame = frame.head(limit)
    return [
        {target: clean_value(getattr(row, source)) for target, source in columns.items()}
        for row in frame.itertuples(index=False)
    ]


def find_metric(frame: pd.DataFrame, metric: str) -> pd.Series:
    matched = frame.loc[frame["metric"].eq(metric)]
    if matched.empty:
        raise KeyError(f"Missing research metric: {metric}")
    return matched.iloc[0]


def analysis_payload(
    raw_pass: pd.DataFrame,
    relative_pass: pd.DataFrame,
    relative_variable_count: int,
    synergy_claims: pd.DataFrame,
    subsets: pd.DataFrame,
    leave_one_out: pd.DataFrame,
    period_top_raw: pd.DataFrame,
    raw_variable_count: int,
) -> dict[str, object]:
    """Build the Nasdaq-style explanatory layer from official SP500 artifacts."""
    relative_pass = relative_pass.sort_values("robust_score", ascending=False)
    strict_pairs = synergy_claims.loc[synergy_claims["classification"].eq("synergistic")].sort_values(
        "robust_score", ascending=False
    )
    subsets = subsets.sort_values("robust_score", ascending=False)
    leave_one_out = leave_one_out.sort_values("loo_contribution", ascending=False)

    oper_margin = find_metric(relative_pass, "sp500_reldelta_quality_oper_margin_lag1_score")
    strict_pair = find_metric(strict_pairs, "sp500_syn_pair_38d49f1c93b4")
    focused_sleeve = find_metric(subsets, "sp500_syn_subset_08e95a53d5")
    full_model = find_metric(subsets, "sp500_syn_full_bucket_equal")

    def performance(row: pd.Series, strict: bool = False) -> dict[str, object]:
        data = {
            "robust": clean_value(row.get("robust_score")),
            "activeCagr": clean_value(row.get("ratio_cagr")),
            "topWorst": clean_value(row.get("top_worst_ratio_return")),
            "drawdown": clean_value(row.get("ratio_max_drawdown")),
            "turnover": clean_value(row.get("avg_turnover")),
        }
        if strict:
            data["synergyScore"] = clean_value(row.get("synergy_score"))
        return data

    period_narratives = {
        "2009-2012": "复苏早期更偏好现金流兑现、账面价值与前瞻股息。风险修复阶段，估值和可分配现金流的安全边际更受奖赏。",
        "2013-2016": "低利率扩张夹杂油价与中国冲击，P/FCF 与 EPS 修正居前：估值仍重要，但预期变化开始提供额外信息。",
        "2017-2019": "晚周期低通胀环境下，ROE、前瞻 EPS 增长与低波动领先，市场更重视资本效率和增长兑现的质量。",
        "2020-2021": "疫情后重启阶段，去杠杆、收入/EBITDA 长期增长占优，反映对资产负债表修复和经营弹性的重新定价。",
        "2022-2023": "加息冲击下，P/FCF、自由现金流与股息覆盖领先；市场把可持续现金流和估值纪律放在更高优先级。",
        "2024-2026": "AI 扩散与软着陆阶段，EPS 修正、PMOM 与前瞻毛利增长显著，但样本较短，只能作为当前轮动观察而非长期定律。",
    }
    period_rows = []
    for period_id, label, _, _ in PERIODS:
        if period_id == "all":
            continue
        rows = period_top_raw.loc[period_top_raw["period"].eq(period_id)].sort_values("period_score", ascending=False)
        period_rows.append(
            {
                "id": period_id,
                "label": label,
                "narrative": period_narratives[period_id],
                "shortWindow": period_id == "2024-2026",
                "leaders": compact_rows(
                    rows,
                    {
                        "metric": "metric",
                        "label": "label",
                        "family": "family",
                        "activeCagr": "ratio_cagr",
                        "topWorst": "top_worst_ratio_return",
                        "drawdown": "ratio_max_drawdown",
                        "periodScore": "period_score",
                    },
                    5,
                ),
            }
        )

    return {
        "verdict": {
            "headline": "SP500 的可复用信号是“改善”，不是静态标签。",
            "copy": "全样本证据首先支持盈利能力、资本结构与估值状态的变化；静态 growth / value / quality 只构成候选池，不能因为属于同一 family 就自动获得组合资格。",
        },
        "stats": [
            {"value": raw_variable_count, "label": "raw variables 已跑 official Top/Worst"},
            {"value": len(raw_pass), "label": "raw variables 通过 gate"},
            {"value": relative_variable_count, "label": "relative variants 已跑 official Top/Worst"},
            {"value": len(relative_pass), "label": "relative variants 通过 gate"},
            {"value": len(strict_pairs), "label": "严格 pair synergy"},
            {"value": 0, "label": "严格 family subset synergy"},
        ],
        "focus": [
            {
                "id": "oper-margin",
                "badge": "RELATIVE GATE",
                "metric": "sp500_reldelta_quality_oper_margin_lag1_score",
                "name": "经营利润率的 1 期改善",
                "thesis": "利润率改善是全样本中最强的单变量相对状态信号。",
                "economics": "同一行业内的利润率改善通常意味着定价、成本控制或经营杠杆兑现；相对变化比单纯的高利润率更接近边际盈利能力的再定价。",
                "evidence": performance(oper_margin),
                "note": "高换手（86.5%）提示实施前须单独评估成本与容量。",
                "kind": "relative",
            },
            {
                "id": "strict-pair",
                "badge": "STRICT SYNERGY",
                "metric": str(strict_pair.metric),
                "name": str(strict_pair.label),
                "thesis": "经营改善与去杠杆是有严格 pair 证据的互补组合。",
                "economics": "一条腿捕捉盈利质量在改善，另一条腿排除由杠杆堆出的表面回报；两者共同指向更可持续的企业基本面修复。",
                "evidence": performance(strict_pair, strict=True),
                "note": "这是 pair 级严格协同证据，不可外推为整个 quality family 的内部协同；换手同样偏高。",
                "kind": "strict",
            },
            {
                "id": "focused-sleeve",
                "badge": "ADDITIVE SLEEVE",
                "metric": str(focused_sleeve.metric),
                "name": str(focused_sleeve.label),
                "thesis": "质量改善 + 去杠杆是最稳健的精简 bucket sleeve。",
                "economics": "它把经营改善与资本结构修复结合，避免把静态低估值或高增长当作无条件信号。",
                "evidence": performance(focused_sleeve),
                "note": "分类为 additive：表现强，但没有通过“超过最佳单组件”的严格 synergy 断言。",
                "kind": "additive",
            },
            {
                "id": "full-model",
                "badge": "BROAD MODEL",
                "metric": str(full_model.metric),
                "name": "十个入选 bucket 等权",
                "thesis": "完整模型提供广泛分散，但没有证明所有 bucket 合在一起会产生乘数效应。",
                "economics": "更宽的组合牺牲一部分集中度，换取跨情景的覆盖；LOO 用来识别哪些 bucket 真正支撑全模型。",
                "evidence": performance(full_model),
                "note": "全模型是 additive，不是严格协同；earnings-yield improvement 的 LOO 贡献为弱负。",
                "kind": "broad",
            },
        ],
        "rawGate": compact_rows(
            raw_pass.sort_values("robust_score", ascending=False),
            {
                "metric": "metric",
                "label": "label",
                "family": "family",
                "coverage": "coverage",
                "activeCagr": "ratio_cagr",
                "topWorst": "top_worst_ratio_return",
                "robust": "robust_score",
                "note": "note",
            },
        ),
        "relativeGate": compact_rows(
            relative_pass,
            {
                "metric": "metric",
                "label": "raw_column",
                "family": "base_family",
                "role": "role",
                "transform": "transform",
                "lag": "lag_observations",
                "coverage": "coverage",
                "activeCagr": "ratio_cagr",
                "topWorst": "top_worst_ratio_return",
                "drawdown": "ratio_max_drawdown",
                "turnover": "avg_turnover",
                "robust": "robust_score",
                "economic": "economic_read",
            },
        ),
        "strictPairs": compact_rows(
            strict_pairs,
            {
                "metric": "metric",
                "label": "label",
                "buckets": "buckets",
                "activeCagr": "ratio_cagr",
                "topWorst": "top_worst_ratio_return",
                "drawdown": "ratio_max_drawdown",
                "turnover": "avg_turnover",
                "robust": "robust_score",
                "synergy": "synergy_score",
            },
            12,
        ),
        "subsets": compact_rows(
            subsets.head(12),
            {
                "metric": "metric",
                "label": "label",
                "buckets": "buckets",
                "components": "component_count",
                "activeCagr": "ratio_cagr",
                "topWorst": "top_worst_ratio_return",
                "drawdown": "ratio_max_drawdown",
                "turnover": "avg_turnover",
                "robust": "robust_score",
                "classification": "classification",
            },
        ),
        "leaveOneOut": compact_rows(
            leave_one_out,
            {
                "bucket": "left_out_bucket",
                "robustContribution": "loo_contribution",
                "activeContribution": "ratio_contribution",
                "withoutRobust": "without_robust_score",
                "classification": "classification",
            },
        ),
        "rotation": period_rows,
        "limitations": [
            "通过 raw 或 relative gate 是入选协同测试的前提，不是部署推荐；所有数字均是官方 20% Top/Worst 的未成本化研究证据。",
            "37 个严格结论只覆盖 cross-bucket pair；family subset 全部归为 additive，不能声称 family 内部存在已证实的协同。",
            "最强单变量和最强 pair 的换手较高，成本、容量、可交易性与风险预算必须另行验证。",
            "2024-2026 为短窗口轮动观察，不能与完整历史同等加权；结果应随新样本滚动复核。",
            "core / supplement 与 CIQ / FactSet / database 只作来源和诊断标签，所有可用字段走相同 official gate。",
        ],
    }


def main() -> None:
    raw_meta, labels = enrich_raw_labels()
    definitions = load_definitions(SYNERGY_DIR / "metric_definitions.json")

    raw_source = metric_index(score_rows(RAW_DIR / "performance_summary.csv"))
    for (metric, side), row in list(raw_source.items()):
        if metric.startswith("eu_small_"):
            raw_source[("sp500_" + metric[len("eu_small_") :], side)] = row
    sources = {
        "latest": metric_index(score_rows(SYNERGY_DIR / "performance_summary.csv")),
        "relative": metric_index(score_rows(RELATIVE_DIR / "performance_summary.csv")),
        "raw": raw_source,
    }
    candidate_map = read_csv(SYNERGY_DIR / "candidate_map.csv").set_index("metric")
    synergy = read_csv(SYNERGY_DIR / "synergy_claims.csv")
    subsets = read_csv(SYNERGY_DIR / "family_subset_results.csv").sort_values("robust_score", ascending=False)
    leave_one_out = read_csv(SYNERGY_DIR / "leave_one_out_results.csv")
    raw_pass = read_csv(SYNERGY_DIR / "report_raw_top_pass.csv")
    relative_gate = read_csv(RELATIVE_DIR / "relative_validation_gate.csv")
    relative_pass = read_csv(SYNERGY_DIR / "report_relative_top_pass.csv")
    period_top_raw = read_csv(SYNERGY_DIR / "report_period_top_raw.csv")
    raw_variable_count = len(
        score_rows(RAW_DIR / "performance_summary.csv").loc[lambda frame: frame["side"].eq("Top"), "metric"].unique()
    )

    chosen: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()

    def choose(metric: str, group: str, source: str, evidence: str) -> None:
        if metric not in seen:
            chosen.append((metric, group, source, evidence))
            seen.add(metric)

    for metric in [
        "sp500_syn_subset_08e95a53d5",
        "sp500_syn_subset_6d32f9616c",
        "sp500_syn_full_bucket_equal",
    ]:
        choose(metric, "最新核心组合", "latest", "family subset / full model official evidence")
    for metric in synergy.loc[synergy["classification"].eq("synergistic"), "metric"]:
        choose(str(metric), "已证实协同 pair", "latest", "pair synergy official evidence")
    for metric in subsets.head(20)["metric"]:
        choose(str(metric), "领先 family subset", "latest", "family subset official evidence")
    for metric in leave_one_out["metric"]:
        choose(str(metric), "最新 leave-one-out", "latest", "leave-one-out official evidence")
    for metric in raw_meta:
        source = "relative" if (metric, "Top") in sources["relative"] else "raw"
        choose(metric, "通过 gate 的单变量", source, "raw / relative raw official evidence")

    candidates = []
    missing = []
    for metric, group, source_name, evidence in chosen:
        index = sources[source_name]
        top = index.get((metric, "Top"))
        worst = index.get((metric, "Worst"))
        if top is None or worst is None:
            missing.append(metric)
            continue
        try:
            nav = joined_nav(top, worst)
        except FileNotFoundError:
            missing.append(metric)
            continue
        label = labels.get(metric)
        if not label and metric in candidate_map.index:
            label = str(candidate_map.loc[metric, "label"])
        label = label or str(top.label)
        labels[metric] = label
        top_metrics = {
            "robust": num(top.robust_score),
            "coverage": num(top.coverage),
            "topCagr": num(top.cagr),
            "activeCagr": num(top.ratio_cagr),
            "activeDrawdown": num(top.ratio_max_drawdown),
            "trackingError": num(top.tracking_error),
            "topWorstReturn": num(top.top_worst_ratio_return),
            "turnover": num(top.avg_turnover),
            "hitRate": num(top.annual_active_hit_rate),
            "rolling3y": num(top.rolling_3y_min_ratio_cagr),
        }
        raw_weight_rows = direct_components(metric, definitions, labels)
        if metric in raw_meta and not raw_weight_rows:
            raw_weight_rows = [{"metric": metric, "label": label, "path": raw_meta[metric]["bucket"], "weight": 1.0}]
        candidates.append(
            {
                "metric": metric,
                "label": label,
                "group": group,
                "evidence": evidence,
                "type": str(getattr(top, "role", "official candidate")),
                "note": str(getattr(top, "note", "")),
                "source": source_name,
                "rawMeta": raw_meta.get(metric, {}),
                "metrics": top_metrics,
                "series": monthly_series(nav),
                "periods": period_stats(nav),
                "rootWeights": root_components(metric, definitions, labels),
                "rawWeights": raw_weight_rows,
            }
        )

    candidates.sort(key=lambda candidate: (candidate["group"] != "最新核心组合", -float(candidate["metrics"]["robust"] or -999)))
    data = {
        "title": "SP500 因子研究浏览器",
        "asOf": "2026-06-30",
        "universe": "Weight in SP500 > 0",
        "benchmark": "SP500",
        "evidence": "official exact Top/Worst; 20% Top/Worst; ICB 19 中性；monthly signal",
        "periods": [
            {"id": period_id, "label": label, "start": start, "end": end}
            for period_id, label, start, end in PERIODS
        ],
        "defaultMetric": "sp500_syn_subset_08e95a53d5",
        "candidateCount": len(candidates),
        "missing": missing,
        "candidates": candidates,
        "analysis": analysis_payload(
            raw_pass,
            relative_pass,
            len(relative_gate),
            synergy,
            subsets,
            leave_one_out,
            period_top_raw,
            raw_variable_count,
        ),
        "provenance": {
            "latestSynergy": str(SYNERGY_DIR),
            "relativeRaw": str(RELATIVE_DIR),
            "rawGate": str(RAW_DIR),
            "officialMatrix": str(SYNERGY_DIR),
        },
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    fragment = html_fragment(payload)
    FRAGMENT.parent.mkdir(parents=True, exist_ok=True)
    FRAGMENT.write_text(fragment, encoding="utf-8")
    write_standalone()
    print(f"Wrote {FRAGMENT}")
    print(f"Wrote {STANDALONE}")
    print(f"Candidates: {len(candidates)}; missing: {len(missing)}; bytes: {FRAGMENT.stat().st_size}")


def write_standalone() -> None:
    spec = importlib.util.spec_from_file_location("tp_visualize_renderer", VISUALIZE_RENDERER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load visualization renderer: {VISUALIZE_RENDERER}")
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    document = renderer.render(FRAGMENT, "SP500 Factor Explorer")
    shell_style = "body{box-sizing:border-box;padding:1rem;background:inherit}iframe{display:block;width:100%;max-width:736px;height:calc(100vh - 2rem);margin:0 auto;border:0}"
    full_width_style = "body{box-sizing:border-box;padding:0;background:inherit}iframe{display:block;width:100%;max-width:none;height:100vh;margin:0;border:0}"
    if shell_style not in document:
        raise RuntimeError("Visualization shell style changed; full-width override needs review")
    STANDALONE.write_text(document.replace(shell_style, full_width_style), encoding="utf-8")


def html_fragment(payload: str) -> str:
    return f'''<div id="sp500-factor-explorer" class="research-explorer">
  <style>
    #sp500-factor-explorer {{
      --bg:#f3f6fa; --surface:rgba(255,255,255,.68); --surface-strong:rgba(255,255,255,.88);
      --ink:#182432; --muted:#66758a; --line:rgba(148,163,184,.22); --glass-line:rgba(255,255,255,.88);
      --green:#23826d; --teal:#087f86; --amber:#c28a35; --red:#c96f63; --blue:#5974ad;
      --shadow:0 10px 28px rgba(35,52,76,.08); --shadow-soft:0 4px 14px rgba(35,52,76,.05);
      color:var(--ink); background:var(--bg); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
    }}
    #sp500-factor-explorer * {{ box-sizing: border-box; }}
    #sp500-factor-explorer .shell {{ max-width:none; min-height:100%; margin:0; padding:28px 24px 44px; }}
    #sp500-factor-explorer .masthead {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-end; padding-bottom:18px; border-bottom:1px solid var(--line); }}
    #sp500-factor-explorer h1 {{ margin:0; font-size:30px; font-weight:500; letter-spacing:0; }}
    #sp500-factor-explorer .subhead {{ color:var(--muted); margin:8px 0 0; line-height:1.55; }}
    #sp500-factor-explorer .stamp {{ color:var(--muted); font-size:12px; line-height:1.55; text-align:right; white-space:nowrap; padding:10px 12px; background:var(--surface); border:1px solid var(--glass-line); border-radius:8px; box-shadow:var(--shadow-soft); backdrop-filter:blur(16px) saturate(125%); -webkit-backdrop-filter:blur(16px) saturate(125%); }}
    #sp500-factor-explorer .controls {{ display:grid; grid-template-columns:minmax(0, 1fr) minmax(230px, .42fr); gap:12px; margin:18px 0; }}
    #sp500-factor-explorer label {{ display:grid; gap:6px; color:var(--muted); font-size:12px; font-weight:500; }}
    #sp500-factor-explorer select {{ width:100%; border:1px solid var(--glass-line); border-radius:8px; background:var(--surface-strong); color:var(--ink); padding:11px 12px; font:inherit; box-shadow:var(--shadow-soft); backdrop-filter:blur(16px) saturate(125%); -webkit-backdrop-filter:blur(16px) saturate(125%); }}
    #sp500-factor-explorer .metric-grid {{ display:grid; grid-template-columns:repeat(6, minmax(0, 1fr)); gap:10px; margin:12px 0 16px; }}
    #sp500-factor-explorer .metric {{ padding:12px 13px; background:var(--surface); border:1px solid var(--glass-line); border-radius:8px; min-height:76px; box-shadow:var(--shadow-soft); backdrop-filter:blur(18px) saturate(125%); -webkit-backdrop-filter:blur(18px) saturate(125%); }}
    #sp500-factor-explorer .metric span {{ display:block; color:var(--muted); font-size:11px; line-height:1.35; }}
    #sp500-factor-explorer .metric strong {{ display:block; font-size:20px; font-weight:500; margin-top:5px; }}
    #sp500-factor-explorer .metric strong.metric-text {{ font-size:12px; line-height:1.35; font-weight:500; }}
    #sp500-factor-explorer .layout {{ display:grid; grid-template-columns:minmax(250px, .72fr) minmax(560px, 1.75fr) minmax(285px, .88fr); gap:14px; align-items:start; }}
    #sp500-factor-explorer .period-rail, #sp500-factor-explorer .weights-rail, #sp500-factor-explorer .leader-rail, #sp500-factor-explorer .chart-column {{ min-width:0; }}
    #sp500-factor-explorer .period-rail {{ grid-column:1; grid-row:1; }}
    #sp500-factor-explorer .chart-column {{ grid-column:2; grid-row:1; }}
    #sp500-factor-explorer .weights-rail {{ grid-column:3; grid-row:1; }}
    #sp500-factor-explorer .leader-rail {{ grid-column:3; grid-row:2; }}
    #sp500-factor-explorer .block {{ background:var(--surface); border:1px solid var(--glass-line); border-radius:8px; padding:16px; margin-bottom:14px; box-shadow:var(--shadow); backdrop-filter:blur(20px) saturate(130%); -webkit-backdrop-filter:blur(20px) saturate(130%); }}
    #sp500-factor-explorer h2 {{ margin:0 0 11px; font-size:17px; font-weight:500; letter-spacing:0; }}
    #sp500-factor-explorer h3 {{ margin:15px 0 8px; font-size:14px; font-weight:500; }}
    #sp500-factor-explorer .chart {{ width:100%; min-height:620px; }}
    #sp500-factor-explorer .chart svg {{ display:block; width:100%; height:620px; }}
    #sp500-factor-explorer .legend {{ display:flex; flex-wrap:wrap; gap:12px; color:var(--muted); font-size:12px; margin:8px 0 0; }}
    #sp500-factor-explorer .legend i {{ display:inline-block; width:9px; height:9px; margin-right:5px; border-radius:2px; }}
    #sp500-factor-explorer .context {{ display:flex; justify-content:space-between; gap:16px; margin-bottom:10px; }}
    #sp500-factor-explorer .context .name {{ font-weight:500; font-size:18px; line-height:1.35; }}
    #sp500-factor-explorer .context .meta {{ color:var(--muted); font-size:12px; line-height:1.5; text-align:right; }}
    #sp500-factor-explorer .weights {{ display:flex; flex-wrap:wrap; gap:7px; }}
    #sp500-factor-explorer .weight-chip {{ border:1px solid var(--glass-line); background:rgba(255,255,255,.54); border-radius:8px; padding:6px 8px; font-size:11px; line-height:1.25; box-shadow:0 2px 8px rgba(35,52,76,.04); }}
    #sp500-factor-explorer .weight-chip b {{ display:block; font-size:12px; font-weight:500; }}
    #sp500-factor-explorer table {{ width:100%; border-collapse:collapse; }}
    #sp500-factor-explorer th, #sp500-factor-explorer td {{ padding:9px 7px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:12px; line-height:1.4; }}
    #sp500-factor-explorer th {{ color:var(--muted); font-size:11px; font-weight:500; background:rgba(248,250,252,.5); }}
    #sp500-factor-explorer tbody tr:hover {{ background:rgba(255,255,255,.42); }}
    #sp500-factor-explorer td.num, #sp500-factor-explorer th.num {{ text-align:right; white-space:nowrap; }}
    #sp500-factor-explorer .table-scroll {{ overflow:auto; max-height:470px; }}
    #sp500-factor-explorer .select-row {{ cursor:pointer; background:transparent; color:var(--ink); border:0; width:100%; text-align:left; padding:0; font:inherit; font-weight:500; }}
    #sp500-factor-explorer .select-row:hover {{ color:var(--teal); }}
    #sp500-factor-explorer .muted {{ color:var(--muted); }}
    #sp500-factor-explorer .path {{ color:var(--muted); font-size:11px; }}
    #sp500-factor-explorer .footer {{ color:var(--muted); font-size:11px; line-height:1.55; margin-top:8px; overflow-wrap:anywhere; }}
    #sp500-factor-explorer .empty {{ color:var(--muted); padding:18px 0; }}
    #sp500-factor-explorer .table-scroll {{ scrollbar-color:rgba(100,116,139,.35) transparent; scrollbar-width:thin; }}
    #sp500-factor-explorer .table-scroll::-webkit-scrollbar {{ width:8px; height:8px; }}
    #sp500-factor-explorer .table-scroll::-webkit-scrollbar-thumb {{ background:rgba(100,116,139,.30); border-radius:8px; }}
    #sp500-factor-explorer .analysis-band {{ margin:20px 0 18px; }}
    #sp500-factor-explorer .analysis-verdict {{ display:grid; grid-template-columns:minmax(0,1.35fr) minmax(290px,.65fr); gap:16px; padding:18px; border:1px solid rgba(8,127,134,.25); border-left:4px solid var(--teal); border-radius:8px; background:rgba(231,245,245,.68); box-shadow:var(--shadow-soft); }}
    #sp500-factor-explorer .analysis-kicker {{ margin:0 0 5px; color:var(--teal); font-size:11px; font-weight:700; letter-spacing:.04em; }}
    #sp500-factor-explorer .analysis-verdict h2 {{ margin:0; font-size:20px; line-height:1.3; }}
    #sp500-factor-explorer .analysis-verdict p {{ margin:8px 0 0; color:var(--muted); font-size:13px; line-height:1.6; }}
    #sp500-factor-explorer .analysis-stats {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); border-left:1px solid rgba(8,127,134,.16); }}
    #sp500-factor-explorer .analysis-stat {{ padding:8px 11px; border-bottom:1px solid rgba(8,127,134,.13); }}
    #sp500-factor-explorer .analysis-stat:nth-child(odd) {{ border-right:1px solid rgba(8,127,134,.13); }}
    #sp500-factor-explorer .analysis-stat b {{ display:block; font-size:20px; font-weight:600; color:var(--teal); }}
    #sp500-factor-explorer .analysis-stat span {{ display:block; margin-top:2px; color:var(--muted); font-size:10px; line-height:1.35; }}
    #sp500-factor-explorer .analysis-grid {{ display:grid; grid-template-columns:minmax(0,1.05fr) minmax(360px,.95fr); gap:14px; margin-top:14px; }}
    #sp500-factor-explorer .analysis-panel {{ min-width:0; padding:16px; border:1px solid var(--glass-line); border-radius:8px; background:var(--surface); box-shadow:var(--shadow-soft); backdrop-filter:blur(18px) saturate(125%); -webkit-backdrop-filter:blur(18px) saturate(125%); }}
    #sp500-factor-explorer .analysis-panel-head {{ display:flex; align-items:flex-end; justify-content:space-between; gap:14px; margin-bottom:10px; }}
    #sp500-factor-explorer .analysis-panel-head h2 {{ margin:0; font-size:17px; font-weight:500; }}
    #sp500-factor-explorer .analysis-panel-head p {{ margin:0; color:var(--muted); font-size:11px; line-height:1.45; text-align:right; }}
    #sp500-factor-explorer .analysis-focus-select {{ width:100%; margin-bottom:10px; }}
    #sp500-factor-explorer .analysis-mode {{ display:flex; gap:6px; margin:10px 0; }}
    #sp500-factor-explorer .analysis-mode button, #sp500-factor-explorer .evidence-tabs button {{ border:1px solid var(--line); border-radius:6px; background:rgba(255,255,255,.5); color:var(--muted); padding:6px 8px; font:inherit; font-size:11px; cursor:pointer; }}
    #sp500-factor-explorer .analysis-mode button.active, #sp500-factor-explorer .evidence-tabs button.active {{ color:var(--teal); border-color:rgba(8,127,134,.35); background:rgba(231,245,245,.86); font-weight:600; }}
    #sp500-factor-explorer .analysis-focus-title {{ display:flex; align-items:center; gap:8px; margin:0; font-size:15px; font-weight:600; }}
    #sp500-factor-explorer .analysis-badge {{ display:inline-block; padding:3px 6px; border-radius:5px; background:rgba(35,130,109,.12); color:var(--green); font-size:10px; font-weight:700; letter-spacing:.03em; white-space:nowrap; }}
    #sp500-factor-explorer .analysis-badge.strict {{ color:var(--teal); background:rgba(8,127,134,.12); }}
    #sp500-factor-explorer .analysis-badge.additive {{ color:var(--amber); background:rgba(194,138,53,.12); }}
    #sp500-factor-explorer .analysis-badge.broad {{ color:var(--blue); background:rgba(89,116,173,.12); }}
    #sp500-factor-explorer .analysis-copy {{ margin:8px 0 0; color:var(--ink); font-size:13px; line-height:1.6; }}
    #sp500-factor-explorer .analysis-metric-row {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:7px; margin-top:12px; }}
    #sp500-factor-explorer .analysis-mini {{ padding:7px; border-radius:6px; background:rgba(255,255,255,.48); border:1px solid var(--glass-line); }}
    #sp500-factor-explorer .analysis-mini span {{ display:block; color:var(--muted); font-size:10px; line-height:1.25; }}
    #sp500-factor-explorer .analysis-mini b {{ display:block; margin-top:3px; font-size:14px; font-weight:600; }}
    #sp500-factor-explorer .analysis-note {{ margin:9px 0 0; padding-left:9px; border-left:2px solid var(--amber); color:var(--muted); font-size:11px; line-height:1.5; }}
    #sp500-factor-explorer .rotation-tabs {{ display:flex; flex-wrap:wrap; gap:6px; margin:0 0 11px; }}
    #sp500-factor-explorer .rotation-tabs button {{ border:0; padding:0 0 4px; background:transparent; color:var(--muted); border-bottom:2px solid transparent; font:inherit; font-size:11px; cursor:pointer; }}
    #sp500-factor-explorer .rotation-tabs button.active {{ color:var(--teal); border-bottom-color:var(--teal); font-weight:600; }}
    #sp500-factor-explorer .rotation-copy {{ margin:0 0 11px; padding-left:9px; border-left:2px solid var(--green); color:var(--muted); font-size:12px; line-height:1.55; }}
    #sp500-factor-explorer .rotation-copy.short {{ border-left-color:var(--amber); }}
    #sp500-factor-explorer .analysis-bar {{ display:grid; grid-template-columns:minmax(155px,1fr) minmax(90px,.55fr) 54px; gap:8px; align-items:center; margin:8px 0; }}
    #sp500-factor-explorer .analysis-bar-label {{ overflow-wrap:anywhere; font-size:11px; line-height:1.3; }}
    #sp500-factor-explorer .analysis-bar-track {{ height:9px; overflow:hidden; border-radius:6px; background:rgba(148,163,184,.15); }}
    #sp500-factor-explorer .analysis-bar-fill {{ height:100%; border-radius:6px; background:var(--teal); }}
    #sp500-factor-explorer .analysis-bar-value {{ text-align:right; font-size:11px; font-weight:600; white-space:nowrap; }}
    #sp500-factor-explorer .evidence-block {{ margin-top:14px; padding:16px; border:1px solid var(--glass-line); border-radius:8px; background:var(--surface); box-shadow:var(--shadow-soft); }}
    #sp500-factor-explorer .evidence-head {{ display:flex; align-items:end; justify-content:space-between; gap:12px; }}
    #sp500-factor-explorer .evidence-head h2 {{ margin:0; font-size:17px; font-weight:500; }}
    #sp500-factor-explorer .evidence-head p {{ margin:0; color:var(--muted); font-size:11px; text-align:right; }}
    #sp500-factor-explorer .evidence-tabs {{ display:flex; flex-wrap:wrap; gap:6px; margin:12px 0; }}
    #sp500-factor-explorer .analysis-table {{ max-height:380px; overflow:auto; }}
    #sp500-factor-explorer .analysis-table th {{ position:sticky; top:0; z-index:1; }}
    #sp500-factor-explorer .analysis-limit {{ display:grid; gap:8px; margin:0; padding:0; list-style:none; }}
    #sp500-factor-explorer .analysis-limit li {{ padding:9px 10px; border-left:3px solid var(--amber); background:rgba(255,255,255,.38); color:var(--muted); font-size:12px; line-height:1.5; }}
    #sp500-factor-explorer .period-list {{ display:grid; gap:0; }}
    #sp500-factor-explorer .period-btn {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; width:100%; padding:10px 1px; border:0; border-bottom:1px solid var(--line); background:transparent; color:var(--ink); font:inherit; text-align:left; cursor:pointer; }}
    #sp500-factor-explorer .period-btn:last-child {{ border-bottom:0; }}
    #sp500-factor-explorer .period-btn:hover, #sp500-factor-explorer .period-btn.active {{ color:var(--teal); }}
    #sp500-factor-explorer .period-btn span {{ display:block; font-size:12px; line-height:1.35; }}
    #sp500-factor-explorer .period-btn small {{ display:block; color:var(--muted); font-size:10px; margin-top:2px; }}
    #sp500-factor-explorer .period-btn b {{ font-size:12px; white-space:nowrap; }}
    #sp500-factor-explorer .period-explanation {{ margin:12px 0 0; padding-left:9px; border-left:2px solid var(--green); color:var(--muted); font-size:11px; line-height:1.55; }}
    @media (min-width: 1700px) {{ #sp500-factor-explorer .metric-grid {{ grid-template-columns:repeat(10, minmax(0, 1fr)); }} #sp500-factor-explorer .layout {{ grid-template-columns:minmax(270px, .75fr) minmax(640px, 1.8fr) minmax(310px, .88fr) minmax(260px, .68fr); }} #sp500-factor-explorer .period-rail {{ grid-column:1; grid-row:1; }} #sp500-factor-explorer .chart-column {{ grid-column:2; grid-row:1; }} #sp500-factor-explorer .weights-rail {{ grid-column:3; grid-row:1; }} #sp500-factor-explorer .leader-rail {{ grid-column:4; grid-row:1; }} }}
    @media (max-width: 1240px) {{ #sp500-factor-explorer .layout {{ grid-template-columns:minmax(0, 1.45fr) minmax(300px, .8fr); }} #sp500-factor-explorer .chart-column {{ grid-column:1; grid-row:1; }} #sp500-factor-explorer .period-rail {{ grid-column:1; grid-row:2; }} #sp500-factor-explorer .weights-rail {{ grid-column:2; grid-row:1; }} #sp500-factor-explorer .leader-rail {{ grid-column:2; grid-row:2; }} #sp500-factor-explorer .metric-grid {{ grid-template-columns:repeat(3, minmax(0, 1fr)); }} }}
    @media (max-width: 1100px) {{ #sp500-factor-explorer .analysis-grid {{ grid-template-columns:1fr; }} #sp500-factor-explorer .analysis-verdict {{ grid-template-columns:1fr; }} #sp500-factor-explorer .analysis-stats {{ border-left:0; border-top:1px solid rgba(8,127,134,.16); }} }}
    @media (max-width: 900px) {{ #sp500-factor-explorer .layout {{ display:block; }} #sp500-factor-explorer .analysis-metric-row {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} }}
    @media (max-width: 640px) {{ #sp500-factor-explorer .shell {{ padding:18px 12px 30px; }} #sp500-factor-explorer .masthead, #sp500-factor-explorer .context, #sp500-factor-explorer .analysis-panel-head, #sp500-factor-explorer .evidence-head {{ display:block; }} #sp500-factor-explorer .stamp, #sp500-factor-explorer .context .meta, #sp500-factor-explorer .analysis-panel-head p, #sp500-factor-explorer .evidence-head p {{ text-align:left; margin-top:9px; white-space:normal; }} #sp500-factor-explorer .controls, #sp500-factor-explorer .metric-grid {{ grid-template-columns:1fr; }} #sp500-factor-explorer .chart {{ min-height:500px; }} #sp500-factor-explorer .chart svg {{ height:500px; }} #sp500-factor-explorer .analysis-stats {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} #sp500-factor-explorer .analysis-metric-row {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} #sp500-factor-explorer .analysis-bar {{ grid-template-columns:minmax(105px,1fr) minmax(60px,.5fr) 48px; }} }}
  </style>
  <div class="shell">
    <header class="masthead">
      <div><h1>SP500 因子研究浏览器</h1><p class="subhead">全样本、时期轮动、官方 Top/Worst 与 raw / relative / synergy 证据</p></div>
      <div class="stamp" id="stamp"></div>
    </header>
    <section class="analysis-band" aria-label="SP500 因子研究解读">
      <div class="analysis-verdict">
        <div><div class="analysis-kicker">RESEARCH VERDICT</div><h2 id="analysis-verdict"></h2><p id="analysis-verdict-copy"></p></div>
        <div class="analysis-stats" id="analysis-stats"></div>
      </div>
      <div class="analysis-grid">
        <section class="analysis-panel">
          <div class="analysis-panel-head"><h2>重点结论</h2><p>选择结论会同步下方完整 NAV、时期表现与候选榜。</p></div>
          <select class="analysis-focus-select" id="analysis-focus-select" aria-label="选择重点研究结论"></select>
          <div class="analysis-mode" aria-label="重点结论阅读模式"><button type="button" data-focus-mode="evidence" class="active">证据</button><button type="button" data-focus-mode="economics">经济含义</button></div>
          <div id="analysis-focus"></div>
        </section>
        <section class="analysis-panel">
          <div class="analysis-panel-head"><h2>时期轮动</h2><p>每期展示该期 raw 变量的 Top / Benchmark 主动 CAGR。</p></div>
          <div class="rotation-tabs" id="rotation-tabs"></div>
          <div id="analysis-rotation"></div>
        </section>
      </div>
      <section class="evidence-block">
        <div class="evidence-head"><h2>证据台账</h2><p>Gate、严格 pair、family subset 与 LOO 分开呈现，避免把不同证据强度混为一谈。</p></div>
        <div class="evidence-tabs" id="evidence-tabs">
          <button type="button" data-evidence-tab="raw" class="active">Raw gate</button>
          <button type="button" data-evidence-tab="relative">Relative gate</button>
          <button type="button" data-evidence-tab="synergy">Pair / subset / LOO</button>
          <button type="button" data-evidence-tab="limits">边界条件</button>
        </div>
        <div class="analysis-table" id="analysis-evidence"></div>
      </section>
    </section>
    <div class="controls">
      <label>变量 / 组合<select id="candidate-select" aria-label="选择变量或组合"></select></label>
      <label>观察区间<select id="period-select" aria-label="选择观察区间"></select></label>
    </div>
    <section class="metric-grid" id="metrics" aria-label="选中候选的指标"></section>
    <main class="layout">
      <aside class="period-rail">
        <section class="block"><h2>时期主动表现</h2><p class="muted">点击任意时期，中央 NAV 与候选榜会同步切换。数值是 Top / Benchmark 主动 CAGR。</p><div class="period-list" id="period-table"></div><div class="period-explanation" id="period-explanation"></div></section>
      </aside>
      <div class="chart-column">
        <section class="block">
          <div class="context"><div class="name" id="selected-name"></div><div class="meta" id="selected-meta"></div></div>
          <div class="chart" id="chart" role="img" aria-label="Top Worst Benchmark NAV and ratio chart"></div>
          <div class="legend"><span><i style="background:var(--teal)"></i>Top</span><span><i style="background:var(--red)"></i>Worst</span><span><i style="background:var(--amber)"></i>Benchmark</span><span><i style="background:var(--green)"></i>Top / Benchmark</span><span><i style="background:var(--blue)"></i>Top / Worst</span></div>
        </section>
      </div>
      <aside class="weights-rail">
        <section class="block"><h2>入选构成与 nominal 权重</h2><div class="weights" id="root-weights"></div><div class="table-scroll" id="raw-weights"></div></section>
      </aside>
      <aside class="leader-rail">
        <section class="block"><h2>该时期的领先候选</h2><div class="table-scroll" id="leaderboard"></div></section>
      </aside>
    </main>
    <div class="footer" id="provenance"></div>
  </div>
  <script id="report-data" type="application/json">{payload}</script>
  <script>
  (() => {{
    const DATA = JSON.parse(document.getElementById('report-data').textContent);
    const ANALYSIS = DATA.analysis;
    const byMetric = new Map(DATA.candidates.map(item => [item.metric, item]));
    const candidateSelect = document.getElementById('candidate-select');
    const periodSelect = document.getElementById('period-select');
    const fmtPct = value => Number.isFinite(value) ? `${{(value * 100).toFixed(1)}}%` : '-';
    const fmtNum = value => Number.isFinite(value) ? value.toFixed(2) : '-';
    const fmtX = value => Number.isFinite(value) ? `${{value.toFixed(2)}}x` : '-';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[char]));
    const period = () => DATA.periods.find(item => item.id === periodSelect.value);
    const selected = () => byMetric.get(candidateSelect.value);
    const seriesFor = (candidate, scope) => candidate.series.filter(point => point.d >= scope.start && point.d <= scope.end);
    const periodMetric = (candidate, scope) => candidate.periods[scope.id] || null;
    let focusMode = 'evidence';
    let evidenceTab = 'raw';
    let rotationPeriod = '2009-2012';
    function options() {{
      const groups = new Map();
      DATA.candidates.forEach(item => {{ if (!groups.has(item.group)) groups.set(item.group, []); groups.get(item.group).push(item); }});
      candidateSelect.innerHTML = [...groups].map(([group, items]) => `<optgroup label="${{esc(group)}}">${{items.map(item => `<option value="${{esc(item.metric)}}">${{esc(item.label)}}</option>`).join('')}}</optgroup>`).join('');
      periodSelect.innerHTML = DATA.periods.map(item => `<option value="${{item.id}}">${{esc(item.label)}} (${{item.start}} 至 ${{item.end}})</option>`).join('');
      candidateSelect.value = DATA.defaultMetric;
      periodSelect.value = 'all';
    }}
    function analysisOptions() {{
      document.getElementById('analysis-verdict').textContent = ANALYSIS.verdict.headline;
      document.getElementById('analysis-verdict-copy').textContent = ANALYSIS.verdict.copy;
      document.getElementById('analysis-stats').innerHTML = ANALYSIS.stats.map(item => `<div class="analysis-stat"><b>${{esc(item.value)}}</b><span>${{esc(item.label)}}</span></div>`).join('');
      document.getElementById('analysis-focus-select').innerHTML = ANALYSIS.focus.map(item => `<option value="${{esc(item.id)}}">${{esc(item.badge)}} · ${{esc(item.name)}}</option>`).join('');
      document.getElementById('rotation-tabs').innerHTML = ANALYSIS.rotation.map(item => `<button type="button" data-rotation-period="${{esc(item.id)}}">${{esc(item.label)}}</button>`).join('');
      document.getElementById('analysis-focus-select').addEventListener('change', event => {{
        const item = ANALYSIS.focus.find(row => row.id === event.target.value);
        if (item && byMetric.has(item.metric)) candidateSelect.value = item.metric;
        render();
      }});
      document.querySelectorAll('[data-focus-mode]').forEach(button => button.addEventListener('click', () => {{ focusMode = button.dataset.focusMode; renderAnalysisFocus(); }}));
      document.querySelectorAll('[data-evidence-tab]').forEach(button => button.addEventListener('click', () => {{ evidenceTab = button.dataset.evidenceTab; renderAnalysisEvidence(); }}));
      document.querySelectorAll('[data-rotation-period]').forEach(button => button.addEventListener('click', () => {{
        rotationPeriod = button.dataset.rotationPeriod;
        periodSelect.value = rotationPeriod;
        render();
      }}));
    }}
    function renderAnalysisFocus() {{
      const select = document.getElementById('analysis-focus-select');
      const item = ANALYSIS.focus.find(row => row.id === select.value) || ANALYSIS.focus[0];
      const evidence = item.evidence;
      document.querySelectorAll('[data-focus-mode]').forEach(button => button.classList.toggle('active', button.dataset.focusMode === focusMode));
      const badgeClass = item.kind === 'strict' ? 'strict' : item.kind === 'additive' ? 'additive' : item.kind === 'broad' ? 'broad' : '';
      const copy = focusMode === 'economics' ? item.economics : item.thesis;
      const cards = [
        ['Robust', fmtNum(evidence.robust)], ['Top / Bench CAGR', fmtPct(evidence.activeCagr)], ['Top / Worst', fmtX(evidence.topWorst)],
        ['Ratio max DD', fmtPct(evidence.drawdown)], ['Turnover', fmtPct(evidence.turnover)], ['Synergy score', fmtNum(evidence.synergyScore)]
      ];
      document.getElementById('analysis-focus').innerHTML = `<div class="analysis-focus-title"><span class="analysis-badge ${{badgeClass}}">${{esc(item.badge)}}</span><span>${{esc(item.name)}}</span></div><p class="analysis-copy">${{esc(copy)}}</p><div class="analysis-metric-row">${{cards.map(([label,value]) => `<div class="analysis-mini"><span>${{esc(label)}}</span><b>${{esc(value)}}</b></div>`).join('')}}</div><p class="analysis-note">${{esc(item.note)}}</p>`;
    }}
    function renderAnalysisRotation() {{
      const active = ANALYSIS.rotation.find(item => item.id === rotationPeriod) || ANALYSIS.rotation[0];
      document.querySelectorAll('[data-rotation-period]').forEach(button => button.classList.toggle('active', button.dataset.rotationPeriod === active.id));
      const max = Math.max(...active.leaders.map(item => Math.abs(Number(item.activeCagr))), .001);
      const bars = active.leaders.map(item => {{
        const value = Number(item.activeCagr);
        const width = Math.min(Math.abs(value) / max * 100, 100);
        return `<div class="analysis-bar"><span class="analysis-bar-label">${{esc(item.label)}}</span><span class="analysis-bar-track"><span class="analysis-bar-fill" style="width:${{width.toFixed(1)}}%"></span></span><span class="analysis-bar-value">${{fmtPct(value)}}</span></div>`;
      }}).join('');
      document.getElementById('analysis-rotation').innerHTML = `<p class="rotation-copy ${{active.shortWindow ? 'short' : ''}}">${{esc(active.narrative)}}</p>${{bars}}`;
    }}
    function analysisTable(headers, rows) {{
      return `<table><thead><tr>${{headers.map(([label, numeric]) => `<th class="${{numeric ? 'num' : ''}}">${{esc(label)}}</th>`).join('')}}</tr></thead><tbody>${{rows.map(row => `<tr>${{row.map(([value, numeric]) => `<td class="${{numeric ? 'num' : ''}}">${{value}}</td>`).join('')}}</tr>`).join('')}}</tbody></table>`;
    }}
    function renderAnalysisEvidence() {{
      document.querySelectorAll('[data-evidence-tab]').forEach(button => button.classList.toggle('active', button.dataset.evidenceTab === evidenceTab));
      const root = document.getElementById('analysis-evidence');
      if (evidenceTab === 'raw') {{
        root.innerHTML = analysisTable(
          [['通过 gate 的 raw variable', false], ['Family', false], ['Coverage', true], ['主动 CAGR', true], ['Top/Worst', true], ['Robust', true]],
          ANALYSIS.rawGate.map(row => [[esc(row.label), false], [esc(row.family), false], [fmtPct(row.coverage), true], [fmtPct(row.activeCagr), true], [fmtX(row.topWorst), true], [fmtNum(row.robust), true]])
        );
        return;
      }}
      if (evidenceTab === 'relative') {{
        root.innerHTML = analysisTable(
          [['通过 gate 的 relative variable', false], ['Transform', false], ['Lag', true], ['主动 CAGR', true], ['DD', true], ['Turnover', true], ['Robust', true]],
          ANALYSIS.relativeGate.map(row => [[esc(row.label), false], [esc(row.transform), false], [esc(row.lag), true], [fmtPct(row.activeCagr), true], [fmtPct(row.drawdown), true], [fmtPct(row.turnover), true], [fmtNum(row.robust), true]])
        );
        return;
      }}
      if (evidenceTab === 'synergy') {{
        const pairs = analysisTable(
          [['严格 pair', false], ['Buckets', false], ['主动 CAGR', true], ['Top/Worst', true], ['Robust', true], ['Synergy', true]],
          ANALYSIS.strictPairs.map(row => [[esc(row.label), false], [esc(String(row.buckets).replaceAll('|', ' + ')), false], [fmtPct(row.activeCagr), true], [fmtX(row.topWorst), true], [fmtNum(row.robust), true], [fmtNum(row.synergy), true]])
        );
        const subsets = analysisTable(
          [['Family subset', false], ['分类', false], ['主动 CAGR', true], ['Top/Worst', true], ['Robust', true]],
          ANALYSIS.subsets.map(row => [[esc(row.label), false], [esc(row.classification), false], [fmtPct(row.activeCagr), true], [fmtX(row.topWorst), true], [fmtNum(row.robust), true]])
        );
        const loo = ANALYSIS.leaveOneOut;
        const max = Math.max(...loo.map(row => Math.abs(Number(row.robustContribution))), .001);
        const looBars = loo.map(row => {{ const value = Number(row.robustContribution), width = Math.abs(value) / max * 100; return `<div class="analysis-bar"><span class="analysis-bar-label">${{esc(row.bucket)}}</span><span class="analysis-bar-track"><span class="analysis-bar-fill" style="width:${{width.toFixed(1)}}%;background:${{value < 0 ? 'var(--red)' : 'var(--green)'}}"></span></span><span class="analysis-bar-value">${{value >= 0 ? '+' : ''}}${{fmtNum(value)}}</span></div>`; }}).join('');
        root.innerHTML = `<h3>严格 cross-bucket pair</h3>${{pairs}}<h3>2 / 3 bucket subset（全部为 additive）</h3>${{subsets}}<h3>Bucket-level leave-one-out：对全模型 Robust 的贡献</h3>${{looBars}}`;
        return;
      }}
      root.innerHTML = `<ul class="analysis-limit">${{ANALYSIS.limitations.map(item => `<li>${{esc(item)}}</li>`).join('')}}</ul>`;
    }}
    function linePath(points, key, x, y) {{ return points.map((point, index) => `${{index ? 'L' : 'M'}}${{x(index).toFixed(2)}},${{y(point[key]).toFixed(2)}}`).join(' '); }}
    function chart(candidate, scope) {{
      const rawPoints = seriesFor(candidate, scope);
      const root = document.getElementById('chart');
      if (rawPoints.length < 2) {{ root.innerHTML = '<div class="empty">该候选在此区间没有足够的 NAV 点。</div>'; return; }}
      const base = rawPoints[0];
      const points = rawPoints.map(point => ({{ ...point, t: point.t / base.t * 100, w: point.w / base.w * 100, b: point.b / base.b * 100 }}));
      const ratioPoints = points.map(point => ({{ ...point, active: point.t / point.b * 100, tw: point.t / point.w * 100 }}));
      const width = 980, height = 620, left = 48, right = 18, top = 18, navBottom = 188, activeTop = 236, activeBottom = 378, twTop = 426, twBottom = 570, bottom = 34;
      const x = index => left + index / Math.max(points.length - 1, 1) * (width - left - right);
      const domain = values => {{ const lo = Math.min(...values), hi = Math.max(...values), pad = Math.max((hi - lo) * .08, 1); return [lo - pad, hi + pad]; }};
      const navBounds = domain(points.flatMap(point => [point.t, point.w, point.b]));
      const activeBounds = domain(ratioPoints.map(point => point.active));
      const twBounds = domain(ratioPoints.map(point => point.tw));
      const scale = (bounds, panelTop, panelBottom) => value => panelTop + (bounds[1] - value) / (bounds[1] - bounds[0]) * (panelBottom - panelTop);
      const yNav = scale(navBounds, top, navBottom);
      const yActive = scale(activeBounds, activeTop, activeBottom);
      const yTw = scale(twBounds, twTop, twBottom);
      const grid = (bounds, y) => [bounds[0], (bounds[0]+bounds[1])/2, bounds[1]].map(value => `<g><line x1="${{left}}" y1="${{y(value)}}" x2="${{width-right}}" y2="${{y(value)}}" stroke="#dfe6ef" stroke-width="1"/><text x="5" y="${{y(value)+4}}" fill="#66758a" font-size="11">${{Math.round(value)}}</text></g>`).join('');
      root.innerHTML = `<svg viewBox="0 0 ${{width}} ${{height}}" width="100%" height="100%" aria-label="${{esc(candidate.label)}} NAV and ratios"><title>${{esc(candidate.label)}}：Top、Worst、Benchmark、Top / Benchmark 与 Top / Worst</title>${{grid(navBounds,yNav)}}<path d="${{linePath(points,'b',x,yNav)}}" fill="none" stroke="#c28a35" stroke-width="2"/><path d="${{linePath(points,'w',x,yNav)}}" fill="none" stroke="#c96f63" stroke-width="2"/><path d="${{linePath(points,'t',x,yNav)}}" fill="none" stroke="#087f86" stroke-width="2.5"/><text x="${{left}}" y="218" fill="#66758a" font-size="11">Top / Benchmark（起点 = 100）</text>${{grid(activeBounds,yActive)}}<path d="${{ratioPoints.map((point,index)=>`${{index?'L':'M'}}${{x(index).toFixed(2)}},${{yActive(point.active).toFixed(2)}}`).join(' ')}}" fill="none" stroke="#23826d" stroke-width="2.3"/><text x="${{left}}" y="408" fill="#66758a" font-size="11">Top / Worst（起点 = 100）</text>${{grid(twBounds,yTw)}}<path d="${{ratioPoints.map((point,index)=>`${{index?'L':'M'}}${{x(index).toFixed(2)}},${{yTw(point.tw).toFixed(2)}}`).join(' ')}}" fill="none" stroke="#5974ad" stroke-width="2.1"/><text x="${{left}}" y="${{height-7}}" fill="#66758a" font-size="11">${{points[0].d}}</text><text x="${{width-right}}" y="${{height-7}}" text-anchor="end" fill="#66758a" font-size="11">${{points[points.length-1].d}}</text></svg>`;
    }}
    function renderMetrics(candidate, scope) {{
      const stat = periodMetric(candidate, scope);
      const whole = scope.id === 'all';
      const performanceCards = whole ? [
        ['Robust score', fmtNum(candidate.metrics.robust)], ['Top / Bench CAGR', fmtPct(candidate.metrics.activeCagr)], ['Ratio max DD', fmtPct(candidate.metrics.activeDrawdown)], ['Top / Worst return', fmtNum(candidate.metrics.topWorstReturn)], ['3Y 最差 relative CAGR', fmtPct(candidate.metrics.rolling3y)], ['年化命中率', fmtPct(candidate.metrics.hitRate)]
      ] : [
        ['Top / Bench CAGR', fmtPct(stat?.activeCagr)], ['Top CAGR', fmtPct(stat?.topCagr)], ['Top / Worst CAGR', fmtPct(stat?.topWorstCagr)], ['Active max DD', fmtPct(stat?.activeDrawdown)], ['有效起点', stat?.start || '-'], ['有效终点', stat?.end || '-']
      ];
      const evidenceCards = [
        ['Official evidence', candidate.evidence.replace(' official evidence', '')], ['Coverage', fmtPct(candidate.metrics.coverage)], ['Tracking error', fmtPct(candidate.metrics.trackingError)], ['Turnover', fmtPct(candidate.metrics.turnover)]
      ];
      document.getElementById('metrics').innerHTML = [...performanceCards, ...evidenceCards].map(([label,value]) => `<div class="metric"><span>${{esc(label)}}</span><strong class="${{String(value).length > 10 ? 'metric-text' : ''}}">${{esc(value)}}</strong></div>`).join('');
    }}
    function renderWeights(candidate) {{
      const root = document.getElementById('root-weights');
      root.innerHTML = candidate.rootWeights.length ? candidate.rootWeights.map(item => `<div class="weight-chip"><b>${{esc(item.label)}}</b>${{fmtPct(item.weight)}}</div>`).join('') : '<span class="muted">单一 raw variable：100%</span>';
      const rows = candidate.rawWeights.length ? candidate.rawWeights.map(item => `<tr><td>${{esc(item.label)}}</td><td class="path">${{esc(item.path || 'raw variable')}}</td><td class="num"><b>${{fmtPct(item.weight)}}</b></td></tr>`).join('') : '<tr><td colspan="3" class="muted">没有可展开的 raw variable 定义。</td></tr>';
      document.getElementById('raw-weights').innerHTML = `<table><thead><tr><th>Raw variable</th><th>归属路径</th><th class="num">总 nominal 权重</th></tr></thead><tbody>${{rows}}</tbody></table><p class="footer">Raw 权重为信号定义中的 nominal 权重；月度最少可用变量规则会在实际计算时对可用项重新归一。</p>`;
    }}
    function renderPeriods(candidate) {{
      const rows = DATA.periods.map(item => {{
        const stat = candidate.periods[item.id];
        const detail = item.id === 'all' ? '完整样本' : `Top/Worst ${{fmtPct(stat?.topWorstCagr)}} · DD ${{fmtPct(stat?.activeDrawdown)}}`;
        return `<button type="button" class="period-btn ${{item.id === periodSelect.value ? 'active' : ''}}" data-period="${{esc(item.id)}}"><span>${{esc(item.label)}}<small>${{esc(detail)}}</small></span><b>${{fmtPct(stat?.activeCagr)}}</b></button>`;
      }}).join('');
      document.getElementById('period-table').innerHTML = rows;
      const rotation = ANALYSIS.rotation.find(item => item.id === periodSelect.value);
      document.getElementById('period-explanation').textContent = rotation ? rotation.narrative : '全样本用于检验长期可复用性；切换单个时期查看该候选在不同市场定价机制中的主动表现。';
      document.querySelectorAll('#period-table [data-period]').forEach(button => button.addEventListener('click', () => {{
        if (button.dataset.period !== 'all') rotationPeriod = button.dataset.period;
        periodSelect.value = button.dataset.period;
        render();
      }}));
    }}
    function renderLeaderboard(scope) {{
      const rows = DATA.candidates.map(candidate => ({{ candidate, stat: periodMetric(candidate, scope) }})).filter(item => item.stat).sort((a,b) => b.stat.activeCagr - a.stat.activeCagr).slice(0, 10).map((item,index) => `<tr><td class="num">${{index+1}}</td><td><button class="select-row" data-metric="${{esc(item.candidate.metric)}}">${{esc(item.candidate.label)}}</button><div class="path">${{esc(item.candidate.group)}}</div></td><td class="num"><b>${{fmtPct(item.stat.activeCagr)}}</b></td><td class="num">${{fmtPct(item.stat.topWorstCagr)}}</td><td class="num">${{fmtPct(item.stat.activeDrawdown)}}</td></tr>`).join('');
      document.getElementById('leaderboard').innerHTML = `<table><thead><tr><th class="num">#</th><th>变量 / 组合</th><th class="num">Relative CAGR</th><th class="num">Top/Worst CAGR</th><th class="num">DD</th></tr></thead><tbody>${{rows}}</tbody></table>`;
      document.querySelectorAll('[data-metric]').forEach(button => button.addEventListener('click', () => {{ candidateSelect.value = button.dataset.metric; render(); }}));
    }}
    function render() {{
      const candidate = selected(), scope = period();
      if (scope.id !== 'all') rotationPeriod = scope.id;
      document.getElementById('selected-name').textContent = candidate.label;
      const economic = candidate.rawMeta?.economic ? `<br>经济角色：${{esc(candidate.rawMeta.economic)}}` : '';
      document.getElementById('selected-meta').innerHTML = `${{esc(candidate.group)}}<br>${{esc(candidate.metric)}}<br>${{esc(scope.label)}}${{economic}}`;
      renderMetrics(candidate, scope); chart(candidate, scope); renderPeriods(candidate); renderWeights(candidate); renderLeaderboard(scope); renderAnalysisFocus(); renderAnalysisRotation(); renderAnalysisEvidence();
    }}
    options();
    analysisOptions();
    document.getElementById('stamp').innerHTML = `截至 ${{DATA.asOf}}<br>${{DATA.candidateCount}} 个可交互候选<br>${{esc(DATA.benchmark)}}`;
    document.getElementById('provenance').innerHTML = `Universe: ${{esc(DATA.universe)}} · ${{esc(DATA.evidence)}}<br>严格协同矩阵：${{esc(DATA.provenance.latestSynergy)}}<br>Relative raw：${{esc(DATA.provenance.relativeRaw)}}<br>Raw gate：${{esc(DATA.provenance.rawGate)}}<br>Official matrix：${{esc(DATA.provenance.officialMatrix)}}`;
    candidateSelect.addEventListener('change', render); periodSelect.addEventListener('change', render); render();
  }})();
  </script>
</div>
'''


if __name__ == "__main__":
    main()

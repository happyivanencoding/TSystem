"""Build a standalone interactive explorer from official MSCI EUR SMALL runs."""

from __future__ import annotations

import json
import importlib.util
from collections import defaultdict
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "07_backtest_code" / "runs" / "ad_hoc"
SYNERGY_DIR = RUNS / "eu_small_relative_synergy_20260709"
RELATIVE_DIR = RUNS / "eu_small_relative_variables_20260709"
RAW_DIR = RUNS / "eu_small_multifactor_20260707_085611"
VALIDATED_DIR = RUNS / "eu_small_validated_gate_20260708_official"
QVM_CONFIG = ROOT / "15_small_cap_model" / "config" / "eu_small_validated_qvm.json"
FRAGMENT = (
    ROOT
    / ".codex"
    / "visualizations"
    / "2026"
    / "07"
    / "10"
    / "eu-small-factor-explorer"
    / "eu-small-factor-explorer.html"
)
STANDALONE = ROOT / "09_reports" / "eu-small-factor-explorer.html"
VISUALIZE_RENDERER = Path(
    r"C:\Users\jingx\.codex\plugins\cache\openai-bundled\visualize\1.0.11\skills\visualize\scripts\render.py"
)

PERIODS = [
    ("all", "全样本", "2005-03-31", "2026-06-30"),
    ("2005-2007", "Pre-GFC 信贷扩张", "2005-03-31", "2007-12-31"),
    ("2008-2012", "GFC 与欧债危机", "2008-01-01", "2012-12-31"),
    ("2013-2016", "ECB 低利率 / QE", "2013-01-01", "2016-12-31"),
    ("2017-2019", "后周期低利率扩张", "2017-01-01", "2019-12-31"),
    ("2020-2021", "疫情冲击与政策反弹", "2020-01-01", "2021-12-31"),
    ("2022-2023", "通胀、能源与加息冲击", "2022-01-01", "2023-12-31"),
    ("2024-2026", "通胀回落与政策正常化", "2024-01-01", "2026-06-30"),
]

PERIOD_ANALYSIS = {
    "all": {
        "headline": "长期主线：融资约束下的改善可见性",
        "leaders": "质量改善 + 去杠杆 + 估值改善",
        "economics": "欧洲小盘的长期定价不是简单偏好便宜或高增长，而是奖励能够改善盈利、降低融资风险，并让估值改善得到基本面确认的公司。",
    },
    "2005-2007": {
        "headline": "信贷扩张：改善需要预期与价格确认",
        "leaders": "Quality + Momentum；EPS Revision + PMOM",
        "economics": "信用扩张抬高风险偏好，市场愿意为改善付费，但盈利预期和价格趋势必须共同确认改善并非短暂噪声。",
    },
    "2008-2012": {
        "headline": "危机阶段：先看生存能力",
        "leaders": "Quality；ROE + Operating Margin；Dividend + Quality",
        "economics": "金融危机与欧债危机放大再融资约束，盈利质量、资产负债表韧性和可持续现金回报压倒成长叙事。",
    },
    "2013-2016": {
        "headline": "QE 修复：便宜需要现金流或增长确认",
        "leaders": "PFCF + DPS Growth；PMOM + PFCF",
        "economics": "低利率支持估值修复，但小盘公司的信息不确定性仍高，现金流或增长确认决定估值折价能否真正收敛。",
    },
    "2017-2019": {
        "headline": "后周期：利润率与趋势共同筛选",
        "leaders": "PMOM + Operating Margin；Quality",
        "economics": "周期后段的收入扩张放缓，利润率改善提供经营杠杆证据，价格趋势则确认市场正在吸收这一变化。",
    },
    "2020-2021": {
        "headline": "疫情重估：盈利路径与偿债能力",
        "leaders": "EPS NTM 3M Growth；EPS Revision + NetDebt/EBITDA",
        "economics": "盈利路径被快速重写，近端增长与分析师修正识别重估方向，偿债能力决定改善能否留给股东。",
    },
    "2022-2023": {
        "headline": "通胀加息：现金流、利润率与现金回报",
        "leaders": "DVD Yield NTM + Operating Margin；PFCF LTM",
        "economics": "融资成本和投入成本同时上升，即时现金流、定价能力与可持续现金回报成为小盘公司的防线。",
    },
    "2024-2026": {
        "headline": "政策正常化：趋势回归，但仍需质量约束",
        "leaders": "Dividend + PMOM；QVM；Growth 不占优",
        "economics": "通胀回落后市场重新接受趋势信号，但小盘融资约束没有消失，质量与现金回报仍是趋势持续性的过滤器。",
    },
}

BUCKET_ECONOMICS = {
    "quality_improvement": "利润率或 ROE 改善表明经营效率正在变好，可过滤静态高质量但边际恶化的公司。",
    "deleveraging": "去杠杆降低再融资、违约和股权稀释风险；这一机制在融资渠道更窄的小盘公司中尤其重要。",
    "value_improvement": "估值相对自身历史变得更便宜，表达的是折价正在形成而非长期停留在便宜状态；仍需基本面催化。",
    "earnings_yield_improvement": "远期盈利收益率改善提供估值纪律，避免为改善预期支付过高价格。",
    "revision": "盈利预期上修捕捉信息扩散和分析师纠错，是基本面改善能否进入市场定价的确认层。",
    "pmom": "价格动量确认投资者已开始吸收新信息，可减少过早押注尚未被市场认可的变化。",
    "growth": "近端盈利增长代表兑现能力，但欧洲小盘的广义 growth 证据较弱，只宜作为有门槛的补充信号。",
    "risk_decline": "波动下降主要是风险过滤器；单独作为 alpha 核心的证据弱于质量改善和去杠杆。",
    "quality": "高盈利能力和利润率提供经营韧性，但静态水平不等同于边际改善。",
    "value": "估值提供安全边际，其中现金流估值比纯账面或企业价值倍数更可靠；静态便宜仍可能是价值陷阱。",
    "momentum": "盈利修正和价格趋势表达信息扩散，但需要质量或估值约束来控制拥挤与反转风险。",
    "dividend": "现金回报体现资本纪律，在高利率或压力阶段更有价值，但必须排除不可持续派息。",
    "lowvol": "低波动更适合作为风险预算和组合稳定器，本轮并不支持把它当作独立 alpha 核心。",
}


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
    raw_gate = read_csv(VALIDATED_DIR / "raw_validation_gate.csv")
    for row in raw_gate.itertuples(index=False):
        metric = str(row.metric)
        labels.setdefault(metric, str(row.label))
    return raw_meta, labels


def add_qvm_definition(definitions: dict[str, dict], labels: dict[str, str]) -> None:
    config = json.loads(QVM_CONFIG.read_text(encoding="utf-8"))
    components = {}
    for family, family_weight in config["final_weights"].items():
        variables = config["subfactors"][family]["variables"]
        family_key = f"qvm::{family}"
        family_components = {}
        for variable in variables:
            raw_key = f"raw::{variable['column']}"
            family_components[raw_key] = 1 / len(variables)
            direction = "高为好" if variable["direction"] > 0 else "低为好"
            labels[raw_key] = f"{variable['column']}（{direction}）"
        definitions[family_key] = family_components
        labels[family_key] = f"{family}"
        components[family_key] = family_weight
    definitions["eu_small_validated_qvm"] = components


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
        child_label = labels.get(child, child.replace("eu_small_syn_bucket_", ""))
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
        {"label": labels.get(child, str(child).replace("eu_small_syn_bucket_", "")), "weight": round(float(weight), 6)}
        for child, weight in components.items()
    ]


def truthy(value: object) -> bool:
    return value is True or str(value).strip().lower() == "true"


def text_value(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value)


def analysis_payload(
    raw_gate: pd.DataFrame,
    relative_gate: pd.DataFrame,
    synergy: pd.DataFrame,
    subsets: pd.DataFrame,
    leave_one_out: pd.DataFrame,
    candidate_map: pd.DataFrame,
    performance: pd.DataFrame,
) -> dict[str, object]:
    raw_rows = []
    for row in raw_gate.sort_values(["pass_gate", "robust_score"], ascending=[False, False]).itertuples(index=False):
        raw_rows.append(
            {
                "metric": str(row.metric),
                "label": str(row.label),
                "family": str(row.raw_family),
                "source": str(row.source_tag),
                "coverage": num(row.coverage),
                "activeCagr": num(row.ratio_cagr),
                "topWorst": num(row.top_worst_ratio_return),
                "robust": num(row.robust_score),
                "passed": truthy(row.pass_gate),
                "reason": text_value(row.failure_reasons),
                "note": text_value(row.note),
            }
        )

    relative_rows = []
    for row in relative_gate.sort_values(["pass_gate", "robust_score"], ascending=[False, False]).itertuples(index=False):
        relative_rows.append(
            {
                "metric": str(row.metric),
                "raw": str(row.raw_column),
                "family": str(row.base_family),
                "source": str(row.source),
                "transform": str(row.transform),
                "lag": int(row.lag_observations),
                "coverage": num(row.coverage),
                "activeCagr": num(row.ratio_cagr),
                "topWorst": num(row.top_worst_ratio_return),
                "robust": num(row.robust_score),
                "passed": truthy(row.pass_gate),
                "reason": text_value(row.fail_reasons),
                "economic": text_value(row.economic_read),
            }
        )

    synergy_rows = []
    for row in synergy.sort_values("synergy_score", ascending=False).itertuples(index=False):
        synergy_rows.append(
            {
                "metric": str(row.metric),
                "label": str(row.label),
                "buckets": str(row.buckets).replace("|", " + "),
                "coverage": num(row.coverage),
                "activeCagr": num(row.ratio_cagr),
                "topWorst": num(row.top_worst_ratio_return),
                "robust": num(row.robust_score),
                "synergy": num(row.synergy_score),
                "classification": str(row.classification),
            }
        )

    subset_rows = []
    for row in subsets.sort_values("robust_score", ascending=False).itertuples(index=False):
        subset_rows.append(
            {
                "metric": str(row.metric),
                "label": str(row.label),
                "buckets": str(row.buckets).replace("|", " + "),
                "coverage": num(row.coverage),
                "activeCagr": num(row.ratio_cagr),
                "topWorst": num(row.top_worst_ratio_return),
                "drawdown": num(row.ratio_max_drawdown),
                "robust": num(row.robust_score),
                "classification": str(row.classification),
            }
        )

    loo_rows = []
    for row in leave_one_out.sort_values("loo_contribution", ascending=False).itertuples(index=False):
        loo_rows.append(
            {
                "bucket": str(row.left_out_bucket),
                "robustContribution": num(row.loo_contribution),
                "activeContribution": num(row.ratio_contribution),
                "classification": str(row.classification),
            }
        )

    tested_candidates = int(
        candidate_map["candidate_type"].isin(["pair", "family_subset", "full_model", "leave_one_out"]).sum()
    )
    successful_sides = int(
        (
            performance["status"].eq("success")
            & performance["valid"].astype(str).eq("True")
        ).sum()
    )
    return {
        "summary": {
            "rawTested": len(raw_rows),
            "rawPassed": sum(row["passed"] for row in raw_rows),
            "relativeTested": len(relative_rows),
            "relativePassed": sum(row["passed"] for row in relative_rows),
            "candidateMetrics": tested_candidates,
            "officialSuccess": successful_sides,
            "officialExpected": tested_candidates * 2,
            "synergyClaims": len(synergy_rows),
        },
        "core": {
            "headline": "小盘不是便宜版欧洲，而是融资约束下的改善可见性",
            "verdict": "长期最稳的结构是质量改善 + 去杠杆 + 估值改善。盈利修正和价格动量更适合作为确认层；广义 growth 与 low-vol 不应被机械纳入等权核心。",
        },
        "bucketEconomics": BUCKET_ECONOMICS,
        "periodAnalysis": PERIOD_ANALYSIS,
        "raw": raw_rows,
        "relative": relative_rows,
        "synergy": synergy_rows,
        "subsets": subset_rows,
        "loo": loo_rows,
        "limits": [
            "只有进入 synergy_claims.csv 的 pair 才称为直接协同；高回报 subset 本身不等于 synergy。",
            "Family 内部若没有 raw、subset 或 leave-one-out 证据，不声称变量之间存在协同。",
            "CIQ、FactSet、database 与本地衍生字段使用同一 gate；来源和 core/supplement 标签不决定入选。",
            "分时期结果用于识别 rotation 和机制变化，不替代全样本 gate，也不是对未来时期的预测。",
            "静态 value 需要现金流或改善催化；revision/PMOM 是确认层，low-vol 更接近风险过滤器。",
        ],
    }


def main() -> None:
    raw_meta, labels = enrich_raw_labels()
    definitions = load_definitions(SYNERGY_DIR / "metric_definitions.json")
    definitions.update(load_definitions(VALIDATED_DIR / "metric_definitions.json"))
    add_qvm_definition(definitions, labels)

    sources = {
        "latest": metric_index(score_rows(SYNERGY_DIR / "performance_summary.csv")),
        "relative": metric_index(score_rows(RELATIVE_DIR / "performance_summary.csv")),
        "raw": metric_index(score_rows(RAW_DIR / "performance_summary.csv")),
        "validated": metric_index(score_rows(VALIDATED_DIR / "performance_summary.csv")),
    }
    raw_gate = read_csv(VALIDATED_DIR / "raw_validation_gate.csv")
    relative_gate = read_csv(RELATIVE_DIR / "relative_validation_gate.csv")
    latest_performance = read_csv(SYNERGY_DIR / "performance_summary.csv")
    candidate_map_frame = read_csv(SYNERGY_DIR / "candidate_map.csv")
    candidate_map = candidate_map_frame.set_index("metric")
    synergy = read_csv(SYNERGY_DIR / "synergy_claims.csv")
    subsets = read_csv(SYNERGY_DIR / "family_subset_results.csv").sort_values("robust_score", ascending=False)
    leave_one_out = read_csv(SYNERGY_DIR / "leave_one_out_results.csv")

    chosen: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()

    def choose(metric: str, group: str, source: str, evidence: str) -> None:
        if metric not in seen:
            chosen.append((metric, group, source, evidence))
            seen.add(metric)

    for metric in [
        "eu_small_syn_subset_ee96431827",
        "eu_small_syn_subset_08e95a53d5",
        "eu_small_syn_full_bucket_equal",
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
    for metric in [
        "eu_small_validated_qvm",
        "eu_small_validated_quality_momentum",
        "eu_small_validated_quality_value",
        "eu_small_validated_value_momentum",
        "eu_small_validated_all_equal",
        "eu_small_validated_loo_growth",
    ]:
        choose(metric, "历史生产候选", "validated", "validated-family official evidence")

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
        "title": "MSCI Europe Small 因子研究浏览器",
        "asOf": "2026-06-30",
        "universe": "Weight in MSCI EUR SMALL > 0",
        "benchmark": "MSCI EUR SMALL",
        "evidence": "official exact Top/Worst; 20% Top/Worst; ICB 19 中性；monthly signal",
        "periods": [
            {"id": period_id, "label": label, "start": start, "end": end}
            for period_id, label, start, end in PERIODS
        ],
        "defaultMetric": "eu_small_syn_subset_ee96431827",
        "candidateCount": len(candidates),
        "missing": missing,
        "candidates": candidates,
        "analysis": analysis_payload(
            raw_gate,
            relative_gate,
            synergy,
            subsets,
            leave_one_out,
            candidate_map_frame,
            latest_performance,
        ),
        "provenance": {
            "latestSynergy": str(SYNERGY_DIR),
            "relativeRaw": str(RELATIVE_DIR),
            "rawGate": str(VALIDATED_DIR),
            "validatedQvm": str(VALIDATED_DIR),
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
    document = renderer.render(FRAGMENT, "MSCI Europe Small Factor Explorer")
    shell_style = "body{box-sizing:border-box;padding:1rem;background:inherit}iframe{display:block;width:100%;max-width:736px;height:calc(100vh - 2rem);margin:0 auto;border:0}"
    full_width_style = "body{box-sizing:border-box;padding:0;background:inherit}iframe{display:block;width:100%;max-width:none;height:100vh;margin:0;border:0}"
    if shell_style not in document:
        raise RuntimeError("Visualization shell style changed; full-width override needs review")
    STANDALONE.write_text(document.replace(shell_style, full_width_style), encoding="utf-8")


def html_fragment(payload: str) -> str:
    return f'''<div id="eu-small-factor-explorer" class="research-explorer">
  <style>
    #eu-small-factor-explorer {{
      --bg:#f3f6fa; --surface:rgba(255,255,255,.68); --surface-strong:rgba(255,255,255,.88);
      --ink:#182432; --muted:#66758a; --line:rgba(148,163,184,.22); --glass-line:rgba(255,255,255,.88);
      --green:#23826d; --teal:#087f86; --amber:#c28a35; --red:#c96f63; --blue:#5974ad;
      --shadow:0 10px 28px rgba(35,52,76,.08); --shadow-soft:0 4px 14px rgba(35,52,76,.05);
      color:var(--ink); background:var(--bg); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
    }}
    #eu-small-factor-explorer * {{ box-sizing: border-box; }}
    #eu-small-factor-explorer .shell {{ max-width:none; min-height:100%; margin:0; padding:28px 24px 44px; }}
    #eu-small-factor-explorer .masthead {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-end; padding-bottom:18px; border-bottom:1px solid var(--line); }}
    #eu-small-factor-explorer h1 {{ margin:0; font-size:30px; font-weight:500; letter-spacing:0; }}
    #eu-small-factor-explorer .subhead {{ color:var(--muted); margin:8px 0 0; line-height:1.55; }}
    #eu-small-factor-explorer .stamp {{ color:var(--muted); font-size:12px; line-height:1.55; text-align:right; white-space:nowrap; padding:10px 12px; background:var(--surface); border:1px solid var(--glass-line); border-radius:8px; box-shadow:var(--shadow-soft); backdrop-filter:blur(16px) saturate(125%); -webkit-backdrop-filter:blur(16px) saturate(125%); }}
    #eu-small-factor-explorer .controls {{ display:grid; grid-template-columns:minmax(0, 1fr) minmax(230px, .42fr); gap:12px; margin:18px 0; }}
    #eu-small-factor-explorer label {{ display:grid; gap:6px; color:var(--muted); font-size:12px; font-weight:500; }}
    #eu-small-factor-explorer select {{ width:100%; border:1px solid var(--glass-line); border-radius:8px; background:var(--surface-strong); color:var(--ink); padding:11px 12px; font:inherit; box-shadow:var(--shadow-soft); backdrop-filter:blur(16px) saturate(125%); -webkit-backdrop-filter:blur(16px) saturate(125%); }}
    #eu-small-factor-explorer .metric-grid {{ display:grid; grid-template-columns:repeat(6, minmax(0, 1fr)); gap:10px; margin:12px 0 16px; }}
    #eu-small-factor-explorer .metric {{ padding:12px 13px; background:var(--surface); border:1px solid var(--glass-line); border-radius:8px; min-height:76px; box-shadow:var(--shadow-soft); backdrop-filter:blur(18px) saturate(125%); -webkit-backdrop-filter:blur(18px) saturate(125%); }}
    #eu-small-factor-explorer .metric span {{ display:block; color:var(--muted); font-size:11px; line-height:1.35; }}
    #eu-small-factor-explorer .metric strong {{ display:block; font-size:20px; font-weight:500; margin-top:5px; }}
    #eu-small-factor-explorer .metric strong.metric-text {{ font-size:12px; line-height:1.35; font-weight:500; }}
    #eu-small-factor-explorer .layout {{ display:grid; grid-template-columns:minmax(250px, .72fr) minmax(560px, 1.75fr) minmax(285px, .88fr); gap:14px; align-items:start; }}
    #eu-small-factor-explorer .period-rail, #eu-small-factor-explorer .weights-rail, #eu-small-factor-explorer .leader-rail, #eu-small-factor-explorer .chart-column {{ min-width:0; }}
    #eu-small-factor-explorer .period-rail {{ grid-column:1; grid-row:1; }}
    #eu-small-factor-explorer .chart-column {{ grid-column:2; grid-row:1; }}
    #eu-small-factor-explorer .weights-rail {{ grid-column:3; grid-row:1; }}
    #eu-small-factor-explorer .leader-rail {{ grid-column:3; grid-row:2; }}
    #eu-small-factor-explorer .block {{ background:var(--surface); border:1px solid var(--glass-line); border-radius:8px; padding:16px; margin-bottom:14px; box-shadow:var(--shadow); backdrop-filter:blur(20px) saturate(130%); -webkit-backdrop-filter:blur(20px) saturate(130%); }}
    #eu-small-factor-explorer h2 {{ margin:0 0 11px; font-size:17px; font-weight:500; letter-spacing:0; }}
    #eu-small-factor-explorer h3 {{ margin:15px 0 8px; font-size:14px; font-weight:500; }}
    #eu-small-factor-explorer .chart {{ width:100%; min-height:620px; }}
    #eu-small-factor-explorer .chart svg {{ display:block; width:100%; height:620px; }}
    #eu-small-factor-explorer .legend {{ display:flex; flex-wrap:wrap; gap:12px; color:var(--muted); font-size:12px; margin:8px 0 0; }}
    #eu-small-factor-explorer .legend i {{ display:inline-block; width:9px; height:9px; margin-right:5px; border-radius:2px; }}
    #eu-small-factor-explorer .context {{ display:flex; justify-content:space-between; gap:16px; margin-bottom:10px; }}
    #eu-small-factor-explorer .context .name {{ font-weight:500; font-size:18px; line-height:1.35; }}
    #eu-small-factor-explorer .context .meta {{ color:var(--muted); font-size:12px; line-height:1.5; text-align:right; }}
    #eu-small-factor-explorer .weights {{ display:flex; flex-wrap:wrap; gap:7px; }}
    #eu-small-factor-explorer .weight-chip {{ border:1px solid var(--glass-line); background:rgba(255,255,255,.54); border-radius:8px; padding:6px 8px; font-size:11px; line-height:1.25; box-shadow:0 2px 8px rgba(35,52,76,.04); }}
    #eu-small-factor-explorer .weight-chip b {{ display:block; font-size:12px; font-weight:500; }}
    #eu-small-factor-explorer table {{ width:100%; border-collapse:collapse; }}
    #eu-small-factor-explorer th, #eu-small-factor-explorer td {{ padding:9px 7px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:12px; line-height:1.4; }}
    #eu-small-factor-explorer th {{ color:var(--muted); font-size:11px; font-weight:500; background:rgba(248,250,252,.5); }}
    #eu-small-factor-explorer tbody tr:hover {{ background:rgba(255,255,255,.42); }}
    #eu-small-factor-explorer td.num, #eu-small-factor-explorer th.num {{ text-align:right; white-space:nowrap; }}
    #eu-small-factor-explorer .table-scroll {{ overflow:auto; max-height:470px; }}
    #eu-small-factor-explorer .select-row {{ cursor:pointer; background:transparent; color:var(--ink); border:0; width:100%; text-align:left; padding:0; font:inherit; font-weight:500; }}
    #eu-small-factor-explorer .select-row:hover {{ color:var(--teal); }}
    #eu-small-factor-explorer .muted {{ color:var(--muted); }}
    #eu-small-factor-explorer .path {{ color:var(--muted); font-size:11px; }}
    #eu-small-factor-explorer .footer {{ color:var(--muted); font-size:11px; line-height:1.55; margin-top:8px; overflow-wrap:anywhere; }}
    #eu-small-factor-explorer .empty {{ color:var(--muted); padding:18px 0; }}
    #eu-small-factor-explorer .period-list {{ display:grid; }}
    #eu-small-factor-explorer .period-btn {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; width:100%; padding:10px 2px; border:0; border-bottom:1px solid var(--line); background:transparent; color:var(--ink); text-align:left; font:inherit; cursor:pointer; }}
    #eu-small-factor-explorer .period-btn:last-child {{ border-bottom:0; }}
    #eu-small-factor-explorer .period-btn:hover, #eu-small-factor-explorer .period-btn.active {{ color:var(--teal); }}
    #eu-small-factor-explorer .period-btn span {{ min-width:0; font-size:12px; line-height:1.35; }}
    #eu-small-factor-explorer .period-btn small {{ display:block; color:var(--muted); font-size:10px; margin-top:2px; }}
    #eu-small-factor-explorer .period-btn b {{ font-size:12px; font-weight:600; white-space:nowrap; }}
    #eu-small-factor-explorer .research-story {{ margin-top:28px; padding-top:24px; border-top:1px solid var(--line); }}
    #eu-small-factor-explorer .section-head {{ display:flex; align-items:flex-end; justify-content:space-between; gap:18px; margin:0 0 14px; }}
    #eu-small-factor-explorer .section-head h2 {{ margin:0; font-size:23px; }}
    #eu-small-factor-explorer .section-head p {{ max-width:760px; margin:5px 0 0; color:var(--muted); font-size:13px; line-height:1.55; }}
    #eu-small-factor-explorer .eyebrow {{ color:var(--teal); font-size:11px; font-weight:700; text-transform:uppercase; }}
    #eu-small-factor-explorer .core-callout {{ display:grid; grid-template-columns:minmax(0,1.3fr) minmax(320px,.7fr); gap:18px; padding:20px; margin-bottom:14px; background:rgba(255,255,255,.64); border:1px solid var(--glass-line); border-radius:8px; box-shadow:var(--shadow); backdrop-filter:blur(22px) saturate(130%); -webkit-backdrop-filter:blur(22px) saturate(130%); }}
    #eu-small-factor-explorer .core-callout h3 {{ margin:5px 0 8px; font-size:22px; }}
    #eu-small-factor-explorer .core-callout p {{ margin:0; color:var(--muted); line-height:1.65; }}
    #eu-small-factor-explorer .coverage-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:9px; }}
    #eu-small-factor-explorer .coverage-item {{ padding:11px 12px; border:1px solid var(--glass-line); background:rgba(255,255,255,.55); border-radius:8px; }}
    #eu-small-factor-explorer .coverage-item span {{ display:block; color:var(--muted); font-size:10px; }}
    #eu-small-factor-explorer .coverage-item strong {{ display:block; margin-top:4px; font-size:17px; font-weight:600; }}
    #eu-small-factor-explorer .analysis-focus {{ margin-bottom:14px; }}
    #eu-small-factor-explorer .analysis-toolbar {{ display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:13px; }}
    #eu-small-factor-explorer .segmented {{ display:flex; gap:4px; padding:3px; border:1px solid var(--glass-line); background:rgba(255,255,255,.48); border-radius:8px; }}
    #eu-small-factor-explorer .segmented button {{ border:0; border-radius:6px; padding:7px 10px; color:var(--muted); background:transparent; font:inherit; font-size:12px; cursor:pointer; }}
    #eu-small-factor-explorer .segmented button.active {{ color:var(--ink); background:var(--surface-strong); box-shadow:var(--shadow-soft); }}
    #eu-small-factor-explorer .focus-grid {{ display:grid; grid-template-columns:minmax(0,1.05fr) minmax(360px,.95fr); gap:18px; }}
    #eu-small-factor-explorer .focus-copy h3 {{ margin:7px 0 8px; font-size:20px; }}
    #eu-small-factor-explorer .focus-copy p {{ margin:0; color:var(--muted); line-height:1.65; }}
    #eu-small-factor-explorer .focus-metrics {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin-top:14px; }}
    #eu-small-factor-explorer .focus-metric {{ padding:9px 10px; border:1px solid var(--line); background:rgba(255,255,255,.4); border-radius:7px; }}
    #eu-small-factor-explorer .focus-metric span {{ display:block; color:var(--muted); font-size:10px; }}
    #eu-small-factor-explorer .focus-metric b {{ display:block; margin-top:3px; font-size:15px; font-weight:600; }}
    #eu-small-factor-explorer .badge {{ display:inline-block; padding:4px 7px; border-radius:6px; font-size:10px; font-weight:700; }}
    #eu-small-factor-explorer .badge.pass {{ color:var(--green); background:rgba(35,130,109,.10); }}
    #eu-small-factor-explorer .badge.warn {{ color:#9a681f; background:rgba(194,138,53,.13); }}
    #eu-small-factor-explorer .badge.fail {{ color:var(--red); background:rgba(201,111,99,.11); }}
    #eu-small-factor-explorer .evidence-list {{ display:grid; gap:9px; }}
    #eu-small-factor-explorer .evidence-row {{ display:grid; grid-template-columns:26px minmax(0,1fr); gap:9px; padding-bottom:9px; border-bottom:1px solid var(--line); }}
    #eu-small-factor-explorer .evidence-row:last-child {{ border-bottom:0; padding-bottom:0; }}
    #eu-small-factor-explorer .evidence-index {{ display:grid; place-items:center; width:24px; height:24px; border:1px solid var(--glass-line); border-radius:7px; background:rgba(255,255,255,.5); color:var(--teal); font-size:10px; }}
    #eu-small-factor-explorer .evidence-row strong {{ display:block; font-size:12px; font-weight:600; }}
    #eu-small-factor-explorer .evidence-row p {{ margin:2px 0 0; color:var(--muted); font-size:11px; line-height:1.45; }}
    #eu-small-factor-explorer .analysis-grid {{ display:grid; grid-template-columns:minmax(0,1.15fr) minmax(340px,.85fr); gap:14px; }}
    #eu-small-factor-explorer .period-narrative {{ padding-left:12px; border-left:3px solid var(--green); }}
    #eu-small-factor-explorer .period-narrative h3 {{ margin:0 0 5px; }}
    #eu-small-factor-explorer .period-narrative p {{ margin:4px 0; color:var(--muted); font-size:12px; line-height:1.55; }}
    #eu-small-factor-explorer .bar-chart {{ display:grid; gap:8px; margin-top:14px; }}
    #eu-small-factor-explorer .bar-row {{ display:grid; grid-template-columns:minmax(160px,1fr) minmax(90px,.8fr) 52px; gap:8px; align-items:center; }}
    #eu-small-factor-explorer .bar-label {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11px; }}
    #eu-small-factor-explorer .bar-track {{ height:8px; overflow:hidden; border-radius:5px; background:rgba(148,163,184,.16); }}
    #eu-small-factor-explorer .bar-fill {{ display:block; height:100%; border-radius:5px; background:var(--teal); }}
    #eu-small-factor-explorer .bar-row.negative .bar-fill {{ background:var(--red); }}
    #eu-small-factor-explorer .bar-value {{ text-align:right; font-size:11px; font-weight:600; }}
    #eu-small-factor-explorer .evidence-tabs {{ display:flex; gap:5px; overflow:auto; margin:0 0 12px; border-bottom:1px solid var(--line); }}
    #eu-small-factor-explorer .evidence-tabs button {{ padding:8px 9px; border:0; border-bottom:2px solid transparent; background:transparent; color:var(--muted); font:inherit; font-size:12px; white-space:nowrap; cursor:pointer; }}
    #eu-small-factor-explorer .evidence-tabs button.active {{ color:var(--ink); border-bottom-color:var(--teal); font-weight:600; }}
    #eu-small-factor-explorer .panel-hidden {{ display:none; }}
    #eu-small-factor-explorer .gate-toolbar {{ display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:9px; }}
    #eu-small-factor-explorer .gate-toolbar select {{ width:auto; min-width:120px; padding:7px 9px; font-size:12px; }}
    #eu-small-factor-explorer .research-table {{ overflow:auto; max-height:520px; }}
    #eu-small-factor-explorer .research-table table {{ min-width:760px; }}
    #eu-small-factor-explorer .research-table th {{ position:sticky; top:0; z-index:1; background:rgba(248,250,252,.94); }}
    #eu-small-factor-explorer .synergy-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }}
    #eu-small-factor-explorer .inner-panel {{ min-width:0; padding:12px; border:1px solid var(--line); border-radius:8px; background:rgba(255,255,255,.34); }}
    #eu-small-factor-explorer .inner-panel h3 {{ margin:0 0 8px; }}
    #eu-small-factor-explorer .limits-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; }}
    #eu-small-factor-explorer .limit-item {{ padding:12px; border-left:3px solid var(--amber); background:rgba(255,255,255,.36); color:var(--muted); font-size:12px; line-height:1.55; }}
    #eu-small-factor-explorer .table-scroll {{ scrollbar-color:rgba(100,116,139,.35) transparent; scrollbar-width:thin; }}
    #eu-small-factor-explorer .table-scroll::-webkit-scrollbar {{ width:8px; height:8px; }}
    #eu-small-factor-explorer .table-scroll::-webkit-scrollbar-thumb {{ background:rgba(100,116,139,.30); border-radius:8px; }}
    @media (min-width: 1700px) {{ #eu-small-factor-explorer .metric-grid {{ grid-template-columns:repeat(10, minmax(0, 1fr)); }} #eu-small-factor-explorer .layout {{ grid-template-columns:minmax(270px, .75fr) minmax(640px, 1.8fr) minmax(310px, .88fr) minmax(260px, .68fr); }} #eu-small-factor-explorer .period-rail {{ grid-column:1; grid-row:1; }} #eu-small-factor-explorer .chart-column {{ grid-column:2; grid-row:1; }} #eu-small-factor-explorer .weights-rail {{ grid-column:3; grid-row:1; }} #eu-small-factor-explorer .leader-rail {{ grid-column:4; grid-row:1; }} }}
    @media (max-width: 1240px) {{ #eu-small-factor-explorer .layout {{ grid-template-columns:minmax(0, 1.45fr) minmax(300px, .8fr); }} #eu-small-factor-explorer .chart-column {{ grid-column:1; grid-row:1; }} #eu-small-factor-explorer .period-rail {{ grid-column:1; grid-row:2; }} #eu-small-factor-explorer .weights-rail {{ grid-column:2; grid-row:1; }} #eu-small-factor-explorer .leader-rail {{ grid-column:2; grid-row:2; }} #eu-small-factor-explorer .metric-grid {{ grid-template-columns:repeat(3, minmax(0, 1fr)); }} #eu-small-factor-explorer .core-callout, #eu-small-factor-explorer .focus-grid, #eu-small-factor-explorer .analysis-grid {{ grid-template-columns:1fr; }} }}
    @media (max-width: 900px) {{ #eu-small-factor-explorer .layout {{ display:block; }} }}
    @media (max-width: 640px) {{ #eu-small-factor-explorer .shell {{ padding:18px 12px 30px; }} #eu-small-factor-explorer .masthead, #eu-small-factor-explorer .context, #eu-small-factor-explorer .section-head, #eu-small-factor-explorer .analysis-toolbar {{ display:block; }} #eu-small-factor-explorer .stamp, #eu-small-factor-explorer .context .meta {{ text-align:left; margin-top:9px; white-space:normal; }} #eu-small-factor-explorer .controls, #eu-small-factor-explorer .metric-grid, #eu-small-factor-explorer .coverage-grid, #eu-small-factor-explorer .focus-metrics, #eu-small-factor-explorer .synergy-grid, #eu-small-factor-explorer .limits-grid {{ grid-template-columns:1fr; }} #eu-small-factor-explorer .segmented {{ margin-top:10px; width:max-content; }} #eu-small-factor-explorer .chart {{ min-height:500px; }} #eu-small-factor-explorer .chart svg {{ height:500px; }} }}
  </style>
  <div class="shell">
    <header class="masthead">
      <div><h1>MSCI Europe Small 因子研究浏览器</h1><p class="subhead">全样本、时期轮动、官方 Top/Worst 与 raw variable 权重结构</p></div>
      <div class="stamp" id="stamp"></div>
    </header>
    <div class="controls">
      <label>变量 / 组合<select id="candidate-select" aria-label="选择变量或组合"></select></label>
      <label>观察区间<select id="period-select" aria-label="选择观察区间"></select></label>
    </div>
    <section class="metric-grid" id="metrics" aria-label="选中候选的指标"></section>
    <main class="layout">
      <aside class="period-rail">
        <section class="block"><h2>时期主动表现</h2><p class="footer">点击任一时期，中央 plot 以该期首个有效月重新初始化为 100；右侧数值为 Top / Benchmark CAGR。</p><div class="period-list" id="period-table"></div></section>
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
    <section class="research-story" aria-labelledby="research-story-title">
      <div class="section-head"><div><div class="eyebrow">Official evidence interpretation</div><h2 id="research-story-title">从回测结果到经济解释</h2><p>沿用 Nasdaq 与 STOXX 600 浏览器的分析层，但结论只来自 MSCI Europe Small 自己的 raw、relative、pair、subset 与 leave-one-out 证据。</p></div></div>
      <section class="core-callout">
        <div><div class="eyebrow">全样本核心结论</div><h3 id="core-headline"></h3><p id="core-verdict"></p></div>
        <div class="coverage-grid" id="coverage-summary" aria-label="研究覆盖摘要"></div>
      </section>
      <section class="block analysis-focus">
        <div class="analysis-toolbar"><div><div class="eyebrow">跟随当前选择</div><h2>候选的证据链与经济含义</h2></div><div class="segmented" role="group" aria-label="切换分析模式"><button type="button" class="active" data-analysis-mode="evidence">证据链</button><button type="button" data-analysis-mode="economics">经济含义</button></div></div>
        <div class="focus-grid"><div class="focus-copy"><span class="badge" id="focus-badge"></span><h3 id="focus-heading"></h3><p id="focus-thesis"></p><div class="focus-metrics" id="focus-metrics"></div></div><div class="evidence-list" id="focus-evidence"></div></div>
      </section>
      <div class="analysis-grid">
        <section class="block"><h2>当前时期的轮动解释</h2><div class="period-narrative" id="period-narrative"></div><div class="bar-chart" id="rotation-bars"></div><p class="footer">排名范围为本页可交互候选；分时期切片是 rotation 诊断，不替代全样本 gate。</p></section>
        <section class="block"><h2>完整模型 leave-one-out</h2><p class="footer">正值表示移除该 bucket 后 robust score 下降，因此支持其对完整模型有增量贡献；负值表示弱贡献或冗余。</p><div class="bar-chart" id="loo-bars"></div></section>
      </div>
      <section class="block">
        <div class="section-head"><div><h2>研究证据矩阵</h2><p>所有来源使用同一 gate。直接协同只列入 synergy claims；subset 与 LOO 分开解释。</p></div><p id="matrix-summary"></p></div>
        <div class="evidence-tabs" role="tablist"><button type="button" class="active" data-evidence-tab="raw">Raw gate</button><button type="button" data-evidence-tab="relative">Relative gate</button><button type="button" data-evidence-tab="synergy">Pair / Subset / LOO</button><button type="button" data-evidence-tab="limits">边界与反例</button></div>
        <div data-evidence-panel="raw"><div class="gate-toolbar"><span class="muted">每个 raw variable 均先单独跑 official Top/Worst</span><label>显示<select id="raw-mode"><option value="pass">通过 gate</option><option value="all">全部</option><option value="fail">未通过</option></select></label></div><div class="research-table" id="raw-gate-table"></div></div>
        <div class="panel-hidden" data-evidence-panel="relative"><div class="gate-toolbar"><span class="muted">directional_delta / score_delta；lag 1 / 3 / 12</span><label>显示<select id="relative-mode"><option value="pass">通过 gate</option><option value="all">全部</option><option value="fail">未通过</option></select></label></div><div class="research-table" id="relative-gate-table"></div></div>
        <div class="panel-hidden synergy-grid" data-evidence-panel="synergy"><div class="inner-panel"><h3>已证实的 pair synergy</h3><div class="research-table" id="synergy-table"></div></div><div class="inner-panel"><h3>Family subset</h3><div class="research-table" id="subset-table"></div></div></div>
        <div class="panel-hidden limits-grid" data-evidence-panel="limits" id="limits-grid"></div>
      </section>
    </section>
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
    const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[char]));
    const period = () => DATA.periods.find(item => item.id === periodSelect.value);
    const selected = () => byMetric.get(candidateSelect.value);
    let analysisMode = 'evidence';
    const seriesFor = (candidate, scope) => candidate.series.filter(point => point.d >= scope.start && point.d <= scope.end);
    const periodMetric = (candidate, scope) => candidate.periods[scope.id] || null;
    function options() {{
      const groups = new Map();
      DATA.candidates.forEach(item => {{ if (!groups.has(item.group)) groups.set(item.group, []); groups.get(item.group).push(item); }});
      candidateSelect.innerHTML = [...groups].map(([group, items]) => `<optgroup label="${{esc(group)}}">${{items.map(item => `<option value="${{esc(item.metric)}}">${{esc(item.label)}}</option>`).join('')}}</optgroup>`).join('');
      periodSelect.innerHTML = DATA.periods.map(item => `<option value="${{item.id}}">${{esc(item.label)}} (${{item.start}} 至 ${{item.end}})</option>`).join('');
      candidateSelect.value = DATA.defaultMetric;
      periodSelect.value = 'all';
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
    function renderPeriods(candidate, scope) {{
      document.getElementById('period-table').innerHTML = DATA.periods.map(item => {{
        const stat = candidate.periods[item.id];
        return `<button type="button" class="period-btn ${{item.id === scope.id ? 'active' : ''}}" data-period-jump="${{item.id}}"><span>${{esc(item.label)}}<small>${{stat ? `Top/Worst ${{fmtPct(stat.topWorstCagr)}} · DD ${{fmtPct(stat.activeDrawdown)}}` : '有效数据不足'}}</small></span><b>${{fmtPct(stat?.activeCagr)}}</b></button>`;
      }}).join('');
      document.querySelectorAll('[data-period-jump]').forEach(button => button.addEventListener('click', () => {{ periodSelect.value = button.dataset.periodJump; render(); }}));
    }}
    function renderLeaderboard(scope) {{
      const rows = DATA.candidates.map(candidate => ({{ candidate, stat: periodMetric(candidate, scope) }})).filter(item => item.stat).sort((a,b) => b.stat.activeCagr - a.stat.activeCagr).slice(0, 10).map((item,index) => `<tr><td class="num">${{index+1}}</td><td><button class="select-row" data-leader-metric="${{esc(item.candidate.metric)}}">${{esc(item.candidate.label)}}</button><div class="path">${{esc(item.candidate.group)}}</div></td><td class="num"><b>${{fmtPct(item.stat.activeCagr)}}</b></td><td class="num">${{fmtPct(item.stat.topWorstCagr)}}</td><td class="num">${{fmtPct(item.stat.activeDrawdown)}}</td></tr>`).join('');
      document.getElementById('leaderboard').innerHTML = `<table><thead><tr><th class="num">#</th><th>变量 / 组合</th><th class="num">Relative CAGR</th><th class="num">Top/Worst CAGR</th><th class="num">DD</th></tr></thead><tbody>${{rows}}</tbody></table>`;
      document.querySelectorAll('[data-leader-metric]').forEach(button => button.addEventListener('click', () => {{ candidateSelect.value = button.dataset.leaderMetric; render(); }}));
    }}
    const bucketLabels = {{
      quality_improvement:'质量改善', deleveraging:'去杠杆', value_improvement:'估值改善', earnings_yield_improvement:'盈利收益率改善',
      revision:'盈利预期上修', pmom:'价格动量', growth:'前瞻增长', risk_decline:'风险下降', quality:'质量', value:'价值', momentum:'动量', dividend:'股息', lowvol:'低波动'
    }};
    function candidateBuckets(candidate) {{
      const roots = candidate.rootWeights.map(item => item.label).filter(Boolean);
      if (roots.length) return [...new Set(roots)];
      if (candidate.rawMeta?.bucket) return [candidate.rawMeta.bucket];
      return [...new Set(candidate.rawWeights.map(item => (item.path || '').split(' > ')[0]).filter(Boolean))];
    }}
    function renderFocus(candidate, scope) {{
      const strict = ANALYSIS.synergy.find(item => item.metric === candidate.metric);
      const subset = ANALYSIS.subsets.find(item => item.metric === candidate.metric);
      const periodStat = periodMetric(candidate, scope);
      const buckets = candidateBuckets(candidate);
      let badge = ['VALIDATED', 'warn'];
      if (strict) badge = ['STRICT SYNERGY', 'pass'];
      else if (subset) badge = ['OFFICIAL SUBSET', 'warn'];
      else if (candidate.evidence.includes('raw / relative')) badge = ['RAW GATE PASS', 'pass'];
      else if (candidate.evidence.includes('leave-one-out')) badge = ['LOO DIAGNOSTIC', 'warn'];
      const badgeRoot = document.getElementById('focus-badge');
      badgeRoot.textContent = badge[0]; badgeRoot.className = `badge ${{badge[1]}}`;
      document.getElementById('focus-heading').textContent = candidate.label;
      const fullMetrics = [
        ['Robust score', fmtNum(candidate.metrics.robust)],
        [scope.id === 'all' ? 'Top / Bench CAGR' : `${{scope.label}} active CAGR`, fmtPct(scope.id === 'all' ? candidate.metrics.activeCagr : periodStat?.activeCagr)],
        [scope.id === 'all' ? 'Top / Worst return' : 'Top / Worst CAGR', scope.id === 'all' ? fmtNum(candidate.metrics.topWorstReturn) : fmtPct(periodStat?.topWorstCagr)],
        ['Active max DD', fmtPct(scope.id === 'all' ? candidate.metrics.activeDrawdown : periodStat?.activeDrawdown)]
      ];
      document.getElementById('focus-metrics').innerHTML = fullMetrics.map(([label,value]) => `<div class="focus-metric"><span>${{esc(label)}}</span><b>${{esc(value)}}</b></div>`).join('');
      let thesis, rows;
      if (analysisMode === 'economics') {{
        const mechanisms = buckets.map(key => [bucketLabels[key] || key, ANALYSIS.bucketEconomics[key]]).filter(item => item[1]);
        thesis = mechanisms.length ? mechanisms.map(item => item[1]).join(' ') : (candidate.rawMeta?.economic || '该候选已有官方绩效证据，但经济机制仍应结合其底层变量与时期环境解释。');
        rows = mechanisms.map(([label,text]) => [label, text]);
        if (!rows.length) rows = [['解释口径', thesis]];
        rows.push(['组合含义', strict ? '该 pair 的增量表现超过最强单腿，且已进入 synergy claims，因此可声称直接协同。' : subset ? '该 subset 已完成官方 Top/Worst，但 additive 分类不自动等同于直接 synergy；需要结合 pair 与 LOO 证据。' : '单变量的经济直觉只解释为何可能有效，是否入选仍由 coverage、主动收益、Top/Worst 与 robust gate 决定。']);
      }} else {{
        const currentRead = periodStat ? `${{scope.label}} Top/Benchmark CAGR ${{fmtPct(periodStat.activeCagr)}}，Top/Worst CAGR ${{fmtPct(periodStat.topWorstCagr)}}，主动最大回撤 ${{fmtPct(periodStat.activeDrawdown)}}。` : `${{scope.label}}没有足够的有效净值观测。`;
        thesis = `全样本 official exact Top/Worst：主动 CAGR ${{fmtPct(candidate.metrics.activeCagr)}}，Top/Worst return ${{fmtNum(candidate.metrics.topWorstReturn)}}，ratio max DD ${{fmtPct(candidate.metrics.activeDrawdown)}}。${{currentRead}}`;
        const synergyRead = strict ? `已进入 synergy_claims.csv；synergy score ${{fmtNum(strict.synergy)}}。` : subset ? `Family subset 分类为 ${{subset.classification}}；这是组合证据，不自动写成直接 synergy。` : candidate.evidence.includes('leave-one-out') ? '这是移除 bucket 后的诊断结果，用于识别增量贡献或冗余。' : '这是单变量或历史验证证据；不据此推断 family 内部 synergy。';
        rows = [
          ['证据层级', candidate.evidence],
          ['Gate 与覆盖', `Coverage ${{fmtPct(candidate.metrics.coverage)}}；tracking error ${{fmtPct(candidate.metrics.trackingError)}}；turnover ${{fmtPct(candidate.metrics.turnover)}}。`],
          ['底层结构', `${{candidate.rawWeights.length}} 个 raw leg；nominal 权重会在月度可用变量集合内重新归一。`],
          ['协同边界', synergyRead]
        ];
      }}
      document.getElementById('focus-thesis').textContent = thesis;
      document.getElementById('focus-evidence').innerHTML = rows.map(([label,text],index) => `<div class="evidence-row"><span class="evidence-index">${{index+1}}</span><div><strong>${{esc(label)}}</strong><p>${{esc(text)}}</p></div></div>`).join('');
    }}
    function bindResearchCandidateButtons(selector, dataKey) {{
      document.querySelectorAll(selector).forEach(button => button.addEventListener('click', () => {{ candidateSelect.value = button.dataset[dataKey]; render(); window.scrollTo({{top:0,behavior:'smooth'}}); }}));
    }}
    function renderRotation(scope) {{
      const note = ANALYSIS.periodAnalysis[scope.id];
      document.getElementById('period-narrative').innerHTML = `<h3>${{esc(note.headline)}}</h3><p><b>历史领先结构：</b>${{esc(note.leaders)}}</p><p>${{esc(note.economics)}}</p>`;
      const leaders = DATA.candidates.map(candidate => ({{candidate, stat:periodMetric(candidate, scope)}})).filter(item => item.stat).sort((a,b) => b.stat.activeCagr - a.stat.activeCagr).slice(0, 8);
      const max = Math.max(...leaders.map(item => Math.abs(item.stat.activeCagr)), .001);
      document.getElementById('rotation-bars').innerHTML = leaders.map(item => {{
        const value = item.stat.activeCagr, width = Math.abs(value) / max * 100;
        return `<div class="bar-row ${{value < 0 ? 'negative' : ''}}"><button class="select-row bar-label" data-rotation-metric="${{esc(item.candidate.metric)}}" title="${{esc(item.candidate.label)}}">${{esc(item.candidate.label)}}</button><span class="bar-track"><span class="bar-fill" style="width:${{width.toFixed(1)}}%"></span></span><span class="bar-value">${{fmtPct(value)}}</span></div>`;
      }}).join('');
      bindResearchCandidateButtons('[data-rotation-metric]', 'rotationMetric');
    }}
    function renderLoo() {{
      const max = Math.max(...ANALYSIS.loo.map(item => Math.abs(item.robustContribution)), .001);
      document.getElementById('loo-bars').innerHTML = ANALYSIS.loo.map(item => {{
        const value = item.robustContribution, width = Math.abs(value) / max * 100;
        return `<div class="bar-row ${{value < 0 ? 'negative' : ''}}"><span class="bar-label" title="${{esc(item.bucket)}}">${{esc(bucketLabels[item.bucket] || item.bucket)}}</span><span class="bar-track"><span class="bar-fill" style="width:${{width.toFixed(1)}}%"></span></span><span class="bar-value">${{value >= 0 ? '+' : ''}}${{fmtNum(value)}}</span></div>`;
      }}).join('');
    }}
    function gateName(metric, label) {{
      return byMetric.has(metric) ? `<button class="select-row" data-gate-metric="${{esc(metric)}}">${{esc(label)}}</button>` : esc(label);
    }}
    function renderGateTable(kind) {{
      const mode = document.getElementById(`${{kind}}-mode`).value;
      const rows = ANALYSIS[kind].filter(row => mode === 'all' || (mode === 'pass' && row.passed) || (mode === 'fail' && !row.passed));
      const raw = kind === 'raw';
      const body = rows.map(row => {{
        const label = raw ? row.label : `${{row.raw}} · ${{row.transform}} lag${{row.lag}}`;
        const context = raw ? `${{row.family}} · ${{row.source}}${{row.note ? ` · ${{row.note}}` : ''}}` : `${{row.family}} · ${{row.source}} · ${{row.economic}}`;
        return `<tr><td>${{gateName(row.metric,label)}}</td><td>${{esc(context)}}</td><td><span class="badge ${{row.passed ? 'pass' : 'fail'}}">${{row.passed ? '通过' : '未通过'}}</span>${{row.reason ? `<div class="path">${{esc(row.reason)}}</div>` : ''}}</td><td class="num">${{fmtPct(row.coverage)}}</td><td class="num">${{fmtPct(row.activeCagr)}}</td><td class="num">${{fmtNum(row.topWorst)}}</td><td class="num">${{fmtNum(row.robust)}}</td></tr>`;
      }}).join('');
      document.getElementById(`${{kind}}-gate-table`).innerHTML = `<table><thead><tr><th>变量</th><th>Family / 来源 / 解释</th><th>结果</th><th class="num">Coverage</th><th class="num">主动 CAGR</th><th class="num">Top/Worst</th><th class="num">Robust</th></tr></thead><tbody>${{body}}</tbody></table>`;
      bindResearchCandidateButtons('[data-gate-metric]', 'gateMetric');
    }}
    function renderSynergyEvidence() {{
      const pairRows = ANALYSIS.synergy.map(row => `<tr><td>${{gateName(row.metric,row.label)}}</td><td>${{esc(row.buckets)}}</td><td class="num">${{fmtPct(row.activeCagr)}}</td><td class="num">${{fmtNum(row.topWorst)}}</td><td class="num">${{fmtNum(row.robust)}}</td><td class="num">${{fmtNum(row.synergy)}}</td></tr>`).join('');
      document.getElementById('synergy-table').innerHTML = `<table><thead><tr><th>Pair</th><th>Buckets</th><th class="num">主动 CAGR</th><th class="num">Top/Worst</th><th class="num">Robust</th><th class="num">Synergy</th></tr></thead><tbody>${{pairRows}}</tbody></table>`;
      const subsetRows = ANALYSIS.subsets.map(row => `<tr><td>${{gateName(row.metric,row.label)}}</td><td>${{esc(row.buckets)}}</td><td><span class="badge warn">${{esc(row.classification)}}</span></td><td class="num">${{fmtPct(row.activeCagr)}}</td><td class="num">${{fmtNum(row.topWorst)}}</td><td class="num">${{fmtNum(row.robust)}}</td></tr>`).join('');
      document.getElementById('subset-table').innerHTML = `<table><thead><tr><th>Subset</th><th>Buckets</th><th>分类</th><th class="num">主动 CAGR</th><th class="num">Top/Worst</th><th class="num">Robust</th></tr></thead><tbody>${{subsetRows}}</tbody></table>`;
      bindResearchCandidateButtons('[data-gate-metric]', 'gateMetric');
    }}
    function renderResearchBase() {{
      document.getElementById('core-headline').textContent = ANALYSIS.core.headline;
      document.getElementById('core-verdict').textContent = ANALYSIS.core.verdict;
      const summary = ANALYSIS.summary;
      const facts = [['Raw gate', `${{summary.rawPassed}} / ${{summary.rawTested}}`], ['Relative gate', `${{summary.relativePassed}} / ${{summary.relativeTested}}`], ['Official sides', `${{summary.officialSuccess}} / ${{summary.officialExpected}}`], ['Strict synergy', String(summary.synergyClaims)]];
      document.getElementById('coverage-summary').innerHTML = facts.map(([label,value]) => `<div class="coverage-item"><span>${{esc(label)}}</span><strong>${{esc(value)}}</strong></div>`).join('');
      document.getElementById('matrix-summary').textContent = `${{summary.candidateMetrics}} 个组合候选 · ${{summary.officialSuccess}} 个 Top/Worst side 成功`;
      document.getElementById('limits-grid').innerHTML = ANALYSIS.limits.map(item => `<div class="limit-item">${{esc(item)}}</div>`).join('');
      renderLoo(); renderGateTable('raw'); renderGateTable('relative'); renderSynergyEvidence();
    }}
    function render() {{
      const candidate = selected(), scope = period();
      document.getElementById('selected-name').textContent = candidate.label;
      const economic = candidate.rawMeta?.economic ? `<br>经济角色：${{esc(candidate.rawMeta.economic)}}` : '';
      document.getElementById('selected-meta').innerHTML = `${{esc(candidate.group)}}<br>${{esc(candidate.metric)}}<br>${{esc(scope.label)}}${{economic}}`;
      renderMetrics(candidate, scope); chart(candidate, scope); renderPeriods(candidate, scope); renderWeights(candidate); renderLeaderboard(scope); renderFocus(candidate, scope); renderRotation(scope);
    }}
    options();
    renderResearchBase();
    document.getElementById('stamp').innerHTML = `截至 ${{DATA.asOf}}<br>${{DATA.candidateCount}} 个可交互候选<br>${{esc(DATA.benchmark)}}`;
    document.getElementById('provenance').innerHTML = `Universe: ${{esc(DATA.universe)}} · ${{esc(DATA.evidence)}}<br>最新协同：${{esc(DATA.provenance.latestSynergy)}}<br>Relative raw：${{esc(DATA.provenance.relativeRaw)}}<br>Raw gate：${{esc(DATA.provenance.rawGate)}}<br>历史 QVM：${{esc(DATA.provenance.validatedQvm)}}`;
    document.querySelectorAll('[data-analysis-mode]').forEach(button => button.addEventListener('click', () => {{
      analysisMode = button.dataset.analysisMode;
      document.querySelectorAll('[data-analysis-mode]').forEach(item => item.classList.toggle('active', item === button));
      renderFocus(selected(), period());
    }}));
    document.querySelectorAll('[data-evidence-tab]').forEach(button => button.addEventListener('click', () => {{
      document.querySelectorAll('[data-evidence-tab]').forEach(item => item.classList.toggle('active', item === button));
      document.querySelectorAll('[data-evidence-panel]').forEach(panel => panel.classList.toggle('panel-hidden', panel.dataset.evidencePanel !== button.dataset.evidenceTab));
    }}));
    document.getElementById('raw-mode').addEventListener('change', () => renderGateTable('raw'));
    document.getElementById('relative-mode').addEventListener('change', () => renderGateTable('relative'));
    candidateSelect.addEventListener('change', render); periodSelect.addEventListener('change', render); render();
  }})();
  </script>
</div>
'''


if __name__ == "__main__":
    main()

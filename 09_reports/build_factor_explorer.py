"""Build one shared factor explorer from the four current TP report artifacts."""

from __future__ import annotations

import ast
import csv
import html
import json
import math
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pandas as pd


REPORT_DIR = Path(__file__).resolve().parent
OUTPUT = REPORT_DIR / "factor-explorer.html"
NASDAQ_EXTENSION_RUN = REPORT_DIR.parent / "07_backtest_code" / "runs" / "ad_hoc" / "nasdaq_tech_factor_extension_20260710"
EU_SMALL_EXTENSION_RUN = REPORT_DIR.parent / "07_backtest_code" / "runs" / "ad_hoc" / "eu_small_factor_extension_20260711"
STOXX600_EXTENSION_RUN = REPORT_DIR.parent / "07_backtest_code" / "runs" / "ad_hoc" / "stoxx600_factor_extension_20260711"
SP500_EXTENSION_RUN = REPORT_DIR.parent / "07_backtest_code" / "runs" / "ad_hoc" / "sp500_factor_extension_20260711"
SOURCES = {
    "eu-small": REPORT_DIR / "eu-small-factor-explorer.html",
    "sp500": REPORT_DIR / "sp500-factor-explorer.html",
    "stoxx600": REPORT_DIR / "stoxx600-factor-explorer.html",
    "nasdaq": REPORT_DIR / "nasdaq-factor-explorer.html",
}

PERIOD_SOURCES = {
    "ecb_2007": {"label": "ECB 2007 金融稳定评估", "url": "https://www.ecb.europa.eu/press/pr/date/2007/html/pr070615.en.html"},
    "fed_balance": {"label": "Fed 资产负债表政策时间线", "url": "https://www.federalreserve.gov/monetarypolicy/timeline-balance-sheet-policies.htm"},
    "fed_rates": {"label": "Fed 历次公开市场利率操作", "url": "https://www.federalreserve.gov/monetarypolicy/openmarket.htm"},
    "ecb_omt": {"label": "ECB 欧债危机与 OMT", "url": "https://www.ecb.europa.eu/press/key/date/2017/html/ecb.sp170912.en.html"},
    "ecb_app": {"label": "ECB 资产购买计划 APP", "url": "https://www.ecb.europa.eu/ecb-and-you/explainers/tell-me-more/html/asset-purchase.en.html"},
    "who_covid": {"label": "WHO 2020-03-11 疫情节点", "url": "https://www.who.int/news-room/speeches/item/who-director-general-s-opening-remarks-at-the-media-briefing-on-covid-19---11-march-2020"},
    "ecb_pepp": {"label": "ECB 疫情紧急购买计划 PEPP", "url": "https://www.ecb.europa.eu/mopo/implement/pepp/html/index.en.html"},
    "fed_postcovid": {"label": "Fed 疫情后高通胀政策回顾", "url": "https://www.federalreserve.gov/econres/notes/feds-notes/the-federal-reserves-responses-to-the-post-covid-period-of-high-inflation-20240214.html"},
    "imf_2022": {"label": "IMF 2022 通胀、能源与收紧", "url": "https://www.imf.org/en/publications/weo/issues/2022/07/26/world-economic-outlook-update-july-2022"},
    "ecb_2024": {"label": "ECB 2024-06-06 降息决定", "url": "https://www.ecb.europa.eu/press/pr/date/2024/html/ecb.mp240606~2148ecdb3c.en.html"},
    "imf_2024": {"label": "IMF 2024 软着陆框架", "url": "https://www.imf.org/en/blogs/articles/2024/01/30/global-economy-approaches-soft-landing-but-risks-remain"},
    "nasdaq_2023": {"label": "Nasdaq 2023 AI 与巨头集中", "url": "https://www.nasdaq.com/articles/2023-impressive-or-an-outlier"},
    "nasdaq_ai": {"label": "Nasdaq-100 AI 资本开支与扩散", "url": "https://www.nasdaq.com/articles/global-indexes/ai-capex-nasdaq-100"},
    "sp_2025": {"label": "S&P DJI 2024 市场集中度回顾", "url": "https://www.spglobal.com/spdji/en/documents/commentary/market-attributes-us-equities-202501.pdf"},
}

PERIOD_CONTEXTS = {
    ("eu-small", "all"): {"definition": "从欧洲小盘样本的第一个可用月延伸到最新官方回测月。它是跨周期统计基准，不代表单一宏观制度，用于判断信号能否穿越多个融资与政策环境。", "sources": []},
    ("eu-small", "2005-2007"): {"definition": "从首个可用月到2007年末，定义为全球金融危机前的信贷扩张窗口。ECB当时记录了低波动、低信用利差、高资产价格与杠杆累积并存的环境。", "sources": ["ecb_2007"]},
    ("eu-small", "2008-2012"): {"definition": "从全球金融危机爆发延伸到欧债危机与2012年 OMT 政策转折。银行融资、主权利差和再融资可得性成为欧洲小盘生存能力的核心约束。", "sources": ["fed_balance", "ecb_omt"]},
    ("eu-small", "2013-2016"): {"definition": "从欧债危机缓和到 ECB 大规模资产购买计划全面运行，定义为低通胀、低利率与信用修复窗口；宽松估值环境仍需现金流和增长兑现确认。", "sources": ["ecb_app"]},
    ("eu-small", "2017-2019"): {"definition": "从欧洲复苏后段到疫情前，定义为后周期低利率扩张窗口。ECB 购债从减量、结束到2019年重启，融资仍宽松，但增长和利润率开始分化。", "sources": ["ecb_app"]},
    ("eu-small", "2020-2021"): {"definition": "从 WHO 将 COVID-19 定性为全球大流行开始，覆盖封锁、盈利路径重写、政策救助和经济重启；ECB 的 PEPP 用于稳定融资条件与政策传导。", "sources": ["who_covid", "ecb_pepp"]},
    ("eu-small", "2022-2023"): {"definition": "覆盖俄乌战争外溢、能源与食品价格冲击、数十年高位通胀及快速货币收紧。对融资更敏感的小盘公司因此面临更高资本成本和利润率压力。", "sources": ["imf_2022", "fed_postcovid"]},
    ("eu-small", "2024-2026"): {"definition": "从2024年欧洲通胀回落与 ECB 首次降息延伸到本报告截止日，定义为政策正常化观察窗口；它仍在发展中，不应视为已经完成的稳定周期。", "sources": ["ecb_2024", "imf_2024"]},
    ("sp500", "all"): {"definition": "从2009年市场修复期的首个可用月到最新官方回测月。全样本用于衡量因子跨越 QE、疫情、通胀和 AI 集中行情后的长期稳健性。", "sources": []},
    ("sp500", "2009-2012"): {"definition": "定义为金融危机后的资产负债表修复与 QE 扩张阶段。Fed 通过长期国债和 MBS 购买压低长期利率、修复信贷并支持经济复苏。", "sources": ["fed_balance"]},
    ("sp500", "2013-2016"): {"definition": "从2013年 taper 信号、2014年结束净购买，到2015年首次加息，定义为由非常规宽松逐步转向正常化的过渡窗口。", "sources": ["fed_balance", "fed_rates"]},
    ("sp500", "2017-2019"): {"definition": "覆盖2017-2018连续加息和2019年预防式降息，定义为成熟扩张末段；估值较高、增长放缓和政策方向反复提高了盈利质量的重要性。", "sources": ["fed_rates"]},
    ("sp500", "2020-2021"): {"definition": "覆盖疫情冲击、零利率、大规模资产购买、财政支持与经济重启。流动性宽松和盈利路径快速重估同时存在。", "sources": ["who_covid", "fed_postcovid"]},
    ("sp500", "2022-2023"): {"definition": "从疫情后高通胀与激进收紧开始，延伸到2023年 AI 主题和少数大型公司主导指数回报的起点；现金流折现与指数集中度同时影响因子表现。", "sources": ["fed_postcovid", "nasdaq_2023"]},
    ("sp500", "2024-2026"): {"definition": "从通胀持续回落、市场交易软着陆开始，延伸到报告截止日。AI 盈利预期继续扩散，但大型公司对指数回报的贡献仍高，因此该窗口同时包含扩散与集中。", "sources": ["imf_2024", "sp_2025"]},
    ("stoxx600", "all"): {"definition": "从 STOXX 600 官方候选序列的首个可用月到最新回测月。它是跨越欧债危机、负利率、疫情和能源冲击的长期比较基准。", "sources": []},
    ("stoxx600", "pre"): {"definition": "覆盖2010年欧债危机启动、2012年 OMT 稳定政策传导，以及2015年后 APP 宽松，直到疫情前。该窗口不是单一状态，而是欧洲低通胀与金融碎片化风险并存的前2020基准。", "sources": ["ecb_omt", "ecb_app"]},
    ("stoxx600", "covid"): {"definition": "覆盖2020-2021疫情封锁、政策托底和重启交易。WHO 的疫情节点和 ECB 的 PEPP 构成分段起点与主要政策背景。", "sources": ["who_covid", "ecb_pepp"]},
    ("stoxx600", "inflation"): {"definition": "覆盖2022-2023欧洲能源冲击、广泛通胀与 ECB 从2022年7月开始的快速加息周期，融资成本和盈利韧性重新成为核心定价变量。", "sources": ["imf_2022", "ecb_2024"]},
    ("stoxx600", "recent"): {"definition": "从2024年 ECB 开始降低限制程度延伸到报告截止日，定义为通胀回落、政策正常化与市场领导集中度变化的观察窗口；尚不是完成的长期制度。", "sources": ["ecb_2024", "imf_2024"]},
    ("nasdaq", "all"): {"definition": "从2014年首个可用月到最新官方回测月，覆盖低利率成长、疫情流动性、利率冲击和 AI 集中行情，用于检验成长市场中的跨周期稳健性。", "sources": []},
    ("nasdaq", "2014-2016"): {"definition": "从 Fed 结束 QE 净购买到2015年首次加息后的早期正常化，定义为低利率仍占主导、但政策转折已经出现的成长扩张窗口。", "sources": ["fed_balance", "fed_rates"]},
    ("nasdaq", "2017-2019"): {"definition": "覆盖 Fed 连续加息、资产负债表正常化和2019年降息，定义为成熟扩张后段；高估值成长需要资本效率和资产负债表纪律支撑。", "sources": ["fed_rates"]},
    ("nasdaq", "2020-2021"): {"definition": "覆盖疫情冲击、零利率与资产购买，以及数字化需求和经济重启带来的成长再定价。该阶段流动性与盈利增长同时放大风格差异。", "sources": ["who_covid", "fed_postcovid"]},
    ("nasdaq", "2022"): {"definition": "单独切出2022年，作为疫情后高通胀、快速加息和长久期资产估值压缩的 rate-shock 窗口，避免其影响被后续 AI 反弹平均掉。", "sources": ["fed_postcovid", "imf_2022"]},
    ("nasdaq", "2023-2024"): {"definition": "从生成式 AI 主题成为主要市场驱动力开始，覆盖 Nasdaq-100 由少数 mega-cap 与科技公司主导的集中行情；这是指数集中度诊断窗口。", "sources": ["nasdaq_2023"]},
    ("nasdaq", "2025-2026H1"): {"definition": "从2025年开始观察 AI 资本开支由基础设施提供者向软件、平台与采用者扩散，并延伸到报告截止日；该分段是研究观察窗，不是已经确认的官方周期。", "sources": ["nasdaq_ai", "sp_2025"]},
}


class IframeSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.srcdoc: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "iframe" and self.srcdoc is None:
            self.srcdoc = dict(attrs).get("srcdoc")


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[dict[str, Any]] = []
        self.table: dict[str, Any] | None = None
        self.row: list[tuple[str, str]] | None = None
        self.cell_kind: str | None = None
        self.cell_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.table = {"header": [], "rows": []}
        elif self.table is not None and tag == "tr":
            self.row = []
        elif self.row is not None and tag in {"th", "td"}:
            self.cell_kind = tag
            self.cell_parts = []
        elif self.cell_kind and tag == "br":
            self.cell_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self.cell_kind:
            self.cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self.cell_kind and self.row is not None:
            text = " ".join("".join(self.cell_parts).split())
            self.row.append((self.cell_kind, text))
            self.cell_kind = None
            self.cell_parts = []
        elif tag == "tr" and self.row is not None and self.table is not None:
            values = [value for _, value in self.row]
            if any(kind == "th" for kind, _ in self.row) and not self.table["header"]:
                self.table["header"] = values
            elif values:
                self.table["rows"].append(values)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def clean_markup(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def inner_document(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    parser = IframeSourceParser()
    parser.feed(raw)
    return parser.srcdoc or raw


def json_script(document: str, script_id: str) -> Any:
    match = re.search(
        rf"<script[^>]*id=[\"']{re.escape(script_id)}[\"'][^>]*>(.*?)</script>",
        document,
        re.DOTALL,
    )
    if not match:
        raise RuntimeError(f"Missing JSON script #{script_id}")
    return json.loads(match.group(1))


def js_array(document: str, name: str) -> list[Any]:
    marker = re.search(rf"\bconst\s+{re.escape(name)}\s*=", document)
    if not marker:
        raise RuntimeError(f"Missing JavaScript array: {name}")
    start = document.find("[", marker.end())
    if start < 0:
        raise RuntimeError(f"Missing opening bracket for {name}")
    depth = 0
    quote: str | None = None
    escaped = False
    end = -1
    for index in range(start, len(document)):
        char = document[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end < 0:
        raise RuntimeError(f"Unclosed JavaScript array: {name}")
    literal = document[start:end]
    literal = re.sub(
        r"([{,]\s*)([A-Za-z_$][A-Za-z0-9_$]*)(\s*:)",
        r"\1'\2'\3",
        literal,
    )
    literal = re.sub(r"\bnull\b", "None", literal)
    literal = re.sub(r"\btrue\b", "True", literal)
    literal = re.sub(r"\bfalse\b", "False", literal)
    value = ast.literal_eval(literal)
    if not isinstance(value, list):
        raise RuntimeError(f"{name} is not an array")
    return value


def parsed_tables(document: str) -> list[dict[str, Any]]:
    parser = TableParser()
    parser.feed(document)
    return parser.tables


def first_match(document: str, pattern: str, fallback: str = "") -> str:
    match = re.search(pattern, document, re.DOTALL)
    return clean_markup(match.group(1)) if match else fallback


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def pct(value: Any) -> str:
    number = finite(value)
    return "-" if number is None else f"{number * 100:.1f}%"


def num(value: Any, digits: int = 2) -> str:
    number = finite(value)
    return "-" if number is None else f"{number:.{digits}f}"


def ratio(value: Any) -> str:
    number = finite(value)
    return "-" if number is None else f"{number:.2f}x"


def ratio_terminal(value: Any) -> str:
    number = finite(value)
    return "-" if number is None else f"{number + 1:.2f}x"


def parse_display_number(value: str) -> float | None:
    text = value.strip().replace(",", "")
    scale = 0.01 if text.endswith("%") else 1.0
    text = text.rstrip("%x")
    number = finite(text)
    return None if number is None else number * scale


def round_series(series: list[Any]) -> list[list[Any]]:
    result: list[list[Any]] = []
    for point in series:
        if isinstance(point, dict):
            row = [point.get("d"), point.get("t"), point.get("w"), point.get("b")]
        else:
            row = list(point[:4])
        if len(row) != 4 or not row[0]:
            continue
        result.append(
            [
                str(row[0]),
                round(float(row[1]), 3),
                round(float(row[2]), 3),
                round(float(row[3]), 3),
            ]
        )
    return result


def resolve_workspace_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPORT_DIR.parent / path


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def standard_subset_data(run_value: str) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    run = resolve_workspace_path(run_value)
    catalog = [
        {
            "id": row["metric"],
            "label": row["label"],
            "kind": row.get("candidate_type") or "family_subset",
            "keys": [key for key in row["buckets"].split("|") if key],
        }
        for row in csv_rows(run / "family_subset_results.csv")
    ]
    bucket_variables: dict[str, list[str]] = {}
    for row in csv_rows(run / "selected_legs.csv"):
        bucket_variables.setdefault(row["bucket"], []).append(row["label"])
    return catalog, bucket_variables


def merged_subset_data(base_run: str, extension_run: Path) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    base_catalog, base_variables = standard_subset_data(base_run)
    extension_catalog, extension_variables = standard_subset_data(str(extension_run))
    catalog = {row["id"]: row for row in base_catalog}
    catalog.update({row["id"]: row for row in extension_catalog})
    for bucket, labels in extension_variables.items():
        base_variables[bucket] = list(dict.fromkeys([*base_variables.get(bucket, []), *labels]))
    return list(catalog.values()), base_variables


def nasdaq_subset_data(run: Path) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    catalog = [
        {
            "id": row["metric"],
            "label": row["label"],
            "kind": "family_subset",
            "keys": [key for key in row["themes"].split(",") if key],
        }
        for row in csv_rows(run / "family_subset_results.csv")
    ]
    labels: dict[str, str] = {}
    for row in csv_rows(run / "single_variable_official_summary.csv"):
        if row.get("raw_column") and row.get("transform"):
            lag = row["lag_observations"].removesuffix(".0")
            label = f'{row["raw_column"]} {row["transform"]} lag{lag}'
        else:
            label = row["label"]
        labels.setdefault(row["metric"], label)
    definitions = {
        row["column"]: row
        for row in json.loads((run / "synergy_metric_definitions.json").read_text(encoding="utf-8"))
    }
    maps = json.loads((run / "synergy_metric_maps.json").read_text(encoding="utf-8"))
    bucket_variables = {
        theme: [labels.get(metric, metric) for metric in definitions[theme_metric]["components"]]
        for theme, theme_metric in maps["theme_scores"].items()
    }
    return catalog, bucket_variables


def nav_series(path_value: str) -> pd.Series:
    path = Path(path_value)
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    date_column = "Date" if "Date" in frame.columns else "index" if "index" in frame.columns else frame.columns[0]
    value_columns = [column for column in frame.columns if column != date_column]
    if not value_columns:
        return pd.Series(dtype=float)
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    values = pd.to_numeric(frame[value_columns[0]], errors="coerce")
    return pd.Series(values.to_numpy(), index=dates).dropna().sort_index()


def monthly_nav(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the true first/last dates so browser CAGR matches official summaries."""
    monthly = frame.groupby(frame.index.to_period("M"), sort=True).tail(1)
    return pd.concat([frame.iloc[[0]], monthly]).sort_index().loc[lambda value: ~value.index.duplicated(keep="first")]


def nasdaq_tech_candidates(run: Path) -> list[dict[str, Any]]:
    gate = csv_rows(run / "tech_validation_gate.csv")
    passed = {row["metric"]: row for row in gate if str(row.get("passed", "")).lower() == "true"}
    if not passed:
        return []
    definitions = {row["metric"]: row for row in csv_rows(run / "tech_candidate_definitions.csv")}
    official = csv_rows(run / "official_run_results.csv")
    by_run = {(row["metric"], row["side"]): row for row in official if row.get("status") == "success"}
    explanations = {
        "nasdaq_tech_growth_confirmation": ("增长必须由盈利预期上修确认。", "收入与毛利增长单独使用会混入昂贵但未兑现的成长；加入 EPS Revision Ratio 后，信号更接近正在被分析师验证的增长。"),
        "nasdaq_tech_capital_efficient_growth_revision": ("寻找既增长、又提高资产生产率、且盈利预期上修的公司。", "Asset TO exFIN 把增长与资本占用联系起来，避免只奖励依赖持续融资或重资产扩张的收入增长。"),
        "nasdaq_tech_asset_light_growth_revision": ("资产轻型增长需要利润率与盈利上修共同确认。", "低物理资本开支、经营利润率和研发信息共同描述无形资产驱动的增长；EPS 上修用于过滤尚未兑现的故事。"),
        "nasdaq_tech_downside_aware_growth_revision": ("在增长与盈利上修中加入公司特有下行风险约束。", "残差下行波动剔除 Nasdaq 市场 beta 后，惩罚基本面虽强但个股下行风险过高的公司。"),
    }
    candidates = []
    for metric, gate_row in passed.items():
        top = by_run.get((metric, "Top"))
        worst = by_run.get((metric, "Worst"))
        definition = definitions.get(metric)
        if not top or not worst or not definition:
            continue
        aligned = pd.concat(
            [nav_series(top["perf_ptf"]).rename("top"), nav_series(top["perf_bench"]).rename("bench"), nav_series(worst["perf_ptf"]).rename("worst")],
            axis=1,
        ).dropna()
        aligned = monthly_nav(aligned)
        series = [
            [date.strftime("%Y-%m-%d"), round(row.top, 5), round(row.worst, 5), round(row.bench, 5)]
            for date, row in aligned.iterrows()
        ]
        inputs = [item for item in definition["inputs"].split("|") if item]
        thesis, economics = explanations.get(metric, (definition["note"], definition["note"]))
        candidates.append(
            {
                "id": metric,
                "label": definition["label"],
                "group": definition["theme"],
                "kind": "tech_engineered",
                "thesis": thesis,
                "economics": economics,
                "metrics": {
                    "robust": finite(gate_row.get("robust_score")),
                    "coverage": finite(gate_row.get("coverage")),
                    "turnover": None,
                },
                "series": series,
                "weights": [
                    {"label": label, "group": definition["theme"], "value": 1 / len(inputs)}
                    for label in inputs
                ],
                "evidenceRows": [
                    ["Top / Benchmark CAGR", pct(gate_row.get("top_ratio_cagr"))],
                    ["Top / Worst 累计比率", num(gate_row.get("top_worst_ratio_return"), 2)],
                    ["Coverage", pct(gate_row.get("coverage"))],
                ],
            }
        )
    return candidates


def official_extension_candidates(run: Path) -> list[dict[str, Any]]:
    gate = csv_rows(run / "extension_validation_gate.csv")
    passed = {row["metric"]: row for row in gate if str(row.get("pass_gate", "")).lower() == "true"}
    official = csv_rows(run / "gate_runs" / "official_run_results.csv")
    by_run = {(row["metric"], row["side"]): row for row in official if row.get("status") == "success"}
    explanations = {
        "capital_efficiency": ("增长需要资本生产率和现金转化共同确认。", "欧洲行业结构差异很大；资本效率用于区分可自我融资的增长与依赖持续资本投入的扩张。"),
        "deleveraging": ("在国家与行业同组内寻找负债改善。", "国家中性化降低欧洲融资制度差异的干扰，净负债改善则直接约束再融资脆弱性。"),
        "dividend_sustainability": ("股息增长必须由盈利上修和派息纪律确认。", "单看高股息容易落入价值陷阱；盈利修正与合理派息率用于确认股息的可持续性。"),
        "earnings_yield": ("估值改善必须与基本面边际改善同步。", "国家与行业同组比较减少市场结构差异，避免把长期低估值行业误判为公司层面的价值改善。"),
        "pmom": ("价格动量在国家与行业同组内作相对确认。", "欧洲市场分散在多个国家，同组相对趋势更接近公司特有信息，而不是国家指数方向。"),
        "quality": ("奖励利润率、资本效率和资产负债表的边际改善。", "改善型质量比静态高质量更能捕捉经营拐点，并减少昂贵质量标签的估值偏差。"),
        "quality_level": ("静态质量必须在本地国家同业中仍然突出。", "欧洲小盘的 ROE 会受到国家融资结构影响；国家优先、行业回退的排序减少把国家差异误当公司质量。"),
        "residual_momentum": ("剔除 STOXX 市场共同波动后再观察趋势。", "残差动量更接近公司特有信息扩散，Revision 确认可过滤纯 beta 驱动的价格上涨。"),
        "residual_risk": ("在基本面改善中约束公司特有下行风险。", "残差下行风险用于避免把高 beta 或尾部脆弱性误当作更强的预期回报。"),
        "revision": ("在国家与行业同组内比较盈利预期修正。", "欧洲国家会计、行业权重与宏观暴露不同，同组排序更聚焦公司层面的盈利信息。"),
        "accrual_quality": ("要求利润改善获得现金流与低应计确认。", "低 operating accruals 用于区分可持续现金盈利与依赖应计项目的账面利润。"),
        "growth": ("增长信号需要控制 mega-cap 与行业规模暴露。", "sector × size 排序用于判断盈利增长是否来自公司信息，而不是指数集中度和巨头领导。"),
        "value_improvement": ("估值改善在行业和规模同组内比较。", "规模中性化减少 mega-cap 长久期估值对横截面排序的干扰。"),
        "value_level": ("P/FCF 在本地国家同业中比较。", "现金流估值适合融资约束更强的小盘公司；国家调整用于减少税制、利率和市场结构差异。"),
        "liquidity_quality": ("流动性代理只能用于过滤，不能代替真实交易成本。", "零收益频率衡量价格停滞而不是成交价差；只有获得 official 主动收益时才允许进入主题。"),
        "shareholder_return": ("现金回报必须由 payout 与现金转化支持。", "回购或股息字段只有在覆盖率和现金质量同时通过时才可进入正式主题。"),
    }
    input_labels = {
        "asset_turnover_score": "Asset TO exFIN",
        "country_asset_turnover_score": "Asset TO exFIN (country-first / industry fallback)",
        "fcf_sales_raw": "FCF / Sales",
        "country_deleveraging_delta3_raw": "NetDebt / EBITDA 3M improvement (country-first / industry fallback)",
        "low_payout_score": "DVD Payout FY0 (lower is better)",
        "country_earnings_yield_delta1_raw": "Earns Yield FY1 1M improvement (country-first / industry fallback)",
        "country_eps_revision_raw": "EPS Revision Ratio (country-first / industry fallback)",
        "country_pmom_raw": "PMOM 12M1M (country-first / industry fallback)",
        "country_roe_raw": "ROE avg FY0 (country-first / industry fallback)",
        "country_pfcf_raw": "PFCF LTM (country-first / industry fallback)",
        "country_oper_margin_delta3_raw": "Oper Margin 3M improvement (country-first / industry fallback)",
        "country_growth_confirmation_score": "Sales / Gross Income Growth + EPS Revision (country-first / industry fallback)",
        "stoxx_residual_momentum_raw": "STOXX-residual Momentum 12-1",
        "stoxx_residual_momentum_risk_adjusted_raw": "STOXX-residual Momentum / Residual Volatility",
        "stoxx_residual_downside_volatility_raw": "STOXX-residual Downside Volatility (lower is better)",
        "size_eps_revision_raw": "EPS Revision Ratio (sector × size rank)",
        "size_pmom_raw": "PMOM 12M1M (sector × size rank)",
        "size_oper_margin_delta3_raw": "Oper Margin 3M improvement (sector × size rank)",
        "size_deleveraging_delta3_raw": "NetDebt / EBITDA 3M improvement (sector × size rank)",
        "size_earnings_yield_delta1_raw": "Earns Yield FY1 1M improvement (sector × size rank)",
        "size_growth_confirmation_score": "Sales / Gross Income Growth + EPS Revision (sector × size rank)",
        "size_asset_turnover_score": "Asset TO exFIN (sector × size rank)",
        "capex_intensity_raw": "Capex / Total Assets (lower is better)",
        "operating_accruals_raw": "(Net Income - CFO) / Total Assets (lower is better)",
        "working_capital_absorption_raw": "Change Net Working Capital / Total Assets (lower is better)",
        "buyback_intensity_raw": "Repurchase Stock / Sales",
        "sp500_residual_momentum_raw": "SP500-residual Momentum 12-1",
        "sp500_residual_momentum_risk_adjusted_raw": "SP500-residual Momentum / Residual Volatility",
        "sp500_residual_volatility_raw": "SP500-residual Volatility (lower is better)",
        "sp500_residual_downside_volatility_raw": "SP500-residual Downside Volatility (lower is better)",
        "eu_small_residual_momentum_raw": "MSCI EUR SMALL-residual Momentum 12-1",
        "eu_small_residual_momentum_risk_adjusted_raw": "MSCI EUR SMALL-residual Momentum / Residual Volatility",
        "eu_small_residual_volatility_raw": "MSCI EUR SMALL-residual Volatility (lower is better)",
        "eu_small_residual_downside_volatility_raw": "MSCI EUR SMALL-residual Downside Volatility (lower is better)",
        "zero_return_frequency_raw": "Zero-return Frequency (lower is better)",
        "zero_return_liquidity_improvement_raw": "Zero-return Frequency Improvement",
    }
    candidates = []
    for metric, row in passed.items():
        top = by_run.get((metric, "Top"))
        worst = by_run.get((metric, "Worst"))
        if not top or not worst:
            continue
        aligned = pd.concat(
            [nav_series(top["perf_ptf"]).rename("top"), nav_series(top["perf_bench"]).rename("bench"), nav_series(worst["perf_ptf"]).rename("worst")],
            axis=1,
        ).dropna()
        aligned = monthly_nav(aligned)
        inputs = [input_labels.get(item, item) for item in row["inputs"].split("|") if item]
        thesis, economics = explanations.get(row["theme"], (row["note"], row["note"] + "。"))
        candidates.append(
            {
                "id": metric,
                "label": row["label"],
                "group": row["theme"],
                "kind": "extension_candidate",
                "thesis": thesis,
                "economics": economics,
                "metrics": {
                    "robust": finite(row.get("robust_score")),
                    "coverage": finite(row.get("coverage")),
                    "turnover": None,
                    "officialActive": finite(row.get("ratio_cagr")),
                    "officialRatio": 1 + finite(row.get("top_worst_ratio_return")) if finite(row.get("top_worst_ratio_return")) is not None else None,
                },
                "series": [[date.strftime("%Y-%m-%d"), round(point.top, 5), round(point.worst, 5), round(point.bench, 5)] for date, point in aligned.iterrows()],
                "weights": [{"label": label, "group": row["theme"], "value": 1 / len(inputs)} for label in inputs],
                "subsetKeys": [],
                "evidenceRows": [
                    ["Top / Benchmark CAGR", pct(row.get("ratio_cagr"))],
                    ["Top / Worst 终值", ratio_terminal(row.get("top_worst_ratio_return"))],
                    ["Coverage", pct(row.get("coverage"))],
                ],
            }
        )
    return sorted(candidates, key=lambda item: item["metrics"]["robust"] or -math.inf, reverse=True)


def extension_theme_candidates(run: Path, include_loo: bool = False) -> list[dict[str, Any]]:
    subsets = pd.read_csv(run / "family_subset_results.csv")
    family = subsets[subsets["candidate_type"].eq("family_subset")].sort_values("robust_score", ascending=False)
    if include_loo:
        candidate_map = pd.read_csv(run / "theme_candidate_map.csv").set_index("metric").to_dict(orient="index")
        summary = pd.read_csv(run / "theme_performance_summary.csv")
        loo_rows = []
        for _, performance in summary[summary["side"].eq("Top") & summary["status"].eq("success")].iterrows():
            meta = candidate_map.get(str(performance["metric"]), {})
            if meta.get("candidate_type") != "leave_one_out":
                continue
            loo_rows.append({**performance.to_dict(), **meta, "classification": "leave_one_out"})
        loo = pd.DataFrame(loo_rows).sort_values("robust_score", ascending=False)
        selected = pd.concat([loo.head(2), family.head(3)], ignore_index=True).drop_duplicates("metric").head(5)
    else:
        selected = pd.concat([family.head(3), family[family["classification"].eq("synergistic")].head(2)]).drop_duplicates("metric").head(5)
    official = csv_rows(run / "theme_runs" / "official_run_results.csv")
    by_run = {(row["metric"], row["side"]): row for row in official if row.get("status") == "success"}
    theme_labels = {
        "revision": "EPS Revision Ratio + size-aware PMOM",
        "growth": "Sales / Gross Income Growth + EPS Revision",
        "quality_improvement": "Oper Margin improvement + quality repair",
        "deleveraging": "NetDebt / EBITDA improvement",
        "value_improvement": "Earns Yield FY1 improvement",
        "accrual_quality": "(Net Income - CFO) / Assets + cash-backed margin",
        "capital_efficiency": "Asset TO + capital-efficient growth",
        "residual_momentum": "SP500-residual Momentum + Revision",
        "residual_risk": "Residual downside risk + downside-aware revision",
        "quality_level": "Country-aware ROE",
        "value_level": "Country-aware P/FCF",
        "pmom": "PMOM + country-aware PMOM",
    }
    eu_small = run.name.startswith("eu_small")
    if eu_small:
        theme_labels.update(
            {
                "revision": "EPS Revision + country-aware EPS Revision",
                "quality_improvement": "Oper Margin improvement + country-aware quality repair",
                "deleveraging": "NetDebt / EBITDA improvement + country-aware deleveraging",
                "value_improvement": "Value improvement + country-aware earnings-yield improvement",
                "residual_momentum": "MSCI EUR SMALL-residual Momentum + Revision",
            }
        )
    candidates = []
    for _, row in selected.iterrows():
        metric = str(row["metric"])
        top, worst = by_run.get((metric, "Top")), by_run.get((metric, "Worst"))
        if not top or not worst:
            continue
        aligned = pd.concat(
            [nav_series(top["perf_ptf"]).rename("top"), nav_series(top["perf_bench"]).rename("bench"), nav_series(worst["perf_ptf"]).rename("worst")],
            axis=1,
        ).dropna()
        aligned = monthly_nav(aligned)
        themes = [item for item in str(row["buckets"]).split("|") if item]
        candidates.append(
            {
                "id": f"{run.name}:{metric}",
                "label": f'{"扩展推荐" if row["candidate_type"] == "leave_one_out" else "扩展模型"}：{row["label"]}',
                "group": "recommended_extension",
                "kind": str(row["candidate_type"]),
                "thesis": "只保留通过主题 Gate、并在组合矩阵中保持较高 Robust 的精简 sleeve。",
                "economics": "该组合用于升级欧洲小盘核心：质量改善、静态 ROE、现金流估值和去杠杆共同约束融资脆弱性；LOO 用于删除与 PMOM、残差确认重复的独立主题。" if eu_small else "该组合用于升级 SP500 核心信号，而不是把所有新增主题等权混合；质量改善和去杠杆负责经营与融资确认，应计质量只在有独立增益时加入。",
                "metrics": {
                    "robust": finite(row["robust_score"]),
                    "coverage": finite(row["coverage"]),
                    "turnover": finite(row.get("avg_turnover")),
                    "officialActive": finite(row["ratio_cagr"]),
                    "officialRatio": 1 + finite(row["top_worst_ratio_return"]),
                },
                "series": [[date.strftime("%Y-%m-%d"), round(point.top, 5), round(point.worst, 5), round(point.bench, 5)] for date, point in aligned.iterrows()],
                "weights": [{"label": theme_labels.get(theme, theme), "group": theme, "value": 1 / len(themes)} for theme in themes],
                "subsetKeys": themes,
                "evidenceRows": [
                    ["Top / Benchmark CAGR", pct(row["ratio_cagr"])],
                    ["Top / Worst 终值", ratio_terminal(row["top_worst_ratio_return"])],
                    ["Robust score", num(row["robust_score"])],
                    ["分类", row["classification"]],
                ],
            }
        )
    return candidates


def stoxx600_recommended_model(run: Path) -> dict[str, Any]:
    metric = "stoxx600_syn_loo_without_revision"
    official = csv_rows(run / "theme_runs" / "official_run_results.csv")
    by_side = {row["side"]: row for row in official if row.get("metric") == metric and row.get("status") == "success"}
    summary = pd.read_csv(run / "theme_performance_summary.csv")
    performance = summary[(summary["metric"].eq(metric)) & (summary["side"].eq("Top")) & (summary["status"].eq("success"))].iloc[-1]
    aligned = pd.concat(
        [nav_series(by_side["Top"]["perf_ptf"]).rename("top"), nav_series(by_side["Top"]["perf_bench"]).rename("bench"), nav_series(by_side["Worst"]["perf_ptf"]).rename("worst")],
        axis=1,
    ).dropna()
    aligned = monthly_nav(aligned)
    themes = [
        ("PMOM 12M1M + country-aware PMOM", "pmom"),
        ("Oper Margin / ROE improvement + country-aware quality repair", "quality_improvement"),
        ("Earns Yield improvement + country-aware value confirmation", "earnings_yield_improvement"),
        ("NetDebt / EBITDA improvement + country-aware deleveraging", "deleveraging"),
        ("Asset TO exFIN + FCF / Sales + capital-efficient growth", "capital_efficiency"),
        ("DPS 1Y Growth FY1 + EPS Revision Ratio + DVD Payout FY0", "dividend_sustainability"),
        ("STOXX-residual Momentum 12-1 + risk-adjusted residual momentum", "residual_momentum"),
        ("STOXX-residual Downside Volatility + downside-aware revision", "residual_risk"),
    ]
    return {
        "id": metric,
        "label": "扩展推荐模型：full model without revision",
        "group": "recommended_extension",
        "kind": "leave_one_out",
        "thesis": "保留八个互补主题，并移除在当前结构中与多种确认信号重复的独立 revision 主题。",
        "economics": "EPS revision 单变量仍有效；这里移除的是重复的主题暴露。残差动量、质量修复和 PMOM 已共同表达盈利信息扩散，因此组合层面减少重复后横截面分离更强。",
        "metrics": {"robust": finite(performance["robust_score"]), "coverage": finite(performance["coverage"]), "turnover": finite(performance.get("avg_turnover"))},
        "series": [[date.strftime("%Y-%m-%d"), round(point.top, 5), round(point.worst, 5), round(point.bench, 5)] for date, point in aligned.iterrows()],
        "weights": [{"label": label, "group": theme, "value": 1 / len(themes)} for label, theme in themes],
        "subsetKeys": [],
        "evidenceRows": [
            ["Top / Benchmark CAGR", pct(performance["ratio_cagr"])],
            ["Top / Worst 终值", ratio_terminal(performance["top_worst_ratio_return"])],
            ["Robust score", num(performance["robust_score"])],
            ["Coverage", pct(performance["coverage"])],
        ],
    }


def evidence_section(
    title: str,
    columns: list[str],
    rows: list[list[Any]],
    note: str = "",
) -> dict[str, Any]:
    return {
        "title": title,
        "columns": columns,
        "rows": [["-" if value is None else str(value) for value in row] for row in rows],
        "note": note,
    }


def evidence_tab(tab_id: str, label: str, sections: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": tab_id, "label": label, "sections": sections}


def normalize_periods(
    periods: list[Any],
    narratives: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    result = []
    narratives = narratives or {}
    for period in periods:
        if isinstance(period, dict):
            period_id = str(period["id"])
            label = str(period.get("label") or period.get("title") or period_id)
            start = period.get("start")
            end = period.get("end")
        else:
            period_id, label, start, end = period[:4]
            period_id = str(period_id)
        narrative = narratives.get(period_id, {})
        result.append(
            {
                "id": period_id,
                "label": label,
                "start": start,
                "end": end,
                "headline": narrative.get("headline") or narrative.get("label") or label,
                "narrative": narrative.get("economics") or narrative.get("narrative") or "",
                "leaders": narrative.get("leaders") or [],
            }
        )
    return result


def attach_period_contexts(report: dict[str, Any]) -> dict[str, Any]:
    for period in report["periods"]:
        context = PERIOD_CONTEXTS[(report["id"], period["id"])]
        period["definition"] = context["definition"]
        period["sources"] = [PERIOD_SOURCES[source_id] for source_id in context["sources"]]
    return report


def normalize_standard_candidate(
    item: dict[str, Any],
    focus: dict[str, Any] | None,
    fallback_economics: str,
) -> dict[str, Any]:
    metrics = item.get("metrics") or {}
    root_weights = item.get("rootWeights") or []
    raw_weights = item.get("rawWeights") or []
    root_total = sum(finite(row.get("weight")) or 0 for row in root_weights)
    root_map = {
        row.get("label"): (finite(row.get("weight")) or 0) / root_total
        for row in root_weights
    } if root_total else {}
    weights = []
    for row in raw_weights or root_weights:
        group = (row.get("path") or "").partition(" > ")[0]
        siblings = sum((other.get("path") or "").partition(" > ")[0] == group for other in raw_weights)
        value = root_map[group] / siblings if group in root_map and siblings else finite(row.get("weight"))
        weights.append({"label": row.get("label") or row.get("metric"), "value": value, "group": group or None})
    economics = (focus or {}).get("economics") or fallback_economics
    thesis = (focus or {}).get("thesis") or item.get("note") or item.get("evidence") or ""
    evidence_rows = (focus or {}).get("evidence") or []
    if isinstance(evidence_rows, dict):
        evidence_rows = [[key, value] for key, value in evidence_rows.items()]
    return {
        "id": item["metric"],
        "label": item.get("label") or item.get("name") or item["metric"],
        "group": item.get("group") or item.get("type") or "候选",
        "kind": item.get("type") or item.get("kind") or "candidate",
        "thesis": thesis,
        "economics": economics,
        "metrics": {
            "robust": finite(metrics.get("robust")),
            "coverage": finite(metrics.get("coverage")),
            "turnover": finite(metrics.get("turnover")),
        },
        "series": round_series(item.get("series") or []),
        "weights": weights,
        "subsetKeys": [row.get("label") for row in root_weights] if (item.get("type") or item.get("kind")) == "family_subset" else [],
        "evidenceRows": evidence_rows,
    }


def build_eu_small(source: dict[str, Any]) -> dict[str, Any]:
    analysis = source["analysis"]
    core = analysis["core"]
    extension_ready = (EU_SMALL_EXTENSION_RUN / "family_subset_results.csv").exists() and (EU_SMALL_EXTENSION_RUN / "selected_legs.csv").exists()
    if extension_ready:
        subset_catalog, bucket_variables = merged_subset_data(source["provenance"]["latestSynergy"], EU_SMALL_EXTENSION_RUN)
    else:
        subset_catalog, bucket_variables = standard_subset_data(source["provenance"]["latestSynergy"])
    bucket_economics = analysis.get("bucketEconomics") or {}
    candidates = []
    for item in source["candidates"]:
        labels = [row.get("label") for row in item.get("rootWeights") or []]
        economics = " ".join(bucket_economics.get(label, "") for label in labels).strip()
        candidates.append(normalize_standard_candidate(item, None, economics or core["verdict"]))
    extension_gate_rows = csv_rows(EU_SMALL_EXTENSION_RUN / "extension_validation_gate.csv") if extension_ready else []
    extension_loo_rows = csv_rows(EU_SMALL_EXTENSION_RUN / "leave_one_out_results.csv") if extension_ready else []
    if extension_ready:
        candidates.extend(official_extension_candidates(EU_SMALL_EXTENSION_RUN))
        candidates.extend(extension_theme_candidates(EU_SMALL_EXTENSION_RUN, include_loo=True))
    summary = analysis["summary"]
    stats = [
        {"value": summary["rawTested"], "label": "Raw 已测试"},
        {"value": summary["rawPassed"], "label": "Raw 通过 gate"},
        {"value": summary["relativeTested"], "label": "Relative 已测试"},
        {"value": summary["relativePassed"], "label": "Relative 通过 gate"},
        {"value": summary["synergyClaims"], "label": "旧版严格 pair synergy" if extension_ready else "严格 pair synergy"},
        {"value": len(candidates), "label": "可交互候选"},
    ]
    if extension_ready:
        stats.extend(
            [
                {"value": sum(str(row.get("pass_gate", "")).lower() == "true" for row in extension_gate_rows), "label": "扩展候选通过 Gate"},
                {"value": len(csv_rows(EU_SMALL_EXTENSION_RUN / "family_subset_results.csv")) - 1, "label": "新增主题组合"},
            ]
        )
    raw_rows = [
        [
            row["label"],
            f'{row["family"]} · {row["source"]}',
            "通过" if row["passed"] else "未通过",
            pct(row["coverage"]),
            pct(row["activeCagr"]),
            ratio(row["topWorst"]),
            num(row["robust"]),
        ]
        for row in analysis["raw"]
    ]
    relative_rows = [
        [
            f'{row["raw"]} · {row["transform"]} lag{row["lag"]}',
            f'{row["family"]} · {row["source"]}',
            "通过" if row["passed"] else "未通过",
            pct(row["coverage"]),
            pct(row["activeCagr"]),
            ratio(row["topWorst"]),
            num(row["robust"]),
        ]
        for row in analysis["relative"]
    ]
    pair_rows = [
        [
            row["label"],
            row["buckets"],
            pct(row["activeCagr"]),
            ratio(row["topWorst"]),
            num(row["robust"]),
            num(row["synergy"]),
            row["classification"],
        ]
        for row in analysis["synergy"]
    ]
    subset_rows = [
        [
            row["label"],
            row["buckets"],
            pct(row["activeCagr"]),
            ratio(row["topWorst"]),
            num(row["robust"]),
            row["classification"],
        ]
        for row in analysis["subsets"]
    ]
    loo_rows = [
        [
            row["bucket"],
            num(row["robustContribution"]),
            pct(row["activeContribution"]),
            row["classification"],
        ]
        for row in analysis["loo"]
    ]
    regime_rows = [
        [
            period_id,
            row.get("headline"),
            row.get("leaders"),
            row.get("economics"),
        ]
        for period_id, row in analysis["periodAnalysis"].items()
    ]
    extension_gate_table = [
        [
            row["label"],
            row["theme"],
            "通过" if str(row.get("pass_gate", "")).lower() == "true" else "失败",
            pct(row["coverage"]),
            pct(row["ratio_cagr"]),
            ratio_terminal(row["top_worst_ratio_return"]),
            num(row["robust_score"]),
            row.get("fail_reasons") or "-",
        ]
        for row in extension_gate_rows
    ]
    extension_loo_table = [
        [
            row["left_out_bucket"],
            pct(row["without_ratio_cagr"]),
            num(row["without_robust_score"]),
            num(row["loo_contribution"]),
            row["classification"],
        ]
        for row in extension_loo_rows
    ]
    extension_candidates = [item for item in candidates if item["group"] == "recommended_extension"]
    default_candidate = extension_candidates[0]["id"] if extension_candidates else source["defaultMetric"]
    headline = "欧洲小盘的升级核心是质量改善、ROE、现金流估值与去杠杆的多重确认。" if extension_ready else core["headline"]
    verdict = "国家调整提高了质量与价值信号的可比性；完整模型中独立 revision、残差动量和残差风险出现重复，最佳 LOO 是 full model without revision。" if extension_ready else core["verdict"]
    return {
        "id": "eu-small",
        "shortName": "EU Small",
        "title": source["title"],
        "universe": source["universe"],
        "benchmark": source["benchmark"],
        "asOf": source["asOf"],
        "method": source["evidence"],
        "headline": headline,
        "verdict": verdict,
        "stats": stats,
        "periods": normalize_periods(source["periods"], analysis["periodAnalysis"]),
        "defaultCandidate": default_candidate,
        "candidates": candidates,
        "subsetCatalog": subset_catalog,
        "bucketVariables": bucket_variables,
        "evidenceTabs": [
            evidence_tab("raw", "Raw gate", [evidence_section("Raw variables", ["变量", "Family / 来源", "结果", "Coverage", "主动 CAGR", "Top/Worst", "Robust"], raw_rows)]),
            evidence_tab("relative", "Relative gate", [evidence_section("Same-security relative variables", ["变量", "Family / 来源", "结果", "Coverage", "主动 CAGR", "Top/Worst", "Robust"], relative_rows)]),
            evidence_tab("synergy", "Pair / Subset / LOO", [
                evidence_section("严格 pair synergy", ["Pair", "Buckets", "主动 CAGR", "Top/Worst", "Robust", "Synergy", "分类"], pair_rows),
                evidence_section("Family subset", ["Subset", "Buckets", "主动 CAGR", "Top/Worst", "Robust", "分类"], subset_rows),
                evidence_section("Leave-one-out", ["Bucket", "Robust 贡献", "主动贡献", "分类"], loo_rows),
            ]),
            evidence_tab("regime", "Regime", [evidence_section("时期机制解释", ["时期", "主题", "领先方向", "经济解释"], regime_rows)]),
            *([evidence_tab("eu-small-extension", "欧洲小盘扩展", [
                evidence_section("国家偏差、资本效率、流动性、残差与低覆盖反证 Gate", ["候选", "主题", "结果", "Coverage", "主动 CAGR", "Top/Worst 终值", "Robust", "失败原因"], extension_gate_table, "Gate 未放宽：Coverage ≥ 75%，Top/Benchmark ratio CAGR、Top/Worst ratio return 与 Robust score 均须为正。"),
                evidence_section("扩展主题 Leave-one-out", ["移除主题", "移除后主动 CAGR", "移除后 Robust", "原主题贡献", "分类"], extension_loo_table),
            ])] if extension_ready else []),
            evidence_tab("limits", "限制与反例", [evidence_section("解释边界", ["限制"], [[row] for row in analysis["limits"]])]),
        ],
        "provenance": [*source["provenance"].values(), *([str(EU_SMALL_EXTENSION_RUN / "extension_validation_gate.csv"), str(EU_SMALL_EXTENSION_RUN / "family_subset_results.csv")] if extension_ready else [])],
    }


def build_sp500(source: dict[str, Any]) -> dict[str, Any]:
    analysis = source["analysis"]
    verdict = analysis["verdict"]
    extension_ready = (SP500_EXTENSION_RUN / "family_subset_results.csv").exists() and (SP500_EXTENSION_RUN / "selected_legs.csv").exists()
    if extension_ready:
        subset_catalog, bucket_variables = merged_subset_data(source["provenance"]["latestSynergy"], SP500_EXTENSION_RUN)
    else:
        subset_catalog, bucket_variables = standard_subset_data(source["provenance"]["latestSynergy"])
    focus_map = {row["metric"]: row for row in analysis["focus"]}
    candidates = [
        normalize_standard_candidate(item, focus_map.get(item["metric"]), verdict["copy"])
        for item in source["candidates"]
    ]
    if extension_ready:
        candidates.extend(official_extension_candidates(SP500_EXTENSION_RUN))
        candidates.extend(extension_theme_candidates(SP500_EXTENSION_RUN))
    stats = list(analysis["stats"])
    extension_gate_rows = csv_rows(SP500_EXTENSION_RUN / "extension_validation_gate.csv") if extension_ready else []
    extension_loo_rows = csv_rows(SP500_EXTENSION_RUN / "leave_one_out_results.csv") if extension_ready else []
    if extension_ready:
        for stat in stats:
            if stat.get("label") == "严格 family subset synergy":
                stat["label"] = "旧版严格 family subset synergy"
        stats.extend(
            [
                {"value": sum(str(row.get("pass_gate", "")).lower() == "true" for row in extension_gate_rows), "label": "扩展候选通过 Gate"},
                {"value": len(csv_rows(SP500_EXTENSION_RUN / "family_subset_results.csv")) - 1, "label": "新增主题组合"},
            ]
        )
    rotation = {row["id"]: row for row in analysis["rotation"]}
    periods = normalize_periods(source["periods"], rotation)
    for period in periods:
        row = rotation.get(period["id"])
        if row:
            period["leaders"] = [
                f'{item["label"]} · {pct(item["activeCagr"])}' for item in row["leaders"]
            ]
    raw_rows = [
        [row["label"], row["family"], "通过", pct(row["coverage"]), pct(row["activeCagr"]), ratio(row["topWorst"]), num(row["robust"])]
        for row in analysis["rawGate"]
    ]
    relative_rows = [
        [
            f'{row["label"]} · {row["transform"]} lag{int(row["lag"])}',
            f'{row["family"]} · {row["role"]}',
            "通过",
            pct(row["coverage"]),
            pct(row["activeCagr"]),
            ratio(row["topWorst"]),
            num(row["robust"]),
        ]
        for row in analysis["relativeGate"]
    ]
    pair_rows = [
        [row["label"], row["buckets"].replace("|", " + "), pct(row["activeCagr"]), ratio(row["topWorst"]), num(row["robust"]), num(row["synergy"])]
        for row in analysis["strictPairs"]
    ]
    subset_rows = [
        [row["label"], row["buckets"].replace("|", " + "), pct(row["activeCagr"]), ratio(row["topWorst"]), num(row["robust"]), row["classification"]]
        for row in analysis["subsets"]
    ]
    loo_rows = [
        [row["bucket"], num(row["robustContribution"]), pct(row["activeContribution"]), num(row["withoutRobust"]), row["classification"]]
        for row in analysis["leaveOneOut"]
    ]
    regime_rows = []
    for row in analysis["rotation"]:
        for leader in row["leaders"]:
            regime_rows.append([row["label"], leader["label"], pct(leader["activeCagr"]), ratio(leader["topWorst"]), row["narrative"]])
    extension_rows = [
        [row["label"], row["theme"], "通过" if str(row.get("pass_gate", "")).lower() == "true" else "失败", pct(row["coverage"]), pct(row["ratio_cagr"]), ratio_terminal(row["top_worst_ratio_return"]), num(row["robust_score"]), row.get("fail_reasons") or "-"]
        for row in extension_gate_rows
    ]
    extension_loo_evidence = [
        [row["left_out_bucket"], pct(row["without_ratio_cagr"]), num(row["without_robust_score"]), num(row["loo_contribution"]), row["classification"]]
        for row in sorted(extension_loo_rows, key=lambda item: float(item["without_robust_score"]), reverse=True)
    ]
    return {
        "id": "sp500",
        "shortName": "SP500",
        "title": source["title"],
        "universe": source["universe"],
        "benchmark": source["benchmark"],
        "asOf": source["asOf"],
        "method": source["evidence"],
        "headline": verdict["headline"],
        "verdict": verdict["copy"],
        "stats": stats,
        "periods": periods,
        "defaultCandidate": source["defaultMetric"],
        "candidates": candidates,
        "subsetCatalog": subset_catalog,
        "bucketVariables": bucket_variables,
        "evidenceTabs": [
            evidence_tab("raw", "Raw gate", [evidence_section("通过 gate 的 Raw variables", ["变量", "Family", "结果", "Coverage", "主动 CAGR", "Top/Worst", "Robust"], raw_rows)]),
            evidence_tab("relative", "Relative gate", [evidence_section("通过 gate 的 Relative variables", ["变量", "Family / 角色", "结果", "Coverage", "主动 CAGR", "Top/Worst", "Robust"], relative_rows)]),
            evidence_tab("synergy", "Pair / Subset / LOO", [
                evidence_section("严格 pair synergy", ["Pair", "Buckets", "主动 CAGR", "Top/Worst", "Robust", "Synergy"], pair_rows),
                evidence_section("Family subset", ["Subset", "Buckets", "主动 CAGR", "Top/Worst", "Robust", "分类"], subset_rows),
                evidence_section("Leave-one-out", ["Bucket", "Robust 贡献", "主动贡献", "移除后 Robust", "分类"], loo_rows),
            ]),
            evidence_tab("regime", "Regime", [evidence_section("时期轮动", ["时期", "领先变量", "主动 CAGR", "Top/Worst", "经济解释"], regime_rows)]),
            evidence_tab("extension", "SP500 扩展", [
                evidence_section("规模中性、应计质量、资本效率、残差动量与股东回报 Gate", ["候选", "主题", "结果", "Coverage", "主动 CAGR", "Top/Worst 终值", "Robust", "失败原因"], extension_rows, "Gate 未放宽：Coverage ≥ 75%，Top/Benchmark ratio CAGR、Top/Worst ratio return 与 Robust score 均须为正。"),
                evidence_section("扩展主题 Leave-one-out", ["移除主题", "移除后主动 CAGR", "移除后 Robust", "原主题贡献", "分类"], extension_loo_evidence),
            ]),
            evidence_tab("limits", "限制与反例", [evidence_section("解释边界", ["限制"], [[row] for row in analysis["limitations"]])]),
        ],
        "provenance": [*source["provenance"].values(), *([str(SP500_EXTENSION_RUN / "extension_validation_gate.csv"), str(SP500_EXTENSION_RUN / "family_subset_results.csv")] if extension_ready else [])],
    }


def build_stoxx600(source: dict[str, Any], document: str) -> dict[str, Any]:
    bucket_economics = {
        "盈利预期上修": "盈利预期上修表示分析师正在确认尚未完全进入价格的经营改善",
        "价格动量": "价格动量表示市场正在用交易行为确认基本面信息",
        "前瞻增长": "前瞻增长强调未来盈利兑现，而不是依赖历史增速",
        "质量改善": "质量改善反映利润率或资本效率的边际提升",
        "盈利收益率改善": "盈利收益率改善意味着盈利相对价格变得更有吸引力",
        "去杠杆": "去杠杆降低财务脆弱性，并提高盈利转化为股东回报的确定性",
        "估值改善": "估值改善与基本面改善同步时，更可能是重估而非价值陷阱",
        "风险下降": "风险下降降低尾部损失和资本成本压力",
    }
    with (Path(source["paths"]["run"]) / "selected_legs.csv").open(encoding="utf-8-sig", newline="") as handle:
        selected_legs = list(csv.DictReader(handle))
    legs_by_bucket = {
        bucket: [row for row in selected_legs if row["bucket"] == bucket]
        for bucket in {row["bucket"] for row in selected_legs}
    }
    leg_labels = {row["metric"]: row["label"] for row in selected_legs}
    leg_buckets = {row["metric"]: row["bucket"] for row in selected_legs}
    extension_ready = (STOXX600_EXTENSION_RUN / "family_subset_results.csv").exists() and (STOXX600_EXTENSION_RUN / "selected_legs.csv").exists()
    subset_run = STOXX600_EXTENSION_RUN if extension_ready else Path(source["paths"]["run"])
    subset_catalog, bucket_variables = standard_subset_data(str(subset_run))
    candidates = []
    for item in source["candidates"]:
        metrics = item["metrics"]
        buckets = item.get("buckets") or []
        components = item.get("components") or []
        if item.get("kind") == "pair":
            weights = [{"label": leg_labels.get(metric, metric), "value": 1 / len(components), "group": leg_buckets.get(metric)} for metric in components]
        else:
            weights = [
                {"label": row["label"], "value": 1 / len(components) / len(legs_by_bucket[bucket]), "group": bucket}
                for bucket in components
                for row in legs_by_bucket[bucket]
            ] if components else []
        economics = "；".join(bucket_economics.get(label, f"{label}提供一条独立验证线索") for label in buckets)
        candidates.append(
            {
                "id": item["metric"],
                "label": item["name"],
                "group": item["kind"].replace("_", " "),
                "kind": item["kind"],
                "thesis": item.get("note") or "",
                "economics": f"{economics}。" if economics else "该候选需要结合其组成信号解释经济机制。",
                "metrics": {
                    "robust": finite(metrics.get("robust")),
                    "coverage": finite(metrics.get("coverage")),
                    "turnover": finite(metrics.get("turnover")),
                },
                "series": round_series(item["series"]),
                "weights": weights,
                "subsetKeys": components if item.get("kind") == "family_subset" else [],
                "evidenceRows": [],
            }
        )
    if extension_ready:
        candidates.extend(official_extension_candidates(STOXX600_EXTENSION_RUN))
        candidates.append(stoxx600_recommended_model(STOXX600_EXTENSION_RUN))
    summary = source["summary"]
    stats = [
        {"value": summary["rawTested"], "label": "Raw 已测试"},
        {"value": summary["rawPassed"], "label": "Raw 通过 gate"},
        {"value": summary["relativeTested"], "label": "Relative 已测试"},
        {"value": summary["relativePassed"], "label": "Relative 通过 gate"},
        {"value": summary["synergyClaims"], "label": "严格 pair synergy"},
        {"value": summary["officialSuccess"], "label": "Official runs 成功"},
    ]
    extension_gate_rows = []
    extension_loo_rows = []
    if extension_ready:
        extension_gate_rows = csv_rows(STOXX600_EXTENSION_RUN / "extension_validation_gate.csv")
        extension_loo_rows = csv_rows(STOXX600_EXTENSION_RUN / "leave_one_out_results.csv")
        stats.extend(
            [
                {"value": sum(str(row.get("pass_gate", "")).lower() == "true" for row in extension_gate_rows), "label": "扩展候选通过 Gate"},
                {"value": len(subset_catalog) - 1, "label": "扩展主题组合"},
            ]
        )
    raw_rows = [
        [row["label"], f'{row["family"]} · {row["source"]}', row["outcome"], pct(row["coverage"]), pct(row["ratio_cagr"]), ratio(row["top_worst_ratio_return"]), num(row["robust_score"])]
        for row in source["raw"]
    ]
    relative_rows = [
        [f'{row["raw_column"]} · {row["transform"]} lag{row["lag_observations"]}', row["family"], row["outcome"], pct(row["coverage"]), pct(row["ratio_cagr"]), ratio(row["top_worst_ratio_return"]), num(row["robust_score"])]
        for row in source["relative"]
    ]
    claim_rows = [
        [row["label"], row["buckets"].replace("|", " + "), pct(row["ratio_cagr"]), ratio(row["top_worst_ratio_return"]), num(row["robust_score"]), num(row["synergy_score"]), row["classification"]]
        for row in source["claims"]
    ]
    subset_rows = [
        [row["label"], row["buckets"].replace("|", " + "), pct(row["ratio_cagr"]), ratio(row["top_worst_ratio_return"]), num(row["robust_score"]), row["classification"]]
        for row in source["subsets"]
    ]
    loo_rows = [
        [source["bucketNames"].get(row["left_out_bucket"], row["left_out_bucket"]), num(row["loo_contribution"]), pct(row["ratio_contribution"]), row["classification"]]
        for row in source["loo"]
    ]
    regime_rows = [
        [row["label"], pct(row["pre_active_cagr"]), pct(row["post_active_cagr"]), pct(row["all_active_cagr"]), pct(row["post_active_cagr"] - row["pre_active_cagr"])]
        for row in source["regime"]
    ]
    extension_rows = [
        [row["label"], row["theme"], "通过" if str(row.get("pass_gate", "")).lower() == "true" else "失败", pct(row["coverage"]), pct(row["ratio_cagr"]), ratio_terminal(row["top_worst_ratio_return"]), num(row["robust_score"]), row.get("fail_reasons") or "-"]
        for row in extension_gate_rows
    ]
    extension_loo_evidence = [
        [row["left_out_bucket"], pct(row["without_ratio_cagr"]), num(row["without_robust_score"]), num(row["loo_contribution"]), row["classification"]]
        for row in sorted(extension_loo_rows, key=lambda item: float(item["without_robust_score"]), reverse=True)
    ]
    period_analysis = {
        "all": {
            "headline": "长期主线：改善型质量，而非静态标签",
            "narrative": "全样本官方候选显示，质量改善、去杠杆与盈利预期或价格确认的组合更稳定；静态价值只有在基本面同步改善时才更可信。",
        },
        "pre": {
            "headline": "2020 前：价格确认、质量改善与去杠杆",
            "narrative": "当前候选中，价格确认、利润率改善和去杠杆组合领先，说明低利率并未消除资产负债表与经营质量的筛选作用。",
        },
        "covid": {
            "headline": "疫情反弹：盈利可见度与偿债能力",
            "narrative": "疫情冲击与政策反弹快速重写盈利路径；盈利预期上修需要质量改善和去杠杆共同确认，才能降低短期反弹被误判为长期改善的风险。",
        },
        "inflation": {
            "headline": "通胀加息：盈利收益率与利润率改善",
            "narrative": "能源、通胀和融资成本上升后，市场更偏好利润率能够改善、盈利相对价格更有吸引力，并保持资产负债表纪律的公司。",
        },
        "recent": {
            "headline": "正常化与集中度上升：趋势需要盈利确认",
            "narrative": "近期候选更偏向 PMOM、利润率改善和盈利收益率改善；集中度上升时，价格趋势需要盈利与质量信号共同确认。",
        },
    }
    verdict = first_match(
        document,
        r"<h2>2020 前后：结论</h2>\s*<p[^>]*>(.*?)</p>",
        "证据支持定价机制发生改变，但不支持所有旧因子失效。",
    )
    return {
        "id": "stoxx600",
        "shortName": "STOXX 600",
        "title": source["title"],
        "universe": source["universe"],
        "benchmark": source["benchmark"],
        "asOf": source["asOf"],
        "method": source["evidence"],
        "headline": "2020 前后：定价机制换挡",
        "verdict": verdict,
        "stats": stats,
        "periods": normalize_periods(source["periods"], period_analysis),
        "defaultCandidate": candidates[0]["id"],
        "candidates": candidates,
        "subsetCatalog": subset_catalog,
        "bucketVariables": bucket_variables,
        "evidenceTabs": [
            evidence_tab("raw", "Raw gate", [evidence_section("Raw variables", ["变量", "Family / 来源", "结果", "Coverage", "主动 CAGR", "Top/Worst", "Robust"], raw_rows)]),
            evidence_tab("relative", "Relative gate", [evidence_section("Same-security relative variables", ["变量", "Family", "结果", "Coverage", "主动 CAGR", "Top/Worst", "Robust"], relative_rows)]),
            evidence_tab("synergy", "Pair / Subset / LOO", [
                evidence_section("严格 pair synergy", ["Pair", "Buckets", "主动 CAGR", "Top/Worst", "Robust", "Synergy", "分类"], claim_rows),
                evidence_section("Family subset", ["Subset", "Buckets", "主动 CAGR", "Top/Worst", "Robust", "分类"], subset_rows),
                evidence_section("Leave-one-out", ["Bucket", "Robust 贡献", "主动贡献", "分类"], loo_rows),
            ]),
            evidence_tab("regime", "Regime", [evidence_section("2020 regime break", ["变量 / 组合", "2010-2019", "2020-2026", "全样本", "变化"], regime_rows)]),
            evidence_tab("extension", "STOXX 扩展", [
                evidence_section("国家中性、资本效率、股息、残差动量与风险 Gate", ["候选", "主题", "结果", "Coverage", "主动 CAGR", "Top/Worst", "Robust", "失败原因"], extension_rows, "Gate 未放宽：Coverage ≥ 75%，Top/Benchmark CAGR、Top/Worst 累计收益与 Robust score 均须为正。"),
                evidence_section("扩展主题 Leave-one-out", ["移除主题", "移除后主动 CAGR", "移除后 Robust", "原主题贡献", "分类"], extension_loo_evidence, "移除 revision 后 Robust 6.60、Top/Worst 10.61x；这表示在当前扩展模型中信息重叠，不代表 EPS revision 单变量失效。"),
            ]),
            evidence_tab("limits", "限制与反例", [evidence_section("解释边界", ["限制"], [["Pair、subset 与 leave-one-out 必须分开阅读；经济直觉或高回报不自动等于 synergy。"]])]),
        ],
        "provenance": list(source["paths"].values()),
    }


def build_nasdaq(document: str) -> dict[str, Any]:
    focus_items = js_array(document, "focusItems")
    relative_rows = js_array(document, "relativeRows")
    synergies = js_array(document, "synergies")
    periods_source = js_array(document, "periods")
    active = json_script(document, "active-series-data")
    tables = parsed_tables(document)
    candidates = []
    for item in focus_items:
        metric_values = {label: parse_display_number(value) for label, value in item["metrics"]}
        payload = active[item["id"]]
        candidates.append(
            {
                "id": payload["metric"],
                "label": item["name"],
                "group": item["badge"],
                "kind": item["id"],
                "thesis": item["thesis"],
                "economics": item["economics"],
                "metrics": {
                    "robust": metric_values.get("robust") or metric_values.get("robust uplift"),
                    "coverage": metric_values.get("coverage"),
                    "turnover": None,
                },
                "series": round_series(payload["series"]),
                "weights": [],
                "evidenceRows": item["evidence"],
            }
        )
    if (NASDAQ_EXTENSION_RUN / "tech_validation_gate.csv").exists():
        candidates.extend(nasdaq_tech_candidates(NASDAQ_EXTENSION_RUN))
    periods = []
    for row in periods_source:
        periods.append(
            {
                "id": row["id"],
                "label": row["title"],
                "start": row["start"],
                "end": row["end"],
                "headline": row["title"],
                "narrative": row["copy"],
                "leaders": [f"{leader[0]} · {pct(leader[1])}" for leader in row["rows"]],
            }
        )
    stats = [
        {"value": int(value), "label": clean_markup(label)}
        for value, label in re.findall(
            r'<article class="card stat[^"]*"><div class="number">(\d+)</div><div class="label">(.*?)</div></article>',
            document,
            re.DOTALL,
        )
    ]
    if (NASDAQ_EXTENSION_RUN / "tech_validation_gate.csv").exists():
        tech_gate = csv_rows(NASDAQ_EXTENSION_RUN / "tech_validation_gate.csv")
        stats.extend(
            [
                {"value": len(tech_gate), "label": "科技专用候选（严格 Gate）"},
                {"value": sum(str(row.get("passed", "")).lower() == "true" for row in tech_gate), "label": "科技专用候选通过"},
            ]
        )
    raw_table = tables[0]
    subset_table = tables[2]
    limits_table = tables[3]
    focus_evidence = []
    for item in focus_items:
        for evidence_type, copy in item["evidence"]:
            focus_evidence.append([item["name"], evidence_type, copy])
    regime_rows = []
    for period in periods_source:
        for leader in period["rows"]:
            regime_rows.append([period["title"], leader[0], pct(leader[1]), period["copy"]])
    provenance = [clean_markup(row) for row in re.findall(r'<p class="path">(.*?)</p>', document, re.DOTALL)]
    synergy_path = next(resolve_workspace_path(row) for row in provenance if row.endswith("synergy_claims.csv"))
    subset_run = NASDAQ_EXTENSION_RUN if (NASDAQ_EXTENSION_RUN / "family_subset_results.csv").exists() else synergy_path.parent
    subset_catalog, bucket_variables = nasdaq_subset_data(subset_run)
    if subset_run == NASDAQ_EXTENSION_RUN:
        provenance.extend(
            [
                str(NASDAQ_EXTENSION_RUN / "tech_validation_gate.csv"),
                str(NASDAQ_EXTENSION_RUN / "family_subset_results.csv"),
            ]
        )
    headline = first_match(
        document,
        r'<aside class="verdict">.*?<strong>(.*?)</strong>',
        "可兑现的改善，而不是静态高成长标签",
    )
    verdict = first_match(
        document,
        r'<aside class="verdict">.*?<p>(.*?)</p>',
        "盈利上修、经营质量改善与估值纪律共同构成核心证据。",
    )
    return {
        "id": "nasdaq",
        "shortName": "Nasdaq",
        "title": "Nasdaq 因子研究浏览器",
        "universe": "NASDAQ Composite",
        "benchmark": "NASDAQ COMP",
        "asOf": max(point[0] for payload in active.values() for point in payload["series"]),
        "method": "Official Top/Worst；20% Top/Worst；市值加权；月度信号",
        "headline": headline,
        "verdict": verdict,
        "stats": stats,
        "periods": periods,
        "defaultCandidate": active["core"]["metric"],
        "candidates": candidates,
        "subsetCatalog": subset_catalog,
        "bucketVariables": bucket_variables,
        "evidenceTabs": [
            evidence_tab("raw", "Raw gate", [evidence_section("通过 gate 的 Raw variables", raw_table["header"], raw_table["rows"])]),
            evidence_tab("relative", "Relative gate", [evidence_section("通过 gate 的 Relative variables", ["变量", "变换", "Lag", "Coverage", "主动 CAGR", "Top/Worst", "Robust"], relative_rows)]),
            evidence_tab("synergy", "Pair / Subset / LOO", [
                evidence_section("严格 pair synergy", ["组合", "Robust"], [[row["name"], num(row["robust"], 3)] for row in synergies]),
                evidence_section("Family subset", subset_table["header"], subset_table["rows"]),
                evidence_section("候选证据链", ["候选", "证据类型", "说明"], focus_evidence),
            ]),
            evidence_tab("regime", "Regime", [evidence_section("时期轮动", ["时期", "领先方向", "主动 CAGR", "经济解释"], regime_rows)]),
            evidence_tab("limits", "限制与反例", [evidence_section("限制与反例", limits_table["header"], limits_table["rows"])]),
        ],
        "provenance": provenance,
    }


HTML_DOCUMENT = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>TP Unified Factor Explorer</title>
  <style>
    :root {
      --background:#f3f6f4; --foreground:#17231f; --card:#ffffff; --card-soft:#eaf0ec;
      --muted:#5f6f67; --border:#d7dfda; --positive:#0a7755; --positive-soft:#dcefe6;
      --negative:#b04450; --negative-soft:#f7e3e6; --warning:#a56710; --warning-soft:#f7ecd7;
      --series-top:#087f62; --series-bench:#356fba; --series-worst:#c85a63; --series-ratio:#c08721; --series-bench-ratio:#7657b1;
      --shadow:0 10px 28px rgba(24,45,34,.07); --radius:10px;
      font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
    }
    @media (prefers-color-scheme:dark) {
      :root {
        --background:#111713; --foreground:#eaf2ed; --card:#18211b; --card-soft:#202b23;
        --muted:#a8b7ae; --border:#314137; --positive:#79d9ae; --positive-soft:#153d2e;
        --negative:#ff9ca5; --negative-soft:#52242a; --warning:#ffc46f; --warning-soft:#4e3917;
        --series-top:#79d9ae; --series-bench:#8abcf3; --series-worst:#ff9ca5; --series-ratio:#ffc46f; --series-bench-ratio:#c6a8f4;
        --shadow:none;
      }
    }
    *{box-sizing:border-box}
    body{margin:0;background:var(--background);color:var(--foreground)}
    button,select{font:inherit;color:inherit}
    button:focus-visible,select:focus-visible{outline:3px solid var(--series-bench);outline-offset:2px}
    .shell{width:100%;max-width:none;margin:0;padding:18px 20px 28px}
    .topline{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;padding-bottom:16px;border-bottom:1px solid var(--border)}
    h1,h2,h3,p{margin-top:0}
    h1{margin-bottom:6px;font-size:30px;font-weight:500}
    h2{font-size:20px;font-weight:500}
    h3{font-size:15px;font-weight:500}
    .eyebrow{margin-bottom:5px;color:var(--positive);font-size:12px;font-weight:500;text-transform:uppercase;letter-spacing:.04em}
    .meta,.muted{color:var(--muted)}
    .meta{max-width:760px;text-align:right;font-size:12px;line-height:1.55}
    .dashboard{display:grid;grid-template-columns:minmax(320px,25%) minmax(0,1fr);gap:16px;align-items:start;margin-top:16px}
    .sidebar,.main-column{min-width:0}
    .market-tabs,.mode-tabs,.evidence-tabs{display:flex;flex-wrap:wrap;gap:6px}
    .market-tabs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));margin:0 0 12px}
    .market-tabs .tab-button{width:100%}
    .tab-button{padding:9px 12px;border:1px solid var(--border);border-radius:8px;background:var(--card);cursor:pointer}
    .tab-button[aria-selected="true"],.tab-button[aria-pressed="true"]{border-color:var(--positive);background:var(--positive-soft);color:var(--positive)}
    .card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow)}
    .verdict{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(320px,.65fr);gap:18px;padding:20px}
    .verdict h2{margin-bottom:8px;font-size:24px}
    .verdict p{margin:0;color:var(--muted);line-height:1.65}
    .method{padding-left:18px;border-left:3px solid var(--positive)}
    .method strong{display:block;margin-bottom:6px}
    .stats,.metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-bottom:12px}
    .stat,.metric{padding:13px;background:var(--card);border:1px solid var(--border);border-radius:9px}
    .stat strong,.metric strong{display:block;margin-top:4px;font-size:21px;font-weight:500;font-variant-numeric:tabular-nums}
    .stat span,.metric span{display:block;color:var(--muted);font-size:11px;line-height:1.35}
    .positive strong,.positive-text{color:var(--positive)}
    .negative strong,.negative-text{color:var(--negative)}
    .subset-card{padding:14px;margin-bottom:12px}
    .subset-card h2{margin-bottom:6px}
    .subset-definition{padding:11px 0;border-top:1px solid var(--border)}
    .subset-definition:first-child{border-top:0}
    .subset-definition code{color:var(--positive);font-size:11px;font-weight:600;overflow-wrap:anywhere}
    .subset-definition p{margin:5px 0;color:var(--muted);font-size:11px;line-height:1.5}
    .subset-variables{font-size:10px;line-height:1.45;color:var(--foreground);overflow-wrap:anywhere}
    .controls{display:grid;grid-template-columns:1fr;gap:10px;padding:13px;margin-bottom:12px}
    label{display:grid;gap:5px;color:var(--muted);font-size:11px;font-weight:500}
    select{width:100%;min-width:0;padding:10px 11px;border:1px solid var(--border);border-radius:7px;background:var(--card)}
    .mode-tabs{align-items:stretch}
    .mode-tabs .tab-button{flex:1}
    .workspace,.lower-grid{display:grid;grid-template-columns:minmax(0,3fr) minmax(320px,.8fr);gap:14px;align-items:start}
    .lower-grid{margin-top:14px}
    .primary-stack{display:grid;gap:14px;min-width:0}
    .chart-card,.detail-card,.evidence-card{padding:16px}
    .chart-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;margin-bottom:8px}
    .chart-head h2{margin-bottom:3px}
    .legend{display:flex;flex-wrap:wrap;gap:12px;color:var(--muted);font-size:11px}
    .legend span{display:inline-flex;align-items:center;gap:5px}
    .swatch{width:18px;height:3px;border-radius:3px}
    .chart-wrap{position:relative;min-height:378px;background:var(--card-soft);border-radius:8px;overflow:hidden}
    .chart-wrap svg{display:block;width:100%;height:auto}
    .period-bars{display:grid;gap:8px;margin-top:14px}
    .period-bar{display:grid;grid-template-columns:minmax(110px,1fr) minmax(80px,2fr) 58px;gap:9px;align-items:center;font-size:11px}
    .period-track{height:10px;position:relative;background:var(--card-soft);border-radius:6px;overflow:hidden}
    .period-fill{display:block;height:100%;border-radius:6px;background:var(--positive)}
    .period-fill.negative{margin-left:auto;background:var(--negative)}
    .period-value{text-align:right;font-variant-numeric:tabular-nums}
    .detail-card{position:relative;align-self:stretch;min-height:560px;overflow:hidden;perspective:1400px}
    .detail-flip{position:absolute;inset:16px;transform-style:preserve-3d;transition:transform .55s ease}
    .detail-card.is-flipped .detail-flip{transform:rotateY(180deg)}
    .detail-face{position:absolute;inset:0;padding-top:38px;overflow:auto;backface-visibility:hidden;-webkit-backface-visibility:hidden}
    .detail-front{pointer-events:auto}
    .detail-back{transform:rotateY(180deg);pointer-events:none}
    .detail-card.is-flipped .detail-front{pointer-events:none}
    .detail-card.is-flipped .detail-back{pointer-events:auto}
    .flip-button{position:absolute;z-index:3;top:12px;right:12px}
    .detail-front>section+section{margin-top:18px;padding-top:16px;border-top:1px solid var(--border)}
    .detail-front p{color:var(--muted);font-size:13px;line-height:1.6}
    .chips{display:flex;flex-wrap:wrap;gap:7px}
    .chip{padding:6px 8px;border-radius:7px;background:var(--card-soft);font-size:11px}
    .chip b{font-weight:500}
    .period-guide-list{display:grid}
    .period-guide-item{padding:13px 0;border-top:1px solid var(--border)}
    .period-guide-item:first-child{padding-top:0;border-top:0}
    .period-guide-item.active{padding-left:10px;border-left:3px solid var(--positive)}
    .period-guide-item h3{margin-bottom:4px}
    .period-guide-dates,.period-factor-label{color:var(--muted);font-size:11px}
    .period-guide-item p{margin:8px 0;color:var(--muted);font-size:12px;line-height:1.55}
    .period-factor-label{margin-bottom:6px;font-weight:500}
    .period-sources{margin-top:8px;color:var(--muted);font-size:11px;line-height:1.5}
    .period-sources a{color:var(--positive);text-decoration:none}
    .period-sources a:hover{text-decoration:underline}
    .evidence-tabs{margin-bottom:14px}
    .evidence-panel[hidden]{display:none}
    .evidence-section+.evidence-section{margin-top:22px;padding-top:18px;border-top:1px solid var(--border)}
    .evidence-section h3{margin-bottom:4px}
    .section-note{margin-bottom:10px;color:var(--muted);font-size:11px}
    .table-wrap{overflow-x:auto}
    table{width:100%;min-width:720px;border-collapse:collapse;font-size:12px}
    th,td{padding:9px 8px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top;line-height:1.4}
    th{position:sticky;top:0;background:var(--card);color:var(--muted);font-size:11px;font-weight:500}
    td.numeric,th.numeric{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
    tr:hover{background:var(--card-soft)}
    .badge{display:inline-flex;padding:3px 6px;border-radius:5px;font-size:10px;font-weight:500}
    .badge.good{background:var(--positive-soft);color:var(--positive)}
    .badge.bad{background:var(--negative-soft);color:var(--negative)}
    .badge.warn{background:var(--warning-soft);color:var(--warning)}
    .provenance{margin-top:16px;padding-top:14px;border-top:1px solid var(--border);color:var(--muted);font-size:11px;line-height:1.6;overflow-wrap:anywhere}
    .sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
    @media(prefers-reduced-motion:reduce){.detail-flip{transition:none}}
    @media(max-width:1200px){.dashboard,.workspace,.lower-grid,.verdict{grid-template-columns:1fr}.market-tabs{display:flex}.market-tabs .tab-button{width:auto}.stats,.metrics{grid-template-columns:repeat(3,minmax(0,1fr))}.controls{grid-template-columns:minmax(0,1.4fr) minmax(220px,.55fr) auto}.method{padding-left:0;padding-top:12px;border-left:0;border-top:3px solid var(--positive)}}
    @media(max-width:720px){.shell{padding:14px}.topline,.chart-head{display:block}.meta{text-align:left;margin-top:8px}.market-tabs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.market-tabs .tab-button{width:100%}.controls{grid-template-columns:1fr}.stats,.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.chart-wrap{min-height:252px}.period-bar{grid-template-columns:100px 1fr 52px}}
  </style>
</head>
<body>
  <main class="shell">
    <header class="topline">
      <div><div class="eyebrow">TP Quant Research / Unified official evidence explorer</div><h1 id="page-title">统一因子研究浏览器</h1></div>
      <div class="meta" id="page-meta"></div>
    </header>
    <div class="dashboard">
      <aside class="sidebar" aria-label="市场、候选与指标控制">
        <nav class="market-tabs" id="market-tabs" role="tablist" aria-label="市场选择"></nav>
        <section class="stats" id="summary-stats" aria-label="研究覆盖概览"></section>
        <section class="card controls" aria-label="报告控制">
          <label for="candidate-select">候选 / 组合<select id="candidate-select"></select></label>
          <label for="period-select">观察时期<select id="period-select"></select></label>
          <div class="mode-tabs" aria-label="解释模式">
            <button type="button" class="tab-button" data-mode="evidence" aria-pressed="true">证据</button>
            <button type="button" class="tab-button" data-mode="economics" aria-pressed="false">经济含义</button>
          </div>
        </section>
        <section class="metrics" id="candidate-metrics" aria-label="候选指标"></section>
        <section class="card subset-card" aria-labelledby="subset-title">
          <div class="eyebrow">Family subset</div>
          <h2 id="subset-title">组合定义</h2>
          <p class="section-note" id="subset-copy"></p>
          <label for="subset-guide-select">官方组合<select id="subset-guide-select"></select></label>
          <div id="subset-definitions"></div>
        </section>
      </aside>
      <div class="main-column">
        <section class="workspace">
      <div class="primary-stack">
        <section class="card verdict" aria-labelledby="verdict-title">
          <div><div class="eyebrow">核心结论</div><h2 id="verdict-title"></h2><p id="verdict-copy"></p></div>
          <div class="method"><strong id="method-universe"></strong><p id="method-copy"></p></div>
        </section>
      <article class="card chart-card">
        <div class="chart-head">
          <div><h2 id="chart-title"></h2><div class="muted" id="chart-subtitle"></div></div>
          <div class="legend" aria-label="图例">
            <span><i class="swatch" style="background:var(--series-top)"></i>Top</span>
            <span><i class="swatch" style="background:var(--series-bench)"></i>Benchmark</span>
            <span><i class="swatch" style="background:var(--series-worst)"></i>Worst</span>
            <span><i class="swatch" style="background:var(--series-ratio)"></i>Top / Worst ratio</span>
            <span><i class="swatch" style="background:var(--series-bench-ratio)"></i>Top / Benchmark ratio</span>
          </div>
        </div>
        <div class="chart-wrap" id="chart"></div>
      </article>
      </div>
      <aside class="card detail-card" id="detail-card">
        <button type="button" class="tab-button flip-button" id="detail-flip-button" aria-pressed="false" aria-controls="detail-back">↻ 查看时期图鉴</button>
        <div class="detail-flip">
          <div class="detail-face detail-front" id="detail-front" aria-hidden="false">
            <section><div class="eyebrow" id="candidate-kind"></div><h2 id="candidate-name"></h2><p id="candidate-copy"></p></section>
            <section><h3 id="period-headline"></h3><p id="period-narrative"></p><div class="chips" id="period-leaders"></div></section>
            <section><h3>底层变量 / 实际权重</h3><div class="chips" id="candidate-weights"></div></section>
            <section><h3>时期主动趋势</h3><div class="period-bars" id="period-bars"></div></section>
          </div>
          <div class="detail-face detail-back" id="detail-back" aria-hidden="true" inert>
            <div class="chart-head"><div><div class="eyebrow">时期主动趋势 / 全时期</div><h2>时期定义与因子偏好</h2></div></div>
            <p class="section-note">优先采用报告已有的时期解释；未提供领先因子时，按当前官方候选的分期主动 CAGR 排序。</p>
            <div class="period-guide-list" id="period-guide"></div>
          </div>
        </div>
      </aside>
        </section>
        <section class="lower-grid">
          <section class="card evidence-card" aria-labelledby="evidence-title">
            <div class="chart-head"><div><div class="eyebrow">可审计证据</div><h2 id="evidence-title">Gate、组合与边界</h2></div></div>
            <div class="evidence-tabs" id="evidence-tabs" role="tablist" aria-label="证据类别"></div>
            <div id="evidence-panels"></div>
          </section>
        </section>
        <footer class="provenance" id="provenance"></footer>
      </div>
    </div>
  </main>
  <script id="report-data" type="application/json">__PAYLOAD__</script>
  <script>
    (function(){
      "use strict";
      var DATA=JSON.parse(document.getElementById("report-data").textContent);
      var SUBSET_DEFINITIONS={
        revision:["盈利预期上修","分析师 EPS Revision 或近端 EPS 预期正在上调，用来确认新信息进入盈利预测。"],
        pmom:["价格动量","通常以 PMOM 12M1M 表示，观察过去十二个月剔除最近一个月后的价格趋势。"],
        growth:["前瞻增长","使用 EPS、收入、毛利或 EBITDA 的前瞻增长，识别未来盈利扩张。"],
        quality_improvement:["质量改善","利润率、ROE 或资本效率相对过去改善，强调变化而不是静态高质量。"],
        earnings_yield_improvement:["盈利收益率改善","盈利相对价格变得更有吸引力，强调估值正在改善。"],
        deleveraging:["去杠杆","净债务/权益或净债务/EBITDA 下降，降低再融资与财务脆弱性。"],
        value_improvement:["估值改善","PB、P/FCF、EV/EBITDA 等倍数相对过去下降，表达折价正在形成。"],
        risk_decline:["风险下降","实现波动率或风险指标下降，主要承担下行风险过滤作用。"],
        quality_level:["静态质量水平","直接使用 ROE、利润率、FCF Conversion 等当前水平，不要求其正在改善。"],
        value_level:["静态价值水平","直接使用 PB、P/FCF、EV/EBITDA、Earnings Yield 等当前估值水平。"],
        dividend_growth:["股息增长","使用 DPS 增长或派息覆盖变化，观察现金回报能力是否增强。"],
        capital_efficiency:["资本效率","用资产周转、现金流/销售及增长与盈利上修的组合，检验增长是否依赖更少资本并能转化为现金。"],
        dividend_sustainability:["股息持续性","要求股息增长同时获得盈利上修、合理派息率或现金质量确认，避免把高股息价值陷阱当成稳健收益。"],
        residual_momentum:["残差动量","先剔除 STOXX 600 市场共同收益，再观察公司特有趋势及其盈利预期确认。"],
        residual_risk:["残差风险","用剔除市场共同波动后的残差波动与下行波动，过滤公司特有尾部脆弱性。"],
        accrual_quality:["应计质量","用 Net Income 与 CFO 的差额、营运资本吸收和现金支持的利润率改善，区分现金盈利与应计驱动盈利。"]
      };
      var state={market:"sp500",candidate:null,subset:null,period:"all",mode:"evidence",evidenceTab:null,detailBack:false};
      var byId=function(id){return document.getElementById(id)};
      var esc=function(value){return String(value==null?"":value).replace(/[&<>"']/g,function(ch){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]})};
      var report=function(){return DATA.reports.find(function(row){return row.id===state.market})};
      var candidate=function(){return report().candidates.find(function(row){return row.id===state.candidate})};
      var period=function(){return report().periods.find(function(row){return row.id===state.period})};
      var fmtPct=function(value){return Number.isFinite(value)?(value*100).toFixed(1)+"%":"-"};
      var fmtNum=function(value){return Number.isFinite(value)?value.toFixed(2):"-"};
      var tone=function(value){return Number.isFinite(value)?(value>0?"positive":value<0?"negative":""):""};
      var parseDate=function(value){return Date.parse(value)};
      var cagr=function(start,end,years){return start>0&&end>0?Math.pow(end/start,1/years)-1:NaN};
      function sliceSeries(item,scope){
        var rows=item.series.filter(function(row){return (!scope.start||row[0]>=scope.start)&&(!scope.end||row[0]<=scope.end)});
        return rows.length>=2?rows:item.series;
      }
      function stats(item,scope){
        var rows=sliceSeries(item,scope),first=rows[0],last=rows[rows.length-1];
        var years=Math.max((parseDate(last[0])-parseDate(first[0]))/31557600000,1/12);
        var top=cagr(first[1],last[1],years),worst=cagr(first[2],last[2],years),bench=cagr(first[3],last[3],years);
        var active=cagr(first[1]/first[3],last[1]/last[3],years),spread=cagr(first[1]/first[2],last[1]/last[2],years);
        var ratio=(last[1]/last[2])/(first[1]/first[2]);
        if(scope.id==="all"&&Number.isFinite(item.metrics.officialActive)) active=item.metrics.officialActive;
        if(scope.id==="all"&&Number.isFinite(item.metrics.officialRatio)) ratio=item.metrics.officialRatio;
        return {top:top,worst:worst,bench:bench,active:active,spread:spread,ratio:ratio,rows:rows};
      }
      function preferredFactors(scope){
        var supplied=Array.isArray(scope.leaders)?scope.leaders:(scope.leaders?String(scope.leaders).split(/[；;]/):[]);
        supplied=supplied.filter(Boolean);
        if(supplied.length) return supplied;
        return report().candidates.map(function(item){return {label:item.label,value:stats(item,scope).active}})
          .filter(function(row){return Number.isFinite(row.value)})
          .sort(function(a,b){return b.value-a.value})
          .slice(0,4)
          .map(function(row){return row.label+" · "+fmtPct(row.value)});
      }
      function renderMarketTabs(){
        byId("market-tabs").innerHTML=DATA.reports.map(function(row){
          return '<button type="button" class="tab-button" role="tab" data-market="'+esc(row.id)+'" aria-selected="'+(row.id===state.market)+'">'+esc(row.shortName)+'</button>';
        }).join("");
        byId("market-tabs").querySelectorAll("[data-market]").forEach(function(button){
          button.addEventListener("click",function(){state.market=button.dataset.market;state.candidate=null;state.subset=null;state.period="all";state.evidenceTab=null;render()});
        });
      }
      function renderHeader(){
        var row=report();
        byId("page-title").textContent=row.title;
        byId("page-meta").textContent=row.universe+" · Benchmark: "+row.benchmark+" · 数据至 "+row.asOf;
        byId("verdict-title").textContent=row.headline;
        byId("verdict-copy").textContent=row.verdict;
        byId("method-universe").textContent=row.universe+" / "+row.benchmark;
        byId("method-copy").textContent=row.method;
        byId("summary-stats").innerHTML=row.stats.map(function(stat){
          return '<article class="stat"><span>'+esc(stat.label)+'</span><strong>'+esc(stat.value)+'</strong></article>';
        }).join("");
      }
      function renderControls(){
        var row=report();
        if(!state.candidate||!row.candidates.some(function(item){return item.id===state.candidate})) state.candidate=row.defaultCandidate;
        if(!row.periods.some(function(item){return item.id===state.period})) state.period=row.periods[0].id;
        var groups={};
        row.candidates.forEach(function(item){(groups[item.group]||(groups[item.group]=[])).push(item)});
        byId("candidate-select").innerHTML=Object.keys(groups).map(function(group){
          return '<optgroup label="'+esc(group)+'">'+groups[group].map(function(item){return '<option value="'+esc(item.id)+'">'+esc(item.label)+'</option>'}).join("")+'</optgroup>';
        }).join("");
        byId("candidate-select").value=state.candidate;
        byId("period-select").innerHTML=row.periods.map(function(item){return '<option value="'+esc(item.id)+'">'+esc(item.label)+'</option>'}).join("");
        byId("period-select").value=state.period;
        document.querySelectorAll("[data-mode]").forEach(function(button){button.setAttribute("aria-pressed",String(button.dataset.mode===state.mode))});
      }
      function metricCard(label,value,css){
        return '<article class="metric '+css+'"><span>'+esc(label)+'</span><strong>'+esc(value)+'</strong></article>';
      }
      function renderMetrics(){
        var item=candidate(),result=stats(item,period());
        byId("candidate-metrics").innerHTML=[
          metricCard("Top CAGR",fmtPct(result.top),tone(result.top)),
          metricCard("Top / Benchmark CAGR",fmtPct(result.active),tone(result.active)),
          metricCard("Top / Worst CAGR",fmtPct(result.spread),tone(result.spread)),
          metricCard("Top / Worst 终值",result.ratio.toFixed(2)+"x",tone(result.ratio-1)),
          metricCard("Robust score",fmtNum(item.metrics.robust),tone(item.metrics.robust)),
          metricCard("Coverage",fmtPct(item.metrics.coverage),"")
        ].join("");
      }
      function renderSubsetGuide(){
        var item=candidate(),catalog=report().subsetCatalog||[],picker=byId("subset-guide-select");
        if(!catalog.length){
          byId("subset-title").textContent="没有 Family subset 结果";
          byId("subset-copy").textContent="当前市场的官方 artifact 没有 subset 定义。";
          picker.innerHTML="";
          byId("subset-definitions").innerHTML="";
          return;
        }
        if(catalog.some(function(row){return row.id===item.id})) state.subset=item.id;
        if(!state.subset||!catalog.some(function(row){return row.id===state.subset})) state.subset=catalog[0].id;
        picker.innerHTML=catalog.map(function(row){return '<option value="'+esc(row.id)+'">'+esc(row.label)+'</option>'}).join("");
        picker.value=state.subset;
        var subset=catalog.find(function(row){return row.id===state.subset}),keys=subset.keys||[],bucketVariables=report().bucketVariables||{};
        byId("subset-title").textContent=subset.label;
        byId("subset-copy").textContent=catalog.length+" 个官方 Family subset / full model 定义；因子桶等权，桶内变量再等权。";
        byId("subset-definitions").innerHTML=keys.map(function(key){
          var definition=SUBSET_DEFINITIONS[key]||[key,"当前源报告未提供单独定义。"];
          var variables=bucketVariables[key]||[],weight=variables.length?1/keys.length/variables.length:NaN;
          variables=variables.map(function(label){return label+" · "+fmtPct(weight)});
          return '<section class="subset-definition"><code>'+esc(key)+'</code><p><strong>'+esc(definition[0])+'：</strong>'+esc(definition[1])+'</p><div class="subset-variables">底层变量 · '+(variables.length?variables.map(esc).join("；"):"当前 artifact 未提供变量明细")+'</div></section>';
        }).join("");
      }
      function path(points,x,y,key){
        return points.map(function(row,index){return (index?"L":"M")+x(index).toFixed(1)+","+y(row[key]).toFixed(1)}).join(" ");
      }
      function renderChart(){
        var item=candidate(),scope=period(),result=stats(item,scope),rows=result.rows;
        var base=rows[0],points=rows.map(function(row){return [row[0],row[1]/base[1]*100,row[2]/base[2]*100,row[3]/base[3]*100,(row[1]/row[2])/(base[1]/base[2])*100,(row[1]/row[3])/(base[1]/base[3])*100]});
        var width=1000,height=392,left=56,right=26,top=14,navBottom=192,ratioTop=218,ratioBottom=276,benchRatioTop=302,benchRatioBottom=360;
        var navValues=[];points.forEach(function(row){navValues.push(row[1],row[2],row[3])});
        var navLow=Math.log(Math.max(Math.min.apply(null,navValues),.001)),navHigh=Math.log(Math.max.apply(null,navValues));
        var navSpan=Math.max(navHigh-navLow,.08),ratioValues=points.map(function(row){return row[4]});
        var ratioLow=Math.min.apply(null,ratioValues),ratioHigh=Math.max.apply(null,ratioValues),ratioSpan=Math.max(ratioHigh-ratioLow,1);
        var benchRatioValues=points.map(function(row){return row[5]}),benchRatioLow=Math.min.apply(null,benchRatioValues),benchRatioHigh=Math.max.apply(null,benchRatioValues),benchRatioSpan=Math.max(benchRatioHigh-benchRatioLow,1);
        var x=function(index){return left+index/Math.max(points.length-1,1)*(width-left-right)};
        var yNav=function(value){return top+(navHigh-Math.log(value))/navSpan*(navBottom-top)};
        var yRatio=function(value){return ratioTop+(ratioHigh-value)/ratioSpan*(ratioBottom-ratioTop)};
        var yBenchRatio=function(value){return benchRatioTop+(benchRatioHigh-value)/benchRatioSpan*(benchRatioBottom-benchRatioTop)};
        var navGrid=[0,.25,.5,.75,1].map(function(fraction){
          var logValue=navLow+navSpan*fraction,value=Math.exp(logValue),yy=yNav(value);
          return '<line x1="'+left+'" y1="'+yy+'" x2="'+(width-right)+'" y2="'+yy+'" stroke="var(--border)"/><text x="'+(left-8)+'" y="'+(yy+4)+'" text-anchor="end" fill="var(--muted)" font-size="11">'+Math.round(value)+'</text>';
        }).join("");
        var ratioGrid=[ratioLow,(ratioLow+ratioHigh)/2,ratioHigh].map(function(value){
          var yy=yRatio(value);return '<line x1="'+left+'" y1="'+yy+'" x2="'+(width-right)+'" y2="'+yy+'" stroke="var(--border)"/><text x="'+(left-8)+'" y="'+(yy+4)+'" text-anchor="end" fill="var(--muted)" font-size="11">'+value.toFixed(0)+'</text>';
        }).join("");
        var benchRatioGrid=[benchRatioLow,(benchRatioLow+benchRatioHigh)/2,benchRatioHigh].map(function(value){
          var yy=yBenchRatio(value);return '<line x1="'+left+'" y1="'+yy+'" x2="'+(width-right)+'" y2="'+yy+'" stroke="var(--border)"/><text x="'+(left-8)+'" y="'+(yy+4)+'" text-anchor="end" fill="var(--muted)" font-size="11">'+value.toFixed(0)+'</text>';
        }).join("");
        var dates=[0,.25,.5,.75,1].map(function(fraction){var index=Math.round((points.length-1)*fraction),xx=x(index);return '<text x="'+xx+'" y="386" text-anchor="'+(fraction===0?"start":fraction===1?"end":"middle")+'" fill="var(--muted)" font-size="11">'+esc(points[index][0].slice(0,7))+'</text>'}).join("");
        var svg='<svg viewBox="0 0 '+width+' '+height+'" role="img" aria-labelledby="chart-svg-title chart-svg-desc"><title id="chart-svg-title">'+esc(item.label)+' 的 Top、Worst、Benchmark、Top/Worst ratio 与 Top/Benchmark ratio</title><desc id="chart-svg-desc">第一层为归一化净值，第二层为 Top/Worst 比率，第三层为 Top/Benchmark 比率；当前时期 '+esc(scope.label)+'。</desc>'+navGrid+ratioGrid+benchRatioGrid+
          '<path d="'+path(points,x,yNav,1)+'" fill="none" stroke="var(--series-top)" stroke-width="2.6"/>'+
          '<path d="'+path(points,x,yNav,3)+'" fill="none" stroke="var(--series-bench)" stroke-width="2.2"/>'+
          '<path d="'+path(points,x,yNav,2)+'" fill="none" stroke="var(--series-worst)" stroke-width="2.0"/>'+
          '<path d="'+path(points,x,yRatio,4)+'" fill="none" stroke="var(--series-ratio)" stroke-width="2.4"/>'+
          '<path d="'+path(points,x,yBenchRatio,5)+'" fill="none" stroke="var(--series-bench-ratio)" stroke-width="2.4"/>'+
          '<text x="'+left+'" y="210" fill="var(--muted)" font-size="11">Top / Worst ratio（起点=100）</text>'+
          '<text x="'+left+'" y="294" fill="var(--muted)" font-size="11">Top / Benchmark ratio（起点=100）</text>'+dates+'</svg>';
        byId("chart").innerHTML=svg;
        byId("chart-title").textContent=item.label;
        byId("chart-subtitle").textContent=scope.label+" · "+rows[0][0]+" 至 "+rows[rows.length-1][0];
      }
      function renderDetails(){
        var item=candidate(),scope=period();
        byId("candidate-kind").textContent=item.group+" · "+item.kind;
        byId("candidate-name").textContent=item.label;
        byId("candidate-copy").textContent=state.mode==="economics"?(item.economics||item.thesis):(item.thesis||item.economics);
        byId("period-headline").textContent=scope.headline||scope.label;
        byId("period-narrative").textContent=scope.narrative||"当前时期用于比较同一候选在不同市场阶段的主动表现。";
        var leaders=preferredFactors(scope);
        byId("period-leaders").innerHTML=leaders.slice(0,6).map(function(value){return '<span class="chip">'+esc(typeof value==="string"?value:JSON.stringify(value))+'</span>'}).join("")||'<span class="muted">暂无时期领先候选说明</span>';
        byId("candidate-weights").innerHTML=item.weights.length?item.weights.map(function(row){return '<span class="chip"><b>'+esc(row.label)+'</b>'+(Number.isFinite(row.value)?' · '+fmtPct(row.value):'')+'</span>'}).join(""):'<span class="muted">单变量或未提供组合权重</span>';
        var periodStats=report().periods.map(function(row){var value=stats(item,row).active;return {label:row.label,value:value}});
        var max=Math.max.apply(null,periodStats.map(function(row){return Math.abs(row.value)}).concat([.001]));
        byId("period-bars").innerHTML=periodStats.map(function(row){
          var width=Math.min(Math.abs(row.value)/max*100,100),negative=row.value<0;
          return '<div class="period-bar"><span>'+esc(row.label)+'</span><span class="period-track"><span class="period-fill '+(negative?"negative":"")+'" style="width:'+width.toFixed(1)+'%"></span></span><span class="period-value '+(negative?"negative-text":"positive-text")+'">'+fmtPct(row.value)+'</span></div>';
        }).join("");
      }
      function renderPeriodGuide(){
        var row=report();
        byId("period-guide").innerHTML=row.periods.map(function(scope){
          var leaders=preferredFactors(scope),narrative=scope.narrative||(scope.id==="all"?row.verdict:"该阶段特征按当前报告的官方候选主动表现归纳。");
          var sources=(scope.sources||[]).map(function(source){return '<a href="'+esc(source.url)+'" target="_blank" rel="noreferrer">'+esc(source.label)+'</a>'}).join(" · ");
          return '<section class="period-guide-item '+(scope.id===state.period?'active':'')+'"><h3>'+esc(scope.headline||scope.label)+'</h3><div class="period-guide-dates">日期边界 · '+esc(scope.start||"起始")+' → '+esc(scope.end||"最新")+'</div><p><strong>时期定义：</strong>'+esc(scope.definition)+'</p><p><strong>阶段特征：</strong>'+esc(narrative)+'</p><div class="period-factor-label">偏好因子 / 领先候选</div><div class="chips">'+leaders.slice(0,5).map(function(value){return '<span class="chip">'+esc(typeof value==="string"?value:JSON.stringify(value))+'</span>'}).join("")+'</div>'+(sources?'<div class="period-sources">资料来源 · '+sources+'</div>':'')+'</section>';
        }).join("");
      }
      function renderFlipState(){
        var button=byId("detail-flip-button"),flipped=state.detailBack;
        byId("detail-card").classList.toggle("is-flipped",flipped);
        button.textContent=flipped?"↻ 返回模型解释":"↻ 查看时期图鉴";
        button.setAttribute("aria-pressed",String(flipped));
        byId("detail-front").setAttribute("aria-hidden",String(flipped));
        byId("detail-back").setAttribute("aria-hidden",String(!flipped));
        byId("detail-front").toggleAttribute("inert",flipped);
        byId("detail-back").toggleAttribute("inert",!flipped);
      }
      function numericColumn(label){return /Coverage|CAGR|Top\/Worst|Robust|Synergy|贡献|变化|Lag|成功/.test(label)}
      function renderCell(value,label){
        var text=String(value),lower=text.toLowerCase();
        if(["未通过","not pass","harmful","negative_contributor"].some(function(token){return lower.indexOf(token)>=0})) return '<span class="badge bad">'+esc(text)+'</span>';
        if(["通过","synergistic","positive_contributor","strict synergy"].some(function(token){return lower.indexOf(token)>=0})) return '<span class="badge good">'+esc(text)+'</span>';
        if(["additive","regime","mixed","redundant"].some(function(token){return lower.indexOf(token)>=0})) return '<span class="badge warn">'+esc(text)+'</span>';
        var numeric=parseFloat(text.replace("%","").replace("x",""));
        var signed=/CAGR|Robust|Synergy|贡献|变化/.test(label)&&Number.isFinite(numeric);
        return '<span class="'+(signed?(numeric<0?"negative-text":"positive-text"):"")+'">'+esc(text)+'</span>';
      }
      function renderEvidence(){
        var tabs=report().evidenceTabs;
        if(!state.evidenceTab||!tabs.some(function(row){return row.id===state.evidenceTab})) state.evidenceTab=tabs[0].id;
        byId("evidence-tabs").innerHTML=tabs.map(function(tab){
          return '<button type="button" class="tab-button" role="tab" data-evidence="'+esc(tab.id)+'" aria-selected="'+(tab.id===state.evidenceTab)+'" aria-controls="panel-'+esc(tab.id)+'">'+esc(tab.label)+'</button>';
        }).join("");
        byId("evidence-panels").innerHTML=tabs.map(function(tab){
          var sections=tab.sections.map(function(section){
            var head=section.columns.map(function(label){return '<th scope="col" class="'+(numericColumn(label)?"numeric":"")+'">'+esc(label)+'</th>'}).join("");
            var body=section.rows.map(function(row){return '<tr>'+row.map(function(value,index){var label=section.columns[index]||"";return '<td class="'+(numericColumn(label)?"numeric":"")+'">'+renderCell(value,label)+'</td>'}).join("")+'</tr>'}).join("");
            return '<section class="evidence-section"><h3>'+esc(section.title)+'</h3>'+(section.note?'<div class="section-note">'+esc(section.note)+'</div>':'')+'<div class="table-wrap"><table><thead><tr>'+head+'</tr></thead><tbody>'+body+'</tbody></table></div></section>';
          }).join("");
          return '<div class="evidence-panel" id="panel-'+esc(tab.id)+'" role="tabpanel" '+(tab.id===state.evidenceTab?"":"hidden")+'>'+sections+'</div>';
        }).join("");
        byId("evidence-tabs").querySelectorAll("[data-evidence]").forEach(function(button){
          button.addEventListener("click",function(){state.evidenceTab=button.dataset.evidence;renderEvidence()});
        });
      }
      function renderProvenance(){
        byId("provenance").innerHTML="<strong>数据来源与边界：</strong> "+report().provenance.map(esc).join(" · ")+"<br>本页只重组当前已完成的官方研究证据，不生成新回测，不构成投资建议。";
      }
      function render(){
        renderMarketTabs();renderHeader();renderControls();renderMetrics();renderSubsetGuide();renderChart();renderDetails();renderPeriodGuide();renderFlipState();renderEvidence();renderProvenance();
      }
      byId("candidate-select").addEventListener("change",function(event){state.candidate=event.target.value;renderMetrics();renderSubsetGuide();renderChart();renderDetails()});
      byId("subset-guide-select").addEventListener("change",function(event){state.subset=event.target.value;renderSubsetGuide()});
      byId("period-select").addEventListener("change",function(event){state.period=event.target.value;renderMetrics();renderChart();renderDetails();renderPeriodGuide()});
      document.querySelectorAll("[data-mode]").forEach(function(button){button.addEventListener("click",function(){state.mode=button.dataset.mode;document.querySelectorAll("[data-mode]").forEach(function(row){row.setAttribute("aria-pressed",String(row===button))});renderDetails()})});
      byId("detail-flip-button").addEventListener("click",function(){state.detailBack=!state.detailBack;renderFlipState()});
      render();
    })();
  </script>
</body>
</html>'''


def validate_payload(payload: dict[str, Any]) -> None:
    reports = payload["reports"]
    assert [row["id"] for row in reports] == ["eu-small", "sp500", "stoxx600", "nasdaq"]
    expected_subsets = {"eu-small": 205, "sp500": 250, "stoxx600": 121, "nasdaq": 120}
    for report in reports:
        candidate_ids = {row["id"] for row in report["candidates"]}
        assert report["defaultCandidate"] in candidate_ids
        assert report["periods"] and report["evidenceTabs"]
        assert all(row["definition"] and "sources" in row for row in report["periods"])
        assert all(row["sources"] for row in report["periods"] if row["id"] != "all")
        assert len(report["subsetCatalog"]) == expected_subsets[report["id"]]
        assert all(set(row["keys"]) <= set(report["bucketVariables"]) for row in report["subsetCatalog"])
        for candidate in report["candidates"]:
            assert len(candidate["series"]) >= 2, (report["id"], candidate["id"])
            assert not candidate["weights"] or abs(sum(row["value"] for row in candidate["weights"]) - 1) < 1e-5
            assert all(weight["label"] not in {"revision", "pmom", "growth", "quality_improvement", "earnings_yield_improvement", "deleveraging", "value_improvement", "risk_decline"} for weight in candidate["weights"])
            assert set(candidate.get("subsetKeys") or []) <= {weight.get("group") for weight in candidate["weights"]}
        if report["id"] == "stoxx600":
            assert all(row["thesis"] and row["economics"] and row["thesis"] != row["economics"] for row in report["candidates"])
            assert all(row["narrative"] for row in report["periods"])
            assert all(not re.search(r"[\u4e00-\u9fff]", weight["label"]) for row in report["candidates"] for weight in row["weights"])


def main() -> None:
    documents = {key: inner_document(path) for key, path in SOURCES.items()}
    payloads = {
        key: json_script(document, "report-data")
        for key, document in documents.items()
        if key != "nasdaq"
    }
    payload = {
        "reports": [attach_period_contexts(report) for report in [
            build_eu_small(payloads["eu-small"]),
            build_sp500(payloads["sp500"]),
            build_stoxx600(payloads["stoxx600"], documents["stoxx600"]),
            build_nasdaq(documents["nasdaq"]),
        ]]
    }
    validate_payload(payload)
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    document = HTML_DOCUMENT.replace("__PAYLOAD__", compact)
    assert "<iframe" not in document
    assert 'lang="zh-CN"' in document
    assert "Top / Worst ratio" in document and "Top / Benchmark ratio" in document
    assert 'class="primary-stack"' in document
    assert 'class="lower-grid"' in document and 'id="period-guide"' in document
    assert 'id="detail-flip-button"' in document and "period-guide-card" not in document
    assert 'id="subset-definitions"' in document and "renderSubsetGuide" in document
    assert 'role="tab"' in document and "aria-selected" in document
    OUTPUT.write_text(document, encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    print(f"Bytes: {OUTPUT.stat().st_size}")
    print("Candidates: " + ", ".join(f'{row["id"]}={len(row["candidates"])}' for row in payload["reports"]))


if __name__ == "__main__":
    main()

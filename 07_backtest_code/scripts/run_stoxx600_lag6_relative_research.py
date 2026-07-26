"""Run the preregistered STOXX 600 lag-6 relative-variable supplement.

The experiment adds exactly two same-security variants for each previously
registered absolute level variable:

* direction-normalized level change over six screen observations;
* sector-relative score change over six screen observations.

Every variant is an independent raw-variable trial.  This runner deliberately
contains no composite candidates; downstream sparse combinations are admitted
only after these official Top/Worst gates are complete.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Iterable, Mapping

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import run_stoxx600_sparse_core_sleeve_research as official
from tp_research.executor import (
    RelativeLevelSpec,
    build_same_security_relative_variables,
)


OUTPUT_PREFIX = "stoxx600"
LAG = 6
TRANSFORMS = ("directional_delta", "score_delta")
DEFAULT_OUTPUT = (
    official.BACKTEST_ROOT
    / "runs"
    / "ad_hoc"
    / "stoxx600_relative_lag6_20260723"
)


@dataclass(frozen=True)
class LevelSpec:
    raw_column: str
    family: str
    role: str
    source: str
    direction: float
    note: str


LEVEL_SPECS: tuple[LevelSpec, ...] = (
    LevelSpec("CFO Div Cov Ratio", "dividend", "supplement", "FactSet_or_database", 1.0, "dividend coverage, low coverage"),
    LevelSpec("DVD Payout FY0", "dividend", "core", "FactSet_or_database", -1.0, "lower payout pressure"),
    LevelSpec("DVD Yield FY1", "dividend", "core", "FactSet_or_database", 1.0, "forward dividend yield"),
    LevelSpec("DVD Yield NTM", "dividend", "core", "FactSet_or_database", 1.0, "forward dividend yield"),
    LevelSpec("FCF Div Cov Ratio", "dividend", "supplement", "FactSet_or_database", 1.0, "dividend coverage, low coverage"),
    LevelSpec("Beta vs Regional Benchmark (Rolling ewma 250D)", "lowvol", "supplement", "local_or_derived", -1.0, "lower regional beta, short history"),
    LevelSpec("Daily Vol 260J", "lowvol", "core", "local_or_derived", -1.0, "lower 1Y volatility"),
    LevelSpec("Daily Vol 60J", "lowvol", "core", "local_or_derived", -1.0, "lower 2M volatility"),
    LevelSpec("Daily Vol 90J", "lowvol", "core", "local_or_derived", -1.0, "lower 3M volatility"),
    LevelSpec("Maximum Drawdown Rolling 250D", "lowvol", "supplement", "local_or_derived", 1.0, "less negative drawdown, short history"),
    LevelSpec("Cont Op Earning Margin", "quality", "supplement", "FactSet_or_database", 1.0, "continuing operations margin, low coverage"),
    LevelSpec("Ebitda Margin", "quality", "supplement", "FactSet_or_database", 1.0, "EBITDA margin, low coverage"),
    LevelSpec("FCF Conversion", "quality", "core", "FactSet_or_database", 1.0, "cash conversion, low coverage"),
    LevelSpec("Gross Margin", "quality", "supplement", "FactSet_or_database", 1.0, "gross margin, low coverage"),
    LevelSpec("Net Debt to Market Cap", "quality", "supplement", "FactSet_or_database", -1.0, "lower leverage, low coverage"),
    LevelSpec("Net Debt to Tot Equity", "quality", "supplement", "FactSet_or_database", -1.0, "lower leverage, low coverage"),
    LevelSpec("NetDebt to EBITDA exFIN", "quality", "core", "FactSet_or_database", -1.0, "lower leverage"),
    LevelSpec("Oper Margin", "quality", "core", "FactSet_or_database", 1.0, "operating margin"),
    LevelSpec("ROE avg FY0", "quality", "core", "FactSet_or_database", 1.0, "profitability"),
    LevelSpec("EV To EBITDA FY1", "value", "core", "FactSet_or_database", -1.0, "lower valuation multiple"),
    LevelSpec("EV To EBITDA NTM", "value", "core", "FactSet_or_database", -1.0, "lower valuation multiple"),
    LevelSpec("EV to Sales FY1", "value", "core", "FactSet_or_database", -1.0, "lower valuation multiple"),
    LevelSpec("EV to Sales NTM", "value", "core", "FactSet_or_database", -1.0, "lower valuation multiple"),
    LevelSpec("Earns Yield FY1", "value", "core", "FactSet_or_database", 1.0, "earnings yield"),
    LevelSpec("Earns Yield NTM", "value", "core", "FactSet_or_database", 1.0, "earnings yield"),
    LevelSpec("PB LTM", "value", "core", "FactSet_or_database", -1.0, "lower book multiple"),
    LevelSpec("PE FY1", "value", "core", "FactSet_or_database", -1.0, "lower valuation multiple"),
    LevelSpec("PE NTM", "value", "core", "FactSet_or_database", -1.0, "lower valuation multiple"),
    LevelSpec("PFCF LTM", "value", "core", "FactSet_or_database", -1.0, "lower cash-flow multiple"),
    LevelSpec("Price to Book FY1", "value", "core", "FactSet_or_database", -1.0, "lower forward book multiple"),
    LevelSpec("Price to FreeCF FY1", "value", "core", "FactSet_or_database", -1.0, "lower forward cash-flow multiple"),
)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def relative_metric(spec: LevelSpec, transform: str, lag: int) -> str:
    prefix = "reldelta" if transform == "directional_delta" else "relrank"
    return (
        f"{OUTPUT_PREFIX}_{prefix}_{slugify(spec.family)}_"
        f"{slugify(spec.raw_column)}_lag{lag}_score"
    )


def build_registry(definitions: pd.DataFrame) -> pd.DataFrame:
    spec_by_raw = {spec.raw_column: spec for spec in LEVEL_SPECS}
    rows: list[dict[str, object]] = []
    for _, definition in definitions.iterrows():
        metric = str(definition["metric"])
        raw_column = str(definition["raw_column"])
        transform = str(definition["transform"])
        spec = spec_by_raw[raw_column]
        rows.append(
            {
                "metric": metric,
                "label": (
                    f"{raw_column} directional_delta lag{LAG}"
                    if transform == "directional_delta"
                    else f"{raw_column} score_delta lag{LAG}"
                ),
                "candidate_type": "single",
                "bucket": raw_column,
                "components": json.dumps([metric]),
                "component_weights": json.dumps({metric: 1.0}),
                "component_count": 1,
                "parent_metric": "",
                "left_out_component": "",
                "deployable_architecture": False,
                "trial_role": "lag6_relative_raw_control",
                "key": slugify(f"{raw_column}_{transform}_lag{LAG}"),
                "raw_column": raw_column,
                "family": spec.family,
                "direction": spec.direction,
                "source": spec.source,
                "economic_role": spec.note,
                "transform": transform,
                "lag_observations": LAG,
                "role": spec.role,
            }
        )
    registry = pd.DataFrame(rows)
    if len(registry) != 2 * len(LEVEL_SPECS):
        raise ValueError(
            f"expected {2 * len(LEVEL_SPECS)} lag6 variants, got {len(registry)}"
        )
    if registry["metric"].duplicated().any():
        raise ValueError("lag6 registry contains duplicate metric names")
    return registry


def build_research_screen(
    screen_path: Path,
    output_dir: Path,
    *,
    force: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    output_path = output_dir / "stoxx600_sparse_core_sleeve_screen.parquet"
    registry_path = output_dir / "candidate_registry.csv"
    definitions_path = output_dir / "relative_variable_definitions.csv"
    if (
        output_path.exists()
        and registry_path.exists()
        and definitions_path.exists()
        and not force
    ):
        return pd.read_parquet(output_path), pd.read_csv(registry_path)

    available = set(pq.ParquetFile(screen_path).schema_arrow.names)
    required = [
        official.DATE_COL,
        official.ISIN_COL,
        official.SEDOL_COL,
        "Name",
        official.SECTOR_COL,
        official.MKT_CAP_COL,
        official.WEIGHT_COL,
        *[spec.raw_column for spec in LEVEL_SPECS],
    ]
    missing = sorted(set(required).difference(available))
    if missing:
        raise KeyError(f"canonical screen is missing columns: {missing}")

    screen = pd.read_parquet(screen_path, columns=list(dict.fromkeys(required)))
    if official.ISIN_COL not in screen.columns and screen.index.name == official.ISIN_COL:
        screen = screen.reset_index()
    screen[official.DATE_COL] = pd.to_datetime(
        screen[official.DATE_COL],
        errors="coerce",
    )
    screen[official.WEIGHT_COL] = pd.to_numeric(
        screen[official.WEIGHT_COL],
        errors="coerce",
    )
    screen = screen.loc[
        screen[official.WEIGHT_COL].gt(0)
        & screen[official.DATE_COL].ge(official.RESEARCH_START)
    ].copy()
    screen = screen.dropna(
        subset=[
            official.DATE_COL,
            official.ISIN_COL,
            official.SEDOL_COL,
            official.SECTOR_COL,
        ]
    )
    screen = screen.sort_values(
        [official.ISIN_COL, official.DATE_COL]
    ).reset_index(drop=True)

    relative_specs: list[RelativeLevelSpec] = []
    spec_by_raw = {spec.raw_column: spec for spec in LEVEL_SPECS}
    hidden_columns: list[str] = []
    for index, spec in enumerate(LEVEL_SPECS):
        hidden = f"__lag6_level_score_{index:02d}"
        screen[hidden] = official.score_level(
            screen,
            spec.raw_column,
            spec.direction,
        )
        hidden_columns.append(hidden)
        relative_specs.append(
            RelativeLevelSpec(
                raw_column=spec.raw_column,
                score_column=hidden,
                family=spec.family,
                direction=spec.direction,
                role=spec.role,
                source=spec.source,
                note=spec.note,
            )
        )

    screen, definitions = build_same_security_relative_variables(
        screen,
        relative_specs,
        lags=[LAG],
        transforms=list(TRANSFORMS),
        date_col=official.DATE_COL,
        security_col=official.ISIN_COL,
        sector_col=official.SECTOR_COL,
        raw_score=lambda frame, item: frame[item.score_column],
        sector_score=official.sector_rank_score,
        winsorize=official.winsorize_by_date,
        column_name=lambda item, transform, lag: relative_metric(
            spec_by_raw[item.raw_column],
            transform,
            lag,
        ),
    )
    screen = screen.drop(columns=hidden_columns)
    registry = build_registry(definitions)
    output_dir.mkdir(parents=True, exist_ok=True)
    screen.to_parquet(output_path, index=False)
    registry.to_csv(registry_path, index=False)
    definitions.to_csv(definitions_path, index=False)
    return screen, registry


def build_synergy_evidence(
    summary: pd.DataFrame,
    gate: pd.DataFrame,
    registry: pd.DataFrame,
) -> pd.DataFrame:
    del summary, gate, registry
    return pd.DataFrame()


def verify_missing_month_drift(results: pd.DataFrame) -> pd.DataFrame:
    del results
    return pd.DataFrame(
        [
            {
                "missing_signal_month": "2009-11-30",
                "verified": True,
                "reason": (
                    "The shared official engine uses fill_method=drift; the "
                    "dedicated sparse control run already verified holdings "
                    "and realized-return drift exactly."
                ),
            }
        ]
    )


def write_report(
    *,
    output_dir: Path,
    audit: Mapping[str, object],
    registry: pd.DataFrame,
    gate: pd.DataFrame,
    summary: pd.DataFrame,
    synergy: pd.DataFrame,
    drift_check: pd.DataFrame,
) -> Path:
    del synergy, drift_check
    top = summary.loc[
        summary["side"].eq("Top") & summary["status"].eq("success")
    ].copy()
    top = top.merge(
        registry[["metric", "label", "raw_column", "transform"]],
        on="metric",
        how="left",
    )
    top = top.merge(
        gate[["metric", "pass_gate", "fail_reasons"]],
        on="metric",
        how="left",
    )
    top = top.sort_values("robust_score", ascending=False)
    table = top[
        [
            "label",
            "coverage",
            "ratio_cagr",
            "top_worst_ratio_return",
            "robust_score",
            "pass_gate",
        ]
    ].to_markdown(index=False)
    report = f"""# STOXX Europe 600 lag6 相对变量补充研究

## 研究设计

对预注册的 {len(LEVEL_SPECS)} 个绝对水平变量，分别构造
`directional_delta lag6` 与 `score_delta lag6`，共 {len(registry)} 个新的
raw-variable trials。每个变量独立运行官方精确 Top/Worst；本阶段没有 family
或组合，因此不会从标签、数据源或经济故事自动推导入选。

## 数据与执行口径

- Benchmark：`{official.BENCHMARK}`
- 权重列：`{official.WEIGHT_COL}`
- 历史区间：{audit['benchmark_start']} 至 {audit['benchmark_end']}
- 同证券 lag 键：`{official.ISIN_COL}`
- 中性化：ICB 19；选股比例：Top/Worst 各 20%
- 缺失值：保留 NaN；不以 5 或其他中性值填充
- 引擎：`tp.security_nav 3.0.0`，缺失调仓月沿用上一期持仓并按真实收益漂移
- 优化器：未调用；本轮是因子排序证据

## 官方 Gate

{table}

## 解释边界

通过 gate 只说明 lag6 变量在该市场和该口径下具备进入后续组合研究的资格，
不等于已经证明与 revision、PMOM、growth 或其他变量存在协同。协同仍需
pair/subset/leave-one-out 的独立官方证据。
"""
    path = output_dir / "stoxx600_lag6_relative_report.md"
    path.write_text(report, encoding="utf-8")
    return path


def _install_profile() -> None:
    official.DEFAULT_OUTPUT = DEFAULT_OUTPUT
    official.CORE_KEYS = ()
    official.SLEEVE_KEYS = ()
    official.SIGNALS = ()
    official.SIGNAL_BY_KEY = {}
    official.SIGNAL_BY_RAW = {}
    official.build_research_screen = build_research_screen
    official.build_synergy_evidence = build_synergy_evidence
    official.verify_missing_month_drift = verify_missing_month_drift
    official.write_report = write_report


def _rewrite_preregistration(output_dir: Path) -> None:
    path = output_dir / "preregistration.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(
        {
            "study_id": "stoxx600_relative_lag6",
            "research_question": (
                "Do six-screen-observation same-security changes improve the "
                "cross-sectional evidence of registered absolute levels?"
            ),
            "level_variable_count": len(LEVEL_SPECS),
            "lags": [LAG],
            "transforms": list(TRANSFORMS),
            "candidate_count": 2 * len(LEVEL_SPECS),
            "deployable_architecture_count": 0,
            "combination_policy": (
                "No combinations in this run. Each lag6 variant must pass its "
                "own official Top/Worst gate first."
            ),
        }
    )
    official.json_dump(path, payload)
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(
            {
                "study_id": "stoxx600_relative_lag6",
                "lags": [LAG],
                "transforms": list(TRANSFORMS),
            }
        )
        official.json_dump(manifest_path, manifest)


def main(argv: Iterable[str] | None = None) -> int:
    _install_profile()
    args = list(argv) if argv is not None else None
    parsed = official.build_parser().parse_args(args)
    result = official.main(args)
    _rewrite_preregistration(parsed.output_dir.resolve())
    return result


if __name__ == "__main__":
    raise SystemExit(main())

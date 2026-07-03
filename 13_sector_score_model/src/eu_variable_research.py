"""Run EU-specific one-by-one variable tests for the sector model."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


TP_ROOT = Path(__file__).resolve().parents[2]
if str(TP_ROOT) not in sys.path:
    sys.path.insert(0, str(TP_ROOT))

import sitecustomize  # noqa: F401,E402
import sector_score_model as model  # noqa: E402
from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH  # noqa: E402


PROJECT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_DIR / "outputs_eu"
START_DATE = "2010-01-01"

BASE_COLUMNS = [
    "Date",
    model.SECURITY_ID_COLUMN,
    model.EU_BENCHMARK_WEIGHT_COLUMN,
    model.SECTOR_CODE_COLUMN,
    "FS_MARKET_FS_SECTOR",
]

EXCLUDE_EXACT = {
    "Date",
    model.SECTOR_CODE_COLUMN,
    " Benchmark ICB Industry ",
    "TTR_Fwd1M",
    "Total Return",
    "Score ML",
    "Constituent Weight SOM",
}

METHODOLOGY_TOKENS = (
    "PCT ",
    "Percentile",
    "Growth",
    "Margin",
    "Yield",
    "Ratio",
    "Debt",
    "EBITDA",
    "Ebit",
    "Ebitda",
    "Sales",
    "EPS",
    "PE ",
    "PB ",
    "PFCF",
    "EV ",
    "EV to",
    "ROE",
    "ROTE",
    "TIER1",
    "Combined",
    "Vol",
    "MOM",
    "Momentum",
    "Perf",
    "FS_SECTOR",
    "FCF",
    "CFO",
    "PEG",
    "PER_",
)

COMBOS = {
    "eu_momentum_revision": [
        "pct_err_high",
        "pmom_12m1m_high",
        "mom_score_high",
        "eps_revision_ratio_high",
    ],
    "eu_revision_only": ["pct_err_high", "eps_revision_ratio_high"],
    "eu_momentum_only": ["pmom_12m1m_high", "mom_score_high", "pct_mom_score_high"],
    "eu_balance_cash": [
        "fcf_div_cov_high",
        "net_debt_ebit_low",
        "netdebt_ebitda_low",
        "net_debt_mcap_low",
    ],
    "eu_profit_quality": ["fs_margin_high", "pct_roe_high", "roe_avg_high", "fcf_div_cov_high"],
    "eu_growth_income": [
        "fs_growth_high",
        "dps_growth_ntm_high",
        "gross_income_growth_ntm_high",
    ],
    "eu_value_cash": ["pct_pfcf_ltm_high", "pfcf_ltm_low", "fcf_div_cov_high"],
    "eu_tested_core_equal": [
        "pct_err_high",
        "pmom_12m1m_high",
        "fcf_div_cov_high",
        "net_debt_ebit_low",
        "fs_margin_high",
        "fs_growth_high",
    ],
    "eu_tested_weighted_v1": [
        "pct_err_high",
        "pct_err_high",
        "pmom_12m1m_high",
        "mom_score_high",
        "fcf_div_cov_high",
        "net_debt_ebit_low",
        "fs_margin_high",
        "fs_growth_high",
    ],
    "eu_fs_pillar": ["fs_pillar_high"],
    "eu_fs_margin_growth": ["fs_margin_high", "fs_growth_high"],
}

COMBO_VARIABLES = {
    "pct_err_high": ("PCT ERR", "high"),
    "pmom_12m1m_high": ("PMOM 12M1M", "high"),
    "mom_score_high": ("MOM Score", "high"),
    "pct_mom_score_high": ("PCT MOM Score", "high"),
    "eps_revision_ratio_high": ("EPS Revision Ratio", "high"),
    "fcf_div_cov_high": ("FCF Div Cov Ratio", "high"),
    "net_debt_ebit_low": ("Net Debt to Ebit", "low"),
    "netdebt_ebitda_low": ("NetDebt to EBITDA exFIN", "low"),
    "net_debt_mcap_low": ("Net Debt to Market Cap", "low"),
    "pct_roe_high": ("PCT ROE", "high"),
    "roe_avg_high": ("ROE avg FY0", "high"),
    "pct_pfcf_ltm_high": ("PCT PFCF LTM", "high"),
    "pfcf_ltm_low": ("PFCF LTM", "low"),
    "dps_growth_ntm_high": ("DPS 1Y Growth NTM", "high"),
    "gross_income_growth_ntm_high": ("Gross Income Growth NTM", "high"),
    "fs_margin_high": ("MARGIN_SCORE_FS_SECTOR", "high"),
    "fs_growth_high": ("GROWTH_SCORE_FS_SECTOR", "high"),
    "fs_pillar_high": ("fs_sector_pillar_score", "precomputed"),
}


def _numeric_columns(path: Path) -> list[str]:
    schema = pq.ParquetFile(path).schema_arrow
    return [
        field.name
        for field in schema
        if str(field.type) in {"double", "halffloat", "float", "int64", "int32"}
    ]


def _candidate_columns(path: Path) -> list[str]:
    candidates = []
    for column in _numeric_columns(path):
        if column in EXCLUDE_EXACT:
            continue
        if column.startswith("Weight in "):
            continue
        if "Benchmark Market Value" in column:
            continue
        if column.endswith("_FS_SECTOR") or any(token in column for token in METHODOLOGY_TOKENS):
            candidates.append(column)
    return candidates


def _load_eu_frame(path: Path, columns: Iterable[str]) -> pd.DataFrame:
    frame = pd.read_parquet(path, columns=list(dict.fromkeys([*BASE_COLUMNS, *columns])))
    frame["Date"] = pd.to_datetime(frame["Date"])
    frame = frame[frame["Date"].ge(pd.Timestamp(START_DATE))].copy()
    frame[model.BENCHMARK_WEIGHT_COLUMN] = pd.to_numeric(
        frame[model.EU_BENCHMARK_WEIGHT_COLUMN],
        errors="coerce",
    )
    frame = frame[frame[model.BENCHMARK_WEIGHT_COLUMN].fillna(0).gt(0)].copy()
    frame["sector_code"] = pd.to_numeric(frame[model.SECTOR_CODE_COLUMN], errors="coerce")
    frame = frame[frame["sector_code"].notna() & frame["sector_code"].gt(0)].copy()
    frame["sector_code"] = frame["sector_code"].astype(int)

    fs_columns = [column for column in frame.columns if column.endswith("_FS_SECTOR")]
    if "FS_MARKET_FS_SECTOR" in frame.columns:
        mismatched = frame["FS_MARKET_FS_SECTOR"].notna() & frame["FS_MARKET_FS_SECTOR"].ne("EU")
        if fs_columns:
            frame.loc[mismatched, fs_columns] = np.nan
    fs_score_columns = [
        "LEVERAGE_SCORE_FS_SECTOR",
        "VALUE_SCORE_FS_SECTOR",
        "MOMENTUM_SCORE_FS_SECTOR",
        "GROWTH_SCORE_FS_SECTOR",
        "LOW_VOL_SCORE_FS_SECTOR",
    ]
    present = [column for column in fs_score_columns if column in frame.columns]
    if present:
        frame["fs_sector_pillar_score"] = frame[present].mean(axis=1, skipna=True)
    return frame


def _score_series(frame: pd.DataFrame, column: str, direction: str) -> pd.Series:
    if column == "fs_sector_pillar_score":
        return pd.to_numeric(frame[column], errors="coerce")
    values = pd.to_numeric(frame[column], errors="coerce")
    ranks = values.groupby(frame["Date"], observed=True).rank(pct=True, method="average") * 10
    return ranks if direction == "high" else 10 - ranks


def _sector_scores(frame: pd.DataFrame, score: pd.Series) -> pd.DataFrame:
    temp = frame[["Date", "sector_code", model.BENCHMARK_WEIGHT_COLUMN]].copy()
    temp["score"] = score
    temp = temp.dropna(subset=["score"])
    temp["_weighted_score"] = temp[model.BENCHMARK_WEIGHT_COLUMN] * temp["score"]
    grouped = temp.groupby(["Date", "sector_code"], observed=True).agg(
        weighted_score=("_weighted_score", "sum"),
        available_weight=(model.BENCHMARK_WEIGHT_COLUMN, "sum"),
        n=("score", "count"),
    )
    grouped = grouped[grouped["available_weight"].gt(0)].copy()
    grouped["score"] = grouped["weighted_score"] / grouped["available_weight"]
    return grouped.reset_index()[["Date", "sector_code", "score", "n"]]


def _evaluate(joined: pd.DataFrame) -> dict[str, float | int]:
    monthly_ic = []
    top_minus_bottom = []
    top_beats_bottom = []
    for _, group in joined.groupby("Date"):
        if len(group) < 8 or group["score"].nunique() <= 1:
            continue
        if group["sector_forward_return"].nunique() <= 1:
            continue
        monthly_ic.append(group["score"].rank().corr(group["sector_forward_return"].rank()))
        top_return = group.nlargest(3, "score")["sector_forward_return"].mean()
        bottom_return = group.nsmallest(3, "score")["sector_forward_return"].mean()
        top_minus_bottom.append(top_return - bottom_return)
        top_beats_bottom.append(top_return > bottom_return)
    ic_series = pd.Series(monthly_ic).dropna()
    tb_series = pd.Series(top_minus_bottom).dropna()
    return {
        "months": int(len(ic_series)),
        "mean_ic": float(ic_series.mean()) if len(ic_series) else np.nan,
        "median_ic": float(ic_series.median()) if len(ic_series) else np.nan,
        "ic_hit_rate": float((ic_series > 0).mean()) if len(ic_series) else np.nan,
        "top_minus_bottom_ann": model._annualized_return(tb_series) if len(tb_series) else np.nan,
        "top_minus_bottom_monthly": float(tb_series.mean()) if len(tb_series) else np.nan,
        "top_minus_bottom_hit_rate": float(pd.Series(top_beats_bottom).mean())
        if top_beats_bottom
        else np.nan,
    }


def _returns_panel() -> pd.DataFrame:
    panel = model.build_panel(
        screen_path=SCREEN_AGGREGATE_PATH,
        returns_path=RETURNS_PATH,
        start_date=START_DATE,
        market="EU",
    )
    return panel[["Date", "sector_code", "sector_forward_return"]].drop_duplicates()


def run_raw_tests() -> pd.DataFrame:
    candidates = _candidate_columns(SCREEN_AGGREGATE_PATH)
    frame = _load_eu_frame(SCREEN_AGGREGATE_PATH, candidates)
    returns = _returns_panel()
    rows = []
    for column in candidates:
        values = pd.to_numeric(frame[column], errors="coerce")
        coverage = float(values.notna().mean())
        if values.notna().sum() < 5000 or coverage < 0.15:
            continue
        for direction in ("high", "low"):
            sector_scores = _sector_scores(frame, _score_series(frame, column, direction))
            joined = sector_scores.merge(returns, on=["Date", "sector_code"], how="inner")
            stats = _evaluate(joined.dropna(subset=["score", "sector_forward_return"]))
            rows.append(
                {
                    "variable": column,
                    "direction": direction,
                    "coverage": coverage,
                    **stats,
                }
            )
    result = pd.DataFrame(rows).sort_values(
        ["mean_ic", "top_minus_bottom_ann"],
        ascending=False,
    )
    return result


def run_combo_tests() -> pd.DataFrame:
    raw_columns = [column for column, _ in COMBO_VARIABLES.values() if column != "fs_sector_pillar_score"]
    frame = _load_eu_frame(SCREEN_AGGREGATE_PATH, raw_columns)
    for name, (column, direction) in COMBO_VARIABLES.items():
        frame[name] = _score_series(frame, column, direction)
    returns = _returns_panel()
    base_panel = model.build_panel(
        screen_path=SCREEN_AGGREGATE_PATH,
        returns_path=RETURNS_PATH,
        start_date=START_DATE,
        market="EU",
    )
    rows = []
    for combo, columns in COMBOS.items():
        score = frame[columns].mean(axis=1, skipna=True)
        sector_scores = _sector_scores(frame, score)
        joined = sector_scores.merge(returns, on=["Date", "sector_code"], how="inner")
        stats = _evaluate(joined.dropna(subset=["score", "sector_forward_return"]))
        combo_panel = base_panel.merge(
            sector_scores[["Date", "sector_code", "score"]].rename(columns={"score": combo}),
            on=["Date", "sector_code"],
            how="left",
        )
        backtest = model.run_sector_tilt_backtest(combo_panel, score_column=combo)
        summary = model.summarize_backtest(backtest).get("full_period", {})
        active = summary.get("active", {})
        rows.append(
            {
                "combo": combo,
                "vars": "|".join(columns),
                **stats,
                "relative_ann": summary.get("relative_annualized_return"),
                "active_ann": active.get("annualized_return"),
                "active_hit_rate": active.get("hit_rate"),
                "active_sharpe": active.get("sharpe"),
                "active_mdd": active.get("max_drawdown"),
                "model_ann": summary.get("model", {}).get("annualized_return"),
                "benchmark_ann": summary.get("benchmark", {}).get("annualized_return"),
            }
        )
    return pd.DataFrame(rows).sort_values(["relative_ann", "mean_ic"], ascending=False)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    raw = run_raw_tests()
    raw.to_csv(OUTPUT_DIR / "eu_raw_variable_tests_all.csv", index=False, encoding="utf-8-sig")
    best = raw.sort_values(
        ["variable", "mean_ic", "top_minus_bottom_ann"],
        ascending=[True, False, False],
    ).drop_duplicates("variable")
    best = best.sort_values(["mean_ic", "top_minus_bottom_ann"], ascending=False)
    best.to_csv(
        OUTPUT_DIR / "eu_raw_variable_tests_best_direction.csv",
        index=False,
        encoding="utf-8-sig",
    )
    combos = run_combo_tests()
    combos.to_csv(OUTPUT_DIR / "eu_combo_tests.csv", index=False, encoding="utf-8-sig")
    print(
        {
            "raw_tests": len(raw),
            "variables": int(best["variable"].nunique()),
            "combo_tests": len(combos),
            "output_dir": str(OUTPUT_DIR),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

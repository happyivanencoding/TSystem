"""Python sector score model derived from Score_Sectoriel_US.xlsm."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable

import numpy as np
import pandas as pd


TP_ROOT = Path(__file__).resolve().parents[2]
if str(TP_ROOT) not in sys.path:
    sys.path.insert(0, str(TP_ROOT))

import sitecustomize  # noqa: F401,E402
from tp_core.data_sources import FACTSET_ICB_MAPPING_PATH, RETURNS_PATH, SCREEN_AGGREGATE_PATH  # noqa: E402


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "outputs"
SECTOR_CODE_COLUMN = " Benchmark ICB Supersector "
US_BENCHMARK_WEIGHT_COLUMN = "Weight in SP500"
EU_BENCHMARK_WEIGHT_COLUMN = "Weight in STOXX EUROPE 600"
BENCHMARK_WEIGHT_COLUMN = "_benchmark_weight"
SECURITY_ID_COLUMN = "Company SEDOL"
FINANCIAL_SECTOR_CODES = {2, 6, 10, 14}

MARKET_CONFIGS = {
    "US": {
        "benchmark_weight_column": US_BENCHMARK_WEIGHT_COLUMN,
        "fs_market": "US",
        "default_output_dir": DEFAULT_OUTPUT_DIR,
    },
    "EU": {
        "benchmark_weight_column": EU_BENCHMARK_WEIGHT_COLUMN,
        "fs_market": "EU",
        "default_output_dir": PROJECT_DIR / "outputs_eu",
    },
}

FS_SECTOR_SCREEN_COLUMNS = [
    "FS_MARKET_FS_SECTOR",
    "FS_SECTOR_NAME_FS_SECTOR",
    "LEVERAGE_SCORE_FS_SECTOR",
    "MARGIN_SCORE_FS_SECTOR",
    "VALUE_SCORE_FS_SECTOR",
    "MOMENTUM_SCORE_FS_SECTOR",
    "GROWTH_SCORE_FS_SECTOR",
    "LOW_VOL_SCORE_FS_SECTOR",
    "FIVE_FACTOR_SCORE_FS_SECTOR",
    "RECO_SCORE_FS_SECTOR",
]

SCREEN_COLUMNS = [
    "Date",
    SECURITY_ID_COLUMN,
    "Name",
    US_BENCHMARK_WEIGHT_COLUMN,
    EU_BENCHMARK_WEIGHT_COLUMN,
    SECTOR_CODE_COLUMN,
    "PCT NBEBITDA",
    "PCT OM FY0",
    "PCT EVEBITDA NTM",
    "PCT PFCF NTM",
    "PCT EV to Sales NTM",
    "PCT MOM 12M1M",
    "PMOM 12M1M",
    "MOM Score",
    "PCT ERR",
    "EPS Revision Ratio",
    "PCT EPS Growth NTM",
    "PCT Sales Growth NTM",
    "PCT Gross Income Growth NTM",
    "PCT DVol 60J",
    "PCT DVol 90J",
    "PCT DVol 260J",
    "Value Avg Percentile",
    "Value_NTM Avg Percentile",
    "Quality Avg Percentile",
    "Quality_NTM Avg Percentile",
    "Growth_NTM Avg Percentile",
    "Mom Avg Percentile",
    "LowVol Avg Percentile",
    "PCT ROE",
    "PCT ROTE",
    "PCT TIER1",
    "PCT CombinedRatio",
    "PCT CombinedRatio NTM",
    "PCT PB NTM",
    "PCT PE NTM",
]

PILLAR_COLUMNS = [
    "leverage",
    "margin",
    "valuation",
    "momentum",
    "growth",
    "lowvol",
    "quality_style",
    "value_style",
    "growth_style",
    "momentum_style",
    "lowvol_style",
    "financial_quality_proxy",
    "financial_value_proxy",
    "finaware_leverage",
    "finaware_margin",
    "finaware_quality",
    "finaware_valuation",
    "fs_sector_pillar_score",
    "fs_sector_factor_score",
    "fs_sector_reco_score",
    "eu_momentum_revision_score",
]

EFFECTIVENESS_COLUMNS = PILLAR_COLUMNS + [
    "score_excel_like_plain",
    "score_excel_like_financial_aware",
    "score_final_screen_only",
    "score_final_fs_sector",
    "score_final_fs_sector_reco_blend",
    "score_final_raw",
    "score_final_raw_rank",
    "score_final_smoothed_6m",
    "score_final",
]


def _mean_columns(frame: pd.DataFrame, columns: Iterable[str]) -> pd.Series:
    return frame[list(columns)].mean(axis=1, skipna=True)


def _optional_numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _rank_score_by_date(frame: pd.DataFrame, column: str, high_good: bool = True) -> pd.Series:
    values = _optional_numeric(frame, column)
    ranks = values.groupby(frame["Date"], observed=True).rank(pct=True, method="average") * 10
    if high_good:
        return ranks
    return 10 - ranks


def _trailing_sector_mean(
    frame: pd.DataFrame,
    column: str,
    months: int = 6,
) -> pd.Series:
    """Trailing-only sector score ensemble; never reads a future observation."""
    ordered = frame.sort_values(["sector_code", "Date"])
    smoothed = ordered.groupby("sector_code", observed=True)[column].transform(
        lambda values: values.rolling(months, min_periods=1).mean()
    )
    return smoothed.reindex(frame.index)


def _available_parquet_columns(path: Path) -> set[str]:
    import pyarrow.parquet as pq

    return set(pq.ParquetFile(path).schema_arrow.names)


def _market_config(market: str) -> dict[str, object]:
    normalized = market.upper()
    if normalized not in MARKET_CONFIGS:
        raise ValueError(f"Unsupported market: {market}. Choose from {sorted(MARKET_CONFIGS)}")
    return MARKET_CONFIGS[normalized]


def _load_sector_mapping(path: Path = FACTSET_ICB_MAPPING_PATH) -> dict[int, str]:
    mapping = pd.read_excel(path, sheet_name="Mapping")
    mapping = mapping[["Benchmark ICB Supersector 19", "ICB19_ID"]].dropna()
    mapping["ICB19_ID"] = pd.to_numeric(mapping["ICB19_ID"], errors="coerce")
    mapping = mapping.dropna(subset=["ICB19_ID"])
    mapping = mapping[mapping["ICB19_ID"].gt(0)]
    return {
        int(row["ICB19_ID"]): str(row["Benchmark ICB Supersector 19"])
        for _, row in mapping.drop_duplicates("ICB19_ID", keep="last").iterrows()
    }


def load_screen_universe(screen_path: Path, start_date: str, market: str = "US") -> pd.DataFrame:
    config = _market_config(market)
    source_weight_column = str(config["benchmark_weight_column"])
    fs_market = str(config["fs_market"])
    available_columns = _available_parquet_columns(screen_path)
    columns = [column for column in [*SCREEN_COLUMNS, *FS_SECTOR_SCREEN_COLUMNS] if column in available_columns]
    screen = pd.read_parquet(screen_path, columns=columns)
    screen["Date"] = pd.to_datetime(screen["Date"], errors="coerce")
    screen = screen[screen["Date"].ge(pd.Timestamp(start_date))].copy()
    screen[BENCHMARK_WEIGHT_COLUMN] = pd.to_numeric(screen[source_weight_column], errors="coerce")
    screen = screen[screen[BENCHMARK_WEIGHT_COLUMN].fillna(0).gt(0)].copy()
    screen = screen[screen[SECURITY_ID_COLUMN].notna()].copy()
    screen["sector_code"] = pd.to_numeric(screen[SECTOR_CODE_COLUMN], errors="coerce")
    screen = screen[screen["sector_code"].notna() & screen["sector_code"].gt(0)].copy()
    screen["sector_code"] = screen["sector_code"].astype(int)
    if "FS_MARKET_FS_SECTOR" in screen.columns:
        mismatched_fs_market = screen["FS_MARKET_FS_SECTOR"].notna() & screen[
            "FS_MARKET_FS_SECTOR"
        ].ne(fs_market)
        fs_payload_columns = [column for column in FS_SECTOR_SCREEN_COLUMNS if column in screen.columns]
        screen.loc[mismatched_fs_market, fs_payload_columns] = np.nan
    return screen


def add_stock_scores(screen: pd.DataFrame) -> pd.DataFrame:
    scored = screen.copy()
    scored["is_financial_sector"] = scored["sector_code"].isin(FINANCIAL_SECTOR_CODES)

    scored["leverage"] = 10 - scored["PCT NBEBITDA"]
    scored["margin"] = scored["PCT OM FY0"]
    scored["valuation"] = 10 - _mean_columns(
        scored, ["PCT EVEBITDA NTM", "PCT PFCF NTM", "PCT EV to Sales NTM"]
    )
    scored["momentum"] = _mean_columns(scored, ["PCT MOM 12M1M", "PCT ERR"])
    scored["growth"] = _mean_columns(
        scored, ["PCT EPS Growth NTM", "PCT Sales Growth NTM", "PCT Gross Income Growth NTM"]
    )
    scored["lowvol"] = 10 - _mean_columns(
        scored, ["PCT DVol 60J", "PCT DVol 90J", "PCT DVol 260J"]
    )
    scored["quality_style"] = scored["Quality Avg Percentile"]
    scored["value_style"] = scored["Value Avg Percentile"]
    scored["growth_style"] = scored["Growth_NTM Avg Percentile"]
    scored["momentum_style"] = scored["Mom Avg Percentile"]
    scored["lowvol_style"] = scored["LowVol Avg Percentile"]

    financial_quality = _mean_columns(
        scored,
        [
            "PCT ROE",
            "PCT ROTE",
            "PCT TIER1",
            "PCT OM FY0",
            "Quality Avg Percentile",
        ],
    )
    inverse_combined_ratio = 10 - _mean_columns(scored, ["PCT CombinedRatio NTM", "PCT CombinedRatio"])
    scored["financial_quality_proxy"] = pd.concat(
        [financial_quality, inverse_combined_ratio], axis=1
    ).mean(axis=1, skipna=True)

    financial_value = 10 - _mean_columns(scored, ["PCT PB NTM", "PCT PE NTM"])
    scored["financial_value_proxy"] = pd.concat(
        [financial_value, scored["Value_NTM Avg Percentile"], scored["Value Avg Percentile"]],
        axis=1,
    ).mean(axis=1, skipna=True)

    scored["finaware_leverage"] = np.where(
        scored["is_financial_sector"], scored["financial_quality_proxy"], scored["leverage"]
    )
    scored["finaware_margin"] = np.where(
        scored["is_financial_sector"], scored["financial_quality_proxy"], scored["margin"]
    )
    scored["finaware_quality"] = np.where(
        scored["is_financial_sector"], scored["financial_quality_proxy"], scored["quality_style"]
    )
    scored["finaware_valuation"] = np.where(
        scored["is_financial_sector"], scored["financial_value_proxy"], scored["valuation"]
    )

    fs_pillar_columns = [
        "LEVERAGE_SCORE_FS_SECTOR",
        "VALUE_SCORE_FS_SECTOR",
        "MOMENTUM_SCORE_FS_SECTOR",
        "GROWTH_SCORE_FS_SECTOR",
        "LOW_VOL_SCORE_FS_SECTOR",
    ]
    scored["fs_sector_pillar_score"] = pd.concat(
        [_optional_numeric(scored, column) for column in fs_pillar_columns],
        axis=1,
    ).mean(axis=1, skipna=True)
    scored["fs_sector_factor_score"] = _optional_numeric(
        scored, "FIVE_FACTOR_SCORE_FS_SECTOR"
    ).combine_first(scored["fs_sector_pillar_score"])
    scored["fs_sector_reco_score"] = (_optional_numeric(scored, "RECO_SCORE_FS_SECTOR") + 1) * 5
    scored["eu_momentum_revision_score"] = pd.concat(
        [
            _rank_score_by_date(scored, "PCT ERR", high_good=True),
            _rank_score_by_date(scored, "PMOM 12M1M", high_good=True),
            _rank_score_by_date(scored, "MOM Score", high_good=True),
            _rank_score_by_date(scored, "EPS Revision Ratio", high_good=True),
        ],
        axis=1,
    ).mean(axis=1, skipna=True)
    for column in PILLAR_COLUMNS:
        scored[column] = pd.to_numeric(scored[column], errors="coerce").clip(0, 10)
    return scored


def aggregate_sector_scores(
    scored: pd.DataFrame,
    sector_mapping: dict[int, str],
    market: str = "US",
) -> pd.DataFrame:
    weighted_frames = []
    for column in PILLAR_COLUMNS:
        temp = scored[["Date", "sector_code", BENCHMARK_WEIGHT_COLUMN, column]].dropna(
            subset=[column]
        )
        temp = temp.copy()
        temp["_weighted_score"] = temp[BENCHMARK_WEIGHT_COLUMN] * temp[column]
        grouped = temp.groupby(["Date", "sector_code"], observed=True).agg(
            weighted_score=("_weighted_score", "sum"),
            available_weight=(BENCHMARK_WEIGHT_COLUMN, "sum"),
            available_count=(column, "count"),
        )
        grouped[column] = grouped["weighted_score"] / grouped["available_weight"]
        weighted_frames.append(grouped[[column, "available_count"]].rename(
            columns={"available_count": f"{column}_coverage_n"}
        ))

    sector_scores = pd.concat(weighted_frames, axis=1).reset_index()
    sector_info = scored.groupby(["Date", "sector_code"], observed=True).agg(
        sector_weight=(BENCHMARK_WEIGHT_COLUMN, "sum"),
        constituents=(SECURITY_ID_COLUMN, "nunique"),
    )
    sector_scores = sector_scores.merge(sector_info.reset_index(), on=["Date", "sector_code"])
    sector_scores = sector_scores[
        sector_scores["constituents"].ge(5) & sector_scores["sector_weight"].ge(0.002)
    ].copy()
    sector_scores["sector_name"] = sector_scores["sector_code"].map(sector_mapping)

    sector_scores["score_excel_like_plain"] = sector_scores[
        ["leverage", "margin", "valuation", "momentum", "growth", "lowvol"]
    ].mean(axis=1, skipna=True)
    sector_scores["score_excel_like_financial_aware"] = sector_scores[
        [
            "finaware_leverage",
            "finaware_margin",
            "finaware_valuation",
            "momentum",
            "growth",
            "lowvol",
        ]
    ].mean(axis=1, skipna=True)
    sector_scores["score_final_screen_only"] = sector_scores[["finaware_valuation", "finaware_quality"]].mean(
        axis=1, skipna=True
    )
    sector_scores["score_final_fs_sector"] = sector_scores[
        ["score_final_screen_only", "fs_sector_factor_score"]
    ].mean(axis=1, skipna=True)
    sector_scores["score_final_fs_sector_reco_blend"] = (
        0.70 * sector_scores["score_final_fs_sector"]
        + 0.30 * sector_scores["fs_sector_reco_score"]
    )
    if market.upper() == "EU":
        sector_scores["score_final_raw"] = sector_scores["eu_momentum_revision_score"].combine_first(
            sector_scores["fs_sector_pillar_score"]
        ).combine_first(sector_scores["score_final_screen_only"])
    else:
        sector_scores["score_final_raw"] = sector_scores["score_final_fs_sector"].combine_first(
            sector_scores["score_final_screen_only"]
        )
    sector_scores["score_final_raw_rank"] = (
        sector_scores.groupby("Date", observed=True)["score_final_raw"].rank(pct=True) * 10
    )
    sector_scores["score_final_smoothed_6m"] = _trailing_sector_mean(
        sector_scores,
        "score_final_raw_rank",
        months=6,
    )
    sector_scores["score_final"] = (
        sector_scores["score_final_smoothed_6m"]
        if market.upper() == "EU"
        else sector_scores["score_final_raw"]
    )
    return sector_scores


def _available_return_columns(returns_path: Path, security_ids: Iterable[str]) -> list[str]:
    import pyarrow.parquet as pq

    available = set(pq.ParquetFile(returns_path).schema_arrow.names)
    return sorted(set(security_ids).intersection(available))


def compute_sector_forward_returns(
    scored: pd.DataFrame,
    sector_scores: pd.DataFrame,
    returns_path: Path,
) -> pd.DataFrame:
    securities = _available_return_columns(returns_path, scored[SECURITY_ID_COLUMN].dropna())
    returns = pd.read_parquet(returns_path, columns=securities)
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    returns = returns.sort_index()

    dates = sorted(sector_scores["Date"].dropna().unique())
    records: list[dict[str, object]] = []
    for idx, date in enumerate(dates[:-1]):
        next_date = dates[idx + 1]
        if next_date > returns.index.max():
            continue
        daily = returns.loc[(returns.index > date) & (returns.index <= next_date), securities]
        if daily.empty:
            continue
        stock_return = (1 + daily).prod(axis=0, skipna=True) - 1
        stock_return[daily.notna().sum(axis=0) == 0] = np.nan

        monthly_screen = scored[
            scored["Date"].eq(date) & scored[SECURITY_ID_COLUMN].isin(securities)
        ][[SECURITY_ID_COLUMN, "sector_code", BENCHMARK_WEIGHT_COLUMN]].copy()
        monthly_screen["stock_forward_return"] = monthly_screen[SECURITY_ID_COLUMN].map(
            stock_return
        )
        monthly_screen = monthly_screen.dropna(subset=["stock_forward_return"])
        if monthly_screen.empty:
            continue
        monthly_screen["_weighted_return"] = (
            monthly_screen[BENCHMARK_WEIGHT_COLUMN] * monthly_screen["stock_forward_return"]
        )
        grouped = monthly_screen.groupby("sector_code", observed=True).agg(
            weighted_return=("_weighted_return", "sum"),
            return_weight=(BENCHMARK_WEIGHT_COLUMN, "sum"),
            return_coverage_n=("stock_forward_return", "count"),
        )
        grouped["sector_forward_return"] = grouped["weighted_return"] / grouped["return_weight"]
        for sector_code, row in grouped.iterrows():
            records.append(
                {
                    "Date": date,
                    "next_date": next_date,
                    "sector_code": int(sector_code),
                    "sector_forward_return": row["sector_forward_return"],
                    "return_coverage_n": int(row["return_coverage_n"]),
                }
            )
    return pd.DataFrame(records)


def _build_scored_and_sector_scores(
    screen_path: Path = SCREEN_AGGREGATE_PATH,
    mapping_path: Path = FACTSET_ICB_MAPPING_PATH,
    start_date: str = "2010-01-01",
    market: str = "US",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sector_mapping = _load_sector_mapping(mapping_path)
    screen = load_screen_universe(screen_path, start_date=start_date, market=market)
    scored = add_stock_scores(screen)
    sector_scores = aggregate_sector_scores(scored, sector_mapping, market=market)
    return scored, sector_scores


def build_panel(
    screen_path: Path = SCREEN_AGGREGATE_PATH,
    returns_path: Path = RETURNS_PATH,
    mapping_path: Path = FACTSET_ICB_MAPPING_PATH,
    start_date: str = "2010-01-01",
    market: str = "US",
) -> pd.DataFrame:
    scored, sector_scores = _build_scored_and_sector_scores(
        screen_path=screen_path,
        mapping_path=mapping_path,
        start_date=start_date,
        market=market,
    )
    sector_returns = compute_sector_forward_returns(scored, sector_scores, returns_path)
    panel = sector_scores.merge(sector_returns, on=["Date", "sector_code"], how="inner")
    panel = panel.sort_values(["Date", "sector_code"]).reset_index(drop=True)
    return panel


def _annualized_return(returns: pd.Series) -> float:
    returns = pd.Series(returns).dropna()
    if returns.empty:
        return float("nan")
    return float((1 + returns).prod() ** (12 / len(returns)) - 1)


def _performance_stats(returns: pd.Series) -> dict[str, float | int]:
    returns = pd.Series(returns).dropna()
    if returns.empty:
        return {
            "months": 0,
            "annualized_return": float("nan"),
            "annualized_volatility": float("nan"),
            "sharpe": float("nan"),
            "max_drawdown": float("nan"),
            "hit_rate": float("nan"),
            "total_return": float("nan"),
        }
    nav = (1 + returns).cumprod()
    drawdown = nav / nav.cummax() - 1
    annualized_return = _annualized_return(returns)
    annualized_volatility = float(returns.std(ddof=1) * np.sqrt(12)) if len(returns) > 1 else 0.0
    return {
        "months": int(len(returns)),
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "sharpe": float(annualized_return / annualized_volatility)
        if annualized_volatility > 0
        else float("nan"),
        "max_drawdown": float(drawdown.min()),
        "hit_rate": float((returns > 0).mean()),
        "total_return": float(nav.iloc[-1] - 1),
    }


def evaluate_factor_effectiveness(
    panel: pd.DataFrame,
    columns: Iterable[str] = EFFECTIVENESS_COLUMNS,
    top_n: int = 3,
    bottom_n: int = 3,
) -> pd.DataFrame:
    rows = []
    for column in columns:
        if column not in panel.columns:
            continue
        monthly_ic = []
        top_minus_bottom = []
        top_beats_bottom = []
        for _, group in panel.dropna(subset=[column, "sector_forward_return"]).groupby("Date"):
            if len(group) < max(top_n + bottom_n, 6):
                continue
            if group[column].nunique() <= 1 or group["sector_forward_return"].nunique() <= 1:
                continue
            monthly_ic.append(
                group[column].rank().corr(group["sector_forward_return"].rank(), method="pearson")
            )
            group = group.assign(_selection_score=group[column].round(12))
            top_return = group.sort_values(
                ["_selection_score", "sector_code"], ascending=[False, True], kind="mergesort"
            ).head(top_n)["sector_forward_return"].mean()
            bottom_return = group.sort_values(
                ["_selection_score", "sector_code"], ascending=[True, True], kind="mergesort"
            ).head(bottom_n)["sector_forward_return"].mean()
            top_minus_bottom.append(top_return - bottom_return)
            top_beats_bottom.append(top_return > bottom_return)
        ic_series = pd.Series(monthly_ic).dropna()
        tb_series = pd.Series(top_minus_bottom).dropna()
        rows.append(
            {
                "factor": column,
                "months": int(len(ic_series)),
                "mean_ic": float(ic_series.mean()) if len(ic_series) else float("nan"),
                "median_ic": float(ic_series.median()) if len(ic_series) else float("nan"),
                "ic_hit_rate": float((ic_series > 0).mean()) if len(ic_series) else float("nan"),
                "top_minus_bottom_annualized": _annualized_return(tb_series)
                if len(tb_series)
                else float("nan"),
                "top_minus_bottom_monthly_mean": float(tb_series.mean())
                if len(tb_series)
                else float("nan"),
                "top_minus_bottom_hit_rate": float(pd.Series(top_beats_bottom).mean())
                if top_beats_bottom
                else float("nan"),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["mean_ic", "top_minus_bottom_annualized"], ascending=False
    )


def run_sector_tilt_backtest(
    panel: pd.DataFrame,
    score_column: str = "score_final",
    top_n: int = 3,
    bottom_n: int = 3,
    absolute_tilt: float = 0.05,
    relative_tilt: float = 0.20,
) -> pd.DataFrame:
    records = []
    required = [score_column, "sector_forward_return", "sector_weight"]
    for date, group in panel.dropna(subset=required).groupby("Date"):
        if len(group) < max(top_n + bottom_n, 8):
            continue
        group = group.sort_values("sector_code", kind="mergesort").copy()
        group["_selection_score"] = group[score_column].round(12)
        top_codes = set(
            group.sort_values(
                ["_selection_score", "sector_code"], ascending=[False, True], kind="mergesort"
            ).head(top_n)["sector_code"]
        )
        bottom_codes = set(
            group.sort_values(
                ["_selection_score", "sector_code"], ascending=[True, True], kind="mergesort"
            ).head(bottom_n)["sector_code"]
        )
        group["benchmark_weight"] = group["sector_weight"] / group["sector_weight"].sum()

        def tilted_weight(row: pd.Series) -> float:
            benchmark_weight = row["benchmark_weight"]
            if row["sector_code"] in top_codes:
                return max(benchmark_weight * (1 + relative_tilt), benchmark_weight + absolute_tilt)
            if row["sector_code"] in bottom_codes:
                return min(
                    benchmark_weight * (1 - relative_tilt),
                    max(0.0, benchmark_weight - absolute_tilt),
                )
            return benchmark_weight

        group["tilted_weight_raw"] = group.apply(tilted_weight, axis=1)
        group["tilted_weight"] = group["tilted_weight_raw"] / group["tilted_weight_raw"].sum()
        benchmark_return = float((group["benchmark_weight"] * group["sector_forward_return"]).sum())
        tilt_return = float((group["tilted_weight"] * group["sector_forward_return"]).sum())
        records.append(
            {
                "Date": date,
                "next_date": group["next_date"].iloc[0],
                "model_return": tilt_return,
                "benchmark_return": benchmark_return,
                "active_return": tilt_return - benchmark_return,
                "top_equal_return": float(
                    group[group["sector_code"].isin(top_codes)]["sector_forward_return"].mean()
                ),
                "bottom_equal_return": float(
                    group[group["sector_code"].isin(bottom_codes)]["sector_forward_return"].mean()
                ),
                "top_sectors": "|".join(
                    group[group["sector_code"].isin(top_codes)]
                    .sort_values(score_column, ascending=False)["sector_name"]
                    .fillna(group["sector_code"].astype(str))
                    .astype(str)
                ),
                "bottom_sectors": "|".join(
                    group[group["sector_code"].isin(bottom_codes)]
                    .sort_values(score_column, ascending=True)["sector_name"]
                    .fillna(group["sector_code"].astype(str))
                    .astype(str)
                ),
            }
        )
    result = pd.DataFrame(records).sort_values("Date").reset_index(drop=True)
    if not result.empty:
        result["model_nav"] = (1 + result["model_return"]).cumprod()
        result["benchmark_nav"] = (1 + result["benchmark_return"]).cumprod()
        result["active_nav"] = result["model_nav"] / result["benchmark_nav"]
    return result


def summarize_backtest(backtest: pd.DataFrame) -> dict[str, object]:
    periods = {
        "full_period": backtest,
        "first_half": backtest.iloc[: len(backtest) // 2],
        "second_half": backtest.iloc[len(backtest) // 2 :],
        "post_2020": backtest[backtest["Date"].ge(pd.Timestamp("2020-01-01"))],
    }
    summary: dict[str, object] = {}
    for name, frame in periods.items():
        if frame.empty:
            continue
        stats = {
            "model": _performance_stats(frame["model_return"]),
            "benchmark": _performance_stats(frame["benchmark_return"]),
            "active": _performance_stats(frame["active_return"]),
        }
        if len(frame):
            stats["relative_annualized_return"] = float(
                (frame["model_nav"].iloc[-1] / frame["benchmark_nav"].iloc[-1])
                ** (12 / len(frame))
                - 1
            )
            stats["start_date"] = str(frame["Date"].min().date())
            stats["end_date"] = str(frame["Date"].max().date())
        summary[name] = stats
    return summary


def add_latest_recommendations(
    panel: pd.DataFrame,
    score_column: str,
    top_n: int,
    bottom_n: int,
) -> pd.DataFrame:
    latest_date = panel["Date"].max()
    latest = panel[panel["Date"].eq(latest_date)].copy()
    latest["rank"] = latest[score_column].rank(ascending=False, method="first")
    latest["recommendation"] = "Neutral"
    latest.loc[latest["rank"].le(top_n), "recommendation"] = "Positive"
    latest.loc[latest["rank"].gt(len(latest) - bottom_n), "recommendation"] = "Negative"
    return latest.sort_values("rank")


def write_outputs(
    panel: pd.DataFrame,
    output_dir: Path,
    score_column: str,
    top_n: int,
    bottom_n: int,
    latest_scores: pd.DataFrame | None = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    factor_effectiveness = evaluate_factor_effectiveness(panel, top_n=top_n, bottom_n=bottom_n)
    backtest = run_sector_tilt_backtest(
        panel, score_column=score_column, top_n=top_n, bottom_n=bottom_n
    )
    summary = summarize_backtest(backtest)
    latest = add_latest_recommendations(
        latest_scores if latest_scores is not None else panel,
        score_column,
        top_n,
        bottom_n,
    )

    paths = {
        "sector_scores_panel": output_dir / "sector_scores_panel.parquet",
        "sector_scores_latest": output_dir / "sector_scores_latest.csv",
        "factor_effectiveness": output_dir / "factor_effectiveness.csv",
        "backtest_monthly_returns": output_dir / "backtest_monthly_returns.csv",
        "backtest_summary": output_dir / "backtest_summary.json",
    }
    panel.to_parquet(paths["sector_scores_panel"], index=False)
    latest.to_csv(paths["sector_scores_latest"], index=False, encoding="utf-8-sig")
    factor_effectiveness.to_csv(
        paths["factor_effectiveness"], index=False, encoding="utf-8-sig"
    )
    backtest.to_csv(paths["backtest_monthly_returns"], index=False, encoding="utf-8-sig")
    with paths["backtest_summary"].open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    return {key: str(value) for key, value in paths.items()}


def run_model(
    screen_path: Path = SCREEN_AGGREGATE_PATH,
    returns_path: Path = RETURNS_PATH,
    mapping_path: Path = FACTSET_ICB_MAPPING_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    start_date: str = "2010-01-01",
    score_column: str = "score_final",
    top_n: int = 3,
    bottom_n: int = 3,
    market: str = "US",
) -> dict[str, object]:
    scored, sector_scores = _build_scored_and_sector_scores(
        screen_path=screen_path,
        mapping_path=mapping_path,
        start_date=start_date,
        market=market,
    )
    sector_returns = compute_sector_forward_returns(scored, sector_scores, returns_path)
    panel = sector_scores.merge(sector_returns, on=["Date", "sector_code"], how="inner")
    panel = panel.sort_values(["Date", "sector_code"]).reset_index(drop=True)
    paths = write_outputs(panel, output_dir, score_column, top_n, bottom_n, latest_scores=sector_scores)
    return {
        "panel_rows": int(len(panel)),
        "market": market.upper(),
        "months": int(panel["Date"].nunique()),
        "latest_date": str(sector_scores["Date"].max().date()),
        "start_date": str(panel["Date"].min().date()),
        "end_date": str(panel["Date"].max().date()),
        "outputs": paths,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the sector score model.")
    parser.add_argument("--screen", default=str(SCREEN_AGGREGATE_PATH), help="screen parquet path")
    parser.add_argument("--returns", default=str(RETURNS_PATH), help="returns parquet path")
    parser.add_argument("--mapping", default=str(FACTSET_ICB_MAPPING_PATH), help="ICB mapping xlsx")
    parser.add_argument("--market", default="US", choices=sorted(MARKET_CONFIGS), help="market universe")
    parser.add_argument("--output-dir", help="output directory")
    parser.add_argument("--start-date", default="2010-01-01", help="first signal date")
    parser.add_argument("--score-column", default="score_final", help="score column for final backtest")
    parser.add_argument("--top-n", type=int, default=3, help="number of positive sectors")
    parser.add_argument("--bottom-n", type=int, default=3, help="number of negative sectors")
    args = parser.parse_args(list(argv) if argv is not None else None)
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else Path(_market_config(args.market)["default_output_dir"])
    )

    result = run_model(
        screen_path=Path(args.screen),
        returns_path=Path(args.returns),
        mapping_path=Path(args.mapping),
        output_dir=output_dir,
        start_date=args.start_date,
        score_column=args.score_column,
        top_n=args.top_n,
        bottom_n=args.bottom_n,
        market=args.market,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

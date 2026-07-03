"""TP canonical screen 与 returns 数据集的共享数据契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

SCREEN_KEY_COLUMNS: tuple[str, str] = ("ISIN", "Date")
ISIN_COLUMN = "ISIN"
DATE_COLUMN = "Date"
SEDOL_COLUMN = "Company SEDOL"
RETURNS_INDEX_NAME = "Date"
WEIGHT_PREFIX = "Weight in "

CORE_WEIGHT_COLUMNS: tuple[str, ...] = (
    "Weight in MSCI WORLD",
    "Weight in SP500",
    "Weight in STOXX EUROPE 600",
    "Weight in MSCI EM",
)

ML_UNIVERSE_WEIGHT_COLUMNS: tuple[str, ...] = (
    "Weight in Univ ML EU",
    "Weight in Univ ML US",
    "Weight in Univ ML OTHER",
)

PERFORMANCE_COLUMNS: tuple[str, ...] = ("Perf5D", "Perf1M", "Perf3M", "Perf6M")

RISK_COLUMNS: tuple[str, ...] = (
    "Volatilite Rolling ewma 250D",
    "VaR 1% Rolling 250D",
    "Maximum Drawdown Rolling 250D",
    "Beta vs SXXP (Rolling ewma 250D)",
    "Beta vs Regional Benchmark (Rolling ewma 250D)",
    "Beta Up vs SXXP (252D)",
    "Beta Down vs SXXP (252D)",
)

DEPRECATED_SCREEN_COLUMNS: tuple[str, ...] = ("EM CountryCluster",)
DEPRECATED_SCREEN_PREFIXES: tuple[str, ...] = ("Weight in MSCI EM - ",)

FIELD_FAMILIES: dict[str, tuple[str, ...] | str] = {
    "keys": SCREEN_KEY_COLUMNS,
    "identifiers": (ISIN_COLUMN, SEDOL_COLUMN, "Symbol", "Name"),
    "date": (DATE_COLUMN,),
    "industry": (
        " Benchmark ICB Industry ",
        " Benchmark ICB Supersector ",
        "ICB11 Industry",
        "ICB19 Supersector",
        "FactSet Ind",
        "FactSet Economy",
    ),
    "geography": ("Exchange Country Name", "Exchange Country Region", "Benchmark Country English"),
    "weights": CORE_WEIGHT_COLUMNS + ML_UNIVERSE_WEIGHT_COLUMNS,
    "factors": "Value/Quality/Growth/Momentum/LowVol/Dividend/Size 的原始值与 percentile 因子列",
    "risk": RISK_COLUMNS,
    "performance": PERFORMANCE_COLUMNS,
    "ciq": "按 (ISIN, Date) 合并的 CIQ 财务报表与预测字段",
}

WEIGHT_NULL_SEMANTICS = (
    "对 Weight in ... 列，空值通常表示非成分股或权重不可得，"
    "本身不等于数据错误。成分股判断应使用 fillna(0) > 0。"
)

SEDOL_JOIN_SEMANTICS = (
    "screen.Company SEDOL 将月度面板连接到 returns.columns。"
    "缺少 Company SEDOL 的行无法获得基于 returns 的风险或表现指标。"
)

DATE_SEMANTICS = (
    "screen.Date 统一归一到月末 timestamp。returns.index 为日频交易日期。"
    "月度指标使用月末当天或之前最近可用的 returns 日期。"
)


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    check: str
    message: str


def is_deprecated_screen_column(column: str) -> bool:
    return column in DEPRECATED_SCREEN_COLUMNS or any(
        column.startswith(prefix) for prefix in DEPRECATED_SCREEN_PREFIXES
    )


def deprecated_screen_columns(columns: Iterable[str]) -> list[str]:
    return [column for column in columns if is_deprecated_screen_column(str(column))]


def drop_deprecated_screen_columns(df: pd.DataFrame) -> pd.DataFrame:
    columns_to_drop = deprecated_screen_columns(df.columns)
    if not columns_to_drop:
        return df
    return df.drop(columns=columns_to_drop)


def ensure_isin_column(df: pd.DataFrame) -> pd.DataFrame:
    if ISIN_COLUMN in df.columns:
        return df.copy()
    if df.index.name == ISIN_COLUMN:
        return df.reset_index()
    raise ValueError("DataFrame 必须以普通列或 index name 暴露 ISIN")


def normalize_screen_dates(df: pd.DataFrame) -> pd.DataFrame:
    screen = ensure_isin_column(df)
    if DATE_COLUMN not in screen.columns:
        raise ValueError("screen DataFrame 缺少 Date 列")
    screen[DATE_COLUMN] = pd.to_datetime(screen[DATE_COLUMN], errors="coerce")
    return screen


def validate_screen_contract(df: pd.DataFrame) -> dict[str, Any]:
    screen = normalize_screen_dates(df)
    issues: list[ValidationIssue] = []

    for column in SCREEN_KEY_COLUMNS:
        if column not in screen.columns:
            issues.append(ValidationIssue("error", "required_column", f"缺少必需列：{column}"))

    if SEDOL_COLUMN not in screen.columns:
        issues.append(ValidationIssue("warning", "sedol_column", f"缺少 {SEDOL_COLUMN}"))

    duplicate_keys = 0
    if all(column in screen.columns for column in SCREEN_KEY_COLUMNS):
        duplicate_keys = int(screen.duplicated(subset=list(SCREEN_KEY_COLUMNS), keep=False).sum())
        if duplicate_keys:
            issues.append(
                ValidationIssue("error", "duplicate_keys", f"重复的 (ISIN, Date) 行数：{duplicate_keys}")
            )

    deprecated = deprecated_screen_columns(screen.columns)
    if deprecated:
        issues.append(
            ValidationIssue("warning", "deprecated_columns", f"仍存在已废弃的 screen 列：{deprecated}")
        )

    return {
        "rows": int(len(screen)),
        "columns": int(len(screen.columns)),
        "date_min": screen[DATE_COLUMN].min() if DATE_COLUMN in screen.columns else None,
        "date_max": screen[DATE_COLUMN].max() if DATE_COLUMN in screen.columns else None,
        "duplicate_keys": duplicate_keys,
        "deprecated_columns": deprecated,
        "issues": [issue.__dict__ for issue in issues],
        "ok": not any(issue.severity == "error" for issue in issues),
    }


def validate_returns_contract(df: pd.DataFrame) -> dict[str, Any]:
    returns = df.copy()
    returns.index = pd.to_datetime(returns.index, errors="coerce")
    duplicate_dates = int(returns.index.duplicated(keep=False).sum())
    null_dates = int(pd.isna(returns.index).sum())
    issues: list[ValidationIssue] = []
    if duplicate_dates:
        issues.append(ValidationIssue("error", "duplicate_dates", f"重复的 returns 日期数：{duplicate_dates}"))
    if null_dates:
        issues.append(ValidationIssue("error", "null_dates", f"无法解析的 returns 日期数：{null_dates}"))
    return {
        "rows": int(len(returns)),
        "columns": int(len(returns.columns)),
        "date_min": returns.index.min() if len(returns) else None,
        "date_max": returns.index.max() if len(returns) else None,
        "duplicate_dates": duplicate_dates,
        "null_dates": null_dates,
        "issues": [issue.__dict__ for issue in issues],
        "ok": not any(issue.severity == "error" for issue in issues),
    }


def sedol_coverage(screen_df: pd.DataFrame, returns_df: pd.DataFrame, latest_only: bool = True) -> dict[str, Any]:
    screen = normalize_screen_dates(screen_df)
    if latest_only and len(screen):
        latest_date = screen[DATE_COLUMN].max()
        screen = screen.loc[screen[DATE_COLUMN] == latest_date]
    else:
        latest_date = None

    if SEDOL_COLUMN not in screen.columns:
        return {"latest_date": latest_date, "valid_sedol_count": 0, "missing_count": None, "missing_sample": []}

    sedol = screen[SEDOL_COLUMN].astype("string").str.strip()
    valid_mask = sedol.notna() & (sedol != "") & (sedol.str.lower() != "nan")
    valid_sedol = sedol.loc[valid_mask].astype(str)
    missing = sorted(set(valid_sedol) - {str(column) for column in returns_df.columns})
    return {
        "latest_date": latest_date,
        "valid_sedol_count": int(len(valid_sedol)),
        "missing_count": int(len(missing)),
        "missing_sample": missing[:20],
    }


def weight_sum_report(screen_df: pd.DataFrame, columns: Iterable[str] = CORE_WEIGHT_COLUMNS) -> dict[str, dict[str, Any]]:
    screen = normalize_screen_dates(screen_df)
    latest = screen.loc[screen[DATE_COLUMN] == screen[DATE_COLUMN].max()] if len(screen) else screen
    report: dict[str, dict[str, Any]] = {}
    for column in columns:
        if column not in latest.columns:
            report[column] = {"exists": False}
            continue
        report[column] = {
            "exists": True,
            "non_null": int(latest[column].notna().sum()),
            "sum": float(latest[column].sum(skipna=True)),
        }
    return report


def data_contract() -> dict[str, Any]:
    return {
        "screen_key": SCREEN_KEY_COLUMNS,
        "screen_date_semantics": DATE_SEMANTICS,
        "sedol_join_semantics": SEDOL_JOIN_SEMANTICS,
        "weight_null_semantics": WEIGHT_NULL_SEMANTICS,
        "field_families": FIELD_FAMILIES,
        "deprecated_screen_columns": DEPRECATED_SCREEN_COLUMNS,
        "deprecated_screen_prefixes": DEPRECATED_SCREEN_PREFIXES,
    }
"""统一信号表 schema、校验和标准化工具。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

REQUIRED_SIGNAL_COLUMNS = [
    "Date",
    "signal_family",
    "signal_name",
    "scope",
    "score",
    "direction",
    "coverage_flag",
    "model_version",
    "source_project",
]

OPTIONAL_SIGNAL_COLUMNS = [
    "Company SEDOL",
    "ISIN",
    "region",
    "benchmark",
    "universe",
    "score_pct",
    "raw_value",
    "as_of_date",
    "effective_date",
    "horizon",
    "confidence",
    "signal_description",
]

SIGNAL_COLUMN_ORDER = REQUIRED_SIGNAL_COLUMNS + OPTIONAL_SIGNAL_COLUMNS

ALLOWED_SCOPES = {"security", "region", "portfolio", "market", "universe"}
ALLOWED_DIRECTIONS = {
    "higher_is_better",
    "lower_is_better",
    "binary_positive",
    "binary_negative",
    "neutral_midpoint",
    "higher_risk_budget",
}


@dataclass
class SignalValidationResult:
    """统一信号表校验结果。"""

    is_valid: bool
    errors: list[str]
    warnings: list[str]

    def as_text(self) -> str:
        lines: list[str] = []
        for item in self.errors:
            lines.append(f"[ERROR] {item}")
        for item in self.warnings:
            lines.append(f"[WARNING] {item}")
        return "\n".join(lines)


def standardize_signal_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """补齐可选列、规范日期和列顺序。"""

    result = frame.copy()
    for column in REQUIRED_SIGNAL_COLUMNS + OPTIONAL_SIGNAL_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result["as_of_date"] = pd.to_datetime(result["as_of_date"], errors="coerce")
    result["effective_date"] = pd.to_datetime(result["effective_date"], errors="coerce")
    result["score"] = pd.to_numeric(result["score"], errors="coerce")
    result["score_pct"] = pd.to_numeric(result["score_pct"], errors="coerce")
    result["confidence"] = pd.to_numeric(result["confidence"], errors="coerce")
    result["coverage_flag"] = result["coverage_flag"].fillna(False).astype(bool)

    text_columns = [
        "signal_family",
        "signal_name",
        "scope",
        "direction",
        "model_version",
        "source_project",
        "Company SEDOL",
        "ISIN",
        "region",
        "benchmark",
        "universe",
        "raw_value",
        "horizon",
        "signal_description",
    ]
    for column in text_columns:
        if column in result.columns:
            result[column] = result[column].astype("string")

    ordered = [column for column in SIGNAL_COLUMN_ORDER if column in result.columns]
    extras = [column for column in result.columns if column not in ordered]
    return result[ordered + extras]


def validate_signal_frame(frame: pd.DataFrame, *, strict: bool = False) -> SignalValidationResult:
    """校验统一信号表。strict=True 时重复键也视为错误。"""

    errors: list[str] = []
    warnings: list[str] = []

    missing = [column for column in REQUIRED_SIGNAL_COLUMNS if column not in frame.columns]
    if missing:
        errors.append(f"缺少必填列: {missing}")
        return SignalValidationResult(False, errors, warnings)

    standardized = standardize_signal_frame(frame)

    if standardized["Date"].isna().any():
        errors.append("Date 存在无法解析的值")
    if standardized["score"].isna().any():
        warnings.append("score 存在空值；这些行应确认 coverage_flag 是否为 False")

    invalid_scopes = sorted(set(standardized["scope"].dropna()) - ALLOWED_SCOPES)
    if invalid_scopes:
        errors.append(f"scope 包含未登记值: {invalid_scopes}")

    invalid_directions = sorted(set(standardized["direction"].dropna()) - ALLOWED_DIRECTIONS)
    if invalid_directions:
        errors.append(f"direction 包含未登记值: {invalid_directions}")

    security_rows = standardized["scope"].eq("security")
    if security_rows.any() and standardized.loc[security_rows, "Company SEDOL"].isna().any():
        errors.append("scope=security 的行必须有 Company SEDOL")

    key_columns = [
        "Date",
        "signal_family",
        "signal_name",
        "scope",
        "Company SEDOL",
        "region",
        "benchmark",
        "universe",
        "model_version",
    ]
    duplicate_count = int(standardized.duplicated(subset=key_columns, keep=False).sum())
    if duplicate_count:
        message = f"发现 {duplicate_count} 行重复信号键"
        if strict:
            errors.append(message)
        else:
            warnings.append(message)

    return SignalValidationResult(not errors, errors, warnings)


def make_security_signal_frame(
    source: pd.DataFrame,
    *,
    score_column: str,
    signal_family: str,
    signal_name: str,
    model_version: str,
    source_project: str,
    direction: str = "higher_is_better",
    date_column: str = "Date",
    sedol_column: str = "Company SEDOL",
    isin_column: str | None = "ISIN",
    benchmark: str | None = None,
    universe: str | None = None,
    raw_value_column: str | None = None,
    horizon: str | None = None,
    signal_description: str | None = None,
) -> pd.DataFrame:
    """把证券级宽表中的一个分数字段转成统一信号表。"""

    if score_column not in source.columns:
        raise KeyError(f"source 缺少 score_column: {score_column}")
    if date_column not in source.columns:
        raise KeyError(f"source 缺少 date_column: {date_column}")

    frame = source.copy()
    if sedol_column not in frame.columns:
        if frame.index.name == sedol_column:
            frame = frame.reset_index()
        else:
            raise KeyError(f"source 缺少 sedol_column: {sedol_column}")

    result = pd.DataFrame(
        {
            "Date": frame[date_column],
            "Company SEDOL": frame[sedol_column].astype("string"),
            "signal_family": signal_family,
            "signal_name": signal_name,
            "scope": "security",
            "score": frame[score_column],
            "direction": direction,
            "coverage_flag": frame[score_column].notna(),
            "model_version": model_version,
            "source_project": source_project,
            "benchmark": benchmark,
            "universe": universe,
            "horizon": horizon,
            "signal_description": signal_description,
        }
    )
    if isin_column and isin_column in frame.columns:
        result["ISIN"] = frame[isin_column].astype("string")
    if raw_value_column and raw_value_column in frame.columns:
        result["raw_value"] = frame[raw_value_column]
    else:
        result["raw_value"] = frame[score_column]

    result["score_pct"] = result.groupby("Date", dropna=False)["score"].rank(pct=True)
    return standardize_signal_frame(result)


def write_signal_frame(frame: pd.DataFrame, output_path: str | Path, *, strict: bool = False) -> Path:
    """校验并写出统一信号表 parquet。"""

    standardized = standardize_signal_frame(frame)
    validation = validate_signal_frame(standardized, strict=strict)
    if not validation.is_valid:
        raise ValueError(validation.as_text())
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    standardized.to_parquet(output, index=False)
    return output


def read_signal_frame(path: str | Path) -> pd.DataFrame:
    """读取并标准化统一信号表。"""

    return standardize_signal_frame(pd.read_parquet(path))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验统一信号表 parquet")
    parser.add_argument("path", help="信号表 parquet 路径")
    parser.add_argument("--strict", action="store_true", help="重复键作为错误处理")
    args = parser.parse_args(list(argv) if argv is not None else None)

    frame = pd.read_parquet(args.path)
    result = validate_signal_frame(frame, strict=args.strict)
    print(result.as_text() or "信号表校验通过。")
    return 0 if result.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

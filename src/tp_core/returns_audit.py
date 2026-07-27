"""日频 returns 异常值审计和治理工具。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .data_sources import RETURNS_PATH
from .io import read_returns


DEFAULT_REVIEW_COLUMNS = (
    "Date",
    "Company SEDOL",
    "return",
    "abs_return",
    "severity",
    "reason",
    "review_status",
    "suggested_action",
    "reviewer",
    "review_notes",
    "approved_action",
    "corrected_return",
)


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _stack_returns(returns: pd.DataFrame) -> pd.DataFrame:
    try:
        stacked_series = returns.stack(future_stack=True).dropna()
    except TypeError:
        stacked_series = returns.stack(dropna=True)
    stacked = stacked_series.rename("return").reset_index()
    stacked.columns = ["Date", "Company SEDOL", "return"]
    stacked["abs_return"] = stacked["return"].abs()
    return stacked


def flag_returns_extremes(
    returns: pd.DataFrame,
    abs_threshold: float = 1.0,
    positive_threshold: float = 2.0,
    negative_threshold: float = -0.95,
) -> pd.DataFrame:
    """返回完整异常收益清单，不修改原始 returns。"""
    stacked = _stack_returns(returns)
    flagged = stacked.loc[
        (stacked["abs_return"] >= abs_threshold)
        | (stacked["return"] >= positive_threshold)
        | (stacked["return"] <= negative_threshold)
    ].copy()
    flagged = flagged.sort_values("abs_return", ascending=False)

    reasons: list[str] = []
    for _, row in flagged.iterrows():
        row_reasons: list[str] = []
        if row["abs_return"] >= abs_threshold:
            row_reasons.append("abs_threshold")
        if row["return"] >= positive_threshold:
            row_reasons.append("positive_threshold")
        if row["return"] <= negative_threshold:
            row_reasons.append("negative_threshold")
        reasons.append(",".join(row_reasons))

    flagged["severity"] = "review"
    flagged.loc[flagged["abs_return"] >= 2.0, "severity"] = "high"
    flagged.loc[flagged["abs_return"] >= 10.0, "severity"] = "critical"
    flagged.loc[flagged["return"] <= -0.99, "severity"] = "critical"
    flagged["reason"] = reasons
    flagged["review_status"] = "needs_review"
    flagged["suggested_action"] = "verify_vendor_or_corporate_action_before_cleaning"
    flagged["reviewer"] = ""
    flagged["review_notes"] = ""
    flagged["approved_action"] = ""
    flagged["corrected_return"] = pd.NA
    return flagged


def audit_returns_extremes(
    returns: pd.DataFrame,
    abs_threshold: float = 1.0,
    positive_threshold: float = 2.0,
    negative_threshold: float = -0.95,
    top_n: int = 50,
) -> dict[str, Any]:
    stacked = _stack_returns(returns)
    flagged = flag_returns_extremes(
        returns,
        abs_threshold=abs_threshold,
        positive_threshold=positive_threshold,
        negative_threshold=negative_threshold,
    )

    top = flagged.head(top_n).copy()
    if not top.empty:
        top["Date"] = pd.to_datetime(top["Date"]).dt.strftime("%Y-%m-%d")
    severity_counts = flagged["severity"].value_counts().to_dict() if len(flagged) else {}

    return {
        "rows": int(len(returns)),
        "columns": int(len(returns.columns)),
        "date_min": returns.index.min(),
        "date_max": returns.index.max(),
        "thresholds": {
            "abs_threshold": abs_threshold,
            "positive_threshold": positive_threshold,
            "negative_threshold": negative_threshold,
        },
        "flagged_cells": int(len(flagged)),
        "flagged_unique_sedol": int(flagged["Company SEDOL"].nunique()) if len(flagged) else 0,
        "severity_counts": {str(key): int(value) for key, value in severity_counts.items()},
        "governance_status": "needs_review" if len(flagged) else "passed",
        "governance_policy": (
            "审计只生成异常清单和复核模板，不直接修改 canonical returns.parquet；"
            "修正或白名单需要人工确认后再进入正式数据修复流程。"
        ),
        "max_return": float(stacked["return"].max()) if len(stacked) else None,
        "min_return": float(stacked["return"].min()) if len(stacked) else None,
        "top": top[["Date", "Company SEDOL", "return", "abs_return", "severity", "reason"]].to_dict("records"),
    }


def audit_returns_file(
    path: str | Path = RETURNS_PATH,
    report_path: str | Path | None = None,
    abs_threshold: float = 1.0,
    positive_threshold: float = 2.0,
    negative_threshold: float = -0.95,
    top_n: int = 50,
    flagged_parquet_path: str | Path | None = None,
    flagged_csv_path: str | Path | None = None,
    review_template_path: str | Path | None = None,
) -> dict[str, Any]:
    returns = read_returns(path)
    flagged = flag_returns_extremes(
        returns,
        abs_threshold=abs_threshold,
        positive_threshold=positive_threshold,
        negative_threshold=negative_threshold,
    )
    report = audit_returns_extremes(
        returns,
        abs_threshold=abs_threshold,
        positive_threshold=positive_threshold,
        negative_threshold=negative_threshold,
        top_n=top_n,
    )
    report["returns_path"] = str(path)

    if report_path is not None:
        output = Path(report_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
        report["report_path"] = str(output)
    if flagged_parquet_path is not None:
        output = Path(flagged_parquet_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        flagged.to_parquet(output, index=False)
        report["flagged_parquet_path"] = str(output)
    if flagged_csv_path is not None:
        output = Path(flagged_csv_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        flagged.to_csv(output, index=False, encoding="utf-8-sig")
        report["flagged_csv_path"] = str(output)
    if review_template_path is not None:
        output = Path(review_template_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        review = flagged.reindex(columns=list(DEFAULT_REVIEW_COLUMNS))
        review.to_csv(output, index=False, encoding="utf-8-sig")
        report["review_template_path"] = str(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="审计 canonical returns.parquet 中的极端日收益。", add_help=False)
    parser._optionals.title = "选项"
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出。")
    parser.add_argument("--returns-path", default=str(RETURNS_PATH), help="待审计的 returns parquet 路径。")
    parser.add_argument("--report-path", help="可选的 JSON 报告输出路径。")
    parser.add_argument("--flagged-parquet-path", help="可选的完整异常明细 parquet 输出路径。")
    parser.add_argument("--flagged-csv-path", help="可选的完整异常明细 CSV 输出路径。")
    parser.add_argument("--review-template-path", help="可选的人工复核模板 CSV 输出路径。")
    parser.add_argument("--fail-on-anomalies", action="store_true", help="如存在异常收益，则以非零状态退出。")
    parser.add_argument("--abs-threshold", type=float, default=1.0, help="按绝对值标记异常收益的阈值。")
    parser.add_argument("--positive-threshold", type=float, default=2.0, help="标记极端正收益的阈值。")
    parser.add_argument("--negative-threshold", type=float, default=-0.95, help="标记极端负收益的阈值。")
    parser.add_argument("--top-n", type=int, default=50, help="报告中保留的最大异常样本数。")
    args = parser.parse_args()
    report = audit_returns_file(
        args.returns_path,
        report_path=args.report_path,
        abs_threshold=args.abs_threshold,
        positive_threshold=args.positive_threshold,
        negative_threshold=args.negative_threshold,
        top_n=args.top_n,
        flagged_parquet_path=args.flagged_parquet_path,
        flagged_csv_path=args.flagged_csv_path,
        review_template_path=args.review_template_path,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    if args.fail_on_anomalies and report["flagged_cells"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

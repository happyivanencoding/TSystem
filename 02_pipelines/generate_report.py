"""生成流水线最新状态报告。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from tp_core.data_sources import TP_ROOT

from .common import (
    CANDIDATES_DIR,
    PIPELINE_MANIFESTS_DIR,
    PORTFOLIOS_DIR,
    REPORTS_DIR,
    StepManifest,
    iso_now,
    path_profile,
)


DEFAULT_OUTPUT = REPORTS_DIR / "latest_pipeline_report.md"
DEFAULT_STEPS = [
    "refresh_data",
    "export_signals",
    "build_candidates",
    "optimize_portfolio",
    "run_backtest",
    "generate_report",
    "run_all",
]
FRESHNESS_WINDOW_DAYS = 7


def _read_latest_manifest(step: str) -> dict | None:
    path = PIPELINE_MANIFESTS_DIR / step / f"{step}_latest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _status_icon(status: str | None) -> str:
    if status == "success":
        return "OK"
    if status == "failed":
        return "FAIL"
    return "N/A"


def _max_parquet_date(path: Path, column: str) -> pd.Timestamp | None:
    if not path.exists():
        return None
    frame = pd.read_parquet(path, columns=[column])
    dates = pd.to_datetime(frame[column], errors="coerce").dropna()
    return pd.Timestamp(dates.max()).normalize() if not dates.empty else None


def _max_csv_date(path: Path, column: str) -> pd.Timestamp | None:
    if not path.exists():
        return None
    frame = pd.read_csv(path, usecols=[column])
    dates = pd.to_datetime(frame[column], errors="coerce").dropna()
    return pd.Timestamp(dates.max()).normalize() if not dates.empty else None


def _max_returns_date(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    frame = pd.read_parquet(path, columns=[])
    dates = pd.to_datetime(frame.index, errors="coerce").dropna()
    return pd.Timestamp(dates.max()).normalize() if len(dates) else None


def _min_existing(dates: Iterable[pd.Timestamp | None]) -> pd.Timestamp | None:
    available = [date for date in dates if date is not None]
    return min(available) if available else None


def _freshness_rows(window_days: int = FRESHNESS_WINDOW_DAYS) -> tuple[pd.Timestamp | None, list[dict[str, object]]]:
    screen_date = _max_parquet_date(TP_ROOT / "00_screen" / "screen_aggregate.parquet", "Date")
    anchor = screen_date
    if anchor is None:
        return None, []
    items = [
        ("canonical screen", screen_date),
        ("canonical returns", _max_returns_date(TP_ROOT / "00_screen" / "returns.parquet")),
        ("ML 信号", _max_parquet_date(TP_ROOT / "04_signals" / "ml_signals.parquet", "Date")),
        ("技术信号", _max_parquet_date(TP_ROOT / "04_signals" / "technical_signals.parquet", "Date")),
        ("Regime 信号", _max_parquet_date(TP_ROOT / "04_signals" / "regime_risk_budget.parquet", "Date")),
        ("Country 信号", _max_parquet_date(TP_ROOT / "04_signals" / "country_model_signals.parquet", "Date")),
        (
            "Sector 信号",
            _min_existing(
                [
                    _max_csv_date(TP_ROOT / "13_sector_score_model" / "outputs_fs_sector_default" / "sector_scores_latest.csv", "Date"),
                    _max_csv_date(TP_ROOT / "13_sector_score_model" / "outputs_eu" / "sector_scores_latest.csv", "Date"),
                ]
            ),
        ),
        ("候选池", _max_parquet_date(CANDIDATES_DIR / "latest_candidates.parquet", "candidate_date")),
        ("目标权重", _max_parquet_date(PORTFOLIOS_DIR / "latest_target_weights.parquet", "candidate_date")),
    ]
    rows: list[dict[str, object]] = []
    for name, date in items:
        lag = int((date - anchor).days) if date is not None else None
        ok = lag is not None and abs(lag) <= window_days
        rows.append({"name": name, "date": date, "lag": lag, "ok": ok})
    return anchor, rows


def _freshness_status(ok: bool) -> str:
    return "OK" if ok else '<span style="color:red">过期</span>'


def _freshness_row(row: dict[str, object]) -> str:
    date = row["date"]
    date_text = date.date().isoformat() if isinstance(date, pd.Timestamp) else "缺失"
    return f"| {row['name']} | {date_text} | {row['lag'] if row['lag'] is not None else ''} | {_freshness_status(bool(row['ok']))} |"


def _manifest_row(step: str, payload: dict | None) -> str:
    if payload is None:
        return f"| `{step}` | N/A | 尚未运行 |  |  |"
    failed = [item["name"] for item in payload.get("validations", []) if item.get("status") != "passed"]
    failed_text = ", ".join(failed) if failed else ""
    return (
        f"| `{step}` | {_status_icon(payload.get('status'))} | {payload.get('finished_at', '')} | "
        f"{payload.get('duration_seconds', '')} | {failed_text} |"
    )


def generate_report(*, output: Path, steps: list[str]) -> str:
    manifests = {step: _read_latest_manifest(step) for step in steps}
    anchor, freshness = _freshness_rows()
    lines = [
        "# TP 流水线最新状态报告",
        "",
        f"生成时间：{iso_now()}",
        "",
        "## 新鲜度闸门",
        "",
        f"锚点日期：{anchor.date().isoformat() if anchor is not None else '缺失'}；允许窗口：{FRESHNESS_WINDOW_DAYS} 天",
        "",
        "| 层 | 日期 | 相对锚点天数 | 状态 |",
        "| --- | --- | ---: | --- |",
    ]
    lines.extend(_freshness_row(row) for row in freshness)
    lines.extend(
        [
            "",
            "## 步骤状态",
            "",
            "| 步骤 | 状态 | 最近完成时间 | 秒数 | 未通过校验 |",
            "| --- | --- | --- | ---: | --- |",
        ]
    )
    lines.extend(_manifest_row(step, manifests[step]) for step in steps)
    lines.extend(
        [
            "",
            "## 标准产物",
            "",
            "| 产物 | 状态 | 说明 |",
            "| --- | --- | --- |",
            f"| `04_signals/` | {'存在' if (TP_ROOT / '04_signals').exists() else '缺失'} | 统一信号表目录 |",
            f"| `05_candidates/latest_candidates.parquet` | {'存在' if (CANDIDATES_DIR / 'latest_candidates.parquet').exists() else '缺失'} | 最新候选池 |",
            f"| `06_portfolios/latest_target_weights.parquet` | {'存在' if (PORTFOLIOS_DIR / 'latest_target_weights.parquet').exists() else '缺失'} | 最新目标权重 |",
            "",
            "## 使用原则",
            "",
            "- 每个步骤可以单独运行和重跑。",
            "- 标准产物使用固定 latest 路径覆盖写入，避免重复数据累积。",
            "- 每次运行的证据写入 `10_pipeline_runs/manifests/<step>/`。",
            "- 旧目录和 quarantine 内容只作为历史参考，不参与新代码引用。",
            "",
        ]
    )
    text = "\n".join(lines)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return text


def run_generate_report(args: argparse.Namespace) -> Path:
    manifest = StepManifest("generate_report", vars(args).copy())
    manifest.inputs = {
        "pipeline_manifests": path_profile(PIPELINE_MANIFESTS_DIR),
        "candidates": path_profile(CANDIDATES_DIR / "latest_candidates.parquet", parquet=True),
        "target_weights": path_profile(PORTFOLIOS_DIR / "latest_target_weights.parquet", parquet=True),
    }
    try:
        steps = args.step or DEFAULT_STEPS
        text = generate_report(output=Path(args.output), steps=steps)
        manifest.outputs = {"report": path_profile(args.output)}
        manifest.details["line_count"] = len(text.splitlines())
        manifest.add_validation("report_written", Path(args.output).exists(), "报告已写出")
        return manifest.write("success")
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成流水线最新状态 Markdown 报告")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="报告输出路径")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    parser.add_argument("--step", action="append", help="纳入报告的步骤；可重复传入")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest_path = run_generate_report(args)
    print(f"generate_report manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

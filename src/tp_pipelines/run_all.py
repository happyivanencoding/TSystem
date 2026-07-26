"""TP 主流水线总编排入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from tp_core.security_nav_engine import NAV_ENGINE_ID, NAV_ENGINE_VERSION
from tp_core.data_sources import LAST_SCREEN_PATH, RETURNS_PATH, SCREEN_AGGREGATE_PATH, TP_ROOT
from tp_experiments import ExperimentRecorder, ExperimentSpec
from tp_portfolio import OPTIMIZER_ID, OPTIMIZER_VERSION

from .build_candidates import DEFAULT_OUTPUT as DEFAULT_CANDIDATES
from .common import REPORTS_DIR, StepManifest
from .optimize_portfolio import DEFAULT_OUTPUT as DEFAULT_PORTFOLIO
from .orchestration import PipelineContext, execute_pipeline_steps, pipeline_steps
from .refresh_small_cap import DEFAULT_OUTPUT_DIR as DEFAULT_SMALL_CAP_OUTPUT_DIR
from .refresh_small_cap import DEFAULT_SIGNAL_OUTPUT as DEFAULT_SMALL_CAP_SIGNAL_OUTPUT
from .refresh_supplemental_data import (
    DEFAULT_CONFIG as DEFAULT_SUPPLEMENTAL_CONFIG,
    DEFAULT_SECURITY_MAP as DEFAULT_SUPPLEMENTAL_SECURITY_MAP,
    SOURCE_CHOICES as SUPPLEMENTAL_SOURCE_CHOICES,
)
from .refresh_technical import DEFAULT_PATTERNS as DEFAULT_TECHNICAL_PATTERNS


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


def _min_existing_date(dates: Iterable[pd.Timestamp | None]) -> pd.Timestamp | None:
    available = [date for date in dates if date is not None]
    return min(available) if available else None


def _max_returns_date(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    frame = pd.read_parquet(path, columns=[])
    dates = pd.to_datetime(frame.index, errors="coerce").dropna()
    return pd.Timestamp(dates.max()).normalize() if len(dates) else None


def _report_generated_date(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[:20]:
        if line.startswith("生成时间："):
            value = pd.to_datetime(line.split("：", 1)[1].strip(), errors="coerce")
            return pd.Timestamp(value).normalize() if pd.notna(value) else None
    return pd.Timestamp.fromtimestamp(path.stat().st_mtime).normalize()


def _latest_manifest_date(step: str, run_type: str) -> pd.Timestamp | None:
    suffix = "" if run_type == "production" else f"_{run_type}"
    path = TP_ROOT / "10_pipeline_runs" / "manifests" / step / f"{step}{suffix}_latest.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = pd.to_datetime(payload.get("finished_at"), errors="coerce")
    return pd.Timestamp(value).normalize() if pd.notna(value) else None


def _freshness_entry(name: str, date: pd.Timestamp | None, anchor: pd.Timestamp, window_days: int) -> dict[str, object]:
    if date is None:
        return {"name": name, "date": None, "lag_days": None, "ok": False}
    lag_days = int((date - anchor).days)
    return {
        "name": name,
        "date": date.date().isoformat(),
        "lag_days": lag_days,
        "ok": abs(lag_days) <= window_days,
    }


def _check_freshness(args: argparse.Namespace) -> dict[str, object]:
    window_days = int(getattr(args, "freshness_window_days", 31))
    screen_date = _max_parquet_date(SCREEN_AGGREGATE_PATH, "Date")
    if screen_date is None:
        raise ValueError(f"无法读取 canonical screen 日期: {SCREEN_AGGREGATE_PATH}")
    anchor = pd.Timestamp(args.as_of).normalize() if getattr(args, "as_of", None) else screen_date
    run_type = getattr(args, "run_type", "production")
    candidates_output = Path(getattr(args, "candidates_output", DEFAULT_CANDIDATES))
    portfolio_output = Path(getattr(args, "portfolio_output", DEFAULT_PORTFOLIO))
    report_output = Path(getattr(args, "report_output", REPORTS_DIR / "latest_pipeline_report.md"))
    checks = [
        _freshness_entry("canonical_screen", screen_date, anchor, window_days),
        _freshness_entry("canonical_returns", _max_returns_date(RETURNS_PATH), anchor, window_days),
        _freshness_entry("signal_ml", _max_parquet_date(TP_ROOT / "04_signals" / "ml_signals.parquet", "Date"), anchor, window_days),
        _freshness_entry(
            "signal_technical",
            _max_parquet_date(TP_ROOT / "04_signals" / "technical_signals.parquet", "Date"),
            anchor,
            window_days,
        ),
        _freshness_entry(
            "signal_regime",
            _max_parquet_date(TP_ROOT / "04_signals" / "regime_risk_budget.parquet", "Date"),
            anchor,
            window_days,
        ),
        _freshness_entry(
            "signal_country",
            _max_parquet_date(TP_ROOT / "04_signals" / "country_model_signals.parquet", "Date"),
            anchor,
            window_days,
        ),
        _freshness_entry(
            "signal_small_cap",
            _max_parquet_date(Path(getattr(args, "small_cap_signal_output", DEFAULT_SMALL_CAP_SIGNAL_OUTPUT)), "Date"),
            anchor,
            window_days,
        ),
        _freshness_entry(
            "signal_sector",
            _min_existing_date(
                [
                    _max_csv_date(
                        TP_ROOT / "13_sector_score_model" / "outputs_fs_sector_default" / "sector_scores_latest.csv",
                        "Date",
                    ),
                    _max_csv_date(TP_ROOT / "13_sector_score_model" / "outputs_eu" / "sector_scores_latest.csv", "Date"),
                ]
            ),
            anchor,
            window_days,
        ),
        _freshness_entry("candidates", _max_parquet_date(candidates_output, "candidate_date"), anchor, window_days),
        _freshness_entry("target_weights", _max_parquet_date(portfolio_output, "candidate_date"), anchor, window_days),
        _freshness_entry("report", _report_generated_date(report_output), anchor, window_days),
        _freshness_entry("backtest_manifest", _latest_manifest_date("run_backtest", run_type), anchor, window_days),
    ]
    failed = [item for item in checks if not item["ok"]]
    return {
        "anchor_date": anchor.date().isoformat(),
        "window_days": window_days,
        "status": "passed" if not failed else "failed",
        "checks": checks,
        "failed": failed,
    }


def _experiment_spec(args: argparse.Namespace) -> ExperimentSpec:
    return ExperimentSpec(
        hypothesis_id=getattr(args, "hypothesis_id", None) or "production-pipeline",
        name=getattr(args, "experiment_name", None) or "TP production pipeline",
        universe=getattr(args, "portfolio_region", None),
        sample_start=getattr(args, "start_date", None),
        sample_end=getattr(args, "as_of", None),
        pit_cutoff=getattr(args, "as_of", None),
        cost_assumptions={
            "transaction_cost": getattr(args, "transaction_cost", 0.0),
            "max_turnover": getattr(args, "max_turnover", None),
        },
        effective_trial_count=getattr(args, "effective_trial_count", None),
        component_versions={
            "nav_engine": f"{NAV_ENGINE_ID}:{NAV_ENGINE_VERSION}",
            "optimizer": f"{OPTIMIZER_ID}:{OPTIMIZER_VERSION}",
        },
        tags=("pipeline", getattr(args, "run_type", "production")),
    )


def _experiment_artifacts(child_manifests: list[str], run_all_manifest: Path) -> dict[str, Path]:
    artifacts = {
        f"child_manifest_{index:03d}": Path(path)
        for index, path in enumerate(child_manifests, start=1)
    }
    artifacts["run_all_manifest"] = run_all_manifest
    return artifacts


def run_all(args: argparse.Namespace) -> Path:
    manifest = StepManifest("run_all", vars(args).copy())
    context = PipelineContext.from_args(args)
    experiment = ExperimentRecorder(
        root=getattr(args, "experiment_root", None),
    ).start_run(
        _experiment_spec(args),
        parameters=vars(args),
        parent_run_id=getattr(args, "parent_run_id", None),
    )
    experiment.log_inputs(
        {
            "screen_aggregate": SCREEN_AGGREGATE_PATH,
            "returns": RETURNS_PATH,
            "last_screen": LAST_SCREEN_PATH,
        }
    )
    context.experiment_parent_run_id = experiment.run_id
    manifest.details["experiment_record"] = str(experiment.path)

    try:
        child_manifests = execute_pipeline_steps(context)
        should_check_freshness = not all(
            [
                args.skip_build_candidates,
                args.skip_optimize_portfolio,
                args.skip_backtest,
                args.skip_report,
            ]
        )
        if should_check_freshness:
            freshness = _check_freshness(args)
            manifest.details["freshness"] = freshness
            manifest.add_validation(
                "freshness_gate",
                freshness["status"] == "passed",
                "全链路日期在允许窗口内"
                if freshness["status"] == "passed"
                else "全链路存在过期产物",
                freshness,
            )
            if freshness["status"] != "passed":
                failed = ", ".join(
                    f"{item['name']}={item['date']}" for item in freshness["failed"]
                )
                raise RuntimeError(f"freshness gate failed: {failed}")
        else:
            manifest.add_validation(
                "freshness_gate_skipped",
                True,
                "未执行候选池/组合/回测/报告链路，跳过全链路 freshness gate",
            )

        manifest.details["pipeline_steps"] = [step.name for step in pipeline_steps()]
        manifest.details["child_manifests"] = child_manifests
        manifest.add_validation(
            "child_steps_completed",
            True,
            "已完成选定流水线步骤",
            {"count": len(child_manifests)},
        )
        manifest_path = manifest.write("success")
        experiment.log_metrics(
            {
                "child_step_count": len(child_manifests),
                "freshness_status": manifest.details.get("freshness", {}).get("status"),
            }
        )
        experiment.log_artifacts(_experiment_artifacts(child_manifests, manifest_path))
        experiment.complete()
        return manifest_path
    except Exception as exc:
        child_manifests = context.child_manifests
        manifest.details["child_manifests"] = child_manifests
        manifest_path = manifest.write("failed", error=exc)
        experiment.log_artifacts(_experiment_artifacts(child_manifests, manifest_path))
        experiment.fail(exc)
        raise

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按顺序运行 TP 主流水线")
    parser.add_argument("--as-of", help="目标日期，传给信号、候选池、优化和报告环节")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    parser.add_argument("--hypothesis-id", default="production-pipeline", help="稳定的研究命题 ID")
    parser.add_argument("--experiment-name", default="TP production pipeline", help="实验名称")
    parser.add_argument("--parent-run-id", help="父运行 ID，用于 lineage")
    parser.add_argument("--effective-trial-count", type=int, help="本命题的有效试验次数")
    parser.add_argument("--experiment-root", help="实验记录根目录；默认 10_pipeline_runs/experiments")
    parser.add_argument("--freshness-window-days", type=int, default=31, help="全链路 freshness 允许偏离天数")
    parser.add_argument("--input-month", help="月更输入批次 YYYYMM")
    parser.add_argument("--update-mode", choices=["both", "screen_only", "returns_only"], default="both")
    parser.add_argument("--ciq-dir", help="CIQ 文件或目录")
    parser.add_argument("--skip-ciq", action="store_true", help="月更时跳过 CIQ")
    parser.add_argument("--dry-run-data", action="store_true", help="数据刷新只 dry-run")
    parser.add_argument("--inspect-only-refresh-data", action="store_true", help="数据刷新只检查入口和 canonical 路径")
    parser.add_argument("--skip-refresh-data", action="store_true", help="跳过数据刷新")
    parser.add_argument(
        "--refresh-supplemental-data",
        action="store_true",
        help="在 refresh_data 后运行显式来源的影子补充数据阶段",
    )
    parser.add_argument(
        "--supplemental-source",
        action="append",
        choices=SUPPLEMENTAL_SOURCE_CHOICES,
        help="补充数据来源，可重复",
    )
    parser.add_argument("--supplemental-from-date", default="2000-01-01")
    parser.add_argument("--supplemental-to-date")
    parser.add_argument("--supplemental-config", default=str(DEFAULT_SUPPLEMENTAL_CONFIG))
    parser.add_argument("--supplemental-security-map", default=str(DEFAULT_SUPPLEMENTAL_SECURITY_MAP))
    parser.add_argument("--supplemental-max-jobs", type=int)
    parser.add_argument("--supplemental-timeout-seconds", type=int, default=30)
    parser.add_argument("--supplemental-resume", action="store_true")
    parser.add_argument("--supplemental-dry-run", action="store_true")
    parser.add_argument(
        "--inspect-only-supplemental",
        action="store_true",
        help="只检查现有补充数据分区，不访问外部 API",
    )
    parser.add_argument("--skip-refresh-technical", action="store_true", help="跳过 technical patterns 刷新")
    parser.add_argument("--inspect-only-technical", action="store_true", help="只检查已有 technical patterns，不重算")
    parser.add_argument("--technical-patterns-output", default=str(DEFAULT_TECHNICAL_PATTERNS), help="technical patterns 输出路径")
    parser.add_argument("--technical-max-lag-days", type=int, default=31, help="technical patterns 相对 screen 月末允许滞后天数")
    parser.add_argument("--technical-timeout-seconds", type=int, default=1800)
    parser.add_argument("--skip-export-signals", action="store_true", help="跳过信号导出")
    parser.add_argument("--skip-country", action="store_true", help="导出信号时跳过国家模型")
    parser.add_argument("--skip-refresh-small-cap", action="store_true", help="跳过 Europe small-cap 模型刷新")
    parser.add_argument("--inspect-only-small-cap", action="store_true", help="只检查已有 Europe small-cap 产物，不重算")
    parser.add_argument("--small-cap-output-dir", default=str(DEFAULT_SMALL_CAP_OUTPUT_DIR))
    parser.add_argument("--small-cap-signal-output", default=str(DEFAULT_SMALL_CAP_SIGNAL_OUTPUT))
    parser.add_argument("--small-cap-min-coverage", type=float, default=0.5)
    parser.add_argument("--skip-build-candidates", action="store_true", help="跳过候选池")
    parser.add_argument("--skip-optimize-portfolio", action="store_true", help="跳过组合优化")
    parser.add_argument("--skip-backtest", action="store_true", help="跳过回测")
    parser.add_argument("--skip-report", action="store_true", help="跳过报告")

    parser.add_argument("--all-history-signals", action="store_true", help="信号导出全历史")
    parser.add_argument("--refresh-ml", action="store_true", help="运行 ML_Enhanced Score ML CLI 后再导出 ML 信号")
    parser.add_argument("--inspect-only-ml", action="store_true", help="只检查 Score ML 覆盖，不重算")
    parser.add_argument("--ml-date", action="append", help="Score ML 目标月末日期，可重复")
    parser.add_argument("--ml-from-date", help="Score ML 起始日期")
    parser.add_argument("--ml-to-date", help="Score ML 截止日期")
    parser.add_argument("--ml-universe", action="append", choices=["EU", "US", "OTHER", "EM"], help="Score ML universe，可重复")
    parser.add_argument("--ml-timeout-seconds", type=int, default=7200)
    parser.add_argument("--refresh-regime", action="store_true", help="刷新 Regime detector、webapp 数据和诊断产物")
    parser.add_argument("--regime-oos", action="store_true", help="Regime 使用 OOS 文件")
    parser.add_argument("--regime-region", action="append", choices=["US", "EU"], help="Regime 区域")
    parser.add_argument("--country-output", default=str(TP_ROOT / "04_signals" / "country_model_signals.parquet"))
    parser.add_argument("--country-workbook", default=str(TP_ROOT / "00_screen" / "production_inputs" / "modele_pays.xlsb"))
    parser.add_argument(
        "--country-database",
        default=str(TP_ROOT / "14_country_model" / "data" / "country_model_database.parquet"),
    )

    parser.add_argument("--candidates-output", default=str(DEFAULT_CANDIDATES), help="候选池输出路径")
    parser.add_argument("--top-n", type=int, help="候选池选择前 N 名")
    parser.add_argument("--top-pct", type=float, default=0.10, help="候选池选择比例")
    parser.add_argument("--ml-weight", type=float, default=0.70)
    parser.add_argument("--technical-weight", type=float, default=0.30)
    parser.add_argument("--allocation-weight", type=float, default=0.20)
    parser.add_argument("--candidate-date-policy", choices=["max_component", "min_component"], default="max_component")
    parser.add_argument("--candidate-max-component-lag-days", type=int, default=31)
    parser.add_argument("--allow-stale-technical", action="store_true", help="允许 technical 缺失或过旧时仍生成候选池")
    parser.add_argument("--by-region", action="store_true", help="候选池按 region 分组选")

    parser.add_argument("--portfolio-output", default=str(DEFAULT_PORTFOLIO), help="目标权重输出路径")
    parser.add_argument("--optimizer-method", choices=["constrained", "score_weight", "equal_weight"], default="constrained")
    parser.add_argument("--max-weight", type=float, default=0.05)
    parser.add_argument("--min-weight", type=float, default=0.0)
    parser.add_argument("--benchmark-active-limit", type=float, default=0.03)
    parser.add_argument("--country-margin", type=float, default=0.05)
    parser.add_argument("--sector-margin", type=float, default=0.04)
    parser.add_argument("--max-turnover", type=float)
    parser.add_argument("--transaction-cost", type=float, default=0.001)
    parser.add_argument("--country-tilt-strength", type=float, default=0.15)
    parser.add_argument("--sector-tilt-strength", type=float, default=0.10)
    parser.add_argument("--portfolio-region", help="只优化某一区域")
    parser.add_argument("--old-portfolio", help="旧组合文件，用于估算换手")

    parser.add_argument("--backtest-profile", default="default")
    parser.add_argument("--backtest-user", help="回测产物用户分组")
    parser.add_argument("--inspect-only-backtest", action="store_true", help="回测只 inspect 不运行")
    parser.add_argument("--bench")
    parser.add_argument("--metric", action="append")
    parser.add_argument("--start-date")
    parser.add_argument("--percentile", type=float)
    parser.add_argument("--ptf-name")
    parser.add_argument("--backtest-output-dir")
    parser.add_argument("--backtest-max-weight", type=float)
    parser.add_argument("--sector-neutral", action="store_true")
    parser.add_argument("--top", action="store_true")
    parser.add_argument("--bottom", action="store_true")
    parser.add_argument("--batch", action="store_true")

    parser.add_argument("--report-output", default=str(REPORTS_DIR / "latest_pipeline_report.md"))
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest_path = run_all(args)
    print(f"run_all manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""TP 主流水线总编排入口。"""

from __future__ import annotations

import argparse
import json
from argparse import Namespace
from pathlib import Path
from typing import Iterable

import pandas as pd

from tp_core.data_sources import LAST_SCREEN_PATH, RETURNS_PATH, SCREEN_AGGREGATE_PATH, TP_ROOT

from .build_candidates import DEFAULT_OUTPUT as DEFAULT_CANDIDATES, run_build_candidates
from .common import PORTFOLIOS_DIR, REPORTS_DIR, StepManifest
from .export_signals import run_export_signals
from .generate_report import run_generate_report
from .optimize_portfolio import DEFAULT_OUTPUT as DEFAULT_PORTFOLIO, run_optimize_portfolio
from .refresh_data import run_refresh_data
from .refresh_regime import run_refresh_regime
from .run_backtest import run_backtest_step


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
    window_days = int(getattr(args, "freshness_window_days", 7))
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


def run_all(args: argparse.Namespace) -> Path:
    manifest = StepManifest("run_all", vars(args).copy())
    child_manifests: list[str] = []
    run_type = getattr(args, "run_type", "production")
    candidates_output = getattr(args, "candidates_output", str(DEFAULT_CANDIDATES))
    portfolio_output = getattr(args, "portfolio_output", str(DEFAULT_PORTFOLIO))
    report_output = getattr(args, "report_output", str(REPORTS_DIR / "latest_pipeline_report.md"))
    allocation_weight = getattr(args, "allocation_weight", 0.2)
    min_weight = getattr(args, "min_weight", 0.0)
    benchmark_active_limit = getattr(args, "benchmark_active_limit", 0.02)
    country_margin = getattr(args, "country_margin", 0.03)
    sector_margin = getattr(args, "sector_margin", 0.03)
    max_turnover = getattr(args, "max_turnover", None)
    transaction_cost = getattr(args, "transaction_cost", 0.0)
    country_tilt_strength = getattr(args, "country_tilt_strength", 0.25)
    sector_tilt_strength = getattr(args, "sector_tilt_strength", 0.2)
    try:
        if not args.skip_refresh_data:
            child_manifests.append(
                str(
                    run_refresh_data(
                        Namespace(
                            base_dir=None,
                            input_month=args.input_month,
                            screen_excel=None,
                            returns_delta=None,
                            update_mode=args.update_mode,
                            ciq_dir=args.ciq_dir,
                            skip_ciq=args.skip_ciq,
                            dry_run=args.dry_run_data,
                            inspect_only=args.inspect_only_refresh_data,
                            qa_report=None,
                            run_type=run_type,
                        )
                    )
                )
            )

        regime_refreshed = False
        if args.refresh_regime and not args.skip_export_signals:
            regime_output = str(TP_ROOT / "04_signals" / "regime_risk_budget.parquet")
            child_manifests.append(str(run_refresh_regime(Namespace(regime_output=regime_output, run_type=run_type))))
            regime_refreshed = True

        if not args.skip_export_signals:
            child_manifests.append(
                str(
                    run_export_signals(
                        Namespace(
                            as_of=args.as_of,
                            all_history=args.all_history_signals,
                            skip_ml=False,
                            skip_technical=False,
                            skip_regime=regime_refreshed,
                            skip_country=getattr(args, "skip_country", False),
                            regime_oos=args.regime_oos,
                            region=args.regime_region,
                            patterns=str(TP_ROOT / "03_technical_analysis" / "output" / "patterns.parquet"),
                            ml_output=str(TP_ROOT / "04_signals" / "ml_signals.parquet"),
                            technical_output=str(TP_ROOT / "04_signals" / "technical_signals.parquet"),
                            regime_output=str(TP_ROOT / "04_signals" / "regime_risk_budget.parquet"),
                            country_output=getattr(
                                args,
                                "country_output",
                                str(TP_ROOT / "04_signals" / "country_model_signals.parquet"),
                            ),
                            country_workbook=getattr(
                                args,
                                "country_workbook",
                                str(TP_ROOT / "14_country_model" / "modele_pays.xlsb"),
                            ),
                            country_database=getattr(
                                args,
                                "country_database",
                                str(TP_ROOT / "14_country_model" / "data" / "country_model_database.parquet"),
                            ),
                            run_type=run_type,
                        )
                    )
                )
            )

        if not args.skip_build_candidates:
            child_manifests.append(
                str(
                    run_build_candidates(
                        Namespace(
                            as_of=args.as_of,
                            output=candidates_output,
                            top_n=args.top_n,
                            top_pct=args.top_pct,
                            ml_weight=args.ml_weight,
                            technical_weight=args.technical_weight,
                            allocation_weight=allocation_weight,
                            by_region=args.by_region,
                            signals_dir=str(TP_ROOT / "04_signals"),
                            last_screen=str(LAST_SCREEN_PATH),
                            run_type=run_type,
                        )
                    )
                )
            )

        if not args.skip_optimize_portfolio:
            child_manifests.append(
                str(
                    run_optimize_portfolio(
                        Namespace(
                            as_of=args.as_of,
                            candidates=candidates_output,
                            output=portfolio_output,
                            method=args.optimizer_method,
                            max_weight=args.max_weight,
                            min_weight=min_weight,
                            region=args.portfolio_region,
                            old_portfolio=args.old_portfolio,
                            benchmark_active_limit=benchmark_active_limit,
                            country_margin=country_margin,
                            sector_margin=sector_margin,
                            max_turnover=max_turnover,
                            transaction_cost=transaction_cost,
                            country_tilt_strength=country_tilt_strength,
                            sector_tilt_strength=sector_tilt_strength,
                            run_type=run_type,
                        )
                    )
                )
            )

        if not args.skip_backtest:
            child_manifests.append(
                str(
                    run_backtest_step(
                        Namespace(
                            profile=args.backtest_profile,
                            screen=None,
                            returns=None,
                            user=args.backtest_user,
                            inspect_only=args.inspect_only_backtest,
                            bench=args.bench,
                            metric=args.metric,
                            start_date=args.start_date,
                            percentile=args.percentile,
                            ptf_name=args.ptf_name,
                            output_dir=args.backtest_output_dir,
                            max_weight=args.backtest_max_weight,
                            sector_neutral=args.sector_neutral,
                            top=args.top,
                            bottom=args.bottom,
                            batch=args.batch,
                            run_type=run_type,
                        )
                    )
                )
            )

        if not args.skip_report:
            child_manifests.append(
                str(
                    run_generate_report(
                        Namespace(
                            output=report_output,
                            step=None,
                            run_type=run_type,
                        )
                    )
                )
            )

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
                "全链路日期在允许窗口内" if freshness["status"] == "passed" else "全链路存在过期产物",
                freshness,
            )
            if freshness["status"] != "passed":
                failed = ", ".join(f"{item['name']}={item['date']}" for item in freshness["failed"])
                raise RuntimeError(f"freshness gate failed: {failed}")
        else:
            manifest.add_validation("freshness_gate_skipped", True, "未执行候选池/组合/回测/报告链路，跳过全链路 freshness gate")

        manifest.details["child_manifests"] = child_manifests
        manifest.add_validation("child_steps_completed", True, "已完成选定流水线步骤", {"count": len(child_manifests)})
        return manifest.write("success")
    except Exception as exc:
        manifest.details["child_manifests"] = child_manifests
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按顺序运行 TP 主流水线")
    parser.add_argument("--as-of", help="目标日期，传给信号、候选池、优化和报告环节")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    parser.add_argument("--freshness-window-days", type=int, default=7, help="全链路 freshness 允许偏离天数")
    parser.add_argument("--input-month", help="月更输入批次 YYYYMM")
    parser.add_argument("--update-mode", choices=["both", "screen_only", "returns_only"], default="both")
    parser.add_argument("--ciq-dir", help="CIQ 文件或目录")
    parser.add_argument("--skip-ciq", action="store_true", help="月更时跳过 CIQ")
    parser.add_argument("--dry-run-data", action="store_true", help="数据刷新只 dry-run")
    parser.add_argument("--inspect-only-refresh-data", action="store_true", help="数据刷新只检查入口和 canonical 路径")
    parser.add_argument("--skip-refresh-data", action="store_true", help="跳过数据刷新")
    parser.add_argument("--skip-export-signals", action="store_true", help="跳过信号导出")
    parser.add_argument("--skip-country", action="store_true", help="导出信号时跳过国家模型")
    parser.add_argument("--skip-build-candidates", action="store_true", help="跳过候选池")
    parser.add_argument("--skip-optimize-portfolio", action="store_true", help="跳过组合优化")
    parser.add_argument("--skip-backtest", action="store_true", help="跳过回测")
    parser.add_argument("--skip-report", action="store_true", help="跳过报告")

    parser.add_argument("--all-history-signals", action="store_true", help="信号导出全历史")
    parser.add_argument("--refresh-regime", action="store_true", help="刷新 Regime detector、webapp 数据和诊断产物")
    parser.add_argument("--regime-oos", action="store_true", help="Regime 使用 OOS 文件")
    parser.add_argument("--regime-region", action="append", choices=["US", "EU"], help="Regime 区域")
    parser.add_argument("--country-output", default=str(TP_ROOT / "04_signals" / "country_model_signals.parquet"))
    parser.add_argument("--country-workbook", default=str(TP_ROOT / "14_country_model" / "modele_pays.xlsb"))
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

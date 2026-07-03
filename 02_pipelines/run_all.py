"""TP 主流水线总编排入口。"""

from __future__ import annotations

import argparse
from argparse import Namespace
from pathlib import Path
from typing import Iterable

from tp_core.data_sources import LAST_SCREEN_PATH, TP_ROOT

from .build_candidates import DEFAULT_OUTPUT as DEFAULT_CANDIDATES, run_build_candidates
from .common import PORTFOLIOS_DIR, REPORTS_DIR, StepManifest
from .export_signals import run_export_signals
from .generate_report import run_generate_report
from .optimize_portfolio import DEFAULT_OUTPUT as DEFAULT_PORTFOLIO, run_optimize_portfolio
from .refresh_data import run_refresh_data
from .run_backtest import run_backtest_step


def run_all(args: argparse.Namespace) -> Path:
    manifest = StepManifest("run_all", vars(args).copy())
    child_manifests: list[str] = []
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
                        )
                    )
                )
            )

        if not args.skip_export_signals:
            child_manifests.append(
                str(
                    run_export_signals(
                        Namespace(
                            as_of=args.as_of,
                            all_history=args.all_history_signals,
                            skip_ml=False,
                            skip_technical=False,
                            skip_regime=False,
                            regime_oos=args.regime_oos,
                            region=args.regime_region,
                            patterns=str(TP_ROOT / "03_technical_analysis" / "output" / "patterns.parquet"),
                            ml_output=str(TP_ROOT / "04_signals" / "ml_signals.parquet"),
                            technical_output=str(TP_ROOT / "04_signals" / "technical_signals.parquet"),
                            regime_output=str(TP_ROOT / "04_signals" / "regime_risk_budget.parquet"),
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
                            output=args.candidates_output,
                            top_n=args.top_n,
                            top_pct=args.top_pct,
                            ml_weight=args.ml_weight,
                            technical_weight=args.technical_weight,
                            by_region=args.by_region,
                            signals_dir=str(TP_ROOT / "04_signals"),
                            last_screen=str(LAST_SCREEN_PATH),
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
                            candidates=args.candidates_output,
                            output=args.portfolio_output,
                            method=args.optimizer_method,
                            max_weight=args.max_weight,
                            region=args.portfolio_region,
                            old_portfolio=args.old_portfolio,
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
                        )
                    )
                )
            )

        if not args.skip_report:
            child_manifests.append(
                str(
                    run_generate_report(
                        Namespace(
                            output=args.report_output,
                            step=None,
                        )
                    )
                )
            )

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
    parser.add_argument("--input-month", help="月更输入批次 YYYYMM")
    parser.add_argument("--update-mode", choices=["both", "screen_only", "returns_only"], default="both")
    parser.add_argument("--ciq-dir", help="CIQ 文件或目录")
    parser.add_argument("--skip-ciq", action="store_true", help="月更时跳过 CIQ")
    parser.add_argument("--dry-run-data", action="store_true", help="数据刷新只 dry-run")
    parser.add_argument("--inspect-only-refresh-data", action="store_true", help="数据刷新只检查入口和 canonical 路径")
    parser.add_argument("--skip-refresh-data", action="store_true", help="跳过数据刷新")
    parser.add_argument("--skip-export-signals", action="store_true", help="跳过信号导出")
    parser.add_argument("--skip-build-candidates", action="store_true", help="跳过候选池")
    parser.add_argument("--skip-optimize-portfolio", action="store_true", help="跳过组合优化")
    parser.add_argument("--skip-backtest", action="store_true", help="跳过回测")
    parser.add_argument("--skip-report", action="store_true", help="跳过报告")

    parser.add_argument("--all-history-signals", action="store_true", help="信号导出全历史")
    parser.add_argument("--regime-oos", action="store_true", help="Regime 使用 OOS 文件")
    parser.add_argument("--regime-region", action="append", choices=["US", "EU"], help="Regime 区域")

    parser.add_argument("--candidates-output", default=str(DEFAULT_CANDIDATES), help="候选池输出路径")
    parser.add_argument("--top-n", type=int, help="候选池选择前 N 名")
    parser.add_argument("--top-pct", type=float, default=0.10, help="候选池选择比例")
    parser.add_argument("--ml-weight", type=float, default=0.70)
    parser.add_argument("--technical-weight", type=float, default=0.30)
    parser.add_argument("--by-region", action="store_true", help="候选池按 region 分组选")

    parser.add_argument("--portfolio-output", default=str(DEFAULT_PORTFOLIO), help="目标权重输出路径")
    parser.add_argument("--optimizer-method", choices=["score_weight", "equal_weight"], default="score_weight")
    parser.add_argument("--max-weight", type=float, default=0.05)
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

"""TP 主流水线总编排入口。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

import pandas as pd

from tp_core.data_sources import LAST_SCREEN_PATH, RETURNS_PATH, SCREEN_AGGREGATE_PATH, TP_ROOT
from tp_core.security_nav_engine import NAV_ENGINE_ID, NAV_ENGINE_VERSION
from tp_core.workspace import PIPELINE_MANIFESTS_DIR, SIGNALS_DIR
from tp_experiments import ExperimentRecorder, ExperimentSpec, ModelReleaseStore
from tp_portfolio import OPTIMIZER_ID, OPTIMIZER_VERSION

from .build_candidates import DEFAULT_OUTPUT as DEFAULT_CANDIDATES
from .common import REPORTS_DIR, StepManifest
from .configs import PipelineRunConfig
from .optimize_portfolio import DEFAULT_OUTPUT as DEFAULT_PORTFOLIO
from .orchestration import (
    PipelineContext,
    execute_pipeline_steps,
    pipeline_dag,
    pipeline_steps,
)
from .lineage import (
    ProductionRunBundle,
    new_production_run_id,
    resolve_catalog_release_id,
    resolve_data_release_id,
)
from .freshness import generated_at_freshness, market_data_freshness
from .refresh_small_cap import DEFAULT_OUTPUT_DIR as DEFAULT_SMALL_CAP_OUTPUT_DIR
from .refresh_small_cap import DEFAULT_SIGNAL_OUTPUT as DEFAULT_SMALL_CAP_SIGNAL_OUTPUT
from .refresh_supplemental_data import (
    DEFAULT_CONFIG as DEFAULT_SUPPLEMENTAL_CONFIG,
)
from .refresh_supplemental_data import (
    DEFAULT_SECURITY_MAP as DEFAULT_SUPPLEMENTAL_SECURITY_MAP,
)
from .refresh_supplemental_data import (
    SOURCE_CHOICES as SUPPLEMENTAL_SOURCE_CHOICES,
)
from .refresh_technical import DEFAULT_PATTERNS as DEFAULT_TECHNICAL_PATTERNS

PIPELINE_SIGNAL_ID = "tp.pipeline.composite-signal"
PIPELINE_SIGNAL_VERSION = "1.0.0"


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


def _report_generated_at(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    return pd.Timestamp.fromtimestamp(path.stat().st_mtime, tz="UTC")


def _latest_manifest_generated_at(step: str, run_type: str) -> pd.Timestamp | None:
    suffix = "" if run_type == "production" else f"_{run_type}"
    path = PIPELINE_MANIFESTS_DIR / step / f"{step}{suffix}_latest.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "success":
        return None
    value = pd.to_datetime(payload.get("finished_at"), errors="coerce")
    return pd.Timestamp(value) if pd.notna(value) else None


def _check_freshness(
    config: PipelineRunConfig,
    *,
    production_run_started_at: object,
    explicit_reuse_manifests: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    window_days = config.freshness_window_days
    screen_date = _max_parquet_date(SCREEN_AGGREGATE_PATH, "Date")
    if screen_date is None:
        raise ValueError(f"无法读取 canonical screen 日期: {SCREEN_AGGREGATE_PATH}")
    anchor = pd.Timestamp(config.as_of).normalize() if config.as_of else screen_date
    run_type = config.run_type
    reuse = explicit_reuse_manifests or {}
    candidates_output = Path(config.candidates_output)
    portfolio_output = Path(config.portfolio_output)
    report_output = Path(config.report_output)
    market_dates = [
        ("canonical_screen", screen_date),
        ("canonical_returns", _max_returns_date(RETURNS_PATH)),
        ("signal_ml", _max_parquet_date(SIGNALS_DIR / "ml_signals.parquet", "Date")),
        ("signal_technical", _max_parquet_date(SIGNALS_DIR / "technical_signals.parquet", "Date")),
        ("signal_regime", _max_parquet_date(SIGNALS_DIR / "regime_risk_budget.parquet", "Date")),
        ("signal_country", _max_parquet_date(SIGNALS_DIR / "country_model_signals.parquet", "Date")),
        ("signal_small_cap", _max_parquet_date(Path(config.refresh_small_cap.signal_output), "Date")),
        (
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
        ),
        ("candidates", _max_parquet_date(candidates_output, "candidate_date")),
        ("target_weights", _max_parquet_date(portfolio_output, "candidate_date")),
    ]
    checks = [
        market_data_freshness(
            name,
            date,
            as_of_date=anchor,
            allowed_lag_days=window_days,
        )
        for name, date in market_dates
    ]
    report_reuse = reuse.get("generate_report")
    checks.append(
        generated_at_freshness(
            "report",
            _report_generated_at(report_output),
            production_run_started_at=production_run_started_at,
            reused=report_reuse is not None,
            reuse_source=str(report_reuse.get("manifest_path")) if report_reuse else None,
            reuse_reason=str(report_reuse.get("reason")) if report_reuse else None,
        )
    )
    backtest_reuse = reuse.get("run_backtest")
    checks.append(
        generated_at_freshness(
            "backtest_manifest",
            _latest_manifest_generated_at("run_backtest", run_type),
            production_run_started_at=production_run_started_at,
            reused=backtest_reuse is not None,
            reuse_source=str(backtest_reuse.get("manifest_path")) if backtest_reuse else None,
            reuse_reason=str(backtest_reuse.get("reason")) if backtest_reuse else None,
        )
    )
    failed = [item for item in checks if not item["ok"]]
    return {
        "anchor_date": anchor.date().isoformat(),
        "window_days": window_days,
        "status": "passed" if not failed else "failed",
        "checks": checks,
        "failed": failed,
    }


def _experiment_spec(config: PipelineRunConfig) -> ExperimentSpec:
    return ExperimentSpec(
        hypothesis_id=config.experiment.hypothesis_id,
        name=config.experiment.name,
        universe=config.optimize_portfolio.region,
        sample_start=config.run_backtest.start_date,
        sample_end=config.as_of,
        pit_cutoff=config.as_of,
        cost_assumptions={
            "transaction_cost": config.optimize_portfolio.transaction_cost,
            "max_turnover": config.optimize_portfolio.max_turnover,
        },
        trial_family=config.experiment.trial_family,
        effective_trial_count=config.experiment.effective_trial_count,
        component_versions={
            "nav_engine": f"{NAV_ENGINE_ID}:{NAV_ENGINE_VERSION}",
            "signal": f"{PIPELINE_SIGNAL_ID}:{PIPELINE_SIGNAL_VERSION}",
            "optimizer": f"{OPTIMIZER_ID}:{OPTIMIZER_VERSION}",
        },
        tags=("pipeline", config.run_type),
    )


def _experiment_artifacts(child_manifests: list[str], run_all_manifest: Path) -> dict[str, Path]:
    artifacts = {
        f"child_manifest_{index:03d}": Path(path)
        for index, path in enumerate(child_manifests, start=1)
    }
    artifacts["run_all_manifest"] = run_all_manifest
    return artifacts


def _sync_bundle(bundle: ProductionRunBundle, context: PipelineContext) -> None:
    for step, state in context.step_states.items():
        if state == "produced_this_run" and step in context.step_manifests:
            bundle.record_manifest(step, context.step_manifests[step])
        elif state == "explicitly_reused" and step in context.explicit_reuse_manifests:
            details = context.explicit_reuse_manifests[step]
            bundle.record_reuse(
                step,
                details,
                reason=str(details.get("reason") or "explicit reuse"),
            )
        else:
            bundle.mark(step, state)


def _write_approval(config: PipelineRunConfig) -> dict[str, object]:
    """Return the machine-readable approval state for refresh_data writes."""

    if config.controls.skip_refresh_data:
        return {
            "status": "not_required",
            "source": "skip_refresh_data",
            "approved": False,
        }
    if config.refresh_data.dry_run or config.refresh_data.inspect_only:
        return {
            "status": "not_required",
            "source": "non_writing_mode",
            "approved": False,
        }
    if config.refresh_data.apply:
        return {
            "status": "approved",
            "source": "explicit_cli_apply",
            "approved": True,
        }
    return {
        "status": "blocked",
        "source": "missing_explicit_cli_apply",
        "approved": False,
    }


def run_all(args: argparse.Namespace | PipelineRunConfig) -> Path:
    config = (
        args
        if isinstance(args, PipelineRunConfig)
        else PipelineRunConfig.from_namespace(args)
    )
    production_run_id = new_production_run_id()
    data_release_id = resolve_data_release_id()
    catalog_release_id = resolve_catalog_release_id()
    config.cli_parameters["production_run_id"] = production_run_id
    config.cli_parameters["data_release_id"] = data_release_id
    config.cli_parameters["catalog_release_id"] = catalog_release_id
    manifest_parameters = config.cli_parameters.copy()
    manifest_parameters["_experiment_managed_externally"] = True
    manifest = StepManifest("run_all", manifest_parameters)
    write_approval = _write_approval(config)
    config.cli_parameters["write_approval"] = write_approval
    manifest.details["write_approval"] = write_approval
    manifest.details["production_run_id"] = production_run_id
    manifest.details["data_release_id"] = data_release_id
    manifest.details["catalog_release_id"] = catalog_release_id
    manifest.add_validation(
        "write_approval",
        write_approval["status"] != "blocked",
        "数据写入已由显式 --apply 授权"
        if write_approval["status"] == "approved"
        else "当前模式不执行数据写入"
        if write_approval["status"] == "not_required"
        else "数据刷新必须显式传入 --apply",
        write_approval,
    )
    context = PipelineContext.from_args(config)
    context.production_run_id = production_run_id
    bundle = ProductionRunBundle.start(
        run_type=config.run_type,
        as_of_date=config.as_of,
        input_month=config.cli_parameters.get("input_month"),
        data_release_id=data_release_id,
        catalog_release_id=catalog_release_id,
        model_release_ids=config.model_release_ids,
        production_run_id=production_run_id,
    )
    experiment = ExperimentRecorder(
        root=config.experiment.root,
    ).start_run(
        _experiment_spec(config),
        parameters=config.cli_parameters,
        parent_run_id=config.experiment.parent_run_id,
        run_kind="production" if config.run_type == "production" else "research",
        production_run={
            "production_run_id": production_run_id,
            "data_release_id": data_release_id,
            "model_release_ids": list(config.model_release_ids),
            "reuse_decisions": [],
            "write_approval": write_approval,
        },
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
        if config.run_type == "production":
            for model_release_id in config.model_release_ids:
                ModelReleaseStore(config.experiment.root).require_production(model_release_id)
        if write_approval["status"] == "blocked":
            raise ValueError("run_all 数据刷新写入必须显式传入 --apply；请使用 --dry-run-data、--inspect-only-refresh-data 或 --skip-refresh-data 进行非写入运行")
        previous_parent = os.environ.get("TP_PARENT_EXPERIMENT_RUN_ID")
        os.environ["TP_PARENT_EXPERIMENT_RUN_ID"] = experiment.run_id
        try:
            child_manifests = execute_pipeline_steps(context)
        finally:
            if previous_parent is None:
                os.environ.pop("TP_PARENT_EXPERIMENT_RUN_ID", None)
            else:
                os.environ["TP_PARENT_EXPERIMENT_RUN_ID"] = previous_parent
        _sync_bundle(bundle, context)
        manifest.details["step_states"] = context.step_states
        manifest.details["explicit_reuse_manifests"] = context.explicit_reuse_manifests
        should_check_freshness = not all(
            [
                config.controls.skip_build_candidates,
                config.controls.skip_optimize_portfolio,
                config.controls.skip_backtest,
                config.controls.skip_report,
            ]
        )
        if should_check_freshness:
            freshness = _check_freshness(
                config,
                production_run_started_at=bundle.started_at,
                explicit_reuse_manifests=context.explicit_reuse_manifests,
            )
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
                    f"{item['name']}={item.get('artifact_date', item.get('generated_at'))}: {item['message']}"
                    for item in freshness["failed"]
                )
                raise RuntimeError(f"freshness gate failed: {failed}")
        else:
            manifest.add_validation(
                "freshness_gate_skipped",
                True,
                "未执行候选池/组合/回测/报告链路，跳过全链路 freshness gate",
            )

        manifest.details["pipeline_steps"] = [step.name for step in pipeline_steps()]
        manifest.details["pipeline_dependencies"] = {
            step.name: list(step.dependencies)
            for step in pipeline_dag().ordered_steps()
        }
        manifest.details["child_manifests"] = child_manifests
        manifest.add_validation(
            "child_steps_completed",
            True,
            "已完成选定流水线步骤",
            {"count": len(child_manifests)},
        )
        bundle_path = bundle.finish("success", validations=manifest.validations)
        manifest.details["production_run_bundle"] = str(bundle_path)
        manifest_path = manifest.write("success")
        experiment.log_metrics(
            {
                "child_step_count": len(child_manifests),
                "freshness_status": manifest.details.get("freshness", {}).get("status"),
            }
        )
        artifacts = _experiment_artifacts(child_manifests, manifest_path)
        artifacts["production_run_bundle"] = bundle_path
        experiment.log_artifacts(artifacts)
        experiment.complete()
        return manifest_path
    except Exception as exc:
        child_manifests = context.child_manifests
        _sync_bundle(bundle, context)
        manifest.details["child_manifests"] = child_manifests
        manifest.details["step_states"] = context.step_states
        manifest.details["explicit_reuse_manifests"] = context.explicit_reuse_manifests
        bundle_path = bundle.finish("failed", validations=manifest.validations)
        manifest.details["production_run_bundle"] = str(bundle_path)
        manifest_path = manifest.write("failed", error=exc)
        artifacts = _experiment_artifacts(child_manifests, manifest_path)
        artifacts["production_run_bundle"] = bundle_path
        experiment.log_artifacts(artifacts)
        experiment.fail(exc)
        raise

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按顺序运行 TP 主流水线")
    parser.add_argument("--as-of", help="目标日期，传给信号、候选池、优化和报告环节")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    parser.add_argument(
        "--reuse-manifest",
        help="JSON step->manifest 映射；只有显式映射的旧产物允许复用",
    )
    parser.add_argument(
        "--model-release-id",
        action="append",
        default=[],
        help="生产模型 release ID，可重复传入；不会自动从 research 目录推断",
    )
    parser.add_argument("--hypothesis-id", default="production-pipeline", help="稳定的研究命题 ID")
    parser.add_argument("--experiment-name", default="TP production pipeline", help="实验名称")
    parser.add_argument("--parent-run-id", help="父运行 ID，用于 lineage")
    parser.add_argument("--effective-trial-count", type=int, help="本命题的有效试验次数")
    parser.add_argument(
        "--trial-family",
        default="production-pipeline",
        help="试验族，用于多重试验审计",
    )
    parser.add_argument("--experiment-root", help="实验记录根目录；默认 artifacts/pipeline_runs/experiments")
    parser.add_argument("--freshness-window-days", type=int, default=31, help="全链路 freshness 允许偏离天数")
    parser.add_argument("--input-month", help="月更输入批次 YYYYMM")
    parser.add_argument("--update-mode", choices=["both", "screen_only", "returns_only"], default="both")
    parser.add_argument("--ciq-dir", help="CIQ 文件或目录")
    parser.add_argument("--skip-ciq", action="store_true", help="月更时跳过 CIQ")
    parser.add_argument("--dry-run-data", action="store_true", help="数据刷新只 dry-run")
    parser.add_argument("--inspect-only-refresh-data", action="store_true", help="数据刷新只检查入口和 canonical 路径")
    parser.add_argument("--skip-refresh-data", action="store_true", help="跳过数据刷新")
    parser.add_argument("--apply", action="store_true", help="确认本次 run_all 允许数据刷新写入")
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
    parser.add_argument("--skip-refresh-sector", action="store_true", help="跳过 EU/US 行业模型刷新")
    parser.add_argument("--inspect-only-sector", action="store_true", help="只检查已有行业模型产物")
    parser.add_argument("--sector-screen", default=str(SCREEN_AGGREGATE_PATH))
    parser.add_argument("--sector-returns", default=str(RETURNS_PATH))
    parser.add_argument("--sector-mapping", default=None, help="行业模型 ICB mapping xlsx")
    parser.add_argument(
        "--sector-us-output-dir",
        default=str(TP_ROOT / "13_sector_score_model" / "outputs_fs_sector_default"),
    )
    parser.add_argument(
        "--sector-eu-output-dir",
        default=str(TP_ROOT / "13_sector_score_model" / "outputs_eu"),
    )
    parser.add_argument(
        "--sector-legacy-us-output-dir",
        default=str(TP_ROOT / "13_sector_score_model" / "outputs"),
    )
    parser.add_argument("--sector-start-date", default="2010-01-01")
    parser.add_argument("--sector-score-column", default="score_final")
    parser.add_argument("--sector-top-n", type=int, default=3)
    parser.add_argument("--sector-bottom-n", type=int, default=3)
    parser.add_argument("--skip-refresh-country-model", action="store_true", help="跳过国家模型数据库和信号刷新")
    parser.add_argument("--inspect-only-country-model", action="store_true", help="只检查已有国家模型产物")
    parser.add_argument("--use-existing-country-database", action="store_true", help="国家模型复用已有数据库，不重新读取 xlsb")
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
    parser.add_argument(
        "--refresh-factor-recommendation",
        action="store_true",
        help="显式运行 research-only 月度因子推荐；默认关闭且不影响生产候选池",
    )
    parser.add_argument(
        "--inspect-only-factor-recommendation",
        dest="factor_recommendation_inspect_only",
        action="store_true",
        help="只检查因子推荐已有产物",
    )
    factor_root = TP_ROOT / "16_factor_recommendation_model"
    parser.add_argument("--factor-recommendation-as-of")
    parser.add_argument("--factor-recommendation-screen", default=str(SCREEN_AGGREGATE_PATH))
    parser.add_argument("--factor-recommendation-returns", default=str(RETURNS_PATH))
    parser.add_argument(
        "--factor-recommendation-universe-config",
        default=str(factor_root / "config" / "region_universes_v1.json"),
    )
    parser.add_argument(
        "--factor-recommendation-factor-config",
        default=str(factor_root / "config" / "factor_definitions_v1.json"),
    )
    parser.add_argument(
        "--factor-recommendation-model-config",
        default=str(factor_root / "config" / "model_v1.json"),
    )
    parser.add_argument(
        "--factor-recommendation-output-dir",
        default=str(factor_root / "outputs"),
    )
    parser.add_argument(
        "--factor-recommendation-signal-output",
        default=str(SIGNALS_DIR / "factor_exposure_snapshot_signals.parquet"),
    )
    parser.add_argument("--factor-recommendation-all-history", action="store_true")
    parser.add_argument("--factor-recommendation-use-frozen-model", action="store_true")
    parser.add_argument("--factor-recommendation-minimum-coverage", type=float, default=0.8)
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
    parser.add_argument("--refresh-regime", dest="refresh_regime", action="store_true", default=True, help="刷新 Regime detector、webapp 数据和诊断产物（默认开启）")
    parser.add_argument("--skip-refresh-regime", dest="refresh_regime", action="store_false", help="跳过 Regime detector 刷新")
    parser.add_argument("--regime-oos", action="store_true", help="Regime 使用 OOS 文件")
    parser.add_argument("--regime-region", action="append", choices=["US", "EU"], help="Regime 区域")
    parser.add_argument("--country-output", default=str(SIGNALS_DIR / "country_model_signals.parquet"))
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

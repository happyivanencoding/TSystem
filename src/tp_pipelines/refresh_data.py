"""月更数据刷新 pipeline 入口。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from tp_core.data_sources import LAST_SCREEN_PATH, PRODUCTION_INCOMING_DIR, RETURNS_PATH, SCREEN_AGGREGATE_PATH, TP_ROOT
from tp_core.data_sources import validate_data_sources
from tp_core.returns_audit import audit_returns_file

from .common import StepManifest, path_profile, timestamp


RETURNS_AUDIT_DIR = TP_ROOT / "00_screen" / "qa" / "returns_anomaly_governance"
RETURNS_AUDIT_LATEST = RETURNS_AUDIT_DIR / "returns_extreme_audit_latest.json"
RETURNS_FLAGS_LATEST = RETURNS_AUDIT_DIR / "returns_extreme_flags_latest.csv"
RETURNS_REVIEW_TEMPLATE_LATEST = RETURNS_AUDIT_DIR / "returns_extreme_review_template_latest.csv"


def _load_monthly_update():
    from tp_data import run_monthly_update
    return run_monthly_update


def _extract_last_json_object(text: str) -> dict[str, Any]:
    for match in reversed(list(re.finditer(r"\{\s*\"", text))):
        try:
            return json.loads(text[match.start():])
        except json.JSONDecodeError:
            continue
    raise ValueError("Score ML 生产脚本未返回 JSON 结果")


def _run_score_ml_production() -> dict[str, Any]:
    venv_python = TP_ROOT / ".venv_tp" / "Scripts" / "python.exe"
    python_exe = venv_python if venv_python.exists() else Path(sys.executable)
    result = subprocess.run(
        [str(python_exe), "-m", "tp_models.ml.production"],
        cwd=str(TP_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    payload = _extract_last_json_object(result.stdout)
    payload["python_executable"] = str(python_exe)
    if result.returncode != 0:
        payload["stderr_tail"] = result.stderr[-4000:]
        raise RuntimeError(f"Score ML production failed with exit code {result.returncode}")
    return payload


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _next_archive_path(archive_root: Path, batch_name: str) -> Path:
    base = archive_root / f"{batch_name}_{timestamp()}"
    candidate = base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = archive_root / f"{base.name}_{suffix:02d}"
    return candidate


def _next_file_path(path: Path) -> Path:
    candidate = path
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = path.with_name(f"{path.stem}_{suffix:02d}{path.suffix}")
    return candidate


def _file_fingerprint(path: Path) -> tuple[int, str]:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return path.stat().st_size, digest.hexdigest()


def _archive_processed_input_batch(input_batch_dir: str | None, *, dry_run: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "action": "skipped",
        "reason": None,
        "input_batch_dir": input_batch_dir,
    }
    if dry_run:
        result["reason"] = "dry_run"
        return result
    if not input_batch_dir:
        result["reason"] = "no_standard_input_batch"
        return result

    try:
        incoming_root = PRODUCTION_INCOMING_DIR.resolve()
        source = Path(input_batch_dir).resolve()
        archive_root = (PRODUCTION_INCOMING_DIR.parent / "archive" / "processed_batches").resolve()

        if not source.exists():
            result["reason"] = "input_batch_missing"
            return result
        if not source.is_dir():
            result["reason"] = "input_batch_not_directory"
            return result
        if not _is_relative_to(source, incoming_root):
            result["reason"] = "input_batch_outside_incoming"
            return result

        relative_source = source.relative_to(incoming_root)
        if len(relative_source.parts) != 1:
            result["reason"] = "input_batch_not_direct_child"
            return result

        items = list(source.rglob("*"))
        file_count = sum(1 for item in items if item.is_file())
        dir_count = sum(1 for item in items if item.is_dir())
        consumed_fingerprints = {
            _file_fingerprint(item)
            for item in items
            if item.is_file()
        }
        target = _next_archive_path(archive_root, relative_source.parts[0]).resolve()
        if not _is_relative_to(target, archive_root):
            result["reason"] = "archive_target_outside_processed_batches"
            return result

        archive_root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))

        loose_originals = []
        loose_originals_dir = target / "loose_originals"
        for candidate in incoming_root.iterdir():
            if not candidate.is_file():
                continue
            if _file_fingerprint(candidate) not in consumed_fingerprints:
                continue
            loose_source = candidate.resolve()
            loose_originals_dir.mkdir(parents=True, exist_ok=True)
            loose_target = _next_file_path(loose_originals_dir / candidate.name).resolve()
            if not _is_relative_to(loose_target, loose_originals_dir.resolve()):
                result["reason"] = "loose_original_target_outside_archive"
                return result
            shutil.move(str(loose_source), str(loose_target))
            loose_originals.append(
                {
                    "source_path": str(loose_source),
                    "target_path": str(loose_target),
                }
            )

        result.update(
            {
                "action": "moved",
                "reason": "prod_success",
                "source_path": str(source),
                "target_path": str(target),
                "file_count": file_count,
                "dir_count": dir_count,
                "loose_originals_moved": loose_originals,
            }
        )
        return result
    except Exception as exc:  # pragma: no cover - filesystem failure is recorded in manifest
        result.update(
            {
                "action": "failed",
                "reason": "archive_error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
        )
        return result


def _run_returns_extreme_audit() -> dict[str, Any]:
    report = audit_returns_file(
        RETURNS_PATH,
        report_path=RETURNS_AUDIT_LATEST,
        flagged_csv_path=RETURNS_FLAGS_LATEST,
        review_template_path=RETURNS_REVIEW_TEMPLATE_LATEST,
    )
    returns_profile = path_profile(RETURNS_PATH, parquet=True)
    report_date = str(report.get("date_max", ""))[:10]
    report["current_with_returns"] = report_date == str(_returns_index_max_date())
    report["returns_profile"] = returns_profile
    return report


def _returns_index_max_date() -> str | None:
    frame = pd.read_parquet(RETURNS_PATH, columns=[])
    dates = pd.to_datetime(frame.index, errors="coerce").dropna()
    return dates.max().date().isoformat() if len(dates) else None


def run_refresh_data(args: argparse.Namespace) -> Path:
    parameters = vars(args).copy()
    manifest = StepManifest("refresh_data", parameters)
    manifest.inputs = {
        "production_incoming": path_profile(PRODUCTION_INCOMING_DIR),
        "input_batch": path_profile(PRODUCTION_INCOMING_DIR / args.input_month) if args.input_month else None,
        "screen_before": path_profile(SCREEN_AGGREGATE_PATH, parquet=True),
        "returns_before": path_profile(RETURNS_PATH, parquet=True),
    }
    try:
        if getattr(args, "inspect_only", False):
            data_source_status = validate_data_sources()
            returns_audit = _run_returns_extreme_audit()
            manifest.outputs = {
                "screen_after": path_profile(SCREEN_AGGREGATE_PATH, parquet=True),
                "returns_after": path_profile(RETURNS_PATH, parquet=True),
                "last_screen": path_profile(LAST_SCREEN_PATH, parquet=True),
                "returns_extreme_audit": path_profile(RETURNS_AUDIT_LATEST),
                "returns_extreme_flags": path_profile(RETURNS_FLAGS_LATEST),
                "returns_review_template": path_profile(RETURNS_REVIEW_TEMPLATE_LATEST),
            }
            manifest.details["returns_extreme_audit"] = returns_audit
            manifest.add_validation(
                "canonical_data_sources_exist",
                all(data_source_status.values()),
                "screen_aggregate 和 returns 均存在" if all(data_source_status.values()) else "canonical 数据源缺失",
                data_source_status,
            )
            manifest.add_validation(
                "returns_extreme_audit_current",
                bool(returns_audit.get("current_with_returns")),
                "returns 异常审计覆盖当前 returns 最新日期"
                if returns_audit.get("current_with_returns")
                else "returns 异常审计未覆盖当前 returns 最新日期",
                returns_audit,
            )
            manifest.add_validation("monthly_update_import_skipped", True, "inspect-only 未执行重计算月更")
            return manifest.write("success")

        result = _load_monthly_update()(
            base_dir=args.base_dir,
            screen_excel=args.screen_excel,
            returns_delta=args.returns_delta,
            update_mode=args.update_mode,
            ciq_dir=args.ciq_dir,
            skip_ciq=args.skip_ciq,
            qa_report=args.qa_report,
            input_month=args.input_month,
            dry_run=args.dry_run,
        )
        data_source_status = validate_data_sources()
        returns_audit = _run_returns_extreme_audit()
        manifest.outputs = {
            "screen_after": path_profile(SCREEN_AGGREGATE_PATH, parquet=True),
            "returns_after": path_profile(RETURNS_PATH, parquet=True),
            "last_screen": path_profile(LAST_SCREEN_PATH, parquet=True),
            "qa_report": path_profile(result.get("qa_report_path")) if result.get("qa_report_path") else None,
            "returns_extreme_audit": path_profile(RETURNS_AUDIT_LATEST),
            "returns_extreme_flags": path_profile(RETURNS_FLAGS_LATEST),
            "returns_review_template": path_profile(RETURNS_REVIEW_TEMPLATE_LATEST),
        }
        manifest.details["monthly_update_result"] = result
        manifest.details["returns_extreme_audit"] = returns_audit
        archive_result = _archive_processed_input_batch(
            result.get("input_batch_dir"),
            dry_run=bool(args.dry_run),
        )
        manifest.details["input_batch_archive"] = archive_result
        if args.dry_run or args.update_mode == "returns_only":
            score_ml_result = {
                "action": "skipped",
                "reason": "dry_run" if args.dry_run else "returns_only",
            }
        else:
            score_ml_result = _run_score_ml_production()
        manifest.details["score_ml_production"] = score_ml_result
        manifest.add_validation(
            "canonical_data_sources_exist",
            all(data_source_status.values()),
            "screen_aggregate 和 returns 均存在" if all(data_source_status.values()) else "canonical 数据源缺失",
            data_source_status,
        )
        manifest.add_validation(
            "qa_report_written",
            bool(result.get("qa_report_path")),
            "月更 QA 报告已生成" if result.get("qa_report_path") else "未返回 QA 报告路径",
        )
        manifest.add_validation(
            "returns_extreme_audit_current",
            bool(returns_audit.get("current_with_returns")),
            "returns 异常审计覆盖当前 returns 最新日期"
            if returns_audit.get("current_with_returns")
            else "returns 异常审计未覆盖当前 returns 最新日期",
            returns_audit,
        )
        if result.get("screen_idempotency"):
            manifest.add_validation("screen_idempotency_recorded", True, "screen 幂等性报告已记录")
        if result.get("returns_idempotency"):
            manifest.add_validation("returns_idempotency_recorded", True, "returns 幂等性报告已记录")
        archive_required = not args.dry_run and bool(result.get("input_batch_dir"))
        archive_ok = archive_result.get("action") == "moved" if archive_required else archive_result.get("action") == "skipped"
        manifest.add_validation(
            "input_batch_archived",
            archive_ok,
            "生产输入批次已归档"
            if archive_result.get("action") == "moved"
            else f"生产输入批次归档跳过或失败: {archive_result.get('reason')}",
            archive_result,
        )
        manifest.add_validation(
            "score_ml_production",
            score_ml_result.get("action") in {"updated", "skipped"},
            "Score ML 生产已执行或无缺失月份"
            if score_ml_result.get("action") in {"updated", "skipped"}
            else "Score ML 生产失败",
            score_ml_result,
        )
        return manifest.write("success")
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新 canonical 00_screen/returns 数据并写 pipeline manifest")
    parser.add_argument("--base-dir", help="screen 基础目录，默认使用 00_screen/monthly_update.py 所在目录")
    parser.add_argument("--input-month", help="生产输入批次，格式 YYYYMM")
    parser.add_argument("--screen-excel", help="显式指定本次月更 screen Excel")
    parser.add_argument("--returns-delta", help="显式指定本次 returns 增量 parquet")
    parser.add_argument("--ciq-dir", help="显式指定 CIQ parquet 文件或目录")
    parser.add_argument("--skip-ciq", action="store_true", help="跳过 CIQ merge")
    parser.add_argument("--dry-run", action="store_true", help="只校验和生成 QA，不写 canonical parquet")
    parser.add_argument("--inspect-only", action="store_true", help="只检查 canonical 路径和输入目录，不执行月更重计算")
    parser.add_argument("--qa-report", help="显式指定 QA JSON 输出路径")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    parser.add_argument(
        "--update-mode",
        default="both",
        choices=["both", "screen_only", "returns_only"],
        help="月更模式",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest_path = run_refresh_data(args)
    print(f"refresh_data manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

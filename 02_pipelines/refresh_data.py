"""月更数据刷新 pipeline 入口。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable

from tp_core.data_sources import LAST_SCREEN_PATH, PRODUCTION_INCOMING_DIR, RETURNS_PATH, SCREEN_AGGREGATE_PATH, TP_ROOT
from tp_core.data_sources import validate_data_sources

from .common import StepManifest, path_profile, timestamp


def _load_monthly_update():
    screen_dir = TP_ROOT / "00_screen"
    if str(screen_dir) not in sys.path:
        sys.path.insert(0, str(screen_dir))
    from monthly_update import run_monthly_update

    return run_monthly_update


def _load_score_ml_producer():
    path = TP_ROOT / "03_ml_enhanced" / "produce_score_ml.py"
    spec = importlib.util.spec_from_file_location("tp_score_ml_producer", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 Score ML 生产模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.produce_score_ml


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
            manifest.outputs = {
                "screen_after": path_profile(SCREEN_AGGREGATE_PATH, parquet=True),
                "returns_after": path_profile(RETURNS_PATH, parquet=True),
                "last_screen": path_profile(LAST_SCREEN_PATH, parquet=True),
            }
            manifest.add_validation(
                "canonical_data_sources_exist",
                all(data_source_status.values()),
                "screen_aggregate 和 returns 均存在" if all(data_source_status.values()) else "canonical 数据源缺失",
                data_source_status,
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
        manifest.outputs = {
            "screen_after": path_profile(SCREEN_AGGREGATE_PATH, parquet=True),
            "returns_after": path_profile(RETURNS_PATH, parquet=True),
            "last_screen": path_profile(LAST_SCREEN_PATH, parquet=True),
            "qa_report": path_profile(result.get("qa_report_path")) if result.get("qa_report_path") else None,
        }
        manifest.details["monthly_update_result"] = result
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
            score_ml_result = _load_score_ml_producer()()
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

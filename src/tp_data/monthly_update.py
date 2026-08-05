from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from tp_core.analytics.writers import PartitionWriterResult, update_dataset_partitions

from .fs_sector_history import (
    DEFAULT_FS_SECTOR_WORKBOOK_DIR,
    apply_fs_sector_history_to_frame,
)
from .screen_func import (
    PERF_WINDOWS,
    RISK_COLUMN_MAPPING,
    ScreenProcessor,
    drop_deprecated_em_cluster_columns,
    get_latest_modified_file,
)

VALID_UPDATE_MODES = {"both", "screen_only", "returns_only"}


def create_file_backup(path: Path, operation: str) -> Optional[str]:
    """为真实写入前的 parquet 文件创建带时间戳和操作名的可回滚备份。"""
    source = Path(path)
    if not source.exists():
        return None
    operation_token = "".join(ch if ch.isalnum() else "_" for ch in operation).strip("_") or "backup"
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_dir = source.parent / "backups" / source.stem
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{source.stem}_{stamp}_{operation_token}{source.suffix}"
    shutil.copy2(source, backup_path)
    return str(backup_path)

CORE_WEIGHT_COLUMNS = [
    "Weight in MSCI WORLD",
    "Weight in SP500",
    "Weight in STOXX EUROPE 600",
    "Weight in MSCI EM",
    "Weight in Univ ML EU",
    "Weight in Univ ML US",
    "Weight in Univ ML OTHER",
]


def build_default_paths(base_dir: Optional[str] = None) -> Dict[str, Path]:
    base_path = Path(base_dir) if base_dir else Path(__file__).resolve().parent
    production_inputs_dir = base_path / "production_inputs"
    incoming_dir = production_inputs_dir / "incoming"
    return {
        "base_dir": base_path,
        "production_inputs_dir": production_inputs_dir,
        "incoming_dir": incoming_dir,
        "archive_dir": production_inputs_dir / "archive",
        "legacy_monthly_dir": base_path / "monthly",
        "legacy_returns_dir": base_path / "returns",
        "legacy_ciq_new_dir": base_path / "ciq" / "new",
        "qa_dir": base_path / "qa",
        "screen_path": base_path / "screen_aggregate.parquet",
        "last_screen_path": base_path / "last_screen.parquet",
        "returns_path": base_path / "returns.parquet",
        "mapping_path": base_path / "Transco_FactSet_ICB.xlsx",
    }


def _normalize_input_month(input_month: Optional[str]) -> Optional[str]:
    if input_month is None:
        return None
    normalized = "".join(char for char in str(input_month) if char.isdigit())
    if len(normalized) != 6:
        raise ValueError(f"input_month 必须是 YYYYMM 格式，当前值: {input_month}")
    return normalized


def _resolve_input_batch_dir(paths: Dict[str, Path], input_month: Optional[str]) -> Path:
    incoming_dir = paths["incoming_dir"]
    normalized_month = _normalize_input_month(input_month)
    if normalized_month:
        batch_dir = incoming_dir / normalized_month
        if not batch_dir.is_dir():
            raise FileNotFoundError(
                f"生产输入批次不存在: {batch_dir}。请先把文件放入 production_inputs/incoming/{normalized_month}/。"
            )
        return batch_dir

    if not incoming_dir.is_dir():
        raise FileNotFoundError(
            f"生产输入根目录不存在: {incoming_dir}。请创建 production_inputs/incoming/YYYYMM/。"
        )

    candidates = []
    for path in incoming_dir.iterdir():
        if not path.is_dir():
            continue
        if any((path / subdir).exists() for subdir in ("screen", "returns", "ciq")):
            candidates.append(path)
    if not candidates:
        raise FileNotFoundError(
            f"未找到生产输入批次。请把文件放入 {incoming_dir}\\YYYYMM\\screen|returns|ciq，或显式传入路径。"
        )

    def sort_key(path: Path) -> tuple[int, float, str]:
        return (int(path.name) if path.name.isdigit() else -1, path.stat().st_mtime, path.name)

    return sorted(candidates, key=sort_key)[-1]


def _resolve_screen_excel(input_screen_dir: Path, screen_excel: Optional[str]) -> Path:
    if screen_excel:
        return Path(screen_excel)
    if not input_screen_dir.is_dir():
        raise FileNotFoundError(f"Screen 输入目录不存在: {input_screen_dir}")
    return Path(get_latest_modified_file(str(input_screen_dir), suffixes=(".xlsx",)))


def _resolve_returns_delta(input_returns_dir: Path, returns_delta: Optional[str]) -> Path:
    if returns_delta:
        return Path(returns_delta)
    if not input_returns_dir.is_dir():
        raise FileNotFoundError(f"Returns 输入目录不存在: {input_returns_dir}")
    return Path(
        get_latest_modified_file(
            str(input_returns_dir),
            suffixes=("", ".parquet"),
            excluded_names=("returns.pkl",),
        )
    )


def _resolve_update_mode(update_mode: str) -> str:
    normalized_mode = update_mode.lower()
    if normalized_mode not in VALID_UPDATE_MODES:
        raise ValueError(
            f"不支持的 update_mode: {update_mode}。可选值: {sorted(VALID_UPDATE_MODES)}"
        )
    return normalized_mode


def _resolve_ciq_path(
    paths: Dict[str, Path],
    ciq_dir: Optional[str],
    input_batch_dir: Optional[Path],
) -> Path:
    if ciq_dir:
        return Path(ciq_dir)
    if input_batch_dir is None:
        input_batch_dir = _resolve_input_batch_dir(paths, None)
    return input_batch_dir / "ciq"


def _list_ciq_files(ciq_path: Path) -> Sequence[Path]:
    if not ciq_path.exists():
        raise FileNotFoundError(f"CIQ 路径不存在: {ciq_path}")
    if ciq_path.is_file():
        return [ciq_path]

    files = sorted(path for path in ciq_path.iterdir() if path.is_file())
    if not files:
        raise FileNotFoundError(f"CIQ 目录中没有可读取文件: {ciq_path}")
    return files


def _ensure_isin_column(df: pd.DataFrame) -> pd.DataFrame:
    if "ISIN" in df.columns:
        return df.copy()
    if df.index.name == "ISIN":
        return df.reset_index()
    raise ValueError("DataFrame 缺少 ISIN 列或 ISIN 索引")


def _safe_float(value: Any) -> Optional[float]:
    if pd.isna(value):
        return None
    return float(value)


def _format_timestamp_list(values: pd.Index | pd.Series | Sequence[Any]) -> list[str]:
    timestamps = pd.DatetimeIndex(pd.to_datetime(list(values))).dropna().unique().sort_values()
    return [pd.Timestamp(value).strftime("%Y-%m-%d") for value in timestamps]


def build_returns_idempotency_report(
    returns_history: pd.DataFrame,
    returns_delta: pd.DataFrame,
    returns_merged: pd.DataFrame,
) -> Dict[str, Any]:
    history_index = pd.DatetimeIndex(pd.to_datetime(returns_history.index)).dropna()
    delta_index = pd.DatetimeIndex(pd.to_datetime(returns_delta.index)).dropna()
    merged_index = pd.DatetimeIndex(pd.to_datetime(returns_merged.index)).dropna()

    history_dates = history_index.unique().sort_values()
    delta_dates = delta_index.unique().sort_values()
    merged_dates = merged_index.unique().sort_values()
    overlap_dates = history_dates.intersection(delta_dates).sort_values()
    new_dates = delta_dates.difference(history_dates).sort_values()
    expected_dates = history_dates.union(delta_dates).sort_values()
    missing_history_dates = history_dates.difference(merged_dates).sort_values()

    duplicate_merged_dates = int(merged_index.duplicated(keep=False).sum())
    if duplicate_merged_dates:
        raise ValueError(f"returns 合并后仍存在重复交易日: {duplicate_merged_dates}")
    if len(merged_dates) != len(expected_dates):
        raise ValueError(
            f"returns 合并日期数异常: expected={len(expected_dates)}, actual={len(merged_dates)}"
        )
    if len(missing_history_dates):
        raise ValueError(
            f"returns 合并后丢失历史日期: {_format_timestamp_list(missing_history_dates[:10])}"
        )

    return {
        "history_rows": int(len(returns_history)),
        "delta_rows": int(len(returns_delta)),
        "merged_rows": int(len(returns_merged)),
        "history_unique_dates": int(len(history_dates)),
        "delta_unique_dates": int(len(delta_dates)),
        "overlap_dates": int(len(overlap_dates)),
        "new_dates": int(len(new_dates)),
        "expected_merged_dates": int(len(expected_dates)),
        "merged_unique_dates": int(len(merged_dates)),
        "duplicate_merged_dates": duplicate_merged_dates,
        "overlap_date_min": overlap_dates.min() if len(overlap_dates) else None,
        "overlap_date_max": overlap_dates.max() if len(overlap_dates) else None,
        "new_date_min": new_dates.min() if len(new_dates) else None,
        "new_date_max": new_dates.max() if len(new_dates) else None,
        "mode": "覆盖同日期最后一版，不追加重复日期",
    }


def build_screen_idempotency_report(
    old_base: pd.DataFrame,
    new_base: pd.DataFrame,
    merged: pd.DataFrame,
) -> Dict[str, Any]:
    old_df = _ensure_isin_column(old_base)
    new_df = _ensure_isin_column(new_base)
    merged_df = _ensure_isin_column(merged)
    old_df["Date"] = pd.to_datetime(old_df["Date"])
    new_df["Date"] = pd.to_datetime(new_df["Date"])
    merged_df["Date"] = pd.to_datetime(merged_df["Date"])

    target_dates = pd.DatetimeIndex(new_df["Date"].dropna().unique()).sort_values()
    if len(target_dates) == 0:
        raise ValueError("new_base 中没有可用于幂等检查的 Date")

    old_target = old_df.loc[old_df["Date"].isin(target_dates)]
    old_non_target_rows = int((~old_df["Date"].isin(target_dates)).sum())
    merged_non_target_rows = int((~merged_df["Date"].isin(target_dates)).sum())
    new_unique_keys = int(new_df.drop_duplicates(subset=["ISIN", "Date"]).shape[0])
    expected_rows = old_non_target_rows + new_unique_keys

    if merged_non_target_rows != old_non_target_rows:
        raise ValueError(
            f"screen 合并后非目标月份行数变化: before={old_non_target_rows}, after={merged_non_target_rows}"
        )
    if len(merged_df) != expected_rows:
        raise ValueError(f"screen 合并行数异常: expected={expected_rows}, actual={len(merged_df)}")

    shared_key_count = 0
    common_values_equal = None
    common_columns = sorted((set(old_target.columns) & set(new_df.columns)) - {"ISIN", "Date"})
    if len(old_target) and common_columns:
        old_keyed = old_target.set_index(["ISIN", "Date"], drop=False).sort_index()
        new_keyed = new_df.set_index(["ISIN", "Date"], drop=False).sort_index()
        shared_index = old_keyed.index.intersection(new_keyed.index)
        shared_key_count = int(len(shared_index))
        if shared_key_count:
            old_values = old_keyed.loc[shared_index, common_columns]
            new_values = new_keyed.loc[shared_index, common_columns]
            common_values_equal = bool(old_values.equals(new_values))

    return {
        "target_dates": _format_timestamp_list(target_dates),
        "old_rows": int(len(old_df)),
        "new_rows": int(len(new_df)),
        "old_target_rows_replaced": int(len(old_target)),
        "new_unique_keys": new_unique_keys,
        "old_non_target_rows_preserved": old_non_target_rows,
        "merged_non_target_rows": merged_non_target_rows,
        "expected_rows_after_merge": expected_rows,
        "merged_rows": int(len(merged_df)),
        "shared_existing_keys": shared_key_count,
        "common_values_equal_before_recalculation": common_values_equal,
        "mode": "只替换 new_base 覆盖的目标月份；非目标月份行数必须保持不变",
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime, pd.Timestamp)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_qa_report(
    report: Dict[str, Any],
    qa_report: Optional[str],
    qa_dir: Path,
    month_date: Optional[pd.Timestamp] = None,
) -> str:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    if qa_report:
        report_path = Path(qa_report)
    else:
        month_suffix = month_date.strftime("%Y%m%d") if month_date is not None else "returns"
        report_path = qa_dir / f"monthly_update_{timestamp}_{month_suffix}.json"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, default=_json_default)
    return str(report_path)


def refresh_derived_screen_outputs(
    screen_df: pd.DataFrame,
    screen_path: Path,
    last_screen_path: Path,
    write: bool = True,
) -> Dict[str, Any]:
    screen = _ensure_isin_column(screen_df)
    screen["Date"] = pd.to_datetime(screen["Date"])
    latest_date = screen["Date"].max()
    latest_screen = screen.loc[screen["Date"] == latest_date].set_index("ISIN")

    screen_5y_path = screen_path.with_name(f"{screen_path.stem}_5Y{screen_path.suffix}")
    cutoff_date = latest_date - pd.DateOffset(years=5)
    screen_5y = screen.loc[screen["Date"] >= cutoff_date].set_index("ISIN")

    if write:
        last_screen_path.parent.mkdir(parents=True, exist_ok=True)
        latest_screen.to_parquet(last_screen_path)
        screen_5y.to_parquet(screen_5y_path)

    return {
        "latest_date": latest_date,
        "last_screen_path": str(last_screen_path),
        "last_screen_rows": int(len(latest_screen)),
        "screen_5y_path": str(screen_5y_path),
        "screen_5y_rows": int(len(screen_5y)),
        "write_skipped": not write,
    }


def apply_ciq_history_to_frame(
    screen_df: pd.DataFrame,
    ciq_dir: Path,
    processor: Optional[ScreenProcessor] = None,
) -> tuple[pd.DataFrame, Dict[str, Any]]:
    ciq_files = _list_ciq_files(ciq_dir)
    parts = [pd.read_parquet(path) for path in ciq_files]
    ciq = drop_deprecated_em_cluster_columns(pd.concat(parts, ignore_index=True))
    index_artifact_columns = [column for column in ciq.columns if str(column).startswith("__index_level_")]
    if index_artifact_columns:
        ciq = ciq.drop(columns=index_artifact_columns)

    missing_columns = [column for column in ("ISIN", "Date") if column not in ciq.columns]
    if missing_columns:
        raise KeyError(f"CIQ 数据缺少键列: {missing_columns}")

    ciq_raw_rows = int(len(ciq))
    ciq["ISIN"] = ciq["ISIN"].astype("string")
    ciq["Date"] = pd.to_datetime(ciq["Date"], errors="coerce") + pd.offsets.MonthEnd(0)
    ciq = ciq.dropna(subset=["ISIN", "Date"])
    ciq = ciq.drop_duplicates(subset=["ISIN", "Date"], keep="last")

    screen = drop_deprecated_em_cluster_columns(_ensure_isin_column(screen_df))
    screen["ISIN"] = screen["ISIN"].astype("string")
    screen["Date"] = pd.to_datetime(screen["Date"])
    columns_before = set(screen.columns)
    rows_before = int(len(screen))

    key_columns = {"ISIN", "Date"}
    overlap_columns = sorted((set(screen.columns) & set(ciq.columns)) - key_columns)
    ciq_only_columns = sorted(set(ciq.columns) - set(screen.columns) - key_columns)

    ciq_dates = pd.DatetimeIndex(ciq["Date"].dropna().unique())
    target_mask = screen["Date"].isin(ciq_dates)
    target_columns = ["ISIN", "Date", *overlap_columns]
    target = screen.loc[target_mask, target_columns].copy()
    target["__row_id"] = target.index

    payload_columns = ["ISIN", "Date", *overlap_columns, *ciq_only_columns]
    ciq_payload = ciq[payload_columns].copy()
    ciq_payload["__ciq_match"] = True
    merged_target = target.merge(ciq_payload, on=["ISIN", "Date"], how="left", suffixes=("", "_ciq"))
    matched_screen_rows = int(merged_target["__ciq_match"].eq(True).sum())

    filled_cells_by_column: Dict[str, int] = {}
    for column in overlap_columns:
        ciq_column = f"{column}_ciq"
        if ciq_column not in merged_target.columns:
            continue
        fill_mask = merged_target[column].isna() & merged_target[ciq_column].notna()
        filled_cells_by_column[column] = int(fill_mask.sum())
        if fill_mask.any():
            row_ids = merged_target.loc[fill_mask, "__row_id"].to_numpy()
            values = merged_target.loc[fill_mask, ciq_column].to_numpy()
            screen.loc[row_ids, column] = values

    for column in ciq_only_columns:
        if column not in screen.columns:
            screen[column] = pd.NA
        value_mask = merged_target[column].notna()
        if value_mask.any():
            row_ids = merged_target.loc[value_mask, "__row_id"].to_numpy()
            values = merged_target.loc[value_mask, column].to_numpy()
            screen.loc[row_ids, column] = values

    if processor is not None:
        processor.validate_unique_keys(screen)

    output = screen.set_index("ISIN")
    if "Symbol" in output.columns:
        output["Symbol"] = output["Symbol"].astype("str")

    if int(len(output)) != rows_before:
        raise ValueError(f"CIQ 合并不应改变 screen 行数: before={rows_before}, after={len(output)}")

    result = {
        "ciq_path": str(ciq_dir),
        "ciq_files": [str(path) for path in ciq_files],
        "backup_path": None,
        "raw_rows": ciq_raw_rows,
        "rows_after_key_cleanup": int(len(ciq)),
        "matched_screen_rows": matched_screen_rows,
        "overlap_columns": overlap_columns,
        "new_columns": sorted(set(screen.columns) - columns_before),
        "ciq_only_columns": ciq_only_columns,
        "ignored_index_artifact_columns": index_artifact_columns,
        "filled_cells_total": int(sum(filled_cells_by_column.values())),
        "filled_cells_by_column": filled_cells_by_column,
        "output_rows": int(len(output)),
        "output_columns": int(len(output.columns)),
        "idempotency_mode": "只填充 screen 中为空的重叠字段；不覆盖已有非空值，不改变行数",
    }
    return output, result

def merge_ciq_history(
    screen_path: Path,
    ciq_dir: Path,
    processor: Optional[ScreenProcessor] = None,
) -> Dict[str, Any]:
    screen_df = pd.read_parquet(screen_path)
    output, result = apply_ciq_history_to_frame(screen_df, ciq_dir, processor=processor)

    backup_path = None
    if processor is not None:
        backup_path = processor.create_backup(str(screen_path), operation="before_ciq_merge")
    result["backup_path"] = backup_path

    output.to_parquet(screen_path, index=True)
    return result


def build_returns_qa_report(
    returns_df: pd.DataFrame,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    returns_index = pd.DatetimeIndex(pd.to_datetime(returns_df.index)).sort_values()
    duplicate_dates = int(returns_index.duplicated(keep=False).sum())
    warnings = []
    if duplicate_dates:
        warnings.append(f"returns 存在重复交易日: {duplicate_dates}")

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "qa_passed": not warnings,
        "warnings": warnings,
        "update_result": result,
        "returns": {
            "rows": int(len(returns_df)),
            "columns": int(len(returns_df.columns)),
            "date_min": returns_index.min() if len(returns_index) else None,
            "date_max": returns_index.max() if len(returns_index) else None,
            "duplicate_dates": duplicate_dates,
        },
    }


def build_monthly_qa_report(
    screen_df: pd.DataFrame,
    returns_df: pd.DataFrame,
    latest_date: pd.Timestamp,
    result: Dict[str, Any],
    ciq_result: Optional[Dict[str, Any]],
    fs_sector_result: Optional[Dict[str, Any]],
    derived_outputs: Dict[str, Any],
) -> Dict[str, Any]:
    warnings = []
    screen = _ensure_isin_column(screen_df)
    screen["Date"] = pd.to_datetime(screen["Date"])
    latest_date = pd.Timestamp(latest_date)
    latest = screen.loc[screen["Date"] == latest_date].copy()

    duplicate_keys = int(screen.duplicated(subset=["ISIN", "Date"], keep=False).sum())
    if duplicate_keys:
        warnings.append(f"screen_aggregate 存在重复 (ISIN, Date): {duplicate_keys}")

    returns_index = pd.DatetimeIndex(pd.to_datetime(returns_df.index)).sort_values()
    returns_columns = {str(column) for column in returns_df.columns}
    sedol_missing_count = None
    sedol_missing_sample: Sequence[str] = []
    valid_sedol_count = 0
    if "Company SEDOL" in latest.columns:
        sedol = latest["Company SEDOL"].astype("string").str.strip()
        valid_mask = sedol.notna() & (sedol != "") & (sedol.str.lower() != "nan")
        valid_sedol = sedol.loc[valid_mask].astype(str)
        valid_sedol_count = int(len(valid_sedol))
        missing_sedol = sorted(set(valid_sedol) - returns_columns)
        sedol_missing_count = int(len(missing_sedol))
        sedol_missing_sample = missing_sedol[:20]
        if sedol_missing_count:
            warnings.append(f"latest 有效 SEDOL 在 returns.columns 缺失: {sedol_missing_count}")
    else:
        warnings.append("latest 缺少 Company SEDOL 列")

    weight_sums = {}
    for column in CORE_WEIGHT_COLUMNS:
        if column not in latest.columns:
            weight_sums[column] = {"exists": False}
            warnings.append(f"latest 缺少权重列: {column}")
            continue
        non_null = int(latest[column].notna().sum())
        weight_sum = _safe_float(latest[column].sum(skipna=True))
        weight_sums[column] = {
            "exists": True,
            "non_null": non_null,
            "sum": weight_sum,
        }
        if non_null and weight_sum is not None and abs(weight_sum - 1.0) > 1e-4:
            warnings.append(f"latest 权重列 {column} sum={weight_sum:.8f}，偏离 1")


    risk_columns = {}
    latest_rows = int(len(latest))
    for column in RISK_COLUMN_MAPPING.values():
        exists = column in screen.columns
        latest_non_null = int(latest[column].notna().sum()) if exists else 0
        total_non_null = int(screen[column].notna().sum()) if exists else 0
        latest_missing_rate = None
        if exists and latest_rows:
            latest_missing_rate = 1.0 - latest_non_null / latest_rows
        risk_columns[column] = {
            "exists": exists,
            "latest_non_null": latest_non_null,
            "total_non_null": total_non_null,
            "latest_missing_rate": latest_missing_rate,
        }
        if not exists:
            warnings.append(f"风险列未落库: {column}")
        elif latest_non_null == 0:
            warnings.append(f"风险列 latest 全为空: {column}")

    perf_columns = {}
    for column in PERF_WINDOWS:
        exists = column in latest.columns
        latest_non_null = int(latest[column].notna().sum()) if exists else 0
        perf_columns[column] = {
            "exists": exists,
            "latest_non_null": latest_non_null,
        }
        if not exists:
            warnings.append(f"Perf 列未落库: {column}")

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "qa_passed": not warnings,
        "warnings": warnings,
        "update_result": result,
        "derived_outputs": derived_outputs,
        "screen": {
            "rows": int(len(screen)),
            "columns": int(len(screen.columns)),
            "date_min": screen["Date"].min(),
            "date_max": screen["Date"].max(),
            "latest_date": latest_date,
            "latest_rows": latest_rows,
            "duplicate_keys": duplicate_keys,
        },
        "returns": {
            "rows": int(len(returns_df)),
            "columns": int(len(returns_df.columns)),
            "date_min": returns_index.min() if len(returns_index) else None,
            "date_max": returns_index.max() if len(returns_index) else None,
            "duplicate_dates": int(returns_index.duplicated(keep=False).sum()),
        },
        "latest_sedol_coverage": {
            "valid_sedol_count": valid_sedol_count,
            "missing_in_returns_count": sedol_missing_count,
            "missing_in_returns_sample": sedol_missing_sample,
        },
        "weight_sums": weight_sums,
        "risk_columns": risk_columns,
        "perf_columns": perf_columns,
        "ciq_merge": ciq_result,
        "fs_sector_merge": fs_sector_result,
    }


def _publish_partitioned_frame(
    frame: pd.DataFrame,
    *,
    dataset_name: str,
    root: Path,
    affected_dates: Sequence[Any],
    apply: bool,
    source_run_id: str,
    compatibility_export_paths: Sequence[Path],
) -> PartitionWriterResult:
    """Send a post-update frame through the immutable partition writer."""

    with tempfile.TemporaryDirectory(prefix=f"tp-{dataset_name}-writer-") as temporary_dir:
        snapshot = Path(temporary_dir) / f"{dataset_name}.parquet"
        if dataset_name == "screen":
            _ensure_isin_column(frame).to_parquet(snapshot, index=False)
        else:
            frame.to_parquet(snapshot, index=True)
        return update_dataset_partitions(
            snapshot,
            dataset_name=dataset_name,
            root=root,
            affected_dates=affected_dates,
            apply=apply,
            source_run_id=source_run_id,
            compatibility_export_paths=tuple(compatibility_export_paths),
        )


def run_monthly_update(
    base_dir: Optional[str] = None,
    screen_excel: Optional[str] = None,
    returns_delta: Optional[str] = None,
    update_mode: str = "both",
    ciq_dir: Optional[str] = None,
    skip_ciq: bool = False,
    fs_sector_dir: Optional[str] = None,
    skip_fs_sector: bool = False,
    qa_report: Optional[str] = None,
    input_month: Optional[str] = None,
    dry_run: bool = False,
    partition_writer: bool = False,
) -> Dict[str, Any]:
    paths = build_default_paths(base_dir)
    update_mode = _resolve_update_mode(update_mode)
    update_screen = update_mode in {"both", "screen_only"}
    update_returns = update_mode in {"both", "returns_only"}

    input_batch_dir = None
    if (update_screen and screen_excel is None) or (update_returns and returns_delta is None) or (
        update_screen and not skip_ciq and ciq_dir is None
    ):
        input_batch_dir = _resolve_input_batch_dir(paths, input_month)

    ciq_path = None
    if update_screen and not skip_ciq:
        ciq_path = _resolve_ciq_path(paths, ciq_dir, input_batch_dir)
        _list_ciq_files(ciq_path)

    processor = ScreenProcessor(
        str(paths["mapping_path"]),
        str(paths["returns_path"]),
    )

    returns_updated = None
    returns_delta_path = None
    returns_affected_dates: Sequence[Any] = ()
    returns_idempotency = None
    if update_returns:
        returns_history = pd.read_parquet(paths["returns_path"])
        input_returns_dir = (input_batch_dir / "returns") if input_batch_dir is not None else paths["incoming_dir"]
        returns_delta_path = _resolve_returns_delta(input_returns_dir, returns_delta)
        returns_delta_df = pd.read_parquet(returns_delta_path)
        returns_affected_dates = tuple(pd.to_datetime(returns_delta_df.index, errors="coerce").dropna())
        returns_updated = processor.merge_returns_history(returns_history, returns_delta_df)
        returns_idempotency = build_returns_idempotency_report(
            returns_history,
            returns_delta_df,
            returns_updated,
        )
    elif update_screen:
        returns_updated = pd.read_parquet(paths["returns_path"])

    result: Dict[str, Any] = {
        "update_mode": update_mode,
        "dry_run": bool(dry_run),
        "update_screen": update_screen,
        "update_returns": update_returns,
        "input_month": _normalize_input_month(input_month),
        "input_batch_dir": str(input_batch_dir) if input_batch_dir else None,
        "screen_excel": None,
        "returns_delta": str(returns_delta_path) if returns_delta_path else None,
        "backup_path": None,
        "returns_backup_path": None,
        "month_date": None,
        "last_screen_path": str(paths["last_screen_path"]),
        "screen_path": str(paths["screen_path"]),
        "returns_path": str(paths["returns_path"]),
        "ciq_path": str(ciq_path) if ciq_path else None,
        "ciq_skipped": bool(skip_ciq or not update_screen),
        "ciq_result": None,
        "fs_sector_dir": str(Path(fs_sector_dir)) if fs_sector_dir else str(DEFAULT_FS_SECTOR_WORKBOOK_DIR),
        "fs_sector_skipped": bool(skip_fs_sector or not update_screen),
        "fs_sector_result": None,
        "fs_sector_backup_path": None,
        "qa_report_path": None,
        "returns_idempotency": returns_idempotency,
        "screen_idempotency": None,
        "write_actions": [],
        "partition_writer": bool(partition_writer),
    }

    if returns_updated is not None:
        returns_index = pd.DatetimeIndex(pd.to_datetime(returns_updated.index)).sort_values()
        result["returns_last_date"] = (
            returns_index.max().strftime("%Y-%m-%d") if len(returns_index) else None
        )
        result["returns_rows"] = int(len(returns_updated))

    if not update_screen:
        if dry_run:
            result["write_actions"].append("dry-run: 未写入 returns.parquet")
        elif partition_writer:
            returns_result = _publish_partitioned_frame(
                returns_updated,
                dataset_name="returns_wide",
                root=paths["base_dir"].parent,
                affected_dates=returns_affected_dates,
                apply=True,
                source_run_id=f"monthly-update-{result.get('input_month') or 'returns'}",
                compatibility_export_paths=(paths["returns_path"],),
            )
            result["partition_writer_returns"] = returns_result.as_dict()
            result["write_actions"].append("partition-writer: returns_wide")
        else:
            print("Saving returns update only...")
            returns_backup_path = create_file_backup(paths["returns_path"], operation="before_returns_update")
            result["returns_backup_path"] = returns_backup_path
            if returns_backup_path:
                result["write_actions"].append(f"backup: {returns_backup_path}")
            returns_updated.to_parquet(paths["returns_path"])
            result["write_actions"].append(str(paths["returns_path"]))
        qa_data = build_returns_qa_report(returns_updated, result)
        result["qa_report_path"] = write_qa_report(
            qa_data,
            qa_report,
            paths["qa_dir"],
            month_date=None,
        )
        return result

    input_screen_dir = (input_batch_dir / "screen") if input_batch_dir is not None else paths["incoming_dir"]
    screen_excel_path = _resolve_screen_excel(input_screen_dir, screen_excel)
    result["screen_excel"] = str(screen_excel_path)

    print("Loading monthly screen...")
    new_base = processor.read_new_FS_screen(str(screen_excel_path))
    new_base = processor.FactSet_ICB_Mapping(new_base)
    new_base = processor.add_score_multifacteur(new_base)
    new_base = processor.rebalance_weight_sum_to_1(new_base)
    new_base = processor.add_univ_ml(new_base)
    new_base = processor.normalize_benchmark_market_value_column(new_base)
    if "Symbol" in new_base.columns:
        new_base["Symbol"] = new_base["Symbol"].astype("str")

    month_dates = pd.DatetimeIndex(pd.to_datetime(new_base["Date"]).dropna().unique()).sort_values()
    if len(month_dates) != 1:
        raise ValueError(f"月更文件必须只包含一个月末日期，当前检测到 {len(month_dates)} 个日期")

    processor.validate_unique_keys(new_base)

    print("Loading historical screen...")
    old_base = pd.read_parquet(paths["screen_path"])
    old_base = processor.normalize_benchmark_market_value_column(old_base)
    processor.validate_unique_keys(old_base)
    if dry_run:
        backup_path = None
        result["write_actions"].append("dry-run: 未创建 screen 备份")
    else:
        backup_path = processor.create_backup(str(paths["screen_path"]), operation="before_monthly_update")

    print("Merging monthly snapshot...")
    df_aggregate = processor.merge_monthly_snapshot(old_base, new_base)
    result["screen_idempotency"] = build_screen_idempotency_report(old_base, new_base, df_aggregate)

    print("Calculating risk metrics...")
    risk_metrics = processor.calculate_risk_metrics(df_aggregate, returns_df=returns_updated)
    date_last = month_dates.max()
    risk_data = processor.prepare_risk_data_for_merge(risk_metrics, date_last)
    df_combined = processor.merge_risk_data(df_aggregate, risk_data)

    print("Adding monthly performance...")
    df_combined = processor.add_perf(
        df_combined,
        target_dates=month_dates,
        returns_df=returns_updated,
    )
    processor.validate_unique_keys(df_combined)

    print("Saving results..." if not dry_run else "Dry-run: validating outputs without writing...")
    if update_returns and not partition_writer:
        if dry_run:
            result["write_actions"].append("dry-run: 未写入 returns.parquet")
        else:
            returns_backup_path = create_file_backup(paths["returns_path"], operation="before_returns_update")
            result["returns_backup_path"] = returns_backup_path
            if returns_backup_path:
                result["write_actions"].append(f"backup: {returns_backup_path}")
            returns_updated.to_parquet(paths["returns_path"])
            result["write_actions"].append(str(paths["returns_path"]))

    if partition_writer:
        result["write_actions"].append("partition-writer: deferred screen manifest publish")
    elif dry_run:
        result["write_actions"].append("dry-run: 未写入 screen_aggregate.parquet")
    else:
        processor.save_results(df_combined, str(paths["screen_path"]))
        result["write_actions"].append(str(paths["screen_path"]))

    ciq_result = None
    if skip_ciq:
        print("Skipping CIQ merge...")
        final_screen = df_combined if (dry_run or partition_writer) else pd.read_parquet(paths["screen_path"])
    else:
        print("Merging CIQ history..." if not dry_run else "Dry-run: validating CIQ merge without writing...")
        if dry_run or partition_writer:
            final_screen, ciq_result = apply_ciq_history_to_frame(df_combined, ciq_path, processor=processor)
            result["write_actions"].append(
                "partition-writer: CIQ merge held in post-update snapshot"
                if partition_writer and not dry_run
                else "dry-run: 未写入 CIQ 合并结果"
            )
        else:
            ciq_result = merge_ciq_history(paths["screen_path"], ciq_path, processor=processor)
            final_screen = pd.read_parquet(paths["screen_path"])
            result["write_actions"].append(str(paths["screen_path"]))

    fs_sector_result = None
    if skip_fs_sector:
        print("Skipping FactSet sector history merge...")
    else:
        fs_sector_path = Path(fs_sector_dir) if fs_sector_dir else DEFAULT_FS_SECTOR_WORKBOOK_DIR
        print(
            "Merging FactSet sector history..."
            if not dry_run
            else "Dry-run: validating FactSet sector history merge without writing..."
        )
        if dry_run or partition_writer:
            final_screen, fs_sector_result = apply_fs_sector_history_to_frame(
                final_screen,
                fs_sector_path,
                processor=processor,
            )
            result["write_actions"].append(
                "partition-writer: FS sector merge held in post-update snapshot"
                if partition_writer and not dry_run
                else "dry-run: 未写入 FS sector 合并结果"
            )
        else:
            fs_sector_backup_path = create_file_backup(
                paths["screen_path"],
                operation="before_fs_sector_history_merge",
            )
            result["fs_sector_backup_path"] = fs_sector_backup_path
            if fs_sector_backup_path:
                result["write_actions"].append(f"backup: {fs_sector_backup_path}")
            final_screen, fs_sector_result = apply_fs_sector_history_to_frame(
                final_screen,
                fs_sector_path,
                processor=processor,
            )
            final_screen.to_parquet(paths["screen_path"], index=True)
            final_screen = pd.read_parquet(paths["screen_path"])
            result["write_actions"].append(str(paths["screen_path"]))

    derived_outputs = refresh_derived_screen_outputs(
        final_screen,
        paths["screen_path"],
        paths["last_screen_path"],
        write=not dry_run and not partition_writer,
    )
    if dry_run:
        result["write_actions"].append("dry-run: 未写入 last_screen.parquet / screen_aggregate_5Y.parquet")

    if partition_writer and not dry_run:
        root = paths["base_dir"].parent
        screen_result = _publish_partitioned_frame(
            final_screen,
            dataset_name="screen",
            root=root,
            affected_dates=month_dates,
            apply=True,
            source_run_id=f"monthly-update-{result.get('input_month') or date_last.strftime('%Y%m')}",
            compatibility_export_paths=(
                paths["screen_path"],
                paths["last_screen_path"],
                paths["screen_path"].with_name(f"{paths['screen_path'].stem}_5Y{paths['screen_path'].suffix}"),
            ),
        )
        result["partition_writer_screen"] = screen_result.as_dict()
        if update_returns:
            returns_result = _publish_partitioned_frame(
                returns_updated,
                dataset_name="returns_wide",
                root=root,
                affected_dates=returns_affected_dates,
                apply=True,
                source_run_id=f"monthly-update-{result.get('input_month') or date_last.strftime('%Y%m')}",
                compatibility_export_paths=(paths["returns_path"],),
            )
            result["partition_writer_returns"] = returns_result.as_dict()
        result["write_actions"].append("partition-writer: screen")

    result.update(
        {
            "backup_path": backup_path,
            "month_date": date_last.strftime("%Y-%m-%d"),
            "new_rows": int(len(new_base)),
            "total_rows": int(len(final_screen)),
            "ciq_result": ciq_result,
            "fs_sector_result": fs_sector_result,
            "derived_outputs": derived_outputs,
        }
    )

    qa_data = build_monthly_qa_report(
        final_screen,
        returns_updated,
        derived_outputs["latest_date"],
        result,
        ciq_result,
        fs_sector_result,
        derived_outputs,
    )
    result["qa_report_path"] = write_qa_report(
        qa_data,
        qa_report,
        paths["qa_dir"],
        month_date=pd.Timestamp(derived_outputs["latest_date"]),
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="执行金融数据月更流程", add_help=False)
    parser._optionals.title = "选项"
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出")
    parser.add_argument("--base-dir", help="基础目录，默认使用当前脚本所在目录")
    parser.add_argument("--input-month", help="生产输入批次，格式 YYYYMM；默认取 production_inputs/incoming 下最新批次")
    parser.add_argument("--screen-excel", help="显式指定本次月更的 screen Excel 文件")
    parser.add_argument("--returns-delta", help="显式指定本次 returns 增量文件")
    parser.add_argument("--ciq-dir", help="显式指定 CIQ parquet 文件或目录；默认使用 production_inputs/incoming/YYYYMM/ciq")
    parser.add_argument("--skip-ciq", action="store_true", help="跳过 CIQ 历史补字段合并")
    parser.add_argument("--fs-sector-dir", help="显式指定 Score_Sectoriel_US/EU.xlsm 所在目录")
    parser.add_argument("--skip-fs-sector", action="store_true", help="跳过 FactSet 行业历史补字段合并")
    parser.add_argument("--dry-run", action="store_true", help="只执行读取、合并和 QA 校验，不写入 canonical parquet")
    parser.add_argument(
        "--partition-writer",
        action="store_true",
        help="将 post-update snapshot 写入 immutable 分区并 atomic swap manifest；默认仍走兼容导出",
    )
    parser.add_argument("--qa-report", help="显式指定 QA JSON 输出路径")
    parser.add_argument(
        "--update-mode",
        default="both",
        choices=sorted(VALID_UPDATE_MODES),
        help="更新模式：both / screen_only / returns_only",
    )
    args = parser.parse_args()

    result = run_monthly_update(
        base_dir=args.base_dir,
        screen_excel=args.screen_excel,
        returns_delta=args.returns_delta,
        update_mode=args.update_mode,
        ciq_dir=args.ciq_dir,
        skip_ciq=args.skip_ciq,
        fs_sector_dir=args.fs_sector_dir,
        skip_fs_sector=args.skip_fs_sector,
        qa_report=args.qa_report,
        input_month=args.input_month,
        dry_run=args.dry_run,
        partition_writer=args.partition_writer,
    )
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()

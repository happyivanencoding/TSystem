"""Run the real pipeline entrypoints in isolated scratch roots."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

from .engines import ENGINE_ORDER, engine_code_root
from .parity import compare_frames

_PROVENANCE_FIELDS = frozenset(
    {
        "source_candidates",
        "source_path",
        "output_path",
        "artifact_path",
        "run_directory",
        "generated_at",
        "run_id",
    }
)


def _copy_pipeline_inputs(source_root: Path, target_root: Path) -> None:
    target_root.mkdir(parents=True, exist_ok=True)
    files = (
        "00_screen/screen_aggregate.parquet",
        "00_screen/returns.parquet",
        "00_screen/last_screen.parquet",
        "00_screen/screen_aggregate_5Y.parquet",
    )
    dirs = (
        "artifacts/signals",
        "artifacts/candidates",
        "artifacts/portfolios",
        "artifacts/pipeline_runs/manifests",
        "config/backtest",
        "03_regime_model",
        "13_sector_score_model",
        "14_country_model",
        "15_small_cap_model",
        "16_factor_recommendation_model",
    )
    for relative in files:
        source = source_root / relative
        if source.exists():
            target = target_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for relative in dirs:
        source = source_root / relative
        if source.exists():
            shutil.copytree(source, target_root / relative, dirs_exist_ok=True)


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    peak_rss = 0
    read_bytes = 0
    write_bytes = 0
    initial_io: dict[int, tuple[int, int]] = {}
    try:
        import psutil

        child = psutil.Process(process.pid)
    except Exception:
        child = None
    deadline = time.monotonic() + timeout_seconds
    while process.poll() is None:
        if child is not None:
            try:
                processes = [child, *child.children(recursive=True)]
                for item in processes:
                    memory = item.memory_info()
                    io = item.io_counters()
                    peak_rss = max(peak_rss, int(memory.rss))
                    initial_io.setdefault(item.pid, (int(io.read_bytes), int(io.write_bytes)))
            except Exception:
                pass
        if time.monotonic() > deadline:
            process.kill()
            stdout, stderr = process.communicate()
            return {
                "status": "timeout",
                "returncode": None,
                "wall_seconds": time.perf_counter() - started,
                "peak_rss_bytes": peak_rss,
                "read_bytes": read_bytes,
                "write_bytes": write_bytes,
                "stdout": stdout[-4000:],
                "stderr": stderr[-4000:],
                "command": command,
            }
        time.sleep(0.05)
    stdout, stderr = process.communicate()
    if child is not None:
        try:
            processes = [child, *child.children(recursive=True)]
            for item in processes:
                io = item.io_counters()
                before_read, before_write = initial_io.get(item.pid, (0, 0))
                read_bytes += max(0, int(io.read_bytes) - before_read)
                write_bytes += max(0, int(io.write_bytes) - before_write)
        except Exception:
            pass
    return {
        "status": "passed" if process.returncode == 0 else "failed",
        "returncode": process.returncode,
        "wall_seconds": time.perf_counter() - started,
        "peak_rss_bytes": peak_rss,
        "read_bytes": read_bytes,
        "write_bytes": write_bytes,
        "stdout": stdout[-4000:],
        "stderr": stderr[-4000:],
        "command": command,
    }


def _pipeline_env(
    *,
    code_root: Path,
    pipeline_root: Path,
    engine: str,
    database: Path,
    temp_root: Path,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "TP_ROOT": str(pipeline_root),
            "TP_DATA_ROOT": str(pipeline_root),
            "TP_ARTIFACT_ROOT": str(pipeline_root / "artifacts"),
            "TP_DATA_ENGINE": {
                "current_duckdb": "duckdb",
                "current_hybrid": "hybrid",
            }.get(engine, "legacy_parquet"),
            "TP_DUCKDB_PATH": str(database),
            "TP_DUCKDB_TEMP_DIR": str(temp_root),
            "TP_DUCKDB_READ_ONLY": "true" if engine in {"current_duckdb", "current_hybrid"} else "false",
            "TP_COMPAT_EXPORTS": "true",
            "PYTHONUTF8": "1",
        }
    )
    env["PYTHONPATH"] = str(code_root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _stage_paths(root: Path) -> dict[str, Path]:
    outputs = root / "artifacts" / "benchmark_pipeline"
    signals = outputs / "signals"
    return {
        "signals": signals,
        "ml": signals / "ml_signals.parquet",
        "technical": signals / "technical_signals.parquet",
        "regime": signals / "regime_risk_budget.parquet",
        "country": signals / "country_model_signals.parquet",
        "candidates": outputs / "latest_candidates.parquet",
        "portfolio": outputs / "latest_target_weights.parquet",
        "backtest": outputs / "backtest",
        "report": outputs / "latest_pipeline_report.md",
    }


def _engine_run(
    *,
    engine: str,
    source_root: Path,
    code_root: Path,
    database: Path,
    run_root: Path,
    as_of: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    pipeline_root = run_root / engine
    _copy_pipeline_inputs(source_root, pipeline_root)
    paths = _stage_paths(pipeline_root)
    paths["signals"].mkdir(parents=True, exist_ok=True)
    temp_root = run_root / "temp" / engine
    temp_root.mkdir(parents=True, exist_ok=True)
    env = _pipeline_env(
        code_root=code_root,
        pipeline_root=pipeline_root,
        engine=engine,
        database=database,
        temp_root=temp_root,
    )
    python = sys.executable
    commands = {
        "export_signals": [
            python,
            "-m",
            "tp_pipelines.export_signals",
            "--as-of",
            as_of,
            "--run-type",
            "smoke",
            "--patterns",
            str(source_root / "03_technical_analysis" / "output" / "patterns.parquet"),
            "--returns",
            str(pipeline_root / "00_screen" / "returns.parquet"),
            "--ml-output",
            str(paths["ml"]),
            "--technical-output",
            str(paths["technical"]),
            "--regime-output",
            str(paths["regime"]),
            "--country-output",
            str(paths["country"]),
            "--skip-country",
        ],
        "build_candidates": [
            python,
            "-m",
            "tp_pipelines.build_candidates",
            "--as-of",
            as_of,
            "--run-type",
            "smoke",
            "--output",
            str(paths["candidates"]),
            "--signals-dir",
            str(paths["signals"]),
            "--last-screen",
            str(pipeline_root / "00_screen" / "last_screen.parquet"),
            "--allow-stale-technical",
        ],
        "optimize_portfolio": [
            python,
            "-m",
            "tp_pipelines.optimize_portfolio",
            "--as-of",
            as_of,
            "--run-type",
            "smoke",
            "--candidates",
            str(paths["candidates"]),
            "--output",
            str(paths["portfolio"]),
        ],
        "run_backtest": [
            python,
            "-m",
            "tp_pipelines.run_backtest",
            "--profile",
            "default",
            "--screen",
            str(pipeline_root / "00_screen" / "screen_aggregate.parquet"),
            "--returns",
            str(pipeline_root / "00_screen" / "returns.parquet"),
            "--run-type",
            "smoke",
            "--bench",
            "STOXX EUROPE 600",
            "--metric",
            "Quality Avg Percentile",
            "--start-date",
            "2020-01-31",
            "--percentile",
            "0.2",
            "--top",
            "--output-dir",
            str(paths["backtest"]),
        ],
        "generate_report": [
            python,
            "-m",
            "tp_pipelines.generate_report",
            "--run-type",
            "smoke",
            "--output",
            str(paths["report"]),
        ],
    }
    stages: dict[str, Any] = {}
    for stage, command in commands.items():
        stages[stage] = _run_command(
            command, cwd=pipeline_root, env=env, timeout_seconds=timeout_seconds
        )
    return {
        "engine": engine,
        "root": str(pipeline_root),
        "paths": {key: str(value) for key, value in paths.items()},
        "stages": stages,
    }


def _read_frame(path: str | Path) -> pd.DataFrame | None:
    target = Path(path)
    if not target.exists() or target.suffix.lower() != ".parquet":
        return None
    return pd.read_parquet(target)


def compare_pipeline_outputs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_engine = {str(run["engine"]): run for run in runs}
    pairs = (
        ("pre_duckdb", "current_legacy"),
        ("current_legacy", "current_duckdb"),
        ("pre_duckdb", "current_duckdb"),
        ("current_legacy", "current_hybrid"),
        ("pre_duckdb", "current_hybrid"),
        ("current_duckdb", "current_hybrid"),
    )
    output_names = ("ml", "technical", "regime", "candidates", "portfolio")
    rows: list[dict[str, Any]] = []
    for left_engine, right_engine in pairs:
        left = by_engine.get(left_engine)
        right = by_engine.get(right_engine)
        if not left or not right:
            continue
        for name in output_names:
            left_path = left["paths"].get(name)
            right_path = right["paths"].get(name)
            left_frame = _read_frame(left_path) if left_path else None
            right_frame = _read_frame(right_path) if right_path else None
            if left_frame is None or right_frame is None:
                rows.append(
                    {
                        "left_engine": left_engine,
                        "right_engine": right_engine,
                        "surface": name,
                        "status": "blocked",
                        "reason": "output missing",
                    }
                )
                continue
            candidates = [
                column
                for column in ("Date", "candidate_date", "ISIN", "Company SEDOL", "signal_name")
                if column in left_frame.columns and column in right_frame.columns
            ]
            business_left = left_frame.drop(columns=list(_PROVENANCE_FIELDS), errors="ignore")
            business_right = right_frame.drop(columns=list(_PROVENANCE_FIELDS), errors="ignore")
            result = compare_frames(business_left, business_right, key_columns=candidates[:3])
            result.update(
                {
                    "business_parity": result.get("status"),
                    "provenance_difference": _provenance_difference(left_frame, right_frame),
                    "provenance_fields_ignored": sorted(_PROVENANCE_FIELDS),
                }
            )
            rows.append(
                {
                    "left_engine": left_engine,
                    "right_engine": right_engine,
                    "surface": name,
                    **result,
                }
            )
    return rows


def _provenance_difference(left: pd.DataFrame, right: pd.DataFrame) -> dict[str, Any]:
    differences: dict[str, Any] = {}
    for field in sorted(_PROVENANCE_FIELDS):
        left_present = field in left.columns
        right_present = field in right.columns
        if left_present and right_present:
            if not compare_frames(left[[field]], right[[field]]).get("equal"):
                differences[field] = {
                    "status": "different",
                    "left_sample": left[field].drop_duplicates().head(3).astype(str).tolist(),
                    "right_sample": right[field].drop_duplicates().head(3).astype(str).tolist(),
                }
        elif left_present or right_present:
            differences[field] = {
                "status": "present_on_one_side",
                "left_present": left_present,
                "right_present": right_present,
            }
    return {
        "status": "different" if differences else "same",
        "fields": differences,
    }


def run_pipeline_suite(
    *,
    source_root: str | Path,
    current_root: str | Path,
    pre_duckdb_root: str | Path,
    database: str | Path,
    run_dir: str | Path,
    as_of: str,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    source = Path(source_root).resolve()
    current = Path(current_root).resolve()
    pre = Path(pre_duckdb_root).resolve()
    database_path = Path(database).resolve()
    root = Path(run_dir) / "pipeline_runs"
    root.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for engine in ENGINE_ORDER:
        code_root = engine_code_root(engine, current_root=current, pre_duckdb_root=pre)
        runs.append(
            _engine_run(
                engine=engine,
                source_root=source,
                code_root=code_root,
                database=database_path,
                run_root=root,
                as_of=as_of,
                timeout_seconds=timeout_seconds,
            )
        )
    return {"runs": runs, "parity": compare_pipeline_outputs(runs)}


__all__ = ["compare_pipeline_outputs", "run_pipeline_suite"]

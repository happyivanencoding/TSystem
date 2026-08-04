"""Generate the read-only baseline for the TSystem V2 DuckDB migration.

The audit deliberately uses Parquet metadata and narrow column reads.  It does
not rewrite canonical data and does not import the future analytics package.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Iterable

import pandas as pd
import pyarrow.parquet as pq


TEXT_SUFFIXES = {
    ".bat",
    ".json",
    ".md",
    ".py",
    ".ps1",
    ".toml",
    ".vbs",
    ".yaml",
    ".yml",
}
SKIP_DIRS = {
    ".git",
    ".venv",
    ".venv_tp",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".codex",
    ".idea",
    ".github",
    "99_archive",
    "archive",
    "archives",
    "artifacts",
    "build",
    "dist",
    "generated",
    "node_modules",
    "outputs",
    "pipeline_runs",
    "runs",
    "__pycache__",
}

CANONICAL_NAMES = {
    "screen_aggregate": "00_screen/screen_aggregate.parquet",
    "returns": "00_screen/returns.parquet",
    "last_screen": "00_screen/last_screen.parquet",
    "screen_aggregate_5y": "00_screen/screen_aggregate_5Y.parquet",
}
CANONICAL_TOKENS = (
    "screen_aggregate",
    "last_screen",
    "returns.parquet",
    "SCREEN_AGGREGATE",
    "LAST_SCREEN",
    "RETURNS_PATH",
    "SCREEN_AGGREGATE_5Y",
)
READ_PATTERNS = (
    r"read_parquet",
    r"read_table",
    r"ParquetFile",
    r"read_screen_aggregate",
    r"read_last_screen",
    r"read_screen_5y",
    r"read_returns",
    r"read_csv",
    r"read_excel",
)
WRITE_PATTERNS = (
    r"to_parquet",
    r"write_table",
    r"write_to_dataset",
    r"_atomic_write_parquet",
)


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return value.as_posix()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=root, text=True, stderr=subprocess.STDOUT
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"unavailable: {exc}"


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_text_files(root: Path) -> Iterable[Path]:
    for current, dir_names, file_names in os.walk(root):
        dir_names[:] = sorted(name for name in dir_names if name not in SKIP_DIRS)
        for name in sorted(file_names):
            path = Path(current) / name
            if path.suffix.lower() in TEXT_SUFFIXES:
                yield path


def _scan_io(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    read_regex = [re.compile(pattern) for pattern in READ_PATTERNS]
    write_regex = [re.compile(pattern) for pattern in WRITE_PATTERNS]
    for path in _iter_text_files(root):
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        relative = _relative(path, root)
        for line_number, line in enumerate(lines, start=1):
            read_matches = [pattern.pattern for pattern in read_regex if pattern.search(line)]
            write_matches = [pattern.pattern for pattern in write_regex if pattern.search(line)]
            if not read_matches and not write_matches:
                continue
            operation = "read" if read_matches and not write_matches else "write"
            if read_matches and write_matches:
                operation = "read_write"
            rows.append(
                {
                    "file": relative,
                    "line": line_number,
                    "operation": operation,
                    "api_matches": ";".join(read_matches + write_matches),
                    "canonical_reference": any(token in line for token in CANONICAL_TOKENS),
                    "text": line.strip()[:400],
                }
            )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _schema_fingerprint(schema: Any) -> str:
    description = "\n".join(f"{field.name}:{field.type}" for field in schema)
    return hashlib.sha256(description.encode("utf-8")).hexdigest()


def _date_column(names: list[str]) -> str | None:
    for candidate in ("Date", "date", "__index_level_0__"):
        if candidate in names:
            return candidate
    return None


def _profile_parquet(path: Path, root: Path, *, include_key_check: bool = False) -> dict[str, Any]:
    if not path.exists():
        return {"path": _relative(path, root), "exists": False}
    parquet = pq.ParquetFile(path)
    names = list(parquet.schema_arrow.names)
    date_name = _date_column(names)
    profile: dict[str, Any] = {
        "path": _relative(path, root),
        "exists": True,
        "bytes": path.stat().st_size,
        "modified_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(path.stat().st_mtime)),
        "rows": parquet.metadata.num_rows,
        "columns": len(names),
        "column_names": names,
        "row_groups": parquet.metadata.num_row_groups,
        "schema_fingerprint": _schema_fingerprint(parquet.schema_arrow),
        "date_column": date_name,
    }
    if date_name is not None:
        try:
            frame = pd.read_parquet(path, columns=[date_name])
            dates = pd.to_datetime(frame[date_name], errors="coerce")
            profile.update(
                {
                    "date_min": dates.min().isoformat() if not dates.dropna().empty else None,
                    "date_max": dates.max().isoformat() if not dates.dropna().empty else None,
                    "date_nulls": int(dates.isna().sum()),
                    "date_duplicates": int(dates.duplicated().sum()),
                }
            )
        except Exception as exc:  # pragma: no cover - audit must survive odd legacy files
            profile["date_read_error"] = repr(exc)
    if include_key_check:
        key_columns = [name for name in ("ISIN", "Date") if name in names]
        if len(key_columns) == 2:
            try:
                # The legacy file stores ISIN as a pandas index.  Asking pandas
                # for that physical field therefore returns it as the index,
                # not as a DataFrame column.
                keys = pd.read_parquet(path, columns=["Date"]).reset_index()
                profile["logical_key"] = key_columns
                profile["key_duplicate_rows"] = int(keys.duplicated(key_columns).sum())
                profile["key_null_rows"] = int(keys[key_columns].isna().any(axis=1).sum())
            except Exception as exc:  # pragma: no cover
                profile["key_read_error"] = repr(exc)
        else:
            profile["logical_key"] = key_columns
            profile["key_check_status"] = "not_available"
    return profile


def _row_group_profile(path: Path, root: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": _relative(path, root), "exists": False}
    parquet = pq.ParquetFile(path)
    names = list(parquet.schema_arrow.names)
    date_name = _date_column(names)
    date_index = names.index(date_name) if date_name in names else None
    groups: list[dict[str, Any]] = []
    for index in range(parquet.metadata.num_row_groups):
        group = parquet.metadata.row_group(index)
        row: dict[str, Any] = {
            "row_group": index,
            "rows": group.num_rows,
            "total_byte_size": group.total_byte_size,
        }
        if date_index is not None:
            statistics = group.column(date_index).statistics
            if statistics is not None:
                row["date_min"] = _json_default(statistics.min)
                row["date_max"] = _json_default(statistics.max)
                row["date_null_count"] = statistics.null_count
        groups.append(row)
    return {
        "path": _relative(path, root),
        "exists": True,
        "row_groups": groups,
    }


def _fingerprint(frame: pd.DataFrame) -> str:
    if frame.empty:
        return hashlib.sha256(b"empty").hexdigest()
    sample = frame.head(1000).copy()
    payload = repr(sample.to_dict(orient="list")).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def _timed(label: str, function: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        frame = function()
        elapsed = time.perf_counter() - started
        return {
            "label": label,
            "status": "passed",
            "elapsed_seconds": round(elapsed, 6),
            "rows": int(len(frame)),
            "columns": int(len(frame.columns)),
            "result_fingerprint": _fingerprint(frame),
        }
    except Exception as exc:  # pragma: no cover - baseline should record failure
        return {
            "label": label,
            "status": "failed",
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "error": repr(exc),
        }


def _performance_baseline(paths: dict[str, Path], root: Path) -> dict[str, Any]:
    screen = paths["screen_aggregate"]
    returns = paths["returns"]
    screen_names = list(pq.ParquetFile(screen).schema_arrow.names) if screen.exists() else []
    date_name = _date_column(screen_names)
    screen_columns = [name for name in (date_name, "Company SEDOL") if name in screen_names]
    extra = next((name for name in screen_names if name not in screen_columns), None)
    if extra is not None:
        screen_columns.append(extra)
    return_names = list(pq.ParquetFile(returns).schema_arrow.names) if returns.exists() else []
    return_columns = return_names[: min(5, len(return_names))]
    workloads: list[dict[str, Any]] = []
    if screen.exists() and screen_columns:
        def latest() -> pd.DataFrame:
            frame = pd.read_parquet(screen, columns=screen_columns)
            if date_name and date_name in frame:
                latest_date = pd.to_datetime(frame[date_name], errors="coerce").max()
                frame = frame[pd.to_datetime(frame[date_name], errors="coerce").eq(latest_date)]
            return frame

        workloads.extend([_timed("legacy_screen_latest_projection", latest), _timed("legacy_screen_latest_projection_warm", latest)])
    if screen.exists() and "ISIN" in screen_names:
        sample = pd.read_parquet(screen, columns=[date_name] if date_name else None).index
        if len(sample) > 0:
            isin = sample[0]

            def company_history() -> pd.DataFrame:
                return pd.read_parquet(screen, filters=[("ISIN", "==", isin)], columns=screen_columns)

            workloads.extend([_timed("legacy_screen_company_filter", company_history), _timed("legacy_screen_company_filter_warm", company_history)])
    if returns.exists() and return_columns:
        def returns_projection() -> pd.DataFrame:
            return pd.read_parquet(returns, columns=return_columns)

        workloads.extend([_timed("legacy_returns_projection", returns_projection), _timed("legacy_returns_projection_warm", returns_projection)])
    return {
        "status": "measured" if workloads else "not_run",
        "engine": "legacy_pandas_pyarrow",
        "root": str(root),
        "workloads": workloads,
        "notes": [
            "Cold/warm are process-level repeated reads; the OS filesystem cache is not forcibly evicted.",
            "DuckDB timings are intentionally absent until Phase 1 installs the dependency.",
        ],
    }


def _pipeline_graph(root: Path, io_rows: list[dict[str, Any]]) -> dict[str, Any]:
    pipeline_root = root / "src" / "tp_pipelines"
    nodes: list[dict[str, Any]] = []
    imports: list[dict[str, str]] = []
    if pipeline_root.exists():
        for path in sorted(pipeline_root.rglob("*.py")):
            relative = _relative(path, root)
            nodes.append({"module": relative, "io_sites": sum(row["file"] == relative for row in io_rows)})
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r"(?:from|import)\s+(tp_[a-z_]+)", text):
                imports.append({"module": relative, "imports": match.group(1)})
    return {
        "nodes": nodes,
        "imports": imports,
        "registered_dag": "src/tp_pipelines/orchestration.py",
        "io_site_count": sum(row["file"].startswith("src/tp_pipelines/") for row in io_rows),
    }


def _migration_plan(io_rows: list[dict[str, Any]], profiles: dict[str, Any]) -> dict[str, Any]:
    canonical_sites = [row for row in io_rows if row["canonical_reference"]]
    canonical_summary = {
        name: {
            key: profile.get(key)
            for key in (
                "exists",
                "bytes",
                "rows",
                "columns",
                "row_groups",
                "date_min",
                "date_max",
                "key_duplicate_rows",
            )
        }
        for name, profile in profiles.items()
    }
    return {
        "schema_version": "tp.duckdb-migration-plan.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "decision": "AUDIT_BASELINE",
        "phases": [
            {"phase": 0, "name": "Audit / Baseline", "status": "complete"},
            {"phase": 1, "name": "DuckDB Foundation", "status": "pending", "depends_on": [0]},
            {"phase": 2, "name": "Partitioned Mirror", "status": "pending", "depends_on": [1]},
            {"phase": 3, "name": "Shadow Query", "status": "pending", "depends_on": [2]},
            {"phase": 4, "name": "Read Cutover", "status": "pending", "depends_on": [3]},
            {"phase": 5, "name": "Writer Cutover", "status": "pending", "depends_on": [4]},
            {"phase": 6, "name": "Materialized Mart Cutover", "status": "pending", "depends_on": [5]},
            {"phase": 7, "name": "Canonical Authority Switch", "status": "blocked_until_user_approval", "depends_on": [6]},
            {"phase": 8, "name": "Retirement", "status": "blocked_until_two_cycles", "depends_on": [7]},
        ],
        "active_canonical_site_count": len(canonical_sites),
        "canonical_summary": canonical_summary,
        "phase_7_prerequisites": [
            "full real-data parity",
            "complete production-chain parity",
            "rollback drill",
            "two independent historical monthly replays or two production monthly cycles",
            "explicit user approval",
        ],
    }


def run(root: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    io_rows = _scan_io(root)
    fields = ["file", "line", "operation", "api_matches", "canonical_reference", "text"]
    _write_csv(output / "repository_io_inventory.csv", io_rows, fields)
    _write_csv(
        output / "canonical_read_sites.csv",
        [row for row in io_rows if row["canonical_reference"] and "read" in row["operation"]],
        fields,
    )
    _write_csv(
        output / "canonical_write_sites.csv",
        [row for row in io_rows if row["canonical_reference"] and "write" in row["operation"]],
        fields,
    )
    dashboard_rows = [
        row
        for row in io_rows
        if row["file"].startswith(("src/presentation_layer/", "08_presentation_layer/"))
        and "read" in row["operation"]
    ]
    _write_csv(output / "dashboard_read_inventory.csv", dashboard_rows, fields)

    canonical_paths = {name: root / relative for name, relative in CANONICAL_NAMES.items()}
    profiles = {
        name: _profile_parquet(path, root, include_key_check=name == "screen_aggregate")
        for name, path in canonical_paths.items()
    }
    _write_json(
        output / "current_data_profile.json",
        {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "git_head": _git(root, "rev-parse", "HEAD"),
            "git_branch": _git(root, "branch", "--show-current"),
            "canonical": profiles,
        },
    )
    _write_json(
        output / "current_row_group_profile.json",
        {name: _row_group_profile(path, root) for name, path in canonical_paths.items()},
    )
    _write_json(output / "performance_baseline.json", _performance_baseline(canonical_paths, root))
    _write_json(
        output / "storage_ab_test.json",
        {
            "status": "not_comparable",
            "workspace_path": str(root),
            "workspace_volume": root.drive,
            "comparison_path": None,
            "reason": "No independent local-disk copy of the canonical dataset was provided; no fabricated A/B result is recorded.",
            "same_volume_observation": "All measured baseline reads use the current Google Drive workspace path.",
        },
    )
    _write_json(output / "pipeline_io_graph.json", _pipeline_graph(root, io_rows))
    _write_json(output / "migration_plan.json", _migration_plan(io_rows, profiles))
    _write_json(
        output / "git_baseline.json",
        {
            "branch": _git(root, "branch", "--show-current"),
            "head": _git(root, "rev-parse", "HEAD"),
            "last_commit": _git(root, "log", "-1", "--oneline"),
            "status_short": _git(root, "status", "--short"),
            "note": "The large pre-existing dirty archive change set was not modified or staged by this audit.",
        },
    )


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="输出目录；默认 11_docs/archive/duckdb_migration_<today>",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.output or root / "11_docs" / "archive" / f"duckdb_migration_{time.strftime('%Y%m%d')}"
    run(root, output.resolve())
    print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

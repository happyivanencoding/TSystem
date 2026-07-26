"""ESG pivot score lookup utilities."""

from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path
from typing import Optional

import pandas as pd

_DATE_8DIG_RE = re.compile(r"(\d{8})")


def parse_yyyymmdd(value: str) -> Optional[dt.date]:
    """Parse a YYYYMMDD string and return None when the date is invalid."""
    try:
        return dt.datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def first_date_in_name(name: str) -> Optional[dt.date]:
    """Return the first valid 8-digit date found in a file or folder name."""
    match = _DATE_8DIG_RE.search(name)
    if not match:
        return None
    return parse_yyyymmdd(match.group(1))


def find_latest_dated_subfolder(base_dir: str | Path) -> Path:
    """Select the latest immediate subfolder by date in name, with mtime fallback."""
    base = Path(base_dir)
    if not base.exists():
        raise FileNotFoundError(f"ESG pivot base directory does not exist: {base}")
    if not base.is_dir():
        raise NotADirectoryError(f"ESG pivot base path is not a directory: {base}")

    dated: list[tuple[dt.date, Path]] = []
    subdirs: list[os.DirEntry[str]] = []
    with os.scandir(base) as entries:
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            subdirs.append(entry)
            folder_date = first_date_in_name(entry.name)
            if folder_date is not None:
                dated.append((folder_date, Path(entry.path)))

    if dated:
        dated.sort(key=lambda item: item[0], reverse=True)
        return dated[0][1]
    if subdirs:
        latest = max(subdirs, key=lambda entry: entry.stat().st_mtime)
        return Path(latest.path)
    raise FileNotFoundError(f"No ESG pivot subfolder found under: {base}")


def find_latest_pivot_file(base_dir: str | Path) -> Path:
    """Find the latest pivot file inside the latest dated pivot folder."""
    folder = find_latest_dated_subfolder(base_dir)
    dated_files: list[tuple[dt.date, Path]] = []
    files: list[os.DirEntry[str]] = []
    with os.scandir(folder) as entries:
        for entry in entries:
            if not entry.is_file(follow_symlinks=False):
                continue
            files.append(entry)
            file_date = first_date_in_name(entry.name)
            if file_date is not None:
                dated_files.append((file_date, Path(entry.path)))

    if dated_files:
        dated_files.sort(key=lambda item: item[0], reverse=True)
        return dated_files[0][1]
    if files:
        latest = max(files, key=lambda entry: entry.stat().st_mtime)
        return Path(latest.path)
    raise FileNotFoundError(f"No ESG pivot file found in latest folder: {folder}")


def read_pivot_file(path: str | Path) -> pd.DataFrame:
    """Read a pivot file, supporting the historical pipe-delimited format and Excel."""
    pivot_path = Path(path)
    suffix = pivot_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(pivot_path)
    if suffix in {".csv", ".txt", ""}:
        try:
            return pd.read_csv(pivot_path, encoding="cp1252", sep="|", engine="python")
        except Exception:
            return pd.read_csv(pivot_path, encoding="cp1252", sep=None, engine="python")
    raise ValueError(f"Unsupported ESG pivot file format: {pivot_path.suffix}")


def resolve_esg_pivot_score(
    base_dir: str | Path,
    bench_name_in_file: str,
    sec_id_col: str = "sec_id",
    score_col: str = "note_pivot",
) -> float:
    """Resolve a textual ESG pivot identifier into a numeric threshold."""
    pivot_file = find_latest_pivot_file(base_dir)
    pivot_data = read_pivot_file(pivot_file)
    missing = [column for column in (sec_id_col, score_col) if column not in pivot_data.columns]
    if missing:
        raise KeyError(f"ESG pivot file is missing required columns: {missing}")

    matches = pivot_data[pivot_data[sec_id_col].astype(str) == str(bench_name_in_file)]
    if matches.empty:
        raise KeyError(f"ESG pivot identifier not found: {bench_name_in_file}")

    score = pd.to_numeric(matches[score_col], errors="coerce").dropna()
    if score.empty:
        raise ValueError(f"ESG pivot score is not numeric for: {bench_name_in_file}")
    return float(score.iloc[0])

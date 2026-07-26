"""Gestion des artefacts produits par les runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import re

import pandas as pd
import yaml

from tp_backtest.config.settings import AppSettings
from tp_core.security_nav_engine import nav_engine_metadata
from tp_core.workspace import BACKTEST_OUTPUT_RUNS_DIR


def get_project_root() -> Path:
    """Retourne la racine du projet."""

    return Path(__file__).resolve().parents[3]


def get_runs_dir() -> Path:
    """Retourne le dossier de stockage des runs."""

    return BACKTEST_OUTPUT_RUNS_DIR


def slugify(text: str) -> str:
    """Transforme un texte libre en identifiant de dossier."""

    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", text.strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "run"


@dataclass
class RunArtifacts:
    """Chemins des artefacts d'un run."""

    run_dir: Path
    config_snapshot: Path
    manifest: Path
    sec_list: Path | None = None
    exclusions: Path | None = None
    perf_ptf: Path | None = None
    perf_bench: Path | None = None
    plot: Path | None = None
    run_log: Path | None = None
    extra: dict[str, Path] = field(default_factory=dict)


def create_run_directory(user_name: str, run_label: str) -> Path:
    """Cree le dossier d'un run."""

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = get_runs_dir() / user_name / f"{timestamp}_{slugify(run_label)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def save_config_snapshot(settings: AppSettings, run_dir: Path) -> Path:
    """Sauvegarde la configuration complete du run."""

    target = run_dir / "config_snapshot.yaml"
    with target.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            settings.to_dict(),
            handle,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    return target


def save_manifest(run_dir: Path, payload: dict[str, Any]) -> Path:
    """Sauvegarde un resume compact du run."""

    target = run_dir / "manifest.yaml"
    manifest_payload = {
        **nav_engine_metadata(
            strictly_after_rebalance=True,
            apply_weights_at_close=True,
        ),
        **payload,
    }
    with target.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            manifest_payload,
            handle,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    return target


def _backup_path(target: Path, suffix: str) -> Path:
    """Retourne le chemin du fichier de sauvegarde associe."""

    return target.parent / f"{target.stem}{suffix}"


def save_dataframe(dataframe: pd.DataFrame | None, target: Path) -> Path | None:
    """Sauvegarde un DataFrame en parquet avec une copie Excel quand la taille le permet."""

    if dataframe is None or dataframe.empty:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".parquet":
        dataframe.to_parquet(target, index=False)
        if len(dataframe) <= 1_048_576 and len(dataframe.columns) <= 16_384:
            dataframe.to_excel(_backup_path(target, ".xlsx"), index=False)
        else:
            note_path = _backup_path(target, ".xlsx.skipped.txt")
            note_path.write_text(
                "Excel backup skipped: dataframe is too large for one worksheet "
                f"({len(dataframe)} rows, {len(dataframe.columns)} columns). "
                "The parquet file is the canonical artifact.\n",
                encoding="utf-8",
            )
        return target
    dataframe.to_excel(target, index=False)
    return target


def save_series(series: pd.Series | None, target: Path) -> Path | None:
    """Sauvegarde une serie en parquet avec une copie CSV."""

    if series is None or series.empty:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".parquet":
        series.reset_index(name=series.name or "value").to_parquet(target, index=False)
        series.to_csv(_backup_path(target, ".csv"), header=True)
        return target
    series.to_csv(target, header=True)
    return target


def save_text(text: str, target: Path) -> Path:
    """Sauvegarde un bloc texte dans un fichier."""

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def list_run_directories(user_name: str | None = None) -> list[Path]:
    """Retourne la liste des dossiers de runs, du plus recent au plus ancien."""

    base_dir = get_runs_dir()
    if not base_dir.exists():
        return []
    if user_name:
        base_dir = base_dir / user_name
        if not base_dir.exists():
            return []
        run_dirs = [path for path in base_dir.iterdir() if path.is_dir()]
    else:
        run_dirs = []
        for user_dir in base_dir.iterdir():
            if not user_dir.is_dir():
                continue
            run_dirs.extend(path for path in user_dir.iterdir() if path.is_dir())
    return sorted(
        run_dirs,
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def list_run_users() -> list[str]:
    """Retourne la liste des utilisateurs disposant d'un historique."""

    base_dir = get_runs_dir()
    if not base_dir.exists():
        return []
    return sorted((path.name for path in base_dir.iterdir() if path.is_dir()), key=str.casefold)


def get_latest_run_directory(user_name: str | None = None) -> Path | None:
    """Retourne le dossier du run le plus recent."""

    run_dirs = list_run_directories(user_name=user_name)
    return run_dirs[0] if run_dirs else None


def read_manifest(run_dir: Path) -> dict[str, Any]:
    """Lit le manifeste d'un run si disponible."""

    manifest_path = run_dir / "manifest.yaml"
    if not manifest_path.exists():
        return {}
    with manifest_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}

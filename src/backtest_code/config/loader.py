"""Chargement et sauvegarde des configurations YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .settings import AppSettings


def get_project_root() -> Path:
    """Retourne la racine du projet."""

    return Path(__file__).resolve().parents[3]


def get_config_dir() -> Path:
    """Retourne le dossier des configurations."""

    return get_project_root() / "configs"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Fusionne deux dictionnaires de maniere recursive."""

    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_yaml_file(file_path: Path) -> dict[str, Any]:
    """Lit un fichier YAML et retourne un dictionnaire."""

    if not file_path.exists():
        return {}
    with file_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data


def list_available_profiles() -> list[str]:
    """Liste les profils utilisateur disponibles."""

    config_dir = get_config_dir()
    if not config_dir.exists():
        return []
    return sorted(path.stem for path in config_dir.glob("*.yaml"))


def get_profile_path(profile_name: str) -> Path:
    """Retourne le chemin YAML associe a un profil."""

    return get_config_dir() / f"{profile_name}.yaml"


def load_settings(profile_name: str = "default") -> AppSettings:
    """Charge la configuration par defaut et la surcharge utilisateur."""

    config_dir = get_config_dir()
    default_data = _read_yaml_file(config_dir / "default.yaml")

    if profile_name == "default":
        merged = default_data
    else:
        profile_data = _read_yaml_file(config_dir / f"{profile_name}.yaml")
        merged = _deep_merge(default_data, profile_data)

    settings = AppSettings.from_dict(merged)
    if profile_name != "default":
        settings.user.name = profile_name
    return settings


def save_settings(settings: AppSettings, profile_name: str | None = None) -> Path:
    """Sauvegarde une configuration utilisateur au format YAML."""

    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    target_name = profile_name or settings.user.name or "user1"
    target_path = config_dir / f"{target_name}.yaml"

    with target_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            settings.to_dict(),
            handle,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )

    return target_path


def create_profile_from_settings(settings: AppSettings, profile_name: str) -> Path:
    """Cree un nouveau profil a partir d'une configuration existante."""

    target_path = get_profile_path(profile_name)
    if target_path.exists():
        raise FileExistsError(f"Le profil '{profile_name}' existe deja.")
    duplicated_settings = settings.copy()
    duplicated_settings.user.name = profile_name
    return save_settings(duplicated_settings, profile_name=profile_name)


def rename_profile_from_settings(
    source_profile_name: str,
    target_profile_name: str,
    settings: AppSettings,
) -> Path:
    """Renomme un profil et met a jour son contenu."""

    source_path = get_profile_path(source_profile_name)
    target_path = get_profile_path(target_profile_name)
    if source_profile_name != target_profile_name and target_path.exists():
        raise FileExistsError(f"Le profil '{target_profile_name}' existe deja.")

    renamed_settings = settings.copy()
    renamed_settings.user.name = target_profile_name
    saved_path = save_settings(renamed_settings, profile_name=target_profile_name)
    if source_profile_name != target_profile_name and source_path.exists():
        source_path.unlink()
    return saved_path

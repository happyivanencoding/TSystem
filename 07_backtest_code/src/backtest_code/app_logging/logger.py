"""Initialisation de la journalisation de l'application."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _project_root() -> Path:
    """Retourne la racine du projet."""

    return Path(__file__).resolve().parents[3]


def setup_logger(user_name: str = "user1") -> logging.Logger:
    """Configure un logger applicatif par utilisateur."""

    log_dir = _project_root() / "logs" / user_name
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    logger = logging.getLogger(f"backtest_code.{user_name}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def get_logger(user_name: str = "user1") -> logging.Logger:
    """Retourne un logger pret a l'emploi."""

    return setup_logger(user_name=user_name)

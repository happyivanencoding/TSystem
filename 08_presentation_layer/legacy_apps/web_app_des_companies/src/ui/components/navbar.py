"""La navigation est dans app_header (en-tête AppShell). Ce module conserve l’ancien nom pour éviter les imports obsolètes."""
from __future__ import annotations

from src.ui.components.app_header import build_app_header_content

__all__ = ["build_app_header_content"]

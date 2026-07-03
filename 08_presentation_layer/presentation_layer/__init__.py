"""Logical ``presentation_layer`` package from ``08_presentation_layer``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_REAL_PACKAGE = Path(__file__).resolve().parents[1]
__path__ = [str(_REAL_PACKAGE)]


def __getattr__(name: str) -> Any:
    if name == "PresentationDataRepository":
        from .data_repository import PresentationDataRepository

        return PresentationDataRepository
    raise AttributeError(name)


__all__ = ["PresentationDataRepository"]

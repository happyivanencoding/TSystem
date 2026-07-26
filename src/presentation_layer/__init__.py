"""展示/报告共享数据层。"""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "PresentationDataRepository":
        from .data_repository import PresentationDataRepository

        return PresentationDataRepository
    raise AttributeError(name)


__all__ = ["PresentationDataRepository"]

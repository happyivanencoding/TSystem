"""兼容包：真实展示/报告共享层位于 `08_presentation_layer/`。"""

from pathlib import Path

_REAL_PACKAGE = Path(__file__).resolve().parents[1] / "08_presentation_layer"
__path__ = [str(_REAL_PACKAGE)]

from .data_repository import PresentationDataRepository

__all__ = ["PresentationDataRepository"]

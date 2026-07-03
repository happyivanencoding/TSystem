"""兼容包：真实流水线代码位于 `02_pipelines/`。"""

from pathlib import Path

_REAL_PACKAGE = Path(__file__).resolve().parents[1] / "02_pipelines"
__path__ = [str(_REAL_PACKAGE)]

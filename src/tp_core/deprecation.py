"""兼容入口的统一弃用提示。"""

from __future__ import annotations

import warnings


def warn_legacy_entrypoint(legacy_path: str, replacement: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("always", FutureWarning)
        warnings.warn(
            (
                f"兼容入口 {legacy_path} 已弃用；请改用 {replacement}。"
                "仓库内部引用迁移完成后，该入口将在两个连续生产周期验证通过后移除。"
            ),
            FutureWarning,
            stacklevel=2,
        )

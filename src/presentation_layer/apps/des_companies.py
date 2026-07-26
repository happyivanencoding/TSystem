"""Dash 公司展示应用的统一入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from presentation_layer.company_browser import settings


APP_ROOT = settings.ROOT_DIR


def _validate_assets() -> None:
    if not APP_ROOT.exists():
        raise FileNotFoundError(f"Dash 公司展示应用目录不存在: {APP_ROOT}")


def create_app() -> Any:
    """创建 Dash 公司展示应用。

    入口、UI、callbacks 和 CSS 均位于统一 presentation layer；
    DES/NEWS 直接读取源文件，screen 数据只读取 canonical contract。
    """

    _validate_assets()
    import dash
    from presentation_layer.company_browser.ui.layout import build_layout

    app = dash.Dash(
        __name__,
        use_pages=True,
        pages_folder=str(Path(__file__).resolve().parents[1] / "company_browser" / "ui" / "pages"),
        assets_folder=str(settings.ASSETS_DIR),
        title=settings.APP_TITLE,
        update_title=None,
        suppress_callback_exceptions=True,
    )
    app.layout = build_layout()

    import presentation_layer.company_browser.callbacks  # noqa: F401

    return app


def run(host: str | None = None, port: int | None = None, debug: bool | None = None) -> None:
    """本地启动 Dash 公司展示应用。"""

    app = create_app()
    app.run(
        host=host or settings.HOST,
        port=port or settings.PORT,
        debug=settings.DEBUG if debug is None else debug,
    )


__all__ = ["APP_ROOT", "create_app", "run"]

"""Dash 公司展示应用的统一入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tp_core.data_sources import TP_ROOT
from presentation_layer.company_browser import settings


APP_ROOT = TP_ROOT / "08_presentation_layer" / "legacy_apps" / "web_app_des_companies"


def _validate_assets() -> None:
    if not APP_ROOT.exists():
        raise FileNotFoundError(f"Dash 公司展示应用目录不存在: {APP_ROOT}")


def create_app() -> Any:
    """创建 Dash 公司展示应用。

    入口位于统一 presentation layer；UI、callbacks 和资源文件暂时复用
    `08_presentation_layer/legacy_apps/web_app_des_companies/src`，以避免一次性重写前端。
    """

    _validate_assets()
    import dash
    from presentation_layer.company_browser.ui.layout import build_layout

    app = dash.Dash(
        __name__,
        use_pages=True,
        pages_folder=str(Path(__file__).resolve().parents[1] / "company_browser" / "ui" / "pages"),
        assets_folder=str(APP_ROOT / "src" / "assets"),
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

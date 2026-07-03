"""Dash 公司展示应用的统一入口。"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from tp_core.data_sources import TP_ROOT


APP_ROOT = TP_ROOT / "08_web_app_des_companies"


def _evict_if_outside(module_name: str, root: Path) -> None:
    module = sys.modules.get(module_name)
    if module is None:
        return
    module_file = getattr(module, "__file__", None)
    if module_file is None:
        return
    try:
        Path(module_file).resolve().relative_to(root.resolve())
    except ValueError:
        sys.modules.pop(module_name, None)


def _prepare_imports() -> None:
    if not APP_ROOT.exists():
        raise FileNotFoundError(f"Dash 公司展示应用目录不存在: {APP_ROOT}")
    app_path = str(APP_ROOT)
    while app_path in sys.path:
        sys.path.remove(app_path)
    sys.path.insert(0, app_path)
    _evict_if_outside("config", APP_ROOT)
    _evict_if_outside("src", APP_ROOT)
    importlib.invalidate_caches()


def _import_legacy_module(module_name: str) -> ModuleType:
    _prepare_imports()
    return importlib.import_module(module_name)


def create_app() -> Any:
    """创建 Dash 公司展示应用。

    入口位于统一 presentation layer；UI、callbacks 和资源文件暂时复用
    `08_web_app_des_companies/src`，以避免一次性重写前端。
    """

    _prepare_imports()
    import dash
    from config import settings
    from src.ui.layout import build_layout

    app = dash.Dash(
        __name__,
        use_pages=True,
        pages_folder=str(APP_ROOT / "src" / "ui" / "pages"),
        assets_folder=str(APP_ROOT / "src" / "assets"),
        title=settings.APP_TITLE,
        update_title=None,
        suppress_callback_exceptions=True,
    )
    app.layout = build_layout()

    import src.callbacks  # noqa: F401

    return app


def run(host: str | None = None, port: int | None = None, debug: bool | None = None) -> None:
    """本地启动 Dash 公司展示应用。"""

    _prepare_imports()
    from config import settings

    app = create_app()
    app.run(
        host=host or settings.HOST,
        port=port or settings.PORT,
        debug=settings.DEBUG if debug is None else debug,
    )


__all__ = ["APP_ROOT", "create_app", "run"]

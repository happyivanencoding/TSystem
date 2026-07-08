"""组合 dashboard 和 PDF 报告的统一入口。"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from tp_core.data_sources import TP_ROOT


DASHBOARD_ROOT = TP_ROOT / "08_presentation_layer" / "legacy_apps" / "dashboard_analysis"


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
    if not DASHBOARD_ROOT.exists():
        raise FileNotFoundError(f"dashboard_analysis 目录不存在: {DASHBOARD_ROOT}")
    dashboard_path = str(DASHBOARD_ROOT)
    while dashboard_path in sys.path:
        sys.path.remove(dashboard_path)
    sys.path.insert(0, dashboard_path)
    _evict_if_outside("dashboard", DASHBOARD_ROOT)
    _evict_if_outside("pdf_report_generator", DASHBOARD_ROOT)
    importlib.invalidate_caches()


def _module(name: str) -> ModuleType:
    _prepare_imports()
    return importlib.import_module(name)


def get_dashboard_class() -> type[Any]:
    """返回当前统一使用的 PortfolioDashboard 类。"""

    return _module("dashboard").PortfolioDashboard


def create_dashboard(*args: Any, **kwargs: Any) -> Any:
    """创建 PortfolioDashboard 实例。"""

    return get_dashboard_class()(*args, **kwargs)


def generate_pdf_report(*args: Any, **kwargs: Any) -> Any:
    """生成 PDF 报告，透传到当前报告实现。"""

    return _module("pdf_report_generator").generate_pdf_report(*args, **kwargs)


__all__ = ["DASHBOARD_ROOT", "create_dashboard", "generate_pdf_report", "get_dashboard_class"]

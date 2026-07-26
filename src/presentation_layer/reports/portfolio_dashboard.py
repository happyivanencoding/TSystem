"""组合 dashboard 和 PDF 报告的统一入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tp_core.data_sources import TP_ROOT
from presentation_layer.portfolio import PortfolioDashboard, generate_pdf_report as _generate_pdf_report


DASHBOARD_ROOT = TP_ROOT / "08_presentation_layer" / "legacy_apps" / "dashboard_analysis"


def get_dashboard_class() -> type[Any]:
    """返回当前统一使用的 PortfolioDashboard 类。"""

    return PortfolioDashboard


def create_dashboard(*args: Any, **kwargs: Any) -> Any:
    """创建 PortfolioDashboard 实例。"""

    return get_dashboard_class()(*args, **kwargs)


def generate_pdf_report(*args: Any, **kwargs: Any) -> Any:
    """生成 PDF 报告，透传到当前报告实现。"""

    return _generate_pdf_report(*args, **kwargs)


__all__ = ["DASHBOARD_ROOT", "create_dashboard", "generate_pdf_report", "get_dashboard_class"]

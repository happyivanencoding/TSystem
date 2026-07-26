"""组合 dashboard 和 PDF 报告的统一入口。"""

from __future__ import annotations

from typing import Any

def get_dashboard_class() -> type[Any]:
    """返回当前统一使用的 PortfolioDashboard 类。"""

    from presentation_layer.portfolio.dashboard import PortfolioDashboard

    return PortfolioDashboard


def create_dashboard(*args: Any, **kwargs: Any) -> Any:
    """创建 PortfolioDashboard 实例。"""

    return get_dashboard_class()(*args, **kwargs)


def generate_pdf_report(*args: Any, **kwargs: Any) -> Any:
    """生成 PDF 报告，透传到当前报告实现。"""

    from presentation_layer.portfolio.pdf_report_generator import generate_pdf_report as implementation

    return implementation(*args, **kwargs)


__all__ = ["create_dashboard", "generate_pdf_report", "get_dashboard_class"]

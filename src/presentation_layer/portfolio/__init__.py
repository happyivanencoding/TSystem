"""Lazy portfolio dashboard public API; optional Excel dependencies load on use."""


def __getattr__(name: str):
    if name == "PortfolioDashboard":
        from .dashboard import PortfolioDashboard

        return PortfolioDashboard
    if name == "generate_pdf_report":
        from .pdf_report_generator import generate_pdf_report

        return generate_pdf_report
    raise AttributeError(name)

__all__ = ["PortfolioDashboard", "generate_pdf_report"]

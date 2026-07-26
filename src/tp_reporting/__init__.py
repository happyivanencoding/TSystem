"""Public reporting APIs for TP."""

from .factor_research_app import build_html, market_payload
from .inline_visualization import render_inline_fragment
from .factor_explorer import main as build_factor_explorer
from .stoxx600_factor_explorer import main as build_stoxx600_factor_explorer

__all__ = [
    "build_factor_explorer",
    "build_html",
    "build_stoxx600_factor_explorer",
    "market_payload",
    "render_inline_fragment",
]

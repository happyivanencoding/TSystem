"""Callback registration entry point.

Import side effects register callbacks with the current Dash app.
"""
from __future__ import annotations

from presentation_layer.company_browser.callbacks import app_shell as _app_shell  # noqa: F401
from presentation_layer.company_browser.callbacks import home as _home  # noqa: F401
from presentation_layer.company_browser.callbacks import index_composition as _idx  # noqa: F401
from presentation_layer.company_browser.callbacks import industry_analysis as _ind2  # noqa: F401
from presentation_layer.company_browser.callbacks import scroll_lock as _scroll_lock  # noqa: F401

__all__ = ["_app_shell", "_home", "_idx", "_ind2"]

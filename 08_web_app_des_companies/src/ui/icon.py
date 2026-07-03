"""Small icon helper with a graceful fallback when dash-iconify is absent."""

from __future__ import annotations

from dash import html

try:
    from dash_iconify import DashIconify as _DashIconify
except ImportError:  # dash-iconify is optional for backend/test smoke checks.
    _DashIconify = None


def DashIconify(icon: str, width: int = 16, color: str | None = None, **kwargs):
    if _DashIconify is not None:
        return _DashIconify(icon=icon, width=width, color=color, **kwargs)
    return html.Span(
        "",
        title=icon,
        style={
            "display": "inline-block",
            "width": width,
            "height": width,
            "color": color,
        },
    )

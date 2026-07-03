"""À chaque changement de route, rétablit le scroll de document.body (évite overflow:hidden bloquant après tiroir ou navigation)."""
from __future__ import annotations

from dash import Input, Output, clientside_callback

clientside_callback(
    """
    function(_pathname) {
        document.body.style.overflow = '';
        return 0;
    }
    """,
    Output("_scroll_reset_sink", "data"),
    Input("_url", "pathname"),
)

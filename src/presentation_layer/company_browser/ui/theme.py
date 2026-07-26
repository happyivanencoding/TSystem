"""Centralized design tokens: colors, typography, radius.

Single source of truth for the look & feel. Change here to re-skin the app.
"""
from __future__ import annotations

# --- Palette (light scheme) ---
COLOR_BG: str = "#FAFAFA"
COLOR_SURFACE: str = "#FFFFFF"
COLOR_PRIMARY: str = "#1E40AF"      # Deep blue — financial tone
COLOR_ACCENT: str = "#0F766E"       # Teal — positive accents
COLOR_TEXT: str = "#111827"
COLOR_TEXT_MUTED: str = "#6B7280"
COLOR_BORDER: str = "#E5E7EB"

# --- Radius & spacing ---
RADIUS_MD: str = "10px"
RADIUS_LG: str = "14px"

# --- Typography ---
FONT_FAMILY: str = (
    "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)

# --- Mantine theme dict consumed by MantineProvider ---
MANTINE_THEME: dict = {
    "fontFamily": FONT_FAMILY,
    "primaryColor": "blue",
    "defaultRadius": "md",
    "white": COLOR_SURFACE,
    "black": COLOR_TEXT,
    # Ne garder que sizes ; ne pas mettre fontWeight sur la racine headings (dmc/Mantine 7 : CSS invalide)
    "headings": {
        "sizes": {
            "h1": {"fontSize": "2.125rem", "lineHeight": "1.3", "fontWeight": 600},
            "h2": {"fontSize": "1.625rem", "lineHeight": "1.35", "fontWeight": 600},
            "h3": {"fontSize": "1.375rem", "lineHeight": "1.4", "fontWeight": 600},
            "h4": {"fontSize": "1.125rem", "lineHeight": "1.45", "fontWeight": 600},
            "h5": {"fontSize": "1rem", "lineHeight": "1.5", "fontWeight": 600},
            "h6": {"fontSize": "0.875rem", "lineHeight": "1.5", "fontWeight": 600},
        },
    },
}

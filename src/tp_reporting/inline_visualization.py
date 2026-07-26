"""Render Codex inline-visualization fragments without importing files as code."""

from __future__ import annotations

from html import escape
import os
from pathlib import Path

_FRAGMENT_PLACEHOLDER = "<!--__INLINE_VISUALIZATION_FRAGMENT__-->"
_RESOURCE_SOURCES = " ".join(
    (
        "blob:",
        "data:",
        "https://cdnjs.cloudflare.com",
        "https://cdn.jsdelivr.net",
        "https://esm.sh",
        "https://fonts.bunny.net",
        "https://fonts.googleapis.com",
        "https://fonts.gstatic.com",
        "https://unpkg.com",
    )
)
_FRAME_CSP = "; ".join(
    (
        "default-src 'none'",
        f"script-src 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' {_RESOURCE_SOURCES}",
        f"style-src 'unsafe-inline' {_RESOURCE_SOURCES}",
        f"img-src {_RESOURCE_SOURCES}",
        f"font-src {_RESOURCE_SOURCES}",
        f"media-src {_RESOURCE_SOURCES}",
        "worker-src blob:",
        "connect-src blob: data:",
        "frame-src 'none'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    )
)
_SHELL_CSP = _FRAME_CSP.replace("frame-src 'none'", "frame-src 'self'")


def _asset_directory() -> Path:
    configured = os.environ.get("TP_VISUALIZE_ASSET_DIR")
    if configured:
        directory = Path(configured).expanduser().resolve()
        if (directory / "visualize.css").is_file() and (
            directory / "visualize.html"
        ).is_file():
            return directory
        raise FileNotFoundError(f"Invalid TP_VISUALIZE_ASSET_DIR: {directory}")

    cache_root = (
        Path.home()
        / ".codex"
        / "plugins"
        / "cache"
        / "openai-bundled"
        / "visualize"
    )
    candidates = sorted(
        cache_root.glob("*/skills/visualize/assets"),
        key=lambda path: path.parts[-4],
        reverse=True,
    )
    for directory in candidates:
        if (directory / "visualize.css").is_file() and (
            directory / "visualize.html"
        ).is_file():
            return directory
    raise FileNotFoundError(
        "Codex visualize assets are unavailable; set TP_VISUALIZE_ASSET_DIR"
    )


def render_inline_fragment(fragment_path: Path, title: str | None = None) -> str:
    """Return a sandboxed standalone document for an inline HTML fragment."""

    assets = _asset_directory()
    fragment = fragment_path.read_text(encoding="utf-8")
    stylesheet = (assets / "visualize.css").read_text(encoding="utf-8")
    inner_kit = (assets / "visualize.html").read_text(encoding="utf-8")
    inner_html = inner_kit.replace(_FRAGMENT_PLACEHOLDER, fragment)
    document_title = escape(title or fragment_path.stem.replace("-", " ").title())
    frame_html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="{_FRAME_CSP}">
<title>{document_title}</title>
<style>{stylesheet}
html>body{{padding:0}}</style>
</head>
<body>
{inner_html}
</body>
</html>
"""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="{_SHELL_CSP}">
<title>{document_title}</title>
<style>:root{{color-scheme:light dark;background:light-dark(rgb(255 255 255), rgb(24 24 24))}}html,body{{margin:0}}body{{box-sizing:border-box;padding:1rem;background:inherit}}iframe{{display:block;width:100%;height:calc(100vh - 2rem);margin:0 auto;border:0}}</style>
</head>
<body>
<iframe sandbox="allow-scripts" referrerpolicy="no-referrer" title="{document_title}" srcdoc="{escape(frame_html)}"></iframe>
</body>
</html>
"""

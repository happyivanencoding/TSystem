"""Text utilities for Markdown content displayed in the UI."""
from __future__ import annotations

import re


# Matches Markdown noise tokens we want to strip from short previews.
_MD_NOISE = re.compile(r"[#*_`>]+")
_WHITESPACE = re.compile(r"\s+")


def summarize_markdown(text: str | None, n_chars: int) -> str:
    """Produce a short plain-text preview from a Markdown string.

    Strips Markdown decorations and collapses whitespace, then truncates
    to n_chars with an ellipsis suffix.
    """
    if not text:
        return ""

    plain = _MD_NOISE.sub("", str(text))
    plain = _WHITESPACE.sub(" ", plain).strip()

    if len(plain) <= n_chars:
        return plain
    return plain[: n_chars - 1].rstrip() + "…"

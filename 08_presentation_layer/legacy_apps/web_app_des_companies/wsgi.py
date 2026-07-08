"""WSGI entry point for production servers (e.g. waitress, gunicorn)."""
from __future__ import annotations

from app import server

__all__ = ["server"]

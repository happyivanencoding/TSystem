"""兼容入口：真实 FastAPI app factory 已迁入 presentation_layer.apps。"""
from __future__ import annotations

from presentation_layer.apps.company_analysis_api import create_app, run


app = create_app()


if __name__ == "__main__":
    run()

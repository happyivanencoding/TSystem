"""兼容入口：真实 Dash app factory 已迁入 presentation_layer.apps。"""
from __future__ import annotations

from presentation_layer.apps.des_companies import create_app, run


app = create_app()
server = app.server


if __name__ == "__main__":
    run()

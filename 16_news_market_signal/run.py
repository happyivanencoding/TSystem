"""Compatibility entrypoint; use :mod:`tp_models.news.run`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_models.news.run import *  # noqa: F403
from tp_models.news.run import main


if __name__ == "__main__":
    warn_legacy_entrypoint("16_news_market_signal/run.py", "python -m tp_models.news.run")
    raise SystemExit(main())

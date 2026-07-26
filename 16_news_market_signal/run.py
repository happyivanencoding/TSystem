"""Compatibility entrypoint; use :mod:`tp_models.news.run`."""

from tp_models.news.run import *  # noqa: F403
from tp_models.news.run import main


if __name__ == "__main__":
    raise SystemExit(main())

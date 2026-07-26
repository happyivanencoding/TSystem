"""Compatibility entrypoint; use :mod:`tp_pipelines.refresh_technical`."""

from tp_pipelines.refresh_technical import *  # noqa: F403
from tp_pipelines.refresh_technical import main


if __name__ == "__main__":
    raise SystemExit(main())

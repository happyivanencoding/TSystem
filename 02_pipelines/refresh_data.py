"""Compatibility entrypoint; use :mod:`tp_pipelines.refresh_data`."""

from tp_pipelines.refresh_data import *  # noqa: F403
from tp_pipelines.refresh_data import main


if __name__ == "__main__":
    raise SystemExit(main())

"""Compatibility entrypoint; use :mod:`tp_pipelines.refresh_small_cap`."""

from tp_pipelines.refresh_small_cap import *  # noqa: F403
from tp_pipelines.refresh_small_cap import main


if __name__ == "__main__":
    raise SystemExit(main())

"""Compatibility entrypoint; use :mod:`tp_pipelines.run_all`."""

from tp_pipelines.run_all import *  # noqa: F403
from tp_pipelines.run_all import main


if __name__ == "__main__":
    raise SystemExit(main())

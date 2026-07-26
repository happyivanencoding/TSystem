"""Compatibility entrypoint; use :mod:`tp_pipelines.generate_report`."""

from tp_pipelines.generate_report import *  # noqa: F403
from tp_pipelines.generate_report import main


if __name__ == "__main__":
    raise SystemExit(main())

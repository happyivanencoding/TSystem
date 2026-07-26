"""Compatibility entrypoint; use :mod:`tp_pipelines.export_signals`."""

from tp_pipelines.export_signals import *  # noqa: F403
from tp_pipelines.export_signals import main


if __name__ == "__main__":
    raise SystemExit(main())

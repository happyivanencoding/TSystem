"""Compatibility entrypoint; use :mod:`tp_pipelines.refresh_ml`."""

from tp_pipelines.refresh_ml import *  # noqa: F403
from tp_pipelines.refresh_ml import main


if __name__ == "__main__":
    raise SystemExit(main())

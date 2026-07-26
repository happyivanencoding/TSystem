"""Compatibility entrypoint; use :mod:`tp_pipelines.refresh_regime`."""

from tp_pipelines.refresh_regime import *  # noqa: F403
from tp_pipelines.refresh_regime import main


if __name__ == "__main__":
    raise SystemExit(main())

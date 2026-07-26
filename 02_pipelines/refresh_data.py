"""Compatibility entrypoint; use :mod:`tp_pipelines.refresh_data`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_pipelines.refresh_data import *  # noqa: F403
from tp_pipelines.refresh_data import main


if __name__ == "__main__":
    warn_legacy_entrypoint("02_pipelines/refresh_data.py", "python -m tp_pipelines.refresh_data")
    raise SystemExit(main())

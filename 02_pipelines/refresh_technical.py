"""Compatibility entrypoint; use :mod:`tp_pipelines.refresh_technical`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_pipelines.refresh_technical import *  # noqa: F403
from tp_pipelines.refresh_technical import main


if __name__ == "__main__":
    warn_legacy_entrypoint("02_pipelines/refresh_technical.py", "python -m tp_pipelines.refresh_technical")
    raise SystemExit(main())

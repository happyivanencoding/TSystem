"""Compatibility entrypoint; use :mod:`tp_pipelines.refresh_small_cap`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_pipelines.refresh_small_cap import *  # noqa: F403
from tp_pipelines.refresh_small_cap import main


if __name__ == "__main__":
    warn_legacy_entrypoint("02_pipelines/refresh_small_cap.py", "python -m tp_pipelines.refresh_small_cap")
    raise SystemExit(main())

"""Compatibility entrypoint; use :mod:`tp_pipelines.run_all`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_pipelines.run_all import *  # noqa: F403
from tp_pipelines.run_all import main


if __name__ == "__main__":
    warn_legacy_entrypoint("02_pipelines/run_all.py", "python -m tp_pipelines.run_all")
    raise SystemExit(main())

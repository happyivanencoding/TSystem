"""Compatibility entrypoint; use :mod:`tp_pipelines.generate_report`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_pipelines.generate_report import *  # noqa: F403
from tp_pipelines.generate_report import main


if __name__ == "__main__":
    warn_legacy_entrypoint("02_pipelines/generate_report.py", "python -m tp_pipelines.generate_report")
    raise SystemExit(main())

"""Compatibility entrypoint; use :mod:`tp_pipelines.export_signals`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_pipelines.export_signals import *  # noqa: F403
from tp_pipelines.export_signals import main


if __name__ == "__main__":
    warn_legacy_entrypoint("02_pipelines/export_signals.py", "python -m tp_pipelines.export_signals")
    raise SystemExit(main())

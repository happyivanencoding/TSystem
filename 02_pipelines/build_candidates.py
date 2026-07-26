"""Compatibility entrypoint; use :mod:`tp_pipelines.build_candidates`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_pipelines.build_candidates import *  # noqa: F403
from tp_pipelines.build_candidates import main


if __name__ == "__main__":
    warn_legacy_entrypoint("02_pipelines/build_candidates.py", "python -m tp_pipelines.build_candidates")
    raise SystemExit(main())

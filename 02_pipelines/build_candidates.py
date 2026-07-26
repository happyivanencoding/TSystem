"""Compatibility entrypoint; use :mod:`tp_pipelines.build_candidates`."""

from tp_pipelines.build_candidates import *  # noqa: F403
from tp_pipelines.build_candidates import main


if __name__ == "__main__":
    raise SystemExit(main())

"""Compatibility entrypoint; use :mod:`tp_models.country`."""

from tp_models.country import *  # noqa: F403
from tp_models.country import main


if __name__ == "__main__":
    raise SystemExit(main())

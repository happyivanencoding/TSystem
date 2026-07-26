"""Compatibility entrypoint; use :mod:`tp_models.sector.model`."""

from tp_models.sector.model import *  # noqa: F403
from tp_models.sector.model import main


if __name__ == "__main__":
    raise SystemExit(main())

"""Compatibility entrypoint; use :mod:`tp_models.ml.production`."""

from tp_models.ml.production import *  # noqa: F403
from tp_models.ml.production import main


if __name__ == "__main__":
    raise SystemExit(main())

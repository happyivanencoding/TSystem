"""Compatibility entrypoint; use :mod:`tp_models.ml.signals`."""

from tp_models.ml.signals import *  # noqa: F403
from tp_models.ml.signals import main


if __name__ == "__main__":
    raise SystemExit(main())

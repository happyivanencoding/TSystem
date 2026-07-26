"""Compatibility entrypoint; use :mod:`tp_models.ml.cli`."""

from tp_models.ml.cli import *  # noqa: F403
from tp_models.ml.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

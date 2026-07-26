"""Compatibility entrypoint; use :mod:`tp_models.small_cap`."""

from tp_models.small_cap import *  # noqa: F403
from tp_models.small_cap import main


if __name__ == "__main__":
    raise SystemExit(main())

"""Compatibility entrypoint; use :mod:`tp_data.monthly_update`."""

from tp_data.monthly_update import *  # noqa: F403
from tp_data.monthly_update import main


if __name__ == "__main__":
    raise SystemExit(main())

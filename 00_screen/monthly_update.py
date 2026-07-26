"""Compatibility entrypoint; use :mod:`tp_data.monthly_update`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_data.monthly_update import *  # noqa: F403
from tp_data.monthly_update import main


if __name__ == "__main__":
    warn_legacy_entrypoint("00_screen/monthly_update.py", "python -m tp_data.monthly_update")
    raise SystemExit(main())

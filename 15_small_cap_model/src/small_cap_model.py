"""Compatibility entrypoint; use :mod:`tp_models.small_cap`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_models.small_cap import *  # noqa: F403
from tp_models.small_cap import main


if __name__ == "__main__":
    warn_legacy_entrypoint("15_small_cap_model/src/small_cap_model.py", "python -m tp_models.small_cap")
    raise SystemExit(main())

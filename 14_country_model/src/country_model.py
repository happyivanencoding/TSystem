"""Compatibility entrypoint; use :mod:`tp_models.country`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_models.country import *  # noqa: F403
from tp_models.country import main


if __name__ == "__main__":
    warn_legacy_entrypoint("14_country_model/src/country_model.py", "python -m tp_models.country")
    raise SystemExit(main())

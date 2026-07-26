"""Compatibility entrypoint; use :mod:`tp_models.sector.model`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_models.sector.model import *  # noqa: F403
from tp_models.sector.model import main


if __name__ == "__main__":
    warn_legacy_entrypoint(
        "13_sector_score_model/src/sector_score_model.py",
        "python -m tp_models.sector.model",
    )
    raise SystemExit(main())

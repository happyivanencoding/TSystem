"""Compatibility entrypoint; use :mod:`tp_models.ml.production`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_models.ml.production import *  # noqa: F403
from tp_models.ml.production import main


if __name__ == "__main__":
    warn_legacy_entrypoint("03_ml_enhanced/produce_score_ml.py", "python -m tp_models.ml.production")
    raise SystemExit(main())

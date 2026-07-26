"""Compatibility entrypoint; use :mod:`tp_models.ml.signals`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_models.ml.signals import *  # noqa: F403
from tp_models.ml.signals import main


if __name__ == "__main__":
    warn_legacy_entrypoint("03_ml_enhanced/export_signals.py", "python -m tp_models.ml.signals")
    raise SystemExit(main())

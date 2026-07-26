"""Compatibility entrypoint; use :mod:`tp_models.ml.cli`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_models.ml.cli import *  # noqa: F403
from tp_models.ml.cli import main


if __name__ == "__main__":
    warn_legacy_entrypoint("03_ml_enhanced/cli.py", "python -m tp_models.ml.cli")
    raise SystemExit(main())

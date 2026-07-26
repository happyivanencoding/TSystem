"""Compatibility entrypoint; use :mod:`tp_models.technical_signals`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_models.technical_signals import *  # noqa: F403
from tp_models.technical_signals import main


if __name__ == "__main__":
    warn_legacy_entrypoint(
        "03_technical_analysis/export_technical_signals.py",
        "python -m tp_models.technical_signals",
    )
    raise SystemExit(main())

"""Compatibility entrypoint; use :mod:`presentation_layer.cli`."""

from tp_core.deprecation import warn_legacy_entrypoint
from presentation_layer.cli import *  # noqa: F403
from presentation_layer.cli import main


if __name__ == "__main__":
    warn_legacy_entrypoint("08_presentation_layer/cli.py", "python -m presentation_layer.cli")
    raise SystemExit(main())

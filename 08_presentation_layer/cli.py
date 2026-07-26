"""Compatibility entrypoint; use :mod:`presentation_layer.cli`."""

from presentation_layer.cli import *  # noqa: F403
from presentation_layer.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

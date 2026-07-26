"""Deprecated workspace entry point for :mod:`tp_reporting.factor_research_app`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_reporting.factor_research_app import main

warn_legacy_entrypoint(
    legacy="09_reports/build_factor_research_app.py",
    replacement="tp-build-factor-research-app",
)


if __name__ == "__main__":
    raise SystemExit(main())

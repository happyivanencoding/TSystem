"""Compatibility entrypoint; use :mod:`tp_models.regime.export_risk_budget`."""

from tp_core.deprecation import warn_legacy_entrypoint
from tp_models.regime.export_risk_budget import *  # noqa: F403
from tp_models.regime.export_risk_budget import main


if __name__ == "__main__":
    warn_legacy_entrypoint(
        "03_regime_model/export_risk_budget.py",
        "python -m tp_models.regime.export_risk_budget",
    )
    raise SystemExit(main())

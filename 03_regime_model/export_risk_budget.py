"""Compatibility entrypoint; use :mod:`tp_models.regime.export_risk_budget`."""

from tp_models.regime.export_risk_budget import *  # noqa: F403
from tp_models.regime.export_risk_budget import main


if __name__ == "__main__":
    raise SystemExit(main())

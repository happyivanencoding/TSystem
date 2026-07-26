"""SP500 wrapper for same-security relative-variable research."""

from __future__ import annotations
from tp_research.runtime import recorded_workflow

from pathlib import Path
from typing import Iterable


from tp_research.paths import SCRIPT_DIR
from tp_research.paths import BACKTEST_ROOT
from tp_research.paths import TP_ROOT

from tp_research.workflows import run_sp500_multifactor_research as sp500  # noqa: E402
from tp_research.workflows import run_stoxx600_relative_variable_research as rel  # noqa: E402


def raw_source(spec) -> str:
    text = f"{spec.column} {spec.note}".lower()
    if "ciq" in text:
        return "CIQ"
    if any(token in text for token in ["daily vol", "drawdown", "beta", "pmom", "total return", "revision", "3m estimate"]):
        return "local_or_derived"
    return "FactSet_or_database"


def configure() -> None:
    sp500.configure_base()
    if not hasattr(sp500.base, "raw_source"):
        sp500.base.raw_source = raw_source
    rel.base = sp500.base
    rel.OUTPUT_PREFIX = "sp500"
    rel.REPORT_TITLE = "SP500 相对变量官方回测研究"
    rel.DEFAULT_OUTPUT_PREFIX = "sp500_relative_variables"
    rel.DEFAULT_LEVEL_GATE = (
        BACKTEST_ROOT
        / "runs"
        / "ad_hoc"
        / "sp500_validated_family_20260708"
        / "raw_validation_gate.csv"
    )


@recorded_workflow
def main(argv: Iterable[str] | None = None) -> int:
    configure()
    return rel.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

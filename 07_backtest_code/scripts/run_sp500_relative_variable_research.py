"""SP500 wrapper for same-security relative-variable research."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
BACKTEST_ROOT = SCRIPT_DIR.parents[0]
TP_ROOT = BACKTEST_ROOT.parent

for path in (SCRIPT_DIR, TP_ROOT, BACKTEST_ROOT, BACKTEST_ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_sp500_multifactor_research as sp500  # noqa: E402
import run_stoxx600_relative_variable_research as rel  # noqa: E402


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


def main(argv: Iterable[str] | None = None) -> int:
    configure()
    return rel.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

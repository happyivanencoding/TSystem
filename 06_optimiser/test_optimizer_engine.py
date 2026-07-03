import sys
from pathlib import Path

import pandas as pd
import pytest

OPT_ROOT = Path(__file__).resolve().parent
if str(OPT_ROOT) not in sys.path:
    sys.path.insert(0, str(OPT_ROOT))

import optimizer_engine as oe


def test_download_optimizer_engine_imports_without_eager_cvxpy():
    assert callable(oe.generate_heuristique)
    assert callable(oe.optimize)
    assert callable(oe.to_standard_weight_table)


def test_cvxpy_mip_solver_available_when_installed():
    if oe.cp is None:
        pytest.skip("cvxpy is optional for import-only usage")

    installed = set(oe.cp.installed_solvers())
    assert {"SCIP", "ECOS_BB", "CBC", "GLPK_MI", "HIGHS"} & installed

    x = oe.cp.Variable(3, boolean=True)
    problem = oe.cp.Problem(oe.cp.Maximize(x[0] + 2 * x[1] + 3 * x[2]), [oe.cp.sum(x) <= 2])
    solver = "ECOS_BB" if "ECOS_BB" in installed else next(iter({"SCIP", "CBC", "GLPK_MI", "HIGHS"} & installed))
    problem.solve(solver=getattr(oe.cp, solver))

    assert problem.status in {"optimal", "optimal_inaccurate"}
    assert problem.value == pytest.approx(5.0, abs=1e-5)

def test_to_standard_weight_table_normalizes_wopt():
    result_df = pd.DataFrame(
        {
            "Date": ["2024-01-31", "2024-01-31", "2024-01-31"],
            "Company SEDOL": ["A", "B", "C"],
            "Wopt": [0.2, 0.3, 0.0],
        }
    )

    weights = oe.to_standard_weight_table(result_df)

    assert weights.columns.tolist() == ["Date", "Company SEDOL", "Portfolio weight"]
    assert weights["Company SEDOL"].tolist() == ["A", "B"]
    assert weights["Portfolio weight"].sum() == pytest.approx(1.0)


def test_generate_heuristique_flags_forced_and_forbidden_boxes():
    df = pd.DataFrame(
        {
            "Exchange Country Region": ["West Europe", "West Europe", "North America", "Others", "Others"],
            "Weight in MSCI WORLD": [0.20, 0.10, 0.30, 0.25, 0.15],
            "Weight_last_drift": [0.00, 0.02, 0.00, 0.00, 0.00],
            "blacklisted": [0, 0, 0, 1, 0],
            "ub": [0.10, 0.10, 0.10, 0.0, 0.00001],
        }
    )

    forbidden, mandatory = oe.generate_heuristique(
        df,
        bench="MSCI WORLD",
        bool_rebal_Europe=True,
        bool_rebal_US=True,
        init=True,
    )

    assert len(forbidden) == len(df)
    assert len(mandatory) == len(df)
    assert sum(mandatory) >= 3
    assert forbidden[3] == 1


def test_optimize_reports_clear_error_when_cvxpy_unavailable():
    if oe.cp is not None:
        pytest.skip("cvxpy imports in this environment")

    with pytest.raises(ImportError, match="cvxpy is required"):
        oe.optimize(
            result_df=None,
            sigma=None,
            df_sector_cible=None,
            df_pays_cible=None,
            bench="MSCI WORLD",
            current_params={},
            init=True,
            scip_options={},
            bool_rebal_Europe=True,
            bool_rebal_US=True,
        )


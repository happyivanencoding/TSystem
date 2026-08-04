from __future__ import annotations

import json
from pathlib import Path
import sys
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from tp_research.registry import HypothesisRegistry, run_definition
from tp_research.workflows import run_monthly_factor_recommendation_research as workflow


def _fake_core_module() -> ModuleType:
    module = ModuleType("tp_models.factor_recommendation")
    dates = pd.date_range("2024-01-31", periods=8, freq="ME")
    securities = ["A", "B", "C", "D"]
    rows = []
    for date_index, date in enumerate(dates):
        for security_index, security in enumerate(securities):
            rows.append(
                {
                    "Date": date,
                    "ISIN": security,
                    "Weight in TEST": 1.0,
                    "Sector": "S1" if security in {"A", "B"} else "S2",
                    "quality": 0.2 * security_index + 0.01 * date_index,
                    "value": 1.0 - 0.1 * security_index,
                }
            )
    screen = pd.DataFrame(rows)
    returns = pd.DataFrame(
        {
            security: [0.01 * (index + 1) + (0.001 if security == "A" else 0.0) for index in range(9)]
            for security in securities
        },
        index=pd.date_range("2024-02-01", periods=9, freq="ME"),
    )

    def load_research_inputs(mode: str = "full", seed: int = 1729) -> dict[str, object]:
        assert mode in {"full", "smoke", "inspect"}
        assert seed == 1729
        return {
            "screen": screen,
            "returns": returns,
            "universe": {
                "name": "TEST",
                "date_column": "Date",
                "security_id_column": "ISIN",
                "weight_column": "Weight in TEST",
                "group_column": "Sector",
            },
            "factors": [
                {"name": "quality", "column": "quality", "direction": 1, "family": "quality"},
                {"name": "value", "column": "value", "direction": 1, "family": "value"},
            ],
            "model": {
                "models": [
                    {"name": "quality_only", "features": ["quality"]},
                    {"name": "value_only", "features": ["value"]},
                ],
                "minimum_train_months": 2,
                "walk_forward_splits": 2,
                "effective_trial_count": 2,
                "cost_assumptions": {"transaction_cost": 0.001, "slippage": 0.0005},
                "bootstrap_samples": 8,
            },
            "components": {"ASIA": {"status": "configured"}, "synthetic": False},
        }

    module.load_research_inputs = load_research_inputs  # type: ignore[attr-defined]
    return module


@pytest.fixture()
def fake_core(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = _fake_core_module()
    monkeypatch.setitem(sys.modules, "tp_models.factor_recommendation", module)
    return module


def _definition() -> object:
    return HypothesisRegistry().load("monthly-factor-recommendation-v1")


def test_registry_validates_monthly_factor_definition() -> None:
    definition = _definition()
    assert definition.hypothesis_id == "monthly-factor-recommendation-v1"
    assert definition.runner["module"] == workflow.__name__
    assert definition.payload["research_contract"]["decision_policy"] == "review_required; never auto-promote"


def test_smoke_writes_required_auditable_artifacts(fake_core: ModuleType, tmp_path: Path) -> None:
    output_dir = tmp_path / "results"
    assert workflow.main(["--smoke", "--output-dir", str(output_dir), "--max-months", "6"]) == 0

    required = set(workflow.REQUIRED_ARTIFACTS)
    assert required <= {path.name for path in output_dir.iterdir()}
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_mode"] == "smoke"
    assert manifest["is_full"] is False
    assert (output_dir / "feature_matrix.parquet").exists()
    assert (output_dir / "fold_predictions.parquet").exists()
    report = (output_dir / "research_report.md").read_text(encoding="utf-8")
    assert "ASIA" in report
    assert "synthetic" in report


def test_registry_run_records_review_required_and_no_auto_promotion(fake_core: ModuleType, tmp_path: Path) -> None:
    run_card = run_definition(_definition(), arguments=["--smoke", "--max-months", "6"], root=tmp_path / "runs")
    payload = json.loads(run_card.read_text(encoding="utf-8"))
    assert payload["run"]["status"] == "success"
    assert payload["decision"]["status"] == "review_required"
    assert payload["decision"]["status"] != "promote"
    results = run_card.parent / "results"
    assert (results / "manifest.json").exists()


def test_registry_rejects_user_output_dir_override(tmp_path: Path) -> None:
    definition = _definition()
    with pytest.raises(ValueError, match="output-dir"):
        run_definition(definition, arguments=["--smoke", "--output-dir", str(tmp_path / "override")], root=tmp_path / "runs")


def test_full_cannot_be_claimed_with_resource_caps(fake_core: ModuleType, tmp_path: Path) -> None:
    assert workflow.main(["--full", "--max-months", "4", "--output-dir", str(tmp_path / "results")]) != 0


def test_prompt_aliases_keep_purge_cost_grid_and_registered_candidates(fake_core: ModuleType, tmp_path: Path) -> None:
    output_dir = tmp_path / "results"
    assert workflow.main(["--smoke", "--output-dir", str(output_dir), "--max-months", "6"]) == 0
    costs = pd.read_csv(output_dir / "cost_sensitivity.csv")
    assert set(costs["transaction_cost_bps"]) == {0.0, 10.0, 25.0, 50.0}
    folds = pd.read_csv(output_dir / "walk_forward_folds.csv")
    assert "purge_months" in folds.columns
    candidates = pd.read_csv(output_dir / "model_candidate_registry.csv")
    assert {"quality_only", "value_only"} <= set(candidates["name"])

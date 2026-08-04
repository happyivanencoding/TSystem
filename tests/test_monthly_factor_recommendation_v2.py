from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from tp_models.factor_recommendation.v2_research import (
    MODEL_IDS,
    allocate_top2,
    block_bootstrap,
    build_factor_panel,
    make_smoke_sleeve_returns,
    walk_forward_predictions,
)
from tp_models.factor_recommendation.v2_sleeves import V2_FACTOR_DEFINITIONS
from tp_research.workflows import run_monthly_factor_recommendation_v2_research as workflow


ROOT = Path(__file__).resolve().parents[1]


def test_v2_contract_defines_eight_factors_and_rejects_v1() -> None:
    config = json.loads((ROOT / "config/research/hypotheses/monthly-factor-recommendation-v2.json").read_text(encoding="utf-8"))
    rejected = json.loads((ROOT / "config/research/model_candidates/monthly-factor-recommendation-v1-rejected.json").read_text(encoding="utf-8"))

    assert config["parent_hypothesis_id"] == "monthly-factor-recommendation-v1"
    assert config["sleeve"]["research_unit"] == "Date x Region x RegionComponent x Factor x SleeveSide"
    assert {item["name"] for item in config["factor_definitions"]} == {item["name"] for item in V2_FACTOR_DEFINITIONS}
    assert next(item for item in V2_FACTOR_DEFINITIONS if item["name"] == "small_size")["direction"] == -1
    assert rejected["decision"] == "reject"
    assert rejected["production_eligible"] is False


def test_v2_smoke_writes_complete_manifest_and_factor_panel(tmp_path: Path) -> None:
    output_dir = tmp_path / "v2-results"
    assert workflow.main(["--smoke", "--output-dir", str(output_dir), "--seed", "42"]) == 0

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    assert manifest["official_engine"].endswith("OfficialPortfolioBacktest")
    assert all(item["exists"] for item in manifest["artifacts"].values())
    panel = pd.read_parquet(output_dir / "factor_panel.parquet")
    assert {"Date", "region", "factor", "feature_as_of_date"} <= set(panel.columns)
    assert not {"ISIN", "Company SEDOL", "security_id"} & set(panel.columns)
    gates = pd.read_csv(output_dir / "promotion_gate.csv")
    stress = gates.loc[gates["gate_name"].eq("50bps_stress"), "actual"]
    assert len(stress) == 1
    assert stress.notna().all()


def test_v2_candidates_use_real_sklearn_backends_and_block_bootstrap() -> None:
    sleeves = make_smoke_sleeve_returns(months=12)
    panel = build_factor_panel(sleeves)
    predictions, fit_records, _, _ = walk_forward_predictions(panel, minimum_train_months=60, purge_months=1, smoke=True)

    assert set(predictions["model_id"]) == set(MODEL_IDS)
    assert set(fit_records["backend"]) == {"sklearn.linear_model.Ridge", "sklearn.linear_model.ElasticNet"}
    distinct_vectors = predictions.groupby("model_id")["prediction"].nunique().to_dict()
    assert len(set(distinct_vectors.values())) > 1
    bootstrap = block_bootstrap(pd.Series([0.01, -0.01, 0.02, 0.01]), block_length=2, samples=32, seed=42)
    assert bootstrap["method"] == "moving_block_bootstrap"
    assert bootstrap["block_length"] == 2


def test_low_factor_coverage_forces_no_view() -> None:
    sleeves = make_smoke_sleeve_returns(months=6, regions=("US",), factors=("value", "quality"))
    panel = build_factor_panel(sleeves)
    panel["factor_coverage"] = 0.5
    panel["coverage"] = 0.5
    predictions, _, _, _ = walk_forward_predictions(panel, minimum_train_months=60, purge_months=1, smoke=True)

    allocations = allocate_top2(predictions, panel, cost_grid_bps=(25.0,), minimum_coverage=0.8)
    assert not allocations.empty
    assert set(allocations["stance"]) == {"NO_VIEW"}
    assert allocations["recommended_weight"].sum() == 0

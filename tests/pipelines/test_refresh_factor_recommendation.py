from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from tp_pipelines import refresh_factor_recommendation as refresh
from tp_pipelines.configs import RefreshFactorRecommendationConfig
from tp_pipelines.orchestration import pipeline_dag


def _args(tmp_path: Path, **overrides: object) -> SimpleNamespace:
    values = {
        "inspect_only": False,
        "as_of": None,
        "screen": str(tmp_path / "screen.parquet"),
        "returns": str(tmp_path / "returns.parquet"),
        "universe_config": str(tmp_path / "universe.json"),
        "factor_config": str(tmp_path / "factors.json"),
        "model_config": str(tmp_path / "model.json"),
        "output_dir": str(tmp_path / "outputs"),
        "signal_output": str(tmp_path / "signals.parquet"),
        "all_history": True,
        "use_frozen_model": False,
        "minimum_coverage": 0.5,
        "run_type": "smoke",
        "experiment_root": str(tmp_path / "experiments"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_parser_and_config_cover_factor_recommendation_flags() -> None:
    args = refresh.build_parser().parse_args(
        [
            "--inspect-only",
            "--as-of",
            "2026-07-31",
            "--all-history",
            "--use-frozen-model",
            "--minimum-coverage",
            "0.8",
            "--run-type",
            "inspect",
        ]
    )
    config = RefreshFactorRecommendationConfig.from_namespace(args)

    assert config.inspect_only is True
    assert config.as_of == "2026-07-31"
    assert config.all_history is True
    assert config.use_frozen_model is True
    assert config.minimum_coverage == 0.8
    assert config.run_type == "inspect"


def test_inspect_only_writes_research_manifest_without_canonical_outputs(tmp_path, monkeypatch) -> None:
    manifest_dir = tmp_path / "manifests"
    monkeypatch.setattr("tp_pipelines.common.PIPELINE_MANIFESTS_DIR", manifest_dir)

    manifest_path = refresh.run_refresh_factor_recommendation(
        _args(tmp_path, inspect_only=True, run_type="inspect")
    )

    assert manifest_path == manifest_dir / "refresh_factor_recommendation" / manifest_path.name
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["step"] == "refresh_factor_recommendation"
    assert payload["status"] == "success"
    assert payload["parameters"]["research_only"] is True
    assert payload["details"]["production_effects"]["security_candidates"] is False
    assert payload["details"]["production_effects"]["optimizer"] is False


def test_refresh_writes_isolated_panel_history_and_signal(tmp_path, monkeypatch) -> None:
    manifest_dir = tmp_path / "manifests"
    monkeypatch.setattr("tp_pipelines.common.PIPELINE_MANIFESTS_DIR", manifest_dir)
    dates = pd.to_datetime(["2026-06-30", "2026-07-31"])
    screen = pd.DataFrame(
        {
            "Date": [dates[0], dates[0], dates[1], dates[1]],
            "Exchange Country Region": ["US", "EU", "US", "ASIA"],
            "Value Avg Percentile": [80, 20, 90, 50],
            "Quality Avg Percentile": [70, 30, 80, 40],
            "Mom Avg Percentile": [60, 40, 70, 30],
            "Growth Avg Percentile": [50, 50, 60, 20],
            "LowVol Avg Percentile": [40, 60, 50, 10],
        }
    )
    screen.to_parquet(tmp_path / "screen.parquet", index=False)
    pd.DataFrame({"Date": dates, "SEDOL": ["A", "A"]}).to_parquet(
        tmp_path / "returns.parquet", index=False
    )
    (tmp_path / "universe.json").write_text(
        json.dumps({"approved_regions": ["US", "EU"]}), encoding="utf-8"
    )
    (tmp_path / "factors.json").write_text(
        json.dumps({"factor_columns": {"Value": "Value Avg Percentile"}}),
        encoding="utf-8",
    )

    output_manifest = refresh.run_refresh_factor_recommendation(_args(tmp_path))
    panel_path = tmp_path / "outputs" / "factor_recommendation_panel.parquet"
    history_path = tmp_path / "outputs" / "factor_recommendation_history.parquet"
    signal_path = tmp_path / "signals.parquet"

    assert output_manifest.exists()
    assert panel_path.exists()
    assert history_path.exists()
    assert signal_path.exists()
    signal = pd.read_parquet(signal_path)
    assert {
        "Date",
        "signal_family",
        "scope",
        "coverage_flag",
        "model_version",
        "source_project",
    } <= set(signal.columns)
    assert set(signal["source_project"].dropna()) == {"16_factor_recommendation_model"}
    assert set(pd.read_parquet(panel_path)["region"]) == {"US", "EU", "ASIA"}


def test_research_step_is_independent_and_disabled_by_default() -> None:
    dag = pipeline_dag()
    step = next(item for item in dag.ordered_steps() if item.name == "refresh_factor_recommendation")

    assert step.dependencies == ()
    assert step.enabled(SimpleNamespace(config=SimpleNamespace(controls=SimpleNamespace()))) is False


def test_v2_snapshot_and_forecast_contracts_are_separate() -> None:
    snapshot = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-07-31", "2026-07-31"]),
            "factor": ["value", "small_size"],
            "score_0_100": [55.0, 65.0],
            "coverage_flag": [True, True],
            "model_version": ["factor-exposure-snapshot-v2"] * 2,
            "region": ["US", "US"],
            "benchmark": ["SP500", "SP500"],
            "region_key": ["US", "US"],
            "as_of_date": pd.to_datetime(["2026-07-31", "2026-07-31"]),
            "effective_date": pd.to_datetime(["2026-07-31", "2026-07-31"]),
            "horizon": ["1M", "1M"],
            "confidence": [0.9, 0.9],
            "recommendation": ["Neutral", "Positive"],
            "factor_label": ["Value", "Small Size"],
            "factor_coverage": [0.9, 0.9],
            "weight_coverage": [0.9, 0.9],
            "production_eligible": [True, True],
            "benchmark_approved": [True, True],
            "approval_status": ["approved", "approved"],
            "prediction_semantics": ["snapshot", "snapshot"],
        }
    )
    signal = refresh._build_exposure_snapshot_signal(snapshot, 0.8)
    forecast = refresh._build_forecast_unavailable_signal(snapshot)

    assert set(signal["mode"]) == {"exposure_snapshot"}
    assert signal["not_a_forecast"].all()
    assert "prediction_semantics" not in signal.columns
    assert set(forecast["stance"]) == {"NO_VIEW"}
    assert set(forecast["model_status"]) == {"model_unavailable"}
    assert len(refresh._v2_snapshot_factor_definitions()) == 8

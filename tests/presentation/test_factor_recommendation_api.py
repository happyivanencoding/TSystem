from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def test_factor_recommendation_state_and_api_contract(tmp_path: Path, monkeypatch) -> None:
    from presentation_layer.apps import system_dashboard as dashboard

    output_dir = tmp_path / "outputs"
    panel_path = output_dir / "factor_recommendation_panel.parquet"
    history_path = output_dir / "factor_recommendation_history.parquet"
    signal_path = tmp_path / "factor_recommendation_signals.parquet"
    manifest_path = tmp_path / "refresh_factor_recommendation_latest.json"
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-07-31", "2026-07-31"]),
            "region": ["US", "ASIA"],
            "factor": ["Value", "Quality"],
            "recommendation": ["Positive", "Positive"],
            "score": [0.8, 0.9],
        }
    )
    output_dir.mkdir(parents=True)
    frame.to_parquet(panel_path, index=False)
    frame.to_parquet(history_path, index=False)
    frame.to_parquet(signal_path, index=False)
    manifest_path.write_text(
        json.dumps(
            {
                "step": "refresh_factor_recommendation",
                "status": "success",
                "run_type": "smoke",
                "details": {"evidence": [{"name": "frozen"}]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard, "FACTOR_RECOMMENDATION_PANEL_PATH", panel_path)
    monkeypatch.setattr(dashboard, "FACTOR_RECOMMENDATION_HISTORY_PATH", history_path)
    monkeypatch.setattr(dashboard, "FACTOR_RECOMMENDATION_SIGNAL_PATH", signal_path)
    monkeypatch.setattr(dashboard, "FACTOR_RECOMMENDATION_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(dashboard, "FACTOR_RECOMMENDATION_OUTPUT_DIR", output_dir)

    app = dashboard.create_app()
    client = app.server.test_client()
    default_state = client.get("/api/dashboard/state").get_json()
    detailed_state = client.get("/api/dashboard/state?include_details=true").get_json()
    payload = client.get("/api/dashboard/signals/factor-recommendation").get_json()

    assert "factor_recommendation" in default_state["signals"]
    assert "factor_recommendation" in detailed_state["signals"]
    assert payload["latest_date"] == "2026-07-31"
    assert payload["research_only"] is True
    assert payload["affects_security_candidates"] is False
    assert payload["affects_optimizer"] is False
    assert payload["asia_approved"] is False
    assert "asian_unapproved" in payload["warnings"]
    assert payload["evidence"] == [{"name": "frozen"}]
    assert len(payload["rows"]) == 2


def test_factor_recommendation_job_uses_registered_pipeline_command(tmp_path: Path, monkeypatch) -> None:
    from presentation_layer.apps import system_dashboard as dashboard

    monkeypatch.setattr(dashboard, "LAUNCH_DIR", tmp_path / "launches")

    class FakeProcess:
        pid = 12345

    monkeypatch.setattr(dashboard.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    response = dashboard.create_app().server.test_client().post(
        "/api/dashboard/jobs/signals/factor-recommendation"
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["record"]["step"] == "signal:factor_recommendation"
    assert "tp_pipelines.refresh_factor_recommendation" in " ".join(
        payload["record"]["command"]
    )

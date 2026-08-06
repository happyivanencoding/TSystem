from __future__ import annotations

from tp_pipelines.freshness import generated_at_freshness, market_data_freshness


def test_future_market_data_is_rejected() -> None:
    result = market_data_freshness(
        "signal",
        "2026-08-02",
        as_of_date="2026-07-31",
        allowed_lag_days=31,
    )

    assert result["ok"] is False
    assert result["lag_days"] == -2
    assert "after" in str(result["message"])


def test_market_data_within_lag_is_allowed() -> None:
    result = market_data_freshness(
        "signal",
        "2026-07-20",
        as_of_date="2026-07-31",
        allowed_lag_days=31,
    )

    assert result["ok"] is True
    assert result["lag_days"] == 11


def test_market_data_outside_lag_is_rejected() -> None:
    result = market_data_freshness(
        "signal",
        "2026-06-01",
        as_of_date="2026-07-31",
        allowed_lag_days=31,
    )

    assert result["ok"] is False
    assert result["lag_days"] == 60
    assert "older" in str(result["message"])


def test_explicit_reuse_records_source_and_reason() -> None:
    result = generated_at_freshness(
        "report",
        "2026-07-01T00:00:00Z",
        production_run_started_at="2026-08-01T00:00:00Z",
        reused=True,
        reuse_source="artifacts/pipeline_runs/manifests/generate_report/old.json",
        reuse_reason="approved month-end evidence",
    )

    assert result["ok"] is True
    assert result["reused"] is True
    assert result["reuse_source"]
    assert result["reuse_reason"] == "approved month-end evidence"


def test_generation_time_is_not_replaced_by_market_data_date() -> None:
    result = generated_at_freshness(
        "report",
        "2026-07-31T12:00:00Z",
        production_run_started_at="2026-08-01T00:00:00Z",
    )

    assert result["ok"] is False
    assert result["kind"] == "run_generation"
    assert str(result["generated_at"]).startswith("2026-07-31T12:00:00")

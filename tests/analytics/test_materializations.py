from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from test_io_engine import _fixture_release

from tp_core.analytics.catalog import build_catalog_release
from tp_core.analytics.config import DuckDBConfig
from tp_core.analytics.connection import connect


def test_refresh_presentation_marts_rebuilds_dashboard_contract(tmp_path: Path) -> None:
    database, _screen_path, _ = _fixture_release(tmp_path)
    artifact_root = tmp_path / "artifacts"
    signals_root = artifact_root / "signals"
    candidates_root = artifact_root / "candidates"
    portfolios_root = artifact_root / "portfolios"
    manifest_root = artifact_root / "pipeline_runs" / "manifests" / "run_research"
    for path in (signals_root, candidates_root, portfolios_root, manifest_root):
        path.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-01-31", "2026-02-28", "2026-02-28"]),
            "Company SEDOL": ["SED1", "SED1", "SED2"],
            "signal_family": ["factor", "regime", "factor"],
            "signal_name": ["value", "country", "momentum"],
            "signal_value": [1.0, 2.0, 3.0],
        }
    ).to_parquet(signals_root / "signals.parquet")
    pd.DataFrame({"Company SEDOL": ["SED1"], "rank": [1]}).to_parquet(
        candidates_root / "latest_candidates.parquet"
    )
    pd.DataFrame({"Company SEDOL": ["SED1", "SED2"], "target_weight": [0.6, 0.4]}).to_parquet(
        portfolios_root / "latest_target_weights.parquet"
    )
    (manifest_root / "research_latest.json").write_text(
        json.dumps(
            {
                "run_id": "research-fixture-1",
                "run_type": "research",
                "status": "passed",
                "finished_at": "2026-02-28T18:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    backtest_root = artifact_root / "pipeline_runs" / "manifests" / "run_backtest"
    backtest_root.mkdir(parents=True, exist_ok=True)
    (backtest_root / "run_backtest_latest.json").write_text(
        json.dumps(
            {
                "run_id": "backtest-fixture-1",
                "status": "passed",
                "finished_at": "2026-02-28T19:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    config = DuckDBConfig(
        database_path=database,
        temp_directory=tmp_path / "artifacts" / "analytics" / "duckdb" / "temp-refresh",
        data_root=tmp_path,
        artifact_root=artifact_root,
        latest_pointer=artifact_root / "analytics" / "duckdb" / "latest.json",
    )
    current_screen = tmp_path / "00_screen" / "datasets" / "manifests" / "screen" / "current.json"
    current_returns = tmp_path / "00_screen" / "datasets" / "manifests" / "returns_wide" / "current.json"
    summary = build_catalog_release(
        config,
        release_id="marts-fixture",
        screen_manifest_path=current_screen,
        returns_manifest_path=current_returns,
        refresh_marts=True,
    )

    assert summary["marts"]["status"] == "passed"
    assert summary["catalog_health"]["ok"] is True
    with connect(config.with_database(Path(str(summary["database_path"])), read_only=True)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM marts.company_master_latest").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM marts.latest_signals").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM marts.latest_candidates").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM marts.latest_portfolio").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM marts.latest_backtest_summary").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM marts.dashboard_overview").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM marts.pipeline_run_summary").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM marts.research_run_summary").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM meta.artifact_registry").fetchone()[0] >= 4
        assert connection.execute("SELECT COUNT(*) FROM meta.run_registry").fetchone()[0] == 2
        assert connection.execute("SELECT validation_status FROM meta.catalog_releases").fetchone()[0] == "marts_ready"

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from presentation_layer.apps import system_repository as repository_module
from presentation_layer.apps.system_repository import SystemDashboardRepository, mart_route_for_path


def _write_mart_database(path: Path, value: str) -> None:
    connection = duckdb.connect(str(path))
    try:
        connection.execute("CREATE SCHEMA marts")
        connection.execute(
            'CREATE TABLE "marts"."latest_candidates" '
            '("Company SEDOL" VARCHAR, "Name" VARCHAR)'
        )
        connection.execute('INSERT INTO "marts"."latest_candidates" VALUES (?, ?)', [value, value])
    finally:
        connection.close()


def _repository(tmp_path: Path) -> SystemDashboardRepository:
    return SystemDashboardRepository(
        config_path=tmp_path / "dashboard.json",
        defaults={},
        qa_dir=tmp_path,
        manifest_dir=tmp_path,
        data_root=tmp_path,
    )


def test_dashboard_repository_reads_current_mart_and_reopens_new_pointer_release(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_one = tmp_path / "release-one.duckdb"
    database_two = tmp_path / "release-two.duckdb"
    _write_mart_database(database_one, "SED1")
    _write_mart_database(database_two, "SED2")
    pointer = tmp_path / "latest.json"
    monkeypatch.setenv("TP_DUCKDB_PATH", str(tmp_path / "missing.duckdb"))
    monkeypatch.setenv("TP_DUCKDB_LATEST_POINTER", str(pointer))
    source = tmp_path / "artifacts" / "candidates" / "latest_candidates.parquet"
    source.parent.mkdir(parents=True)
    pd.DataFrame({"Company SEDOL": ["artifact"], "Name": ["artifact"]}).to_parquet(source)
    repository = _repository(tmp_path)

    pointer.write_text(
        json.dumps({"release_id": "release-one", "database_path": str(database_one)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(repository_module.pd, "read_parquet", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("artifact fallback used")))
    first = repository.read_frame(source)
    assert first is not None
    assert first["Company SEDOL"].tolist() == ["SED1"]
    assert repository.catalog_identity().release_id == "release-one"

    pointer.write_text(
        json.dumps({"release_id": "release-two", "database_path": str(database_two)}),
        encoding="utf-8",
    )
    second = repository.read_frame(source)
    assert second is not None
    assert second["Company SEDOL"].tolist() == ["SED2"]


def test_dashboard_repository_refuses_unbounded_or_unallowlisted_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = _repository(tmp_path)
    allowed = tmp_path / "artifacts" / "signals" / "technical_signals.parquet"
    allowed.parent.mkdir(parents=True)
    pd.DataFrame({"Date": [pd.Timestamp("2026-01-01")], "value": [1.0]}).to_parquet(allowed)
    outside = tmp_path / "other" / "untrusted.parquet"
    outside.parent.mkdir()
    pd.DataFrame({"value": [1.0]}).to_parquet(outside)
    monkeypatch.setattr(repository_module, "MAX_DASHBOARD_ARTIFACT_FALLBACK_BYTES", 1)

    assert repository.read_frame(allowed) is None
    assert repository.read_frame(outside) is None


def test_dashboard_repository_requires_a_valid_pointer_for_mart_reads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "release.duckdb"
    _write_mart_database(database, "SED1")
    pointer = tmp_path / "latest.json"
    monkeypatch.setenv("TP_DUCKDB_PATH", str(tmp_path / "missing.duckdb"))
    monkeypatch.setenv("TP_DUCKDB_LATEST_POINTER", str(pointer))
    source = tmp_path / "artifacts" / "candidates" / "latest_candidates.parquet"
    repository = _repository(tmp_path)

    pointer.write_text(
        json.dumps({"release_id": "release", "database_path": str(database)}),
        encoding="utf-8",
    )
    current = repository.read_frame(source)
    assert current is not None
    assert current["Company SEDOL"].tolist() == ["SED1"]

    pointer.write_text(
        json.dumps({"release_id": "stale", "database_path": str(tmp_path / "gone.duckdb")}),
        encoding="utf-8",
    )
    assert repository.catalog_identity() is None
    assert repository.read_frame(source) is None


def test_latest_route_mapping_does_not_treat_history_as_latest() -> None:
    assert mart_route_for_path(Path("artifacts/signals/regime_risk_budget.parquet")).name == "latest_regime"
    assert mart_route_for_path(Path("artifacts/signals/technical_signals.parquet")).name == "latest_signals"
    assert mart_route_for_path(Path("13_sector_score_model/outputs/sector_scores_panel.parquet"), purpose="history") is None

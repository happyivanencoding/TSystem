from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from presentation_layer import PresentationDataRepository
from presentation_layer.cli import main


def test_repository_exposes_canonical_paths() -> None:
    repo = PresentationDataRepository()
    assert repo.signals_dir.name == "04_signals"
    assert repo.signal_path("ml_signals.parquet").name == "ml_signals.parquet"


def test_cli_inventory(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["inventory"]) == 0
    out = capsys.readouterr().out
    assert "web-companies" in out
    assert "company-api" in out
    assert "system-dashboard" in out
    assert "system-worker" in out
    assert "system-checks" in out
    assert "system-registry" in out
    assert "dashboard" in out


def test_company_api_factory_imports_without_loading_data() -> None:
    from presentation_layer.apps.company_analysis_api import create_app

    app = create_app()
    routes = {route.path for route in app.routes}
    assert "/api/health" in routes
    assert "/api/search" in routes


def test_system_worker_cli_once_on_empty_queue(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["system-worker", "--once", "--launch-dir", str(tmp_path / "launches")]) == 0
    assert "processed 0 queued jobs" in capsys.readouterr().out


def test_report_wrapper_exposes_lazy_entrypoints() -> None:
    from presentation_layer.reports import portfolio_dashboard

    assert portfolio_dashboard.DASHBOARD_ROOT.name == "08_dashboard_analysis"
    assert callable(portfolio_dashboard.get_dashboard_class)


def test_system_dashboard_factory_imports_without_loading_data() -> None:
    from presentation_layer.apps.system_dashboard import create_app

    app = create_app()
    assert app.title == "TP System Dashboard"
    assert "tp-action-feedback" in repr(app.layout)
    assert "tp-active-job" in repr(app.layout)
    assert "tp-job-api-state" in repr(app.layout)
    assert "React 交互版" in repr(app.layout)
    assert "/client/" in repr(app.layout)
    assert "EventSource" in app.index_string
    assert "/api/dashboard/state" in {rule.rule for rule in app.server.url_map.iter_rules()}
    assert "/api/dashboard/jobs/latest" in app.index_string
    assert "/api/dashboard/jobs/pipeline" in app.index_string
    assert "/api/dashboard/jobs/project" in app.index_string
    assert "/api/dashboard/jobs/system-checks" in app.index_string
    assert "/events" in app.index_string
    assert "stopImmediatePropagation" in app.index_string
    assert "apiLaunchJob" in app.index_string
    assert "tpJobEvents" in app.index_string
    assert "tpClientLaunch" in app.index_string
    assert "jobRealtime" in app.index_string
    assert "tpDashboardJobEvents" in app.index_string
    assert any("tp-action-feedback" in output for output in app.callback_map)
    assert any("tp-active-job" in output for output in app.callback_map)
    assert any("tp-job-api-state" in output for output in app.callback_map)
    routes = {rule.rule for rule in app.server.url_map.iter_rules()}
    assert "/" in routes
    assert "/index.html" in routes
    assert any(route.startswith("/dash/") for route in routes)
    assert "/api/dashboard/state" in routes
    assert "/api/dashboard/jobs/latest" in routes
    assert "/api/dashboard/jobs/queue" in routes
    assert "/api/dashboard/jobs/queue/events" in routes
    assert "/api/dashboard/jobs/<job_id>" in routes
    assert "/api/dashboard/jobs/<job_id>/events" in routes
    assert "/api/dashboard/jobs/system-checks" in routes
    assert "/api/dashboard/jobs/project" in routes
    assert "/api/dashboard/jobs/pipeline" in routes
    assert "/client/" in routes
    assert "/client/index.html" in routes
    assert "/client/assets/<path:filename>" in routes


def test_system_dashboard_serves_react_client_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from presentation_layer.apps import system_dashboard as dashboard

    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text(
        '<div id="root"></div><script type="module" src="/client/assets/app.js"></script>',
        encoding="utf-8",
    )
    (assets_dir / "app.js").write_text("console.log('tp client')", encoding="utf-8")
    monkeypatch.setattr(dashboard, "CLIENT_DIST_DIR", dist_dir)
    monkeypatch.setattr(dashboard, "CLIENT_ASSETS_DIR", assets_dir)

    client = dashboard.create_app().server.test_client()
    root_response = client.get("/")
    assert root_response.status_code == 200
    assert "/client/assets/app.js" in root_response.data.decode("utf-8")

    index_response = client.get("/client/")
    assert index_response.status_code == 200
    assert "/client/assets/app.js" in index_response.data.decode("utf-8")

    asset_response = client.get("/client/assets/app.js")
    assert asset_response.status_code == 200
    assert asset_response.data == b"console.log('tp client')"

    dash_layout_response = client.get("/dash/_dash-layout")
    assert dash_layout_response.status_code == 200
    assert "React 交互版" in dash_layout_response.data.decode("utf-8")


def test_system_dashboard_job_api_exposes_launch_status_and_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from presentation_layer.apps import system_dashboard as dashboard

    monkeypatch.setattr(dashboard, "LAUNCH_DIR", tmp_path / "launches")

    class FakeProcess:
        pid = 54321

    monkeypatch.setattr(dashboard.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(dashboard, "_pid_is_running", lambda pid: True)

    app = dashboard.create_app()
    client = app.server.test_client()

    state_response = client.get("/api/dashboard/state")
    assert state_response.status_code == 200
    state_payload = state_response.get_json()
    assert {"generated_at", "overview", "projects", "assets", "core_database", "alerts", "pipeline", "queue"} <= set(
        state_payload
    )
    assert isinstance(state_payload["overview"], list)
    assert "counts" in state_payload["queue"]

    queue_response = client.get("/api/dashboard/jobs/queue")
    assert queue_response.status_code == 200
    queue_payload = queue_response.get_json()
    assert queue_payload["queue_name"] == "tp_dashboard_local"
    assert "queued" in queue_payload["counts"]

    queue_event_response = client.get("/api/dashboard/jobs/queue/events?limit=1&interval=0")
    assert queue_event_response.status_code == 200
    assert queue_event_response.mimetype == "text/event-stream"
    queue_event_text = queue_event_response.data.decode("utf-8")
    assert "event: queue" in queue_event_text
    assert "tp_dashboard_local" in queue_event_text

    launch_response = client.post("/api/dashboard/jobs/system-checks")
    assert launch_response.status_code == 202
    launch_payload = launch_response.get_json()
    assert launch_payload["job"]["job_id"].startswith("system_checks_")
    assert launch_payload["job"]["status"] == "queued"
    assert launch_payload["job"]["backend"] == "local_thread_queue"
    assert launch_payload["job"]["queue_name"] == "tp_dashboard_local"
    assert launch_payload["job"]["status_updated_at"]
    assert launch_payload["record"]["backend"] == "local_thread_queue"

    job_id = launch_payload["job"]["job_id"]
    latest_response = client.get("/api/dashboard/jobs/latest")
    assert latest_response.status_code == 200
    assert latest_response.get_json()["job_id"] == job_id

    job_response = client.get(f"/api/dashboard/jobs/{job_id}")
    assert job_response.status_code == 200
    assert job_response.get_json()["job_id"] == job_id

    event_response = client.get(f"/api/dashboard/jobs/{job_id}/events?limit=1&interval=0")
    assert event_response.status_code == 200
    assert event_response.mimetype == "text/event-stream"
    event_text = event_response.data.decode("utf-8")
    assert "event: job" in event_text
    assert job_id in event_text


def test_system_dashboard_dash_launch_callback_is_guarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from presentation_layer.apps import system_dashboard as dashboard

    def fail_launch(*args: object, **kwargs: object) -> None:
        raise AssertionError("Dash callback should not launch when client API mode is enabled")

    monkeypatch.setattr(dashboard, "_launch", fail_launch)
    app = dashboard.create_app()
    client = app.server.test_client()
    response = client.post(
        "/dash/_dash-update-component",
        json={
            "output": "tp-checks-run-result.children",
            "outputs": {"id": "tp-checks-run-result", "property": "children"},
            "changedPropIds": ["tp-checks-run.n_clicks"],
            "inputs": [{"id": "tp-checks-run", "property": "n_clicks", "value": 1}],
            "state": [],
        },
    )
    assert response.status_code == 200
    assert "未重复启动" in response.get_data(as_text=True)


def test_system_jobs_runner_writes_and_reads_records(tmp_path: Path) -> None:
    from presentation_layer.apps import system_jobs

    class FakeProcess:
        pid = 65432

    record = system_jobs.launch_job(
        [sys.executable, "-c", "print('ok')"],
        "project:05_candidates:safe_check",
        tmp_path / "launches",
        tmp_path,
        popen_factory=lambda *args, **kwargs: FakeProcess(),
        creationflags=0,
    )
    assert record["job_id"].startswith("project_05_candidates_safe_check_")
    assert record["pid"] == 65432
    assert record["command"] == [sys.executable, "-c", "print('ok')"]
    assert Path(record["record_path"]).exists()
    assert (tmp_path / "launches" / "launch_latest.json").exists()

    latest = system_jobs.latest_launch_record(tmp_path / "launches")
    assert latest and latest["job_id"] == record["job_id"]
    by_job_id = system_jobs.launch_record_by_job_id(record["job_id"], tmp_path / "launches")
    assert by_job_id and by_job_id["pid"] == 65432
    assert system_jobs.launch_record_by_job_id("../bad", tmp_path / "launches") is None

    class FakeQueuedProcess:
        pid = 76543

        def wait(self) -> int:
            return 0

    queued = system_jobs.submit_job(
        [sys.executable, "-c", "print('queued')"],
        "run_all",
        tmp_path / "queued_launches",
        tmp_path,
        popen_factory=lambda *args, **kwargs: FakeQueuedProcess(),
        creationflags=0,
    )
    assert queued["status"] == "queued"
    assert queued["pid"] == ""
    assert queued["backend"] == "local_thread_queue"

    deadline = time.time() + 2
    completed = None
    while time.time() < deadline:
        completed = system_jobs.launch_record_by_job_id(queued["job_id"], tmp_path / "queued_launches")
        if completed and completed.get("status") == "completed":
            break
        time.sleep(0.02)
    assert completed and completed["status"] == "completed"
    assert completed["pid"] == 76543
    assert completed["returncode"] == 0

    claim_dir = tmp_path / "claim_guard"
    claim_dir.mkdir()
    claim_record_path = claim_dir / "claim.json"
    claim_latest_path = claim_dir / "launch_latest.json"
    claim_record = {
        "job_id": "claim",
        "status": "queued",
        "command": [sys.executable, "-c", "print('claim')"],
        "log_path": str(claim_dir / "claim.log"),
        "record_path": str(claim_record_path),
    }
    system_jobs._write_record(claim_record, claim_record_path, claim_latest_path)
    first_claim = system_jobs._claim_queued_record(claim_record_path, claim_latest_path, "worker-a")
    assert first_claim and first_claim.exists()
    assert system_jobs._claim_queued_record(claim_record_path, claim_latest_path, "worker-b") is None
    claimed_record = system_jobs.launch_record_by_job_id("claim", claim_dir)
    assert claimed_record and claimed_record["status"] == "running"
    assert claimed_record["worker_id"] == "worker-a"
    system_jobs._release_claim(first_claim)
    assert not first_claim.exists()
    assert system_jobs._claim_queued_record(claim_record_path, claim_latest_path, "worker-c") is None

    latest_dir = tmp_path / "latest_guard"
    latest_dir.mkdir()
    latest_path = latest_dir / "launch_latest.json"
    older_record = {"job_id": "older", "status": "running"}
    newer_record = {"job_id": "newer", "status": "queued"}
    system_jobs._write_record(newer_record, latest_dir / "newer.json", latest_path)
    system_jobs._write_worker_record(older_record, latest_dir / "older.json", latest_path)
    guarded_latest = system_jobs.latest_launch_record(latest_dir)
    assert guarded_latest and guarded_latest["job_id"] == "newer"

    file_worker_dir = tmp_path / "file_worker"
    file_worker_dir.mkdir()
    manual_record_path = file_worker_dir / "manual.json"
    manual_log_path = file_worker_dir / "manual.log"
    manual_record = {
        "job_id": "manual",
        "status": "queued",
        "status_updated_at": "2026-07-02T10:00:00",
        "queued_at": "2026-07-02T10:00:00",
        "started_at": "2026-07-02T10:00:00",
        "step": "manual",
        "pid": "",
        "command": [sys.executable, "-c", "print('manual')"],
        "log_path": str(manual_log_path),
        "record_path": str(manual_record_path),
        "backend": "local_file_queue",
        "queue_name": "tp_dashboard_local",
    }
    system_jobs._write_record(manual_record, manual_record_path, file_worker_dir / "launch_latest.json")

    class FakeFileWorkerProcess:
        pid = 87654

        def wait(self) -> int:
            return 0

    processed = system_jobs.run_queued_jobs_once(
        file_worker_dir,
        tmp_path,
        popen_factory=lambda *args, **kwargs: FakeFileWorkerProcess(),
        creationflags=0,
    )
    assert processed == 1
    manual_completed = system_jobs.launch_record_by_job_id("manual", file_worker_dir)
    assert manual_completed and manual_completed["status"] == "completed"
    assert manual_completed["pid"] == 87654
    queue_payload = system_jobs.queue_status(file_worker_dir)
    assert queue_payload["counts"]["completed"] == 1
    assert queue_payload["total_records"] == 1
    assert queue_payload["recent"][0]["job_id"] == "manual"


def test_system_registry_declares_control_tower_projects() -> None:
    from presentation_layer.apps.system_registry import DATA_ASSET_REGISTRY, PIPELINE_STEPS, PROJECT_REGISTRY

    project_ids = {entry.project_id for entry in PROJECT_REGISTRY}
    assert {
        "00_screen",
        "01_tp_core",
        "02_pipelines",
        "03_ml_enhanced",
        "03_regime_model",
        "03_technical_analysis",
        "04_signals",
        "05_candidates",
        "06_optimiser",
        "06_portfolios",
        "07_backtest_code",
        "08_presentation_layer",
        "08_web_app_des_companies",
        "08_company_analysis",
        "08_dashboard_analysis",
        "09_reports",
        "10_pipeline_runs",
        "11_docs",
        "12_small_cap",
    } <= project_ids
    asset_names = {entry.name for entry in DATA_ASSET_REGISTRY}
    assert {"screen_aggregate", "returns", "last_screen", "screen_aggregate_5Y"} <= asset_names
    assert "run_all" in PIPELINE_STEPS


def test_system_dashboard_monitoring_rows_are_structured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from presentation_layer.apps import system_dashboard as dashboard
    from presentation_layer.apps.system_dashboard import (
        _audit_filter_options,
        _audit_detail_payload,
        _audit_rows,
        _asset_filter_options,
        _alert_rows,
        _active_job_card,
        _active_job_payload,
        _backtest_rows,
        _build_project_command,
        _build_system_checks_command,
        _client_job_api_fallback_message,
        _check_rows,
        _command_from_callback,
        _config_rows,
        _core_database_rows,
        _data_quality_rows,
        _filter_asset_rows,
        _is_ignored_asset,
        _launch,
        _launch_rows,
        _latest_manifest,
        _latest_launch_record,
        _latest_project_launch,
        _lineage_edge_rows,
        _lineage_node_from_click,
        _lineage_node_payload,
        _overview_card_payloads,
        _project_card_button_id,
        _project_card_selection,
        _project_asset_summary_rows,
        _project_context_payload,
        _project_has_registered_command,
        _production_rows,
        _project_options,
        _read_dashboard_config,
        _write_dashboard_config,
    )
    from presentation_layer.apps.system_registry import FLOW_EDGES, PROJECT_REGISTRY

    assert dashboard.CLIENT_JOB_API_ENABLED
    assert "未重复启动" in _client_job_api_fallback_message("pipeline 启动")

    production = _production_rows()
    assert {row["产物"] for row in production} >= {
        "ml_signals",
        "technical_signals",
        "regime_risk_budget",
        "latest_candidates",
        "latest_target_weights",
    }
    assert all("质量" in row for row in production)

    backtest = _backtest_rows()
    assert backtest
    assert {"来源", "状态", "报告/路径"} <= set(backtest[0])
    assert {"收益/Alpha", "TE/IR", "报告状态"} <= set(backtest[0])

    active_project_count = sum(1 for project in PROJECT_REGISTRY if project.status == "active")
    overview_cards = _overview_card_payloads(
        production,
        backtest,
        [{"项目": project.project_id, "状态": "success"} for project in PROJECT_REGISTRY],
    )
    overview_by_label = {card[0]: card for card in overview_cards}
    assert {"项目健康度", "最新组合", "报告状态"} <= set(overview_by_label)
    assert overview_by_label["项目健康度"][1] == f"{active_project_count}/{active_project_count}"
    assert overview_by_label["最新组合"][1]
    assert overview_by_label["报告状态"][1]

    partial_checks_path = tmp_path / "partial_system_checks_latest.json"
    partial_checks_path.write_text(
        """
{
  "generated_at": "2026-07-02T09:00:00",
  "status": "success",
  "project_count": 1,
  "results": [
    {
      "project_id": "00_screen",
      "project": "00_screen",
      "role": "核心数据库",
      "data_kind": "database",
      "required": true,
      "command": ["python", "-m", "02_pipelines.refresh_data", "--inspect-only"],
      "status": "success",
      "returncode": 0,
      "duration_seconds": 1.2,
      "outputs": []
    }
  ]
}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard, "CHECK_LATEST", partial_checks_path)
    check_rows = _check_rows()
    assert len(check_rows) >= len(PROJECT_REGISTRY)
    assert {"项目", "状态", "检查批次", "必需", "命令", "输出概况"} <= set(check_rows[0])
    assert any(row["项目"] == "00_screen" and row["状态"] == "success" for row in check_rows)
    assert any(row["项目"] == "01_tp_core" and row["状态"] == "未检查" for row in check_rows)
    partial_health = _overview_card_payloads(production, backtest, check_rows)
    partial_health_by_label = {card[0]: card for card in partial_health}
    assert partial_health_by_label["项目健康度"][1] == f"1/{active_project_count}"
    assert "未检查" in partial_health_by_label["项目健康度"][2]

    core_database = _core_database_rows()
    assert {row["数据资产"] for row in core_database} == {
        "screen_aggregate",
        "returns",
        "last_screen",
        "screen_aggregate_5Y",
    }
    assert {"更新状态", "最新日期", "行", "列", "Schema", "Schema 证据", "路径"} <= set(core_database[0])
    assert any(row["数据资产"] == "returns" and row["Schema"] == "BASELINE" for row in core_database)

    audit = _audit_rows(limit=5)
    assert audit
    assert {"时间", "step", "状态", "manifest"} <= set(audit[0])
    audit_detail = _audit_detail_payload(audit[0])
    assert audit_detail["manifest"].endswith(".json")
    assert {"inputs", "outputs", "validations", "idempotency"} <= set(audit_detail)
    audit_step_options, audit_status_options = _audit_filter_options()
    assert any(option["value"] == "run_all" for option in audit_step_options)
    assert any(option["value"] == "success" for option in audit_status_options)
    assert _audit_rows(limit=5, step="__missing__") == []
    assert _audit_rows(limit=5, date_from="2999-01-01") == []
    success_audit = _audit_rows(limit=5, status="success")
    assert all(row["状态"] == "success" for row in success_audit)

    quality = _data_quality_rows()
    assert any(row["检查项"] == "returns anomaly audit" for row in quality)
    assert {"检查项", "状态", "范围/资产", "指标", "异常/缺口", "证据"} <= set(quality[0])
    alerts = _alert_rows(
        core_database,
        [{"项目": "00_screen", "状态": "success"}],
        [{"步骤": "refresh_data", "状态": "OK"}],
        [{"检查项": "returns anomaly audit", "状态": "passed"}],
        [{"产物": "latest_target_weights", "状态": "OK"}],
    )
    assert any(row["模块"] == "核心数据库" and row["状态"] == "CHECK" for row in alerts)
    clear_alert = _alert_rows(
        [{"数据资产": "returns", "更新状态": "OK", "质量信号": "", "Schema": "BASELINE", "Schema 证据": ""}],
        [{"项目": "00_screen", "状态": "success"}],
        [{"步骤": "refresh_data", "状态": "OK"}],
        [{"检查项": "returns anomaly audit", "状态": "passed"}],
        [{"产物": "latest_target_weights", "状态": "OK"}],
    )
    assert clear_alert == [
        {
            "级别": "INFO",
            "模块": "系统总览",
            "对象": "all clear",
            "状态": "OK",
            "证据": "核心库、项目检查、pipeline、数据质量和生产产物未发现阻断项",
        }
    ]

    asset_project_options, asset_source_options, asset_status_options = _asset_filter_options()
    assert any(option["value"] == "00_screen" for option in asset_project_options)
    assert any(option["value"] == "registry" for option in asset_source_options)
    assert any(option["value"] == "缺失" for option in asset_status_options)
    asset_rows = dashboard._asset_rows()
    assert any(row["项目"] == "00_screen" and row["必需"] == "是" for row in asset_rows)
    assert _is_ignored_asset(Path("00_screen/backups/screen.parquet"))
    assert _is_ignored_asset(Path("03_ml_enhanced/_quarantine_20260629/model.json"))
    assert _is_ignored_asset(Path("00_screen/备份/returns.parquet"))
    assert not _is_ignored_asset(Path("04_signals/ml_signals.parquet"))
    project_asset_summary = _project_asset_summary_rows(
        [
            {"项目": "00_screen", "来源": "registry", "状态": "存在", "必需": "是", "数据/产物": "screen_aggregate", "_bytes": 1024, "_mtime": 1000},
            {"项目": "00_screen", "来源": "registry", "状态": "缺失", "必需": "是", "数据/产物": "returns", "_bytes": 0, "_mtime": 0},
            {"项目": "00_screen", "来源": "discovered", "状态": "存在", "必需": "否", "数据/产物": "qa.json", "_bytes": 512, "_mtime": 2000},
            {"项目": "04_signals", "来源": "registry", "状态": "存在", "必需": "是", "数据/产物": "ml_signals", "_bytes": 2048, "_mtime": 3000},
        ]
    )
    project_summary_by_id = {row["项目"]: row for row in project_asset_summary}
    assert project_summary_by_id["00_screen"]["资产状态"] == "CHECK"
    assert project_summary_by_id["00_screen"]["注册资产"] == "2"
    assert project_summary_by_id["00_screen"]["自动发现"] == "1"
    assert project_summary_by_id["00_screen"]["必需缺失"] == "1"
    assert project_summary_by_id["00_screen"]["总大小"] == "1.5 KB"
    assert "screen_aggregate" in project_summary_by_id["00_screen"]["关键资产"]
    assert project_summary_by_id["04_signals"]["资产状态"] == "OK"
    sample_assets = [
        {"项目": "00_screen", "来源": "registry", "状态": "存在"},
        {"项目": "04_signals", "来源": "discovered", "状态": "存在"},
        {"项目": "12_small_cap", "来源": "registry", "状态": "缺失"},
    ]
    assert _filter_asset_rows(sample_assets, project_id="00_screen") == [sample_assets[0]]
    assert _filter_asset_rows(sample_assets, source="discovered") == [sample_assets[1]]
    assert _filter_asset_rows(sample_assets, status="缺失") == [sample_assets[2]]

    config = _config_rows()
    assert any(row["配置项"] == "dashboard_default_flags" for row in config)
    monkeypatch.setattr(dashboard, "DASHBOARD_CONFIG_PATH", tmp_path / "dashboard_config.json")
    saved = _write_dashboard_config(
        {
            "step": "run_backtest",
            "input_month": "202606",
            "as_of": "2026-06-30",
            "bench": "MSCI WORLD",
            "universe": "Global developed",
            "project_id": "05_candidates",
            "project_mode": "safe_check",
        }
    )
    assert saved["saved_at"]
    loaded = _read_dashboard_config()
    assert loaded["step"] == "run_backtest"
    assert loaded["input_month"] == "202606"
    assert loaded["universe"] == "Global developed"
    assert loaded["project_id"] == "05_candidates"
    saved_rows = _config_rows()
    assert any(row["配置项"] == "saved_input_month" and row["当前值"] == "202606" for row in saved_rows)
    assert any(row["配置项"] == "saved_universe" and row["当前值"] == "Global developed" for row in saved_rows)
    assert any(row["配置项"] == "sector_neutral" for row in saved_rows)
    assert any(row["配置项"] == "dashboard_config_path" for row in saved_rows)

    monkeypatch.setattr(dashboard, "LAUNCH_DIR", tmp_path / "launches")

    class FakeProcess:
        pid = 43210

    monkeypatch.setattr(dashboard.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    launch_record = _launch([sys.executable, "-c", "print('ok')"], "project:05_candidates:safe_check")
    Path(launch_record["log_path"]).write_text("starting\ncompleted marker\n", encoding="utf-8")
    assert launch_record["job_id"].startswith("project_05_candidates_safe_check_")
    assert launch_record["status"] == "running"
    assert Path(launch_record["record_path"]).exists()
    assert ":" not in Path(launch_record["record_path"]).name
    assert (tmp_path / "launches" / "launch_latest.json").exists()
    latest_record = _latest_launch_record()
    assert latest_record and latest_record["pid"] == 43210
    assert latest_record["job_id"] == launch_record["job_id"]
    monkeypatch.setattr(dashboard, "_pid_is_running", lambda pid: True)
    active_job = _active_job_payload()
    assert active_job["job_id"] == launch_record["job_id"]
    assert active_job["status"] == "running"
    assert active_job["phase"] == "running"
    active_job_card = repr(_active_job_card())
    assert "RUNNING" in active_job_card
    assert "tp-job-progress" in active_job_card
    assert "tp-job-log" in active_job_card
    assert "tp-job-title" in active_job_card
    assert "data-job-id" in active_job_card
    assert "completed marker" in active_job_card

    launches = _launch_rows()
    assert launches
    assert {"时间", "job_id", "step", "PID", "命令", "日志", "日志摘要", "manifest状态", "manifest/证据", "状态"} <= set(launches[0])
    assert launches[0]["job_id"] == launch_record["job_id"]
    assert "completed marker" in launches[0]["日志摘要"]
    assert len([row for row in launches if row["step"] == "project:05_candidates:safe_check"]) == 1
    latest_project_launch = _latest_project_launch("05_candidates")
    assert latest_project_launch and latest_project_launch["pid"] == 43210

    run_all_record = _launch([sys.executable, "-c", "print('ok')"], "run_all")
    Path(run_all_record["log_path"]).write_text("run all marker\n", encoding="utf-8")
    run_all_rows = _launch_rows()
    run_all_row = next(row for row in run_all_rows if row["step"] == "run_all")
    assert run_all_row["manifest/证据"].endswith("run_all_latest.json")
    expected_status = "未更新" if _latest_manifest("run_all") else "缺失"
    assert run_all_row["manifest状态"] in {expected_status, "OK", "FAIL", "RUNNING", "等待"}

    project_options = _project_options()
    assert any(option["value"] == "03_ml_enhanced" for option in project_options)
    projects = {project.project_id: project for project in PROJECT_REGISTRY}
    assert _project_card_button_id("05_candidates", "registered_command") == {
        "type": "tp-project-card-select",
        "project": "05_candidates",
        "mode": "registered_command",
    }
    assert _project_card_selection(_project_card_button_id("05_candidates", "safe_check")) == (
        "05_candidates",
        "safe_check",
    )
    assert _project_has_registered_command(projects["05_candidates"])
    assert not _project_has_registered_command(projects["12_small_cap"])
    project_context = _project_context_payload("05_candidates")
    assert project_context["title"].startswith("05_candidates")
    assert "latest_candidates" in project_context["assets"]
    assert {"role", "inputs", "outputs", "latest_check", "manifest"} <= set(project_context)
    with pytest.raises(ValueError):
        _project_card_selection({"project": "missing", "mode": "safe_check"})

    safe_command = _build_project_command("03_ml_enhanced", "safe_check")
    assert safe_command == [
        sys.executable,
        "-m",
        "presentation_layer.cli",
        "system-checks",
        "--project",
        "03_ml_enhanced",
    ]
    assert _build_system_checks_command() == [sys.executable, "-m", "presentation_layer.cli", "system-checks"]

    registered_command = _build_project_command("05_candidates", "registered_command")
    assert registered_command[:3] == [sys.executable, "-m", "02_pipelines.build_candidates"]

    with pytest.raises(ValueError):
        _build_project_command("12_small_cap", "registered_command")

    sector_command = _command_from_callback(
        "run_backtest",
        None,
        None,
        "both",
        None,
        None,
        None,
        0.05,
        "score_weight",
        "",
        "default",
        "STOXX EUROPE 600",
        "2020-01-01",
        0.8,
        ["sector_neutral", "inspect_backtest"],
    )
    assert sector_command[:3] == [sys.executable, "-m", "02_pipelines.run_backtest"]
    assert "--sector-neutral" in sector_command

    lineage = _lineage_node_payload("候选池")
    assert lineage["upstream"] == "统一信号"
    assert lineage["downstream"] == "组合权重"
    assert any(project["project_id"] == "05_candidates" for project in lineage["projects"])
    assert {"command", "inputs", "outputs", "manifest_path"} <= set(lineage["projects"][0])

    lineage_edges = _lineage_edge_rows()
    assert len(lineage_edges) == len(FLOW_EDGES)
    assert {"上游", "下游", "负责项目", "最近状态", "manifest", "关键输出"} <= set(lineage_edges[0])
    assert any(row["上游"] == "统一信号" and row["下游"] == "候选池" for row in lineage_edges)

    assert _lineage_node_from_click({"points": [{"label": "回测"}]}) == "回测"
    assert _lineage_node_from_click(None) == "核心数据库"

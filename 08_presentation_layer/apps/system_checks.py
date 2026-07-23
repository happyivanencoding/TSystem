"""Safe smoke checks for TP subprojects used by the system dashboard."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from presentation_layer.apps.system_registry import project_by_id
from tp_core.data_sources import TP_ROOT


_pipeline_common = import_module("02_pipelines.common")
path_profile = _pipeline_common.path_profile

CHECK_ROOT = TP_ROOT / ".tmp_dashboard_work" / "system_checks"
CHECK_LATEST = CHECK_ROOT / "system_checks_latest.json"


@dataclass(frozen=True)
class ProjectCheck:
    project_id: str
    project: str
    role: str
    command: list[str]
    expected_outputs: list[Path] = field(default_factory=list)
    timeout_seconds: int = 120
    data_kind: str = "code"
    required: bool = True


def _python() -> str:
    return sys.executable


def _tmp(name: str) -> Path:
    return CHECK_ROOT / "outputs" / name


def project_checks() -> list[ProjectCheck]:
    py = _python()
    entry = project_by_id
    return [
        ProjectCheck(
            entry("00_screen").project_id,
            entry("00_screen").project_id,
            entry("00_screen").role,
            [py, "-m", "02_pipelines.refresh_data", "--inspect-only", "--run-type", "inspect"],
            data_kind="database",
        ),
        ProjectCheck(
            entry("01_tp_core").project_id,
            entry("01_tp_core").project_id,
            entry("01_tp_core").role,
            [
                py,
                "-c",
                (
                    "from tp_core.data_sources import validate_data_sources; "
                    "from tp_core.io import read_last_screen; "
                    "print(validate_data_sources()); "
                    "print(read_last_screen(columns=['Date','ISIN']).shape)"
                ),
            ],
            data_kind="library",
        ),
        ProjectCheck(
            entry("02_pipelines").project_id,
            entry("02_pipelines").project_id,
            entry("02_pipelines").role,
            [
                py,
                "-m",
                "02_pipelines.generate_report",
                "--output",
                str(_tmp("pipeline_report_smoke.md")),
                "--step",
                "refresh_data",
                "--run-type",
                "smoke",
            ],
            [_tmp("pipeline_report_smoke.md")],
            data_kind="pipeline",
        ),
        ProjectCheck(
            entry("03_ml_enhanced").project_id,
            entry("03_ml_enhanced").project_id,
            entry("03_ml_enhanced").role,
            [
                py,
                "-m",
                "03_ml_enhanced.cli",
                "export-signals",
                "--output",
                str(_tmp("ml_signals_smoke.parquet")),
            ],
            [_tmp("ml_signals_smoke.parquet")],
            timeout_seconds=180,
            data_kind="signal parquet",
        ),
        ProjectCheck(
            entry("03_regime_model").project_id,
            entry("03_regime_model").project_id,
            entry("03_regime_model").role,
            [
                py,
                str(TP_ROOT / "03_regime_model" / "export_risk_budget.py"),
                "--output",
                str(_tmp("regime_risk_budget_smoke.parquet")),
            ],
            [_tmp("regime_risk_budget_smoke.parquet")],
            data_kind="signal parquet",
        ),
        ProjectCheck(
            entry("03_technical_analysis").project_id,
            entry("03_technical_analysis").project_id,
            entry("03_technical_analysis").role,
            [
                py,
                str(TP_ROOT / "03_technical_analysis" / "export_technical_signals.py"),
                "--output",
                str(_tmp("technical_signals_smoke.parquet")),
            ],
            [_tmp("technical_signals_smoke.parquet")],
            timeout_seconds=180,
            data_kind="signal parquet",
        ),
        ProjectCheck(
            entry("04_signals").project_id,
            entry("04_signals").project_id,
            entry("04_signals").role,
            [py, "-m", "01_tp_core.signals", str(TP_ROOT / "04_signals" / "ml_signals.parquet")],
            [TP_ROOT / "04_signals" / "ml_signals.parquet"],
            data_kind="signal parquet",
        ),
        ProjectCheck(
            entry("05_candidates").project_id,
            entry("05_candidates").project_id,
            entry("05_candidates").role,
            [
                py,
                "-m",
                "02_pipelines.build_candidates",
                "--output",
                str(_tmp("latest_candidates_smoke.parquet")),
                "--top-pct",
                "0.10",
                "--run-type",
                "smoke",
            ],
            [_tmp("latest_candidates_smoke.parquet")],
            data_kind="candidate parquet",
        ),
        ProjectCheck(
            entry("06_optimiser").project_id,
            entry("06_optimiser").project_id,
            entry("06_optimiser").role,
            [py, "-m", "pytest", "06_optimiser/test_optimizer.py", "-q"],
            timeout_seconds=180,
            data_kind="optimizer code",
        ),
        ProjectCheck(
            entry("06_portfolios").project_id,
            entry("06_portfolios").project_id,
            entry("06_portfolios").role,
            [
                py,
                "-m",
                "02_pipelines.optimize_portfolio",
                "--candidates",
                str(TP_ROOT / "05_candidates" / "latest_candidates.parquet"),
                "--output",
                str(_tmp("latest_target_weights_smoke.parquet")),
                "--method",
                "score_weight",
                "--run-type",
                "smoke",
            ],
            [_tmp("latest_target_weights_smoke.parquet")],
            data_kind="portfolio parquet",
        ),
        ProjectCheck(
            entry("07_backtest_code").project_id,
            entry("07_backtest_code").project_id,
            entry("07_backtest_code").role,
            [py, "-m", "02_pipelines.run_backtest", "--inspect-only", "--run-type", "inspect"],
            timeout_seconds=180,
            data_kind="backtest inspect json",
        ),
        ProjectCheck(
            entry("08_presentation_layer").project_id,
            entry("08_presentation_layer").project_id,
            entry("08_presentation_layer").role,
            [py, "-m", "pytest", "08_presentation_layer/tests/test_presentation_layer_entrypoints.py", "-q"],
            timeout_seconds=180,
            data_kind="dashboard code",
        ),
        ProjectCheck(
            entry("08_web_app_des_companies").project_id,
            entry("08_web_app_des_companies").project_id,
            entry("08_web_app_des_companies").role,
            [
                py,
                "-c",
                (
                    "from presentation_layer.apps.des_companies import create_app; "
                    "app=create_app(); print(app.title)"
                ),
            ],
            data_kind="dash app",
        ),
        ProjectCheck(
            entry("08_company_analysis").project_id,
            entry("08_company_analysis").project_id,
            entry("08_company_analysis").role,
            [
                py,
                "-c",
                (
                    "from presentation_layer.apps.company_analysis_api import create_app; "
                    "app=create_app(); print(len(app.routes))"
                ),
            ],
            data_kind="fastapi app",
        ),
        ProjectCheck(
            entry("08_dashboard_analysis").project_id,
            entry("08_dashboard_analysis").project_id,
            entry("08_dashboard_analysis").role,
            [py, "-m", "presentation_layer.cli", "dashboard-smoke"],
            data_kind="report wrapper",
        ),
        ProjectCheck(
            entry("09_reports").project_id,
            entry("09_reports").project_id,
            entry("09_reports").role,
            [
                py,
                "-c",
                (
                    "from pathlib import Path; "
                    "p=Path(r'C:/GoogleDrive/TP/09_reports/latest_pipeline_report.md'); "
                    "print(p.exists(), p.stat().st_size if p.exists() else 0)"
                ),
            ],
            [TP_ROOT / "09_reports" / "latest_pipeline_report.md"],
            data_kind="markdown report",
        ),
        ProjectCheck(
            entry("10_pipeline_runs").project_id,
            entry("10_pipeline_runs").project_id,
            entry("10_pipeline_runs").role,
            [
                py,
                "-c",
                (
                    "import json; from pathlib import Path; "
                    "p=Path(r'C:/GoogleDrive/TP/10_pipeline_runs/manifests/run_all/run_all_latest.json'); "
                    "d=json.loads(p.read_text(encoding='utf-8')); print(d['status'], d['finished_at'])"
                ),
            ],
            [TP_ROOT / "10_pipeline_runs" / "manifests" / "run_all" / "run_all_latest.json"],
            data_kind="manifest json",
        ),
        ProjectCheck(
            entry("11_docs").project_id,
            entry("11_docs").project_id,
            entry("11_docs").role,
            [
                py,
                "-c",
                (
                    "from pathlib import Path; "
                    "docs=Path(r'C:/GoogleDrive/TP/11_docs'); "
                    "print((docs/'README.md').exists(), len(list(docs.glob('*.md'))))"
                ),
            ],
            [TP_ROOT / "11_docs" / "README.md"],
            data_kind="docs",
        ),
        ProjectCheck(
            entry("12_small_cap").project_id,
            entry("12_small_cap").project_id,
            entry("12_small_cap").role,
            [
                py,
                "-c",
                (
                    "from pathlib import Path; "
                    "p=Path(r'C:/GoogleDrive/TP/99_archive/project_cleanup_20260707/12_small_cap/README.md'); "
                    "print(p.exists(), p.stat().st_size if p.exists() else 0)"
                ),
            ],
            [TP_ROOT / "99_archive" / "project_cleanup_20260707" / "12_small_cap" / "README.md"],
            data_kind="research docs",
            required=False,
        ),
        ProjectCheck(
            entry("13_sector_score_model").project_id,
            entry("13_sector_score_model").project_id,
            entry("13_sector_score_model").role,
            [
                py,
                "-c",
                (
                    "import json; from pathlib import Path; "
                    "base=Path(r'C:/GoogleDrive/TP/13_sector_score_model'); "
                    "paths=["
                    "base/'outputs_fs_sector_default'/'sector_scores_panel.parquet', "
                    "base/'outputs_fs_sector_default'/'backtest_summary.json', "
                    "base/'outputs_eu'/'sector_scores_panel.parquet', "
                    "base/'outputs_eu'/'backtest_summary.json']; "
                    "missing=[str(p) for p in paths if not p.exists()]; "
                    "assert not missing, missing; "
                    "us=json.loads((base/'outputs_fs_sector_default'/'backtest_summary.json').read_text(encoding='utf-8')); "
                    "eu=json.loads((base/'outputs_eu'/'backtest_summary.json').read_text(encoding='utf-8')); "
                    "print('US', us['full_period']['end_date'], 'EU', eu['full_period']['end_date'])"
                ),
            ],
            [
                TP_ROOT / "13_sector_score_model" / "outputs_fs_sector_default" / "sector_scores_panel.parquet",
                TP_ROOT / "13_sector_score_model" / "outputs_fs_sector_default" / "backtest_summary.json",
                TP_ROOT / "13_sector_score_model" / "outputs_eu" / "sector_scores_panel.parquet",
                TP_ROOT / "13_sector_score_model" / "outputs_eu" / "backtest_summary.json",
            ],
            data_kind="sector model outputs",
        ),
        ProjectCheck(
            entry("14_country_model").project_id,
            entry("14_country_model").project_id,
            entry("14_country_model").role,
            [
                py,
                "-c",
                (
                    "import importlib.util; from pathlib import Path; import pandas as pd; "
                    "module_path=Path(r'C:/GoogleDrive/TP/14_country_model/src/country_model.py'); "
                    "spec=importlib.util.spec_from_file_location('country_model_smoke', module_path); "
                    "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
                    "database=pd.read_parquet(m.COUNTRY_DATABASE_PATH); "
                    "panel=m.build_country_model_panel(database); "
                    "signal=m.make_country_signal_frame(panel); "
                    "out=Path(r'C:/GoogleDrive/TP/.tmp_dashboard_work/system_checks/outputs/country_model_signals_smoke.parquet'); "
                    "m.write_signal_frame(signal, out); "
                    "print(len(panel), len(signal), out)"
                ),
            ],
            [_tmp("country_model_signals_smoke.parquet")],
            data_kind="country model signal parquet",
        ),
    ]


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _profile_output(path: Path) -> dict[str, Any]:
    return path_profile(path, parquet=path.suffix.lower() == ".parquet")


def run_project_check(check: ProjectCheck) -> dict[str, Any]:
    started = datetime.now().isoformat(timespec="seconds")
    timer = time.perf_counter()
    CHECK_ROOT.mkdir(parents=True, exist_ok=True)
    (_tmp("placeholder").parent).mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "project_id": check.project_id,
        "project": check.project,
        "role": check.role,
        "data_kind": check.data_kind,
        "required": check.required,
        "command": check.command,
        "started_at": started,
    }
    try:
        completed = subprocess.run(
            check.command,
            cwd=TP_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=check.timeout_seconds,
        )
        status = "success" if completed.returncode == 0 else "failed"
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        result.update(
            {
                "status": status,
                "returncode": completed.returncode,
                "duration_seconds": round(time.perf_counter() - timer, 3),
                "stdout_tail": stdout[-4000:],
                "stderr_tail": stderr[-4000:],
            }
        )
    except subprocess.TimeoutExpired as exc:
        result.update(
            {
                "status": "timeout",
                "returncode": None,
                "duration_seconds": round(time.perf_counter() - timer, 3),
                "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
                "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
                "error": f"timeout after {check.timeout_seconds}s",
            }
        )
    except Exception as exc:
        result.update(
            {
                "status": "failed",
                "returncode": None,
                "duration_seconds": round(time.perf_counter() - timer, 3),
                "stdout_tail": "",
                "stderr_tail": "",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )

    result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    result["outputs"] = [_profile_output(path) for path in check.expected_outputs]
    return result


def run_checks(selected_projects: set[str] | None = None) -> dict[str, Any]:
    checks = project_checks()
    if selected_projects:
        checks = [
            check
            for check in checks
            if check.project in selected_projects or check.project_id in selected_projects
        ]
    results = [run_project_check(check) for check in checks]
    required_results = [item for item in results if item.get("required")]
    failed_required = [
        item["project"]
        for item in required_results
        if item.get("status") not in {"success"}
    ]
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(TP_ROOT),
        "status": "success" if not failed_required else "failed",
        "failed_required": failed_required,
        "project_count": len(results),
        "results": results,
    }
    CHECK_ROOT.mkdir(parents=True, exist_ok=True)
    stamped = CHECK_ROOT / f"system_checks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
    stamped.write_text(text, encoding="utf-8")
    CHECK_LATEST.write_text(text, encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 TP 子项目安全 smoke/inspect 检查")
    parser.add_argument("--project", action="append", help="只检查指定 project 或 project_id；可重复")
    args = parser.parse_args(argv)
    payload = run_checks(set(args.project or []))
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0 if payload["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

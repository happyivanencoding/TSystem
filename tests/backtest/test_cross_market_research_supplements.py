from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from tp_reporting import factor_research_app as report_builder
from tp_research.paths import REPORT_ROOT as REPORT_DIR, TP_ROOT
from tp_research.workflows import analyze_cross_market_leave_one_period_out as lopo
from tp_research.workflows import run_cross_market_lag6_anchor_synergy as synergy
from tp_research.workflows import run_cross_market_lag6_relative_research as lag6


def _require_market_runs() -> None:
    missing = [
        report_builder.RUN_ROOT / config["oop"]
        for config in report_builder.MARKETS.values()
        if not (report_builder.RUN_ROOT / config["oop"]).is_dir()
    ]
    if missing:
        pytest.skip(f"cross-market generated runs are unavailable: {missing[0]}")


def _factor_explorer_html() -> str:
    path = REPORT_DIR / "factor-explorer.html"
    if not path.is_file():
        pytest.skip(f"generated factor explorer report is unavailable: {path}")
    return path.read_text(encoding="utf-8")


def test_lag6_registry_has_two_independent_variants_per_level_field() -> None:
    missing = [
        lag6.frozen_definition_path(profile)
        for profile in lag6.PROFILES.values()
        if not lag6.frozen_definition_path(profile).is_file()
    ]
    if missing:
        pytest.skip(f"frozen lag6 definitions are unavailable: {missing[0]}")

    for profile in lag6.PROFILES.values():
        level_specs = lag6.load_level_specs(profile)
        definitions = pd.DataFrame(
            [
                {
                    "raw_column": item.raw_column,
                    "transform": transform,
                    "metric": lag6.relative_metric(profile, item, transform),
                }
                for item in level_specs
                for transform in lag6.TRANSFORMS
            ]
        )
        registry = lag6.build_registry(profile, definitions, level_specs)
        assert len(registry) == 2 * len(level_specs)
        assert set(registry["lag_observations"]) == {6}
        assert registry["metric"].is_unique


def test_nav_drift_without_real_formations_is_not_period_validation() -> None:
    dates = pd.bdate_range("2020-01-02", periods=260)
    top = pd.Series(np.linspace(100, 120, len(dates)), index=dates)
    worst = pd.Series(np.linspace(100, 105, len(dates)), index=dates)
    benchmark = pd.Series(np.linspace(100, 110, len(dates)), index=dates)
    regime = {
        "regime_id": "test",
        "label_zh": "测试",
        "start": str(dates.min().date()),
        "end": str(dates.max().date()),
        "market_snapshot_count": 4,
        "market_signal_validation_available": True,
    }

    drift_only = lopo.period_stats(
        top,
        worst,
        benchmark,
        pd.DatetimeIndex([]),
        regime,
    )
    assert drift_only["nav_available"] is True
    assert drift_only["signal_validation_available"] is False

    formed = lopo.period_stats(
        top,
        worst,
        benchmark,
        pd.DatetimeIndex([dates[5], dates[70], dates[140], dates[210]]),
        regime,
    )
    assert formed["signal_validation_available"] is True


def test_anchor_subset_matrix_formula_matches_completed_runs() -> None:
    for study in synergy.STUDIES.values():
        manifest_path = lag6.AD_HOC_ROOT / study.output_name / "manifest.json"
        if not manifest_path.exists():
            pytest.skip("completed local supplement run is unavailable")
        manifest = synergy.json.loads(manifest_path.read_text(encoding="utf-8"))
        passed_lag6 = int(manifest["passed_lag6_count"])
        passed_anchors = int(manifest["passed_anchor_count"])
        expected = (
            passed_lag6 * (2**passed_anchors - 1)
            + (2**passed_anchors - passed_anchors - 1)
        )
        assert manifest["combination_candidate_count"] == expected
        assert manifest["status"] == "complete"
        assert manifest["failed_count"] == 0


def test_four_market_app_is_embedded_and_has_static_fallback() -> None:
    _require_market_runs()

    payload = {
        key: report_builder.market_payload(key, config)
        for key, config in report_builder.MARKETS.items()
    }
    html = report_builder.build_html(payload)

    assert set(payload) == {"stoxx600", "sp500", "nasdaq", "eu-small"}
    assert "STOXX Europe 600 跨时期单变量证据" in html
    assert "const DATA=" in html
    assert "fetch(" not in html
    assert "https://cdn" not in html
    assert "EPS Revision Ratio" in html
    assert "@media (max-width: 640px)" in html
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in html
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)" in html
    assert ".audit-grid > div { min-width: 0; }" in html
    assert "width: 100%; overflow: auto" in html


def test_authoritative_explorer_preserves_return_ratio_and_economic_views() -> None:
    html = _factor_explorer_html()
    marker = '<script id="report-data" type="application/json">'
    payload_text = html.split(marker, 1)[1].split("</script>", 1)[0]
    payload = json.loads(payload_text)
    stoxx = next(report for report in payload["reports"] if report["id"] == "stoxx600")
    default = next(candidate for candidate in stoxx["candidates"] if candidate["id"] == stoxx["defaultCandidate"])

    assert 'var state={market:"stoxx600"' in html
    assert "Top / Worst ratio" in html
    assert "Top / Benchmark ratio" in html
    assert 'data-mode="economics"' in html
    assert "经济含义" in html
    assert {"supplemental-lag6", "supplemental-matrix", "supplemental-oop", "supplemental-dsr"} <= {
        tab["id"] for tab in stoxx["evidenceTabs"]
    }
    assert stoxx["defaultCandidate"] == "stoxx600_sx_full_q3_e1"
    assert default["label"].startswith("EPS Revision Ratio + PMOM 12M1M")
    assert len(default["series"]) > 100
    assert default["economics"]
    assert any(candidate["label"] == "Oper Margin directional_delta lag6" for candidate in stoxx["candidates"])

    dashboard_source = (
        TP_ROOT
        / "08_presentation_layer"
        / "frontend"
        / "system_dashboard"
        / "src"
        / "pages"
        / "DashboardPage.jsx"
    ).read_text(encoding="utf-8")
    assert 'src="/reports/factor-explorer.html"' in dashboard_source
    assert 'src="/reports/factor-research-app.html"' not in dashboard_source


def test_authoritative_explorer_has_auditable_rotation_map_for_every_market() -> None:
    html = _factor_explorer_html()
    marker = '<script id="report-data" type="application/json">'
    payload_text = html.split(marker, 1)[1].split("</script>", 1)[0]
    payload = json.loads(payload_text)

    assert 'id="rotation-chart"' in html
    assert 'id="rotation-date"' in html
    assert 'data-rotation-trail="6"' in html
    assert 'data-rotation-trail="12"' in html
    assert "renderFactorRotation" in html
    assert "RRG-inspired descriptive map" in html
    for report in payload["reports"]:
        candidate_ids = {candidate["id"] for candidate in report["candidates"]}
        rotation_ids = report["rotationCandidateIds"]
        method = report["rotationMethod"]
        assert report["method"].count("lag1/3/6/12") == 1
        assert 4 <= len(rotation_ids) <= 8
        assert len(rotation_ids) == len(set(rotation_ids))
        assert set(rotation_ids) <= candidate_ids
        assert method["id"] == "tp_factor_rotation_v1"
        assert method["strengthLookbackObservations"] == 12
        assert method["momentumLagObservations"] == 3
        assert method["xDefinition"].startswith("100 + 10 * ln")
        assert method["datePolicy"].startswith("Only performance observations dated on or before")

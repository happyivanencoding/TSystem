"""TP system monitoring and pipeline control dashboard."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Dash, Input, Output, State, ctx, dash_table, dcc, html
from dash.exceptions import PreventUpdate

from presentation_layer.apps import system_jobs
from presentation_layer.company_browser.settings import (
    DES_PARQUET as COMPANY_DES_PATH,
    NEWS_PARQUET as COMPANY_NEWS_PATH,
)
from presentation_layer.apps.system_api import (
    DashboardStaticAssets,
    register_dashboard_routes,
)
from presentation_layer.apps.system_backtests import (
    BacktestDashboardContext,
    backtest_rows as build_backtest_rows,
    outputs_summary as _outputs_summary,
    validation_summary as _validation_summary,
)
from presentation_layer.apps.system_checks import CHECK_LATEST, project_checks
from presentation_layer.apps.system_domain import DashboardDomainService
from presentation_layer.apps.system_repository import SystemDashboardRepository
from presentation_layer.apps.system_view_models import (
    JobViewModelContext,
    format_bytes as _format_bytes,
    format_date as _fmt_date,
    format_int as _fmt_int,
    format_number as _fmt_number,
    format_pct as _fmt_pct,
    job_payload_from_record,
    relative_path,
    status_class as _status_class,
    status_label as _status_label,
)
from presentation_layer.apps.system_registry import (
    DATA_ASSET_REGISTRY,
    FLOW_EDGES,
    FLOW_NODES,
    PIPELINE_STEPS,
    PROJECT_REGISTRY,
    DataAssetEntry,
)
from tp_core.data_sources import (
    PRODUCTION_INCOMING_DIR,
    PRODUCTION_INPUTS_DIR,
    TP_ROOT,
)
from tp_core.workspace import (
    BACKTEST_OUTPUT_RUNS_DIR,
    CANDIDATES_DIR,
    DASHBOARD_WORK_DIR,
    HISTORICAL_RESEARCH_RUNS_DIR,
    PIPELINE_MANIFESTS_DIR,
    PORTFOLIOS_DIR,
    REPORTS_DIR,
    SIGNALS_DIR,
)
from tp_pipelines.common import path_profile


PORT = 8060
LAUNCH_DIR = DASHBOARD_WORK_DIR / "launches"
DASHBOARD_CONFIG_PATH = DASHBOARD_WORK_DIR / "dashboard_config.json"
CLIENT_JOB_API_ENABLED = os.environ.get("TP_DASHBOARD_CLIENT_JOB_API", "1") != "0"
CLIENT_DIST_DIR = TP_ROOT / "08_presentation_layer" / "frontend" / "system_dashboard" / "dist"
CLIENT_ASSETS_DIR = CLIENT_DIST_DIR / "assets"
FACTOR_EXPLORER_PATH = REPORTS_DIR / "factor-explorer.html"
FACTOR_RESEARCH_APP_PATH = REPORTS_DIR / "factor-research-app.html"
REGIME_SIGNAL_PATH = SIGNALS_DIR / "regime_risk_budget.parquet"
COUNTRY_SIGNAL_PATH = SIGNALS_DIR / "country_model_signals.parquet"
SMALL_CAP_SIGNAL_PATH = SIGNALS_DIR / "small_cap_model_signals.parquet"
SMALL_CAP_MODEL_DIR = TP_ROOT / "15_small_cap_model"
SMALL_CAP_PANEL_PATH = SMALL_CAP_MODEL_DIR / "outputs" / "eu_small_model_scores_latest.parquet"
SMALL_CAP_SUMMARY_PATH = SMALL_CAP_MODEL_DIR / "outputs" / "eu_small_model_summary.json"
FACTOR_RECOMMENDATION_PROJECT_ROOT = TP_ROOT / "16_factor_recommendation_model"
FACTOR_RECOMMENDATION_OUTPUT_DIR = FACTOR_RECOMMENDATION_PROJECT_ROOT / "outputs"
FACTOR_RECOMMENDATION_PANEL_PATH = (
    FACTOR_RECOMMENDATION_OUTPUT_DIR / "factor_recommendation_panel.parquet"
)
FACTOR_RECOMMENDATION_HISTORY_PATH = (
    FACTOR_RECOMMENDATION_OUTPUT_DIR / "factor_recommendation_history.parquet"
)
FACTOR_RECOMMENDATION_SUMMARY_PATH = (
    FACTOR_RECOMMENDATION_OUTPUT_DIR / "factor_recommendation_summary.json"
)
FACTOR_RECOMMENDATION_VALIDATION_PATH = (
    FACTOR_RECOMMENDATION_OUTPUT_DIR / "factor_recommendation_validation.json"
)
FACTOR_RECOMMENDATION_OUTPUT_MANIFEST_PATH = (
    FACTOR_RECOMMENDATION_OUTPUT_DIR / "factor_recommendation_manifest.json"
)
FACTOR_RECOMMENDATION_MANIFEST_PATH = (
    PIPELINE_MANIFESTS_DIR
    / "refresh_factor_recommendation"
    / "refresh_factor_recommendation_latest.json"
)
FACTOR_RECOMMENDATION_SIGNAL_PATH = SIGNALS_DIR / "factor_recommendation_signals.parquet"
FACTOR_RECOMMENDATION_REGIONS = ("US", "EU", "ASIA")
FACTOR_RECOMMENDATION_STALE_DAYS = 62
COUNTRY_DATABASE_PATH = TP_ROOT / "14_country_model" / "data" / "country_model_database.parquet"
COUNTRY_SINGLE_COUNTRY_SCORE_PATH = (
    TP_ROOT / "14_country_model" / "outputs" / "country_model_single_country_scores.parquet"
)
SECTOR_SIGNAL_PATHS = (
    ("US", TP_ROOT / "13_sector_score_model" / "outputs_fs_sector_default" / "sector_scores_panel.parquet"),
    ("EU", TP_ROOT / "13_sector_score_model" / "outputs_eu" / "sector_scores_panel.parquet"),
)
SECTOR_RECOMMENDATION_PATHS = (
    ("US", TP_ROOT / "13_sector_score_model" / "outputs_fs_sector_default" / "sector_scores_latest.csv"),
    ("EU", TP_ROOT / "13_sector_score_model" / "outputs_eu" / "sector_scores_latest.csv"),
)
SECTOR_MONTHLY_VIEW_DIR = (
    TP_ROOT.parent / "笔记" / "卡片盒子" / "10_Investment" / "02_Sectors" / "Monthly_Sector_Views"
)
NEWS_ROOM_DIR = TP_ROOT.parent / "笔记" / "卡片盒子" / "40_News_Room"
NEWS_OKF_BUNDLE_DIR = TP_ROOT.parent / "笔记" / "_okf_bundles" / "personal_knowledge_catalog" / "news"
SECTOR_QUALITATIVE_OUTPUT_DIR = TP_ROOT / "13_sector_score_model" / "outputs_qualitative"
REGIME_OUTPUT_DIR = TP_ROOT / "03_regime_model" / "output"
REGIME_DASHBOARD_DATA_PATH = TP_ROOT / "03_regime_model" / "webapp" / "data.js"
REGIME_MODEL_DIAGNOSTICS_PATH = REGIME_OUTPUT_DIR / "model_diagnostics.json"
QA_DIR = TP_ROOT / "00_screen" / "qa"
RETURNS_AUDIT_PATH = QA_DIR / "returns_anomaly_governance" / "returns_extreme_audit_latest.json"
DATABASE_PROFILE_PATH = (
    TP_ROOT / "00_screen" / "production_inputs" / "profiles" / "latest_database_profile_latest.json"
)
FULL_BACKTEST_VALIDATION_PATH = (
    PIPELINE_MANIFESTS_DIR / "run_backtest" / "full_backtest_validation_latest.json"
)
SCORE_ML_BACKTEST_RUN_ROOT = (
    HISTORICAL_RESEARCH_RUNS_DIR / "score_ml_vs_if_msci_world_top_worst_20"
)
SCORE_ML_SCREEN_PATH = TP_ROOT / "00_screen" / "screen_aggregate.parquet"
TECHNICAL_SIGNAL_PATH = SIGNALS_DIR / "technical_signals.parquet"
TECHNICAL_SCREEN_PATH = TP_ROOT / "00_screen" / "last_screen.parquet"
SCORE_ML_COMPONENT_COLUMNS = [
    "Date",
    "Name",
    "Company SEDOL",
    "Score ML",
    "Score ML_IF",
    "Dividend Avg Percentile",
    "Value Avg Percentile",
    "Quality Avg Percentile",
    "Mom Avg Percentile",
    "Growth Avg Percentile",
    "LowVol Avg Percentile",
    "Size Avg Percentile",
    "PE LTM",
    "PE FY1",
    "PE NTM",
    "EPS Growth FY1",
    "ROE avg FY0",
    "DVD Yield FY1",
    "Earns Yield FY0",
    "Benchmark Market Value Millions in EUR",
    " Benchmark ICB Supersector ",
    "Exchange Country Region",
    "Benchmark Country English",
]

TECHNICAL_MARKETS = ("SP500", "STOXX EUROPE 600", "MSCI WORLD", "NASDAQ COMP")
TECHNICAL_METRIC_DEFINITIONS = (
    {
        "metric": "technical_structure_score",
        "label": "Structure",
        "source": "structure_signal",
        "kind": "discrete",
        "description": "HH=1, HL=0.5, LH=-0.5, LL=-1",
    },
    {
        "metric": "technical_momentum_10",
        "label": "Momentum 10",
        "source": "momentum_10",
        "kind": "continuous",
        "description": "10 日动量原始值，高值为好",
    },
    {
        "metric": "technical_macdh_12_26_9",
        "label": "MACDh",
        "source": "MACDh_12_26_9",
        "kind": "continuous",
        "description": "MACD histogram 原始值，高值为好",
    },
    {
        "metric": "technical_rsi_14_midpoint",
        "label": "RSI midpoint",
        "source": "rsi_14",
        "kind": "continuous",
        "description": "-abs(RSI14 - 50)，越接近 50 越高",
    },
    {
        "metric": "technical_triangle_score",
        "label": "Triangle",
        "source": "triangle_pattern",
        "kind": "pattern",
        "description": "Ascending Triangle=1, Descending Triangle=-1, None=0",
    },
    {
        "metric": "technical_wedge_score",
        "label": "Wedge",
        "source": "wedge_pattern",
        "kind": "pattern",
        "description": "Wedge Down=1, Wedge Up=-1, None=0",
    },
    {
        "metric": "technical_double_score",
        "label": "Double",
        "source": "double_pattern",
        "kind": "pattern",
        "description": "Double Bottom=1, Double Top=-1, None=0",
    },
    {
        "metric": "technical_composite",
        "label": "Composite",
        "source": "derived",
        "kind": "composite",
        "description": "子信号横截面 percentile rank 等权平均，至少 3 个有效子信号",
    },
)
TECHNICAL_PATTERN_SCORE_COLUMNS = {
    "technical_triangle_score",
    "technical_wedge_score",
    "technical_double_score",
}
TECHNICAL_METRIC_LABELS = {item["metric"]: item["label"] for item in TECHNICAL_METRIC_DEFINITIONS}
TECHNICAL_MARKET_RULES = {
    "SP500": {
        "technical_triangle_score": ("正向保留", "显著正向", "高分端", "clean run: Top excess +0.72%, Worst -3.67%, Top-Worst edge 4.40pp"),
        "technical_macdh_12_26_9": ("正向保留", "显著正向", "高分端", "clean run: Top excess +1.61%, Worst -1.23%, edge 2.84pp"),
        "technical_momentum_10": ("正向保留", "显著正向", "高分端", "clean run: Top excess +1.57%, Worst -0.21%, edge 1.79pp"),
        "technical_composite": ("弱辅助", "弱证据", "高分端", "clean run: Top excess +0.26%, Worst -0.82%, edge 1.07pp"),
        "technical_rsi_14_midpoint": ("反向使用", "反向有效", "低分端", "clean run: Worst excess +2.65%, Top -1.07%，高 midpoint 不是优势"),
        "technical_wedge_score": ("反向使用", "反向有效", "低分端", "clean run: Worst excess +0.99%, Top -2.68%，高分端偏拥挤/失败形态"),
        "technical_structure_score": ("弱辅助", "弱证据", "高分端", "clean run: Top/Worst 均为正 excess，edge 仅 0.07pp，不作强排序"),
        "technical_double_score": ("反向使用", "弱证据", "低分端", "clean run: edge -2.13pp，且形态离散并列较多"),
    },
    "STOXX EUROPE 600": {
        "technical_triangle_score": ("风险过滤", "避雷有效", "高分端", "clean run: Top excess -0.57%, Worst -3.94%, edge 3.37pp，主要用于避开弱技术面"),
        "technical_momentum_10": ("风险过滤", "弱证据", "高分端", "clean run: Top excess -0.46%, Worst -1.37%, edge 0.91pp"),
        "technical_double_score": ("弱辅助", "弱证据", "高分端", "clean run: Top excess +0.86%, Worst +0.32%, edge 0.54pp，但 tie-heavy"),
        "technical_composite": ("弱辅助", "弱证据", "高分端", "clean run: Top excess -1.54%, Worst -2.13%, edge 0.59pp"),
        "technical_rsi_14_midpoint": ("反向使用", "反向有效", "低分端", "clean run: Worst excess +1.01%, Top -2.06%"),
        "technical_wedge_score": ("反向使用", "反向有效", "低分端", "clean run: Worst excess +1.51%, Top -1.46%"),
        "technical_macdh_12_26_9": ("弱辅助", "弱证据", "高分端", "clean run: Top/Worst excess 接近，edge -0.06pp"),
        "technical_structure_score": ("弱辅助", "弱证据", "高分端", "clean run: edge -0.07pp，不作单独排序"),
    },
    "MSCI WORLD": {
        "technical_composite": ("正向保留", "显著正向", "高分端", "clean run: Top excess +0.55%, Worst -1.43%, edge 1.98pp"),
        "technical_momentum_10": ("正向保留", "显著正向", "高分端", "clean run: Top excess +0.95%, Worst -0.92%, edge 1.87pp"),
        "technical_macdh_12_26_9": ("正向保留", "显著正向", "高分端", "clean run: Top excess +0.76%, Worst -1.03%, edge 1.79pp"),
        "technical_double_score": ("风险过滤", "弱证据", "高分端", "clean run: Top -0.82%, Worst -2.61%, edge 1.79pp；tie-heavy"),
        "technical_triangle_score": ("风险过滤", "弱证据", "高分端", "clean run: edge 0.86pp，但 Top/Worst excess 均为负"),
        "technical_structure_score": ("弱辅助", "弱证据", "高分端", "clean run: edge 0.64pp，方向性不足"),
        "technical_rsi_14_midpoint": ("反向使用", "反向有效", "低分端", "clean run: Worst excess +1.24%, Top -0.68%"),
        "technical_wedge_score": ("反向使用", "弱证据", "低分端", "clean run: high wedge 更差，edge -1.20pp"),
    },
    "NASDAQ COMP": {
        "technical_structure_score": ("正向保留", "弱证据", "高分端", "clean run: Top excess +0.62%, Worst -2.23%, edge 2.85pp"),
        "technical_wedge_score": ("风险过滤", "弱证据", "高分端", "clean run: Top -0.03%, Worst -2.10%, edge 2.06pp"),
        "technical_triangle_score": ("风险过滤", "弱证据", "高分端", "clean run: Top +0.17%, Worst -1.59%, edge 1.76pp"),
        "technical_macdh_12_26_9": ("弱辅助", "弱证据", "高分端", "clean run: Top/Worst 均弱，edge 0.22pp"),
        "technical_rsi_14_midpoint": ("反向使用", "反向有效", "低分端", "clean run: Worst excess +2.52%, Top -2.56%，NASDAQ 更像反转/拥挤结构"),
        "technical_momentum_10": ("反向使用", "弱证据", "低分端", "clean run: Worst excess +0.61%, Top +0.29%，短动量不宜照搬趋势"),
        "technical_double_score": ("反向使用", "弱证据", "低分端", "clean run: Worst excess +1.55%, Top +0.86%，tie-heavy"),
        "technical_composite": ("反向使用", "弱证据", "低分端", "clean run: high composite underperforms，edge -0.86pp"),
    },
}

SECTOR_MONTHLY_HEADING_RE = re.compile(r"^#### \[\[(?P<region>US|EU) (?P<sector>.+?)\]\] - (?P<view>.+?)\s*$")
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
FRONTMATTER_LINE_RE = re.compile(r'^([A-Za-z0-9_-]+):\s*"?([^"]*)"?\s*$')

ASSET_SUFFIXES = {".parquet", ".xlsx", ".xls", ".csv", ".json", ".md", ".yaml", ".yml"}
IGNORED_ASSET_PARTS = {
    "__pycache__",
    ".git",
    ".ipynb_checkpoints",
    ".pytest_cache",
    "artifacts",
    ".venv",
    ".venv_tp",
    "99_archive",
    "build",
    "dist",
    "node_modules",
    "runs",
}
IGNORED_ASSET_PART_KEYWORDS = ("backup", "quarantine", "备份", "隔离")
DISCOVERY_MAX_PER_PROJECT = 24
DISCOVERY_TTL_SECONDS = 120
_ASSET_DISCOVERY_CACHE: tuple[float, list[DataAssetEntry]] | None = None
DEFAULT_DASHBOARD_CONFIG: dict[str, Any] = {
    "step": "run_all",
    "input_month": "",
    "as_of": "",
    "update_mode": "both",
    "flags": ["skip_refresh", "skip_backtest", "dry_run_data", "inspect_backtest"],
    "top_pct": 0.1,
    "ml_weight": 0.7,
    "technical_weight": 0.3,
    "max_weight": 0.05,
    "optimizer_method": "constrained",
    "portfolio_region": "",
    "backtest_profile": "default",
    "bench": "",
    "universe": "",
    "start_date": "",
    "percentile": None,
    "project_id": "00_screen",
    "project_mode": "safe_check",
}
QUALITY_KEYS = {
    "screen_aggregate": ("Date", "Company SEDOL"),
    "screen_aggregate_5Y": ("Date", "Company SEDOL"),
    "last_screen": ("Company SEDOL",),
    "ml_signals": ("Date", "signal_family", "signal_name", "Company SEDOL", "region"),
    "technical_signals": ("Date", "signal_family", "signal_name", "Company SEDOL"),
    "regime_risk_budget": ("Date", "signal_family", "signal_name", "region"),
    "country_model_database": ("Date", "country"),
    "country_model_signals": ("Date", "signal_family", "signal_name", "region"),
    "small_cap_model_signals": ("Date", "signal_family", "signal_name", "Company SEDOL"),
    "country_model_single_country_scores": ("Date", "country"),
    "sector_score_model": ("Date", "sector_code"),
    "latest_candidates": ("candidate_date", "Company SEDOL"),
    "latest_target_weights": ("candidate_date", "Company SEDOL"),
}
QUALITY_FULL_SCAN_MAX_BYTES = 80 * 1024 * 1024
CORE_SCHEMA_ASSETS = (
    ("screen_aggregate", TP_ROOT / "00_screen" / "screen_aggregate.parquet"),
    ("last_screen", TP_ROOT / "00_screen" / "last_screen.parquet"),
    ("screen_aggregate_5Y", TP_ROOT / "00_screen" / "screen_aggregate_5Y.parquet"),
)
CORE_DATABASE_NAMES = ("screen_aggregate", "returns", "last_screen", "screen_aggregate_5Y")
LINEAGE_NODE_PROJECTS: dict[str, tuple[str, ...]] = {
    "生产输入": ("00_screen",),
    "核心数据库": ("00_screen", "tp_core"),
    "ML / Regime / Technical": (
        "03_ml_enhanced",
        "03_regime_model",
        "03_technical_analysis",
        "14_country_model",
        "15_small_cap_model",
    ),
    "统一信号": ("signals",),
    "候选池": ("candidates",),
    "组合权重": ("portfolios", "optimizer"),
    "回测": ("backtests",),
    "报告 / Dashboard": ("reports", "08_presentation_layer"),
}

STYLE = """
:root {
  --tp-bg: #eeecec;
  --tp-bg-2: #f5f4f3;
  --tp-surface: #ffffff;
  --tp-surface-soft: #f9f8f7;
  --tp-border: #d8d6d4;
  --tp-text: #20242a;
  --tp-muted: #6f747b;
  --tp-blue: #315d9f;
  --tp-teal: #187d72;
  --tp-amber: #aa741c;
  --tp-rose: #b23a50;
  --tp-green-soft: #e8f4f0;
  --tp-blue-soft: #e9eef7;
  --tp-amber-soft: #fbf2df;
  --tp-rose-soft: #f9e8eb;
  --tp-shadow: 0 1px 0 rgba(15, 23, 42, .05), 0 12px 32px rgba(15, 23, 42, .07);
}

html, body, #_dash-app-content {
  margin: 0;
  min-height: 100%;
  background: var(--tp-bg);
  color: var(--tp-text);
  font-family: Inter, "Segoe UI", system-ui, -apple-system, sans-serif;
}

* { box-sizing: border-box; }

.tp-dashboard {
  min-height: 100vh;
  overflow-x: hidden;
  background:
    linear-gradient(180deg, rgba(255,255,255,.62), rgba(255,255,255,0) 260px),
    var(--tp-bg);
}

.tp-header {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 28px;
  background: rgba(238, 236, 236, .88);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid rgba(216, 214, 212, .82);
}

.tp-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.tp-mark {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: var(--tp-blue);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.24), 0 8px 18px rgba(49,93,159,.22);
}

.tp-title {
  margin: 0;
  font-size: 19px;
  line-height: 1.1;
  font-weight: 700;
  letter-spacing: 0;
}

.tp-subtitle {
  margin-top: 3px;
  color: var(--tp-muted);
  font-size: 12px;
}

.tp-header-meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.tp-header-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

.tp-client-link {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  border-radius: 8px;
  border: 1px solid rgba(49,93,159,.28);
  background: var(--tp-surface);
  color: var(--tp-blue);
  padding: 0 12px;
  font-size: 13px;
  font-weight: 760;
  text-decoration: none;
}

.tp-client-link:hover {
  background: #e8edf7;
}

.tp-pill {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid var(--tp-border);
  background: rgba(255,255,255,.68);
  color: var(--tp-muted);
  font-size: 12px;
  white-space: nowrap;
}

.tp-main {
  width: min(1480px, 100%);
  margin: 0 auto;
  padding: 22px 24px 40px;
}

.tp-grid-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.tp-card, .tp-panel {
  border: 1px solid rgba(216,214,212,.9);
  border-radius: 8px;
  background: rgba(255,255,255,.82);
  box-shadow: var(--tp-shadow);
}

.tp-card {
  min-height: 106px;
  padding: 15px;
}

.tp-card-label {
  color: var(--tp-muted);
  font-size: 12px;
  font-weight: 650;
  text-transform: uppercase;
  letter-spacing: .06em;
}

.tp-card-value {
  margin-top: 9px;
  font-size: 26px;
  font-weight: 720;
  line-height: 1.05;
  word-break: break-word;
}

.tp-card-note {
  margin-top: 8px;
  color: var(--tp-muted);
  font-size: 12px;
  line-height: 1.35;
}

.tp-status-success { color: var(--tp-teal); }
.tp-status-failed { color: var(--tp-rose); }
.tp-status-warning { color: var(--tp-amber); }
.tp-status-muted { color: var(--tp-muted); }

.tp-workbench {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(360px, .75fr);
  gap: 14px;
  margin-top: 14px;
}

.tp-panel {
  padding: 16px;
  min-width: 0;
}

.tp-panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.tp-panel-title {
  margin: 0;
  font-size: 15px;
  font-weight: 720;
}

.tp-panel-meta {
  color: var(--tp-muted);
  font-size: 12px;
}

.tp-project-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.tp-project-card {
  padding: 14px;
  min-height: 134px;
}

.tp-project-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.tp-project-id {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 34px;
  width: auto;
  height: 28px;
  padding: 0 8px;
  border-radius: 7px;
  background: var(--tp-blue-soft);
  color: var(--tp-blue);
  font-weight: 740;
  font-size: 12px;
}

.tp-project-name {
  margin-top: 12px;
  font-weight: 720;
  font-size: 14px;
  word-break: break-word;
}

.tp-project-role {
  margin-top: 7px;
  color: var(--tp-muted);
  font-size: 12px;
  line-height: 1.42;
}

.tp-project-detail,
.tp-project-command {
  margin-top: 7px;
  color: var(--tp-muted);
  font-size: 11px;
  line-height: 1.35;
  word-break: break-word;
}

.tp-project-command {
  color: #3d424a;
  font-family: Consolas, "SFMono-Regular", monospace;
}

.tp-project-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 10px;
}

.tp-project-action {
  border: 1px solid var(--tp-border);
  border-radius: 8px;
  background: var(--tp-surface);
  color: var(--tp-blue);
  min-height: 30px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 720;
  cursor: pointer;
}

.tp-project-action:hover {
  background: var(--tp-blue-soft);
}

.tp-project-action:disabled {
  cursor: not-allowed;
  color: var(--tp-muted);
  background: #f0efee;
}

.tp-status-chip {
  border-radius: 999px;
  padding: 4px 8px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.tp-chip-success { background: var(--tp-green-soft); color: var(--tp-teal); }
.tp-chip-failed { background: var(--tp-rose-soft); color: var(--tp-rose); }
.tp-chip-warning { background: var(--tp-amber-soft); color: var(--tp-amber); }
.tp-chip-muted { background: #f0efee; color: var(--tp-muted); }

.tp-control-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.tp-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.tp-label {
  color: var(--tp-muted);
  font-size: 11px;
  font-weight: 680;
  text-transform: uppercase;
  letter-spacing: .05em;
}

.tp-field input,
.tp-field select,
.tp-field .Select-control {
  min-height: 34px;
  border-radius: 7px;
}

.tp-checks {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px 10px;
  margin-top: 12px;
}

.tp-checks label {
  color: var(--tp-text);
  font-size: 12px;
  line-height: 1.25;
}

.tp-command {
  margin-top: 12px;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid var(--tp-border);
  background: var(--tp-surface-soft);
  color: #353a42;
  font-family: Consolas, "SFMono-Regular", monospace;
  font-size: 11px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

.tp-lineage-detail {
  margin-top: 10px;
  padding: 10px;
  border: 1px solid var(--tp-border);
  border-radius: 8px;
  background: rgba(255,255,255,.64);
}

.tp-lineage-title {
  color: var(--tp-text);
  font-size: 13px;
  font-weight: 780;
  margin-bottom: 6px;
}

.tp-lineage-meta {
  color: var(--tp-muted);
  font-size: 12px;
  line-height: 1.35;
}

.tp-lineage-projects {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.tp-lineage-project {
  border: 1px solid var(--tp-border);
  border-radius: 8px;
  background: var(--tp-surface);
  padding: 9px;
}

.tp-lineage-project-name {
  color: var(--tp-text);
  font-size: 12px;
  font-weight: 760;
}

.tp-lineage-project-note {
  color: var(--tp-muted);
  font-size: 11px;
  line-height: 1.35;
  margin-top: 4px;
}

.tp-run-row {
  display: flex;
  align-items: stretch;
  gap: 10px;
  margin-top: 12px;
}

.tp-button {
  border: 0;
  border-radius: 8px;
  background: var(--tp-blue);
  color: white;
  min-height: 38px;
  padding: 0 16px;
  font-size: 13px;
  font-weight: 760;
  cursor: pointer;
  box-shadow: 0 8px 20px rgba(49,93,159,.22);
}

.tp-button:hover { filter: brightness(.97); }

.tp-button-secondary {
  background: var(--tp-surface);
  color: var(--tp-blue);
  border: 1px solid var(--tp-border);
  box-shadow: none;
}

.tp-run-result {
  flex: 1;
  min-height: 38px;
  border: 1px solid var(--tp-border);
  border-radius: 8px;
  padding: 9px 10px;
  background: rgba(255,255,255,.58);
  color: var(--tp-muted);
  font-size: 12px;
  line-height: 1.35;
}

.tp-job-status {
  margin-top: 12px;
  border: 1px solid var(--tp-border);
  border-radius: 8px;
  background: var(--tp-surface-soft);
  padding: 10px;
}

.tp-job-status-running {
  border-color: rgba(49,93,159,.32);
  background: var(--tp-blue-soft);
}

.tp-job-status-completed {
  border-color: rgba(24,125,114,.24);
  background: var(--tp-green-soft);
}

.tp-job-status-failed {
  border-color: rgba(178,58,80,.34);
  background: var(--tp-rose-soft);
}

.tp-job-status-evidence_waiting {
  border-color: rgba(170,116,28,.3);
  background: var(--tp-amber-soft);
}

.tp-job-title {
  color: var(--tp-text);
  font-size: 12px;
  font-weight: 780;
}

.tp-job-line {
  margin-top: 5px;
  color: var(--tp-muted);
  font-size: 11px;
  line-height: 1.4;
  word-break: break-word;
}

.tp-job-progress {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  margin-top: 10px;
}

.tp-job-phase {
  border: 1px solid var(--tp-border);
  border-radius: 8px;
  background: rgba(255,255,255,.7);
  color: var(--tp-muted);
  font-size: 10px;
  font-weight: 760;
  padding: 5px 6px;
  text-align: center;
}

.tp-job-phase-active {
  border-color: rgba(49,93,159,.35);
  background: #fff;
  color: var(--tp-blue);
}

.tp-job-log {
  margin: 9px 0 0;
  border: 1px solid rgba(32,36,42,.08);
  border-radius: 8px;
  background: rgba(255,255,255,.72);
  color: var(--tp-text);
  max-height: 118px;
  overflow: auto;
  padding: 8px;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 11px;
  line-height: 1.42;
  white-space: pre-wrap;
}

.tp-action-feedback {
  position: fixed;
  top: 18px;
  right: 18px;
  z-index: 40;
  max-width: min(420px, calc(100vw - 36px));
  min-width: 260px;
  border: 1px solid rgba(32,36,42,.1);
  border-radius: 8px;
  background: rgba(32,36,42,.94);
  color: #fff;
  box-shadow: 0 16px 36px rgba(15, 23, 42, .18);
  padding: 10px 12px;
  font-size: 12px;
  font-weight: 640;
  line-height: 1.45;
  white-space: pre-line;
  opacity: 0;
  pointer-events: none;
  transform: translateY(-8px);
  transition: opacity .16s ease, transform .16s ease;
}

.tp-action-feedback-active {
  opacity: 1;
  transform: translateY(0);
}

.tp-subcontrol {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--tp-border);
}

.tp-subcontrol-title {
  margin: 0 0 10px;
  color: var(--tp-text);
  font-size: 13px;
  font-weight: 760;
}

.tp-advanced {
  margin-top: 12px;
  border-top: 1px solid var(--tp-border);
  padding-top: 10px;
}

.tp-advanced summary {
  cursor: pointer;
  color: var(--tp-muted);
  font-size: 12px;
  font-weight: 720;
  text-transform: uppercase;
  letter-spacing: .05em;
}

.tp-advanced[open] summary {
  margin-bottom: 10px;
}

.tp-section {
  margin-top: 14px;
}

.tp-table {
  min-width: 0;
  overflow-x: hidden;
}

.tp-table .dash-table-container,
.tp-table .dash-spreadsheet-container,
.tp-table .dash-spreadsheet-inner {
  max-width: 100%;
  overflow-x: auto;
}

.tp-table .dash-table-container {
  border-radius: 8px;
  overflow-x: auto;
  overflow-y: hidden;
}

.tp-qa-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.tp-qa-item {
  min-height: 86px;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid var(--tp-border);
  background: var(--tp-surface-soft);
}

.tp-qa-name {
  font-weight: 720;
  font-size: 13px;
}

.tp-qa-value {
  margin-top: 8px;
  font-size: 18px;
  font-weight: 760;
}

.tp-qa-note {
  margin-top: 6px;
  color: var(--tp-muted);
  font-size: 12px;
  line-height: 1.35;
}

.tp-audit-detail {
  margin-top: 12px;
  padding: 10px;
  border-top: 1px solid var(--tp-border);
  color: var(--tp-muted);
  font-size: 12px;
  line-height: 1.42;
}

.tp-audit-detail-title {
  color: var(--tp-text);
  font-size: 13px;
  font-weight: 760;
  margin-bottom: 6px;
}

.tp-audit-detail-line {
  margin-top: 4px;
  word-break: break-word;
}

.tp-audit-detail-label {
  color: var(--tp-text);
  font-weight: 720;
}

@media (max-width: 1180px) {
  .tp-grid-stats,
  .tp-project-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .tp-workbench {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .tp-action-feedback {
    left: 12px;
    right: 12px;
    top: 12px;
    min-width: 0;
    max-width: calc(100vw - 24px);
  }
  .tp-header {
    align-items: flex-start;
    flex-direction: column;
    padding: 16px;
  }
  .tp-header-meta {
    justify-content: flex-start;
  }
  .tp-main {
    padding: 16px 12px 28px;
  }
  .tp-grid-stats,
  .tp-project-grid,
  .tp-control-grid,
  .tp-lineage-projects,
  .tp-checks,
  .tp-qa-list {
    grid-template-columns: 1fr;
  }
}
"""

TP_JOB_EVENT_SCRIPT = """
(function () {
  const phaseOrder = ["submitted", "running", "evidence", "done"];
  let currentSource = null;
  let currentJobId = "";

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) {
      node.textContent = value || "";
    }
  }

  function readApiState() {
    const node = document.getElementById("tp-job-api-state");
    if (!node || !node.textContent) {
      return {};
    }
    try {
      return JSON.parse(node.textContent);
    } catch (error) {
      return {};
    }
  }

  function setFeedback(title, note) {
    const node = document.getElementById("tp-action-feedback");
    if (!node) {
      return;
    }
    const timeText = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    node.className = "tp-action-feedback tp-action-feedback-active";
    node.textContent = timeText + "  " + title + "\\n" + (note || "");
  }

  function setResult(id, lines) {
    const node = document.getElementById(id);
    if (!node) {
      return;
    }
    node.style.whiteSpace = "pre-line";
    node.textContent = (lines || []).filter(Boolean).join("\\n");
  }

  function pipelinePayload(state) {
    return {
      step: state.step || "run_all",
      input_month: state.input_month || "",
      as_of: state.as_of || "",
      update_mode: state.update_mode || "both",
      top_pct: state.top_pct,
      ml_weight: state.ml_weight,
      technical_weight: state.technical_weight,
      max_weight: state.max_weight,
      optimizer_method: state.optimizer_method || "constrained",
      portfolio_region: state.portfolio_region || "",
      backtest_profile: state.backtest_profile || "",
      bench: state.bench || "",
      start_date: state.start_date || "",
      percentile: state.percentile,
      flags: Array.isArray(state.flags) ? state.flags : []
    };
  }

  function launchTarget(button) {
    const state = readApiState();
    if (button.id === "tp-checks-run") {
      return {
        endpoint: "/api/dashboard/jobs/system-checks",
        payload: {},
        resultId: "tp-checks-run-result",
        pendingStep: "system_checks",
        title: "已提交全部项目检查"
      };
    }
    if (button.id === "tp-project-run") {
      return {
        endpoint: "/api/dashboard/jobs/project",
        payload: {
          project_id: state.project_id || "00_screen",
          mode: state.project_mode || "safe_check"
        },
        resultId: "tp-project-run-result",
        pendingStep: "project:" + (state.project_id || "00_screen") + ":" + (state.project_mode || "safe_check"),
        title: "已提交子项目启动"
      };
    }
    return {
      endpoint: "/api/dashboard/jobs/pipeline",
      payload: pipelinePayload(state),
      resultId: "tp-run-result",
      pendingStep: state.step || "run_all",
      title: "已提交 pipeline 启动"
    };
  }

  function renderJob(job) {
    if (!job) {
      return false;
    }
    const card = document.querySelector("#tp-active-job .tp-job-status");
    if (!card) {
      return false;
    }
    const status = job.status || "idle";
    const phase = job.phase || "submitted";
    const activeIndex = Math.max(0, phaseOrder.indexOf(phase));
    card.className = "tp-job-status tp-job-status-" + status;
    card.dataset.jobId = job.job_id || "";
    card.dataset.jobStatus = status;
    card.dataset.jobRealtime = currentSource ? "sse" : "api";
    setText("tp-job-title", "当前任务: " + (job.step || "暂无启动任务") + " [" + (job.status_label || "IDLE") + "]");
    setText(
      "tp-job-detail",
      "job_id: " + (job.job_id || "N/A") + " / PID: " + (job.pid || "N/A") + " / started: " + (job.started_at || "N/A")
    );
    setText("tp-job-evidence", "manifest: " + (job.manifest_status || "N/A") + " / " + (job.manifest || "N/A"));
    setText("tp-job-log-path", "log: " + (job.log_path || "N/A"));
    setText("tp-job-log-tail", job.log_tail || "暂无日志摘要");
    document.querySelectorAll("#tp-active-job .tp-job-phase").forEach(function (node, index) {
      node.className = index <= activeIndex ? "tp-job-phase tp-job-phase-active" : "tp-job-phase";
    });
    window.tpDashboardJobState = { job: job, eventSourceActive: Boolean(currentSource) };
    return true;
  }

  async function refreshLatestJob() {
    try {
      const response = await fetch("/api/dashboard/jobs/latest", { headers: { "Accept": "application/json" } });
      if (!response.ok) {
        return;
      }
      const job = await response.json();
      if (renderJob(job)) {
        subscribeToJob(job.job_id || "");
      } else {
        window.setTimeout(refreshLatestJob, 1000);
      }
    } catch (error) {
      window.tpDashboardJobState = { error: String(error) };
    }
  }

  function closeSource() {
    if (currentSource) {
      currentSource.close();
      currentSource = null;
    }
  }

  function subscribeToJob(jobId) {
    if (!window.EventSource || !jobId || jobId === currentJobId) {
      return;
    }
    closeSource();
    currentJobId = jobId;
    currentSource = new EventSource("/api/dashboard/jobs/" + encodeURIComponent(jobId) + "/events");
    currentSource.addEventListener("job", function (event) {
      const job = JSON.parse(event.data);
      renderJob(job);
      if (job.status === "completed" || job.status === "failed") {
        closeSource();
      }
    });
    currentSource.onerror = function () {
      closeSource();
      window.setTimeout(refreshLatestJob, 3000);
    };
  }

  async function apiLaunchJob(button) {
    const target = launchTarget(button);
    button.disabled = true;
    button.dataset.apiLaunch = "pending";
    renderJob({
      job_id: "pending",
      step: target.pendingStep,
      status: "running",
      status_label: "SUBMITTING",
      phase: "submitted",
      pid: "",
      started_at: "",
      manifest_status: "N/A",
      manifest: "",
      log_path: "",
      log_tail: "正在向后端提交 job..."
    });
    setFeedback(target.title, "前端已接管按钮点击，正在通过 API 创建后台 job。");
    setResult(target.resultId, ["正在通过 API 提交 job..."]);
    try {
      const response = await fetch(target.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(target.payload)
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "job API request failed");
      }
      const job = payload.job || {};
      renderJob(job);
      subscribeToJob(job.job_id || "");
      setFeedback(target.title, "job_id " + (job.job_id || "N/A") + " 已返回，后续状态走实时事件流。");
      setResult(target.resultId, [
        "已通过 API 提交 " + (job.step || target.pendingStep),
        "job_id " + (job.job_id || "N/A"),
        "PID " + (job.pid || "N/A"),
        job.log_path || ""
      ]);
    } catch (error) {
      setFeedback("启动失败", String(error && error.message ? error.message : error));
      setResult(target.resultId, ["启动失败", String(error && error.message ? error.message : error)]);
    } finally {
      window.setTimeout(function () {
        button.disabled = false;
        button.dataset.apiLaunch = "";
      }, 900);
    }
  }

  function boot() {
    document.documentElement.dataset.tpJobEvents = "ready";
    document.documentElement.dataset.tpClientLaunch = "api";
    refreshLatestJob();
    document.addEventListener("click", function (event) {
      const button = event.target.closest("#tp-run, #tp-project-run, #tp-checks-run");
      if (button && document.documentElement.dataset.tpClientLaunch === "api") {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        apiLaunchJob(button);
      }
    }, true);
    window.setInterval(refreshLatestJob, 10000);
    window.tpDashboardJobEvents = {
      apiLaunchJob: apiLaunchJob,
      refreshLatestJob: refreshLatestJob,
      renderJob: renderJob,
      subscribeToJob: subscribeToJob
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
"""


def _system_repository() -> SystemDashboardRepository:
    return SystemDashboardRepository(
        config_path=DASHBOARD_CONFIG_PATH,
        defaults=DEFAULT_DASHBOARD_CONFIG,
        qa_dir=QA_DIR,
        manifest_dir=PIPELINE_MANIFESTS_DIR,
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    return _system_repository().read_json(path)


def _latest_manifest(step: str) -> dict[str, Any] | None:
    return _system_repository().latest_manifest(step)


def _latest_json_by_glob(pattern: str) -> dict[str, Any] | None:
    return _system_repository().latest_qa_json(pattern)


def _read_dashboard_config() -> dict[str, Any]:
    return _system_repository().read_config()


def _write_dashboard_config(values: dict[str, Any]) -> dict[str, Any]:
    return _system_repository().write_config(values)


def _rel(path: str | Path | None) -> str:
    return relative_path(path, root=TP_ROOT)


@lru_cache(maxsize=64)
def _date_profile_cached(path_text: str, column: str, mtime_ns: int) -> dict[str, Any]:
    del mtime_ns
    import pyarrow.parquet as pq

    table = pq.read_table(path_text, columns=[column])
    values = pd.to_datetime(table[column].to_pandas(), errors="coerce").dropna()
    if values.empty:
        return {"date_min": "", "date_max": "", "date_count": 0}
    return {
        "date_min": values.min().date().isoformat(),
        "date_max": values.max().date().isoformat(),
        "date_count": int(values.nunique()),
    }


def _date_profile(path: Path, column: str | None) -> dict[str, Any]:
    if not column or not path.exists() or path.suffix.lower() != ".parquet":
        return {}
    try:
        return _date_profile_cached(str(path), column, path.stat().st_mtime_ns)
    except Exception as exc:
        return {"date_error": str(exc)}


@lru_cache(maxsize=64)
def _quality_profile_cached(
    path_text: str,
    mtime_ns: int,
    asset_name: str,
    date_column: str | None,
    size_bytes: int,
) -> dict[str, Any]:
    del mtime_ns
    path = Path(path_text)
    if not path.exists() or path.suffix.lower() != ".parquet":
        return {}

    import pyarrow.parquet as pq

    schema_names = set(pq.ParquetFile(path).schema.names)
    key_columns = tuple(column for column in QUALITY_KEYS.get(asset_name, ()) if column in schema_names)
    is_full_scan = size_bytes <= QUALITY_FULL_SCAN_MAX_BYTES
    if is_full_scan:
        frame = pd.read_parquet(path)
        quality_scope = "full table"
    else:
        read_columns = list(dict.fromkeys(column for column in (*key_columns, date_column or "") if column in schema_names))
        if not read_columns:
            return {"quality_scope": "metadata only"}
        frame = pd.read_parquet(path, columns=read_columns)
        quality_scope = "key columns"

    cell_count = int(frame.shape[0] * frame.shape[1])
    null_rate = None
    if cell_count:
        null_rate = float(frame.isna().sum().sum() / cell_count)

    duplicate_rows = None
    if key_columns and all(column in frame.columns for column in key_columns):
        duplicate_rows = int(frame.duplicated(list(key_columns)).sum())

    return {
        "null_rate": null_rate,
        "duplicate_rows": duplicate_rows,
        "quality_scope": quality_scope,
        "quality_columns": ", ".join(key_columns) if key_columns else "",
    }


def _quality_profile(asset: DataAssetEntry, profile: dict[str, Any]) -> dict[str, Any]:
    try:
        return _quality_profile_cached(
            str(asset.path),
            asset.path.stat().st_mtime_ns,
            asset.name,
            asset.date_column,
            int(profile.get("bytes") or 0),
        )
    except Exception as exc:
        return {"quality_error": str(exc)}


@lru_cache(maxsize=32)
def _schema_names_cached(path_text: str, mtime_ns: int) -> tuple[str, ...]:
    del mtime_ns
    import pyarrow.parquet as pq

    path = Path(path_text)
    if not path.exists() or path.suffix.lower() != ".parquet":
        return ()
    return tuple(pq.ParquetFile(path).schema.names)


def _schema_names(path: Path) -> tuple[str, ...]:
    try:
        return _schema_names_cached(str(path), path.stat().st_mtime_ns)
    except Exception:
        return ()


@lru_cache(maxsize=32)
def _date_gap_profile_cached(path_text: str, column: str, mtime_ns: int, frequency: str) -> dict[str, Any]:
    del mtime_ns
    import pyarrow.parquet as pq

    table = pq.read_table(path_text, columns=[column])
    values = pd.to_datetime(table[column].to_pandas(), errors="coerce").dropna().drop_duplicates().sort_values()
    if values.empty:
        return {"observed": 0, "expected": 0, "missing": 0, "sample": ""}
    if frequency == "month_end":
        expected = pd.date_range(values.min(), values.max(), freq="ME")
    else:
        expected = pd.bdate_range(values.min(), values.max())
    expected_dates = set(pd.Series(expected).dt.normalize())
    observed_dates = set(values.dt.normalize())
    missing = sorted(expected_dates - observed_dates)
    return {
        "observed": int(len(observed_dates)),
        "expected": int(len(expected_dates)),
        "missing": int(len(missing)),
        "sample": ", ".join(item.date().isoformat() for item in missing[:5]),
    }


def _date_gap_profile(path: Path, column: str, frequency: str) -> dict[str, Any]:
    try:
        return _date_gap_profile_cached(str(path), column, path.stat().st_mtime_ns, frequency)
    except Exception as exc:
        return {"error": str(exc)}


def _asset_profile(asset: DataAssetEntry, source: str) -> dict[str, Any]:
    profile = path_profile(asset.path, parquet=asset.path.suffix.lower() == ".parquet")
    profile.update(_date_profile(asset.path, asset.date_column))
    quality = (
        _quality_profile(asset, profile)
        if source == "registry"
        else {"quality_scope": "metadata only"}
    )
    status = "存在" if profile.get("exists") else "缺失"
    date_range = ""
    if profile.get("date_min") or profile.get("date_max"):
        date_range = f"{profile.get('date_min', '')} -> {profile.get('date_max', '')}"
    return {
        "项目": asset.project_id,
        "数据/产物": asset.name,
        "类型": asset.kind,
        "状态": status,
        "必需": "是" if asset.required else "否",
        "行": _fmt_int(profile.get("rows")),
        "列": _fmt_int(profile.get("columns")),
        "日期范围": date_range,
        "空值率": _fmt_pct(quality.get("null_rate")),
        "重复键": _fmt_int(quality.get("duplicate_rows")),
        "质量口径": quality.get("quality_scope") or quality.get("quality_error", ""),
        "更新时间": profile.get("modified_at", ""),
        "大小": _format_bytes(profile.get("bytes")),
        "路径": _rel(profile.get("path")),
        "来源": source,
        "_bytes": int(profile.get("bytes") or 0),
        "_mtime": _safe_mtime(asset.path),
    }


def _asset_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return "parquet"
    if suffix in {".xlsx", ".xls"}:
        return "spreadsheet"
    if suffix == ".csv":
        return "csv"
    if suffix == ".json":
        return "json"
    if suffix == ".md":
        return "markdown"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    return "file"


def _is_ignored_asset(path: Path) -> bool:
    for part in path.parts:
        normalized = part.lower()
        if part in IGNORED_ASSET_PARTS:
            return True
        if any(keyword in normalized for keyword in IGNORED_ASSET_PART_KEYWORDS):
            return True
    return False


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _discovered_asset_entries() -> list[DataAssetEntry]:
    global _ASSET_DISCOVERY_CACHE
    now = time.time()
    if _ASSET_DISCOVERY_CACHE and now - _ASSET_DISCOVERY_CACHE[0] < DISCOVERY_TTL_SECONDS:
        return _ASSET_DISCOVERY_CACHE[1]

    registered_paths = {entry.path.resolve(strict=False) for entry in DATA_ASSET_REGISTRY}
    entries: list[DataAssetEntry] = []
    for project in PROJECT_REGISTRY:
        root = project.root_path
        if _is_ignored_asset(root) or not root.exists() or not root.is_dir():
            continue
        candidates: list[Path] = []
        try:
            for current_dir, dir_names, file_names in os.walk(root):
                current_path = Path(current_dir)
                dir_names[:] = [
                    name
                    for name in dir_names
                    if not _is_ignored_asset(current_path / name)
                ]
                for name in file_names:
                    path = current_path / name
                    if (
                        path.suffix.lower() not in ASSET_SUFFIXES
                        or path.resolve(strict=False) in registered_paths
                    ):
                        continue
                    candidates.append(path)
        except OSError:
            continue
        candidates.sort(key=_safe_mtime, reverse=True)
        for path in candidates[:DISCOVERY_MAX_PER_PROJECT]:
            entries.append(
                DataAssetEntry(
                    project_id=project.project_id,
                    name=_rel(path),
                    path=path,
                    kind=_asset_kind(path),
                    required=False,
                )
            )

    _ASSET_DISCOVERY_CACHE = (now, entries)
    return entries


def _asset_rows() -> list[dict[str, Any]]:
    rows = [_asset_profile(asset, "registry") for asset in DATA_ASSET_REGISTRY if not _is_ignored_asset(asset.path)]
    rows.extend(_asset_profile(asset, "discovered") for asset in _discovered_asset_entries())
    return rows


def _project_asset_summary_rows(asset_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    rows = asset_rows if asset_rows is not None else _asset_rows()
    rows_by_project: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_project.setdefault(str(row.get("项目") or ""), []).append(row)

    summaries: list[dict[str, Any]] = []
    for project in PROJECT_REGISTRY:
        project_rows = rows_by_project.get(project.project_id, [])
        registered = [row for row in project_rows if row.get("来源") == "registry"]
        discovered = [row for row in project_rows if row.get("来源") == "discovered"]
        present = [row for row in project_rows if row.get("状态") == "存在"]
        missing = [row for row in project_rows if row.get("状态") == "缺失"]
        required_missing = [row for row in missing if row.get("必需") == "是"]
        latest = max((float(row.get("_mtime") or 0) for row in project_rows), default=0.0)
        key_assets = [
            f"{row.get('数据/产物', '')} ({row.get('状态', '')})"
            for row in registered[:4]
        ]
        if len(registered) > 4:
            key_assets.append(f"+{len(registered) - 4} registered")
        if not key_assets and discovered:
            key_assets = [str(row.get("数据/产物", "")) for row in discovered[:3]]
        status = "CHECK" if required_missing else "OK" if project_rows else "无资产"
        summaries.append(
            {
                "项目": project.project_id,
                "项目状态": project.status,
                "资产状态": status,
                "注册资产": _fmt_int(len(registered)),
                "自动发现": _fmt_int(len(discovered)),
                "存在": _fmt_int(len(present)),
                "缺失": _fmt_int(len(missing)),
                "必需缺失": _fmt_int(len(required_missing)),
                "总大小": _format_bytes(sum(int(row.get("_bytes") or 0) for row in project_rows)),
                "最新更新时间": datetime.fromtimestamp(latest).isoformat(timespec="seconds") if latest else "",
                "关键资产": "; ".join(item for item in key_assets if item),
            }
        )
    return summaries


def _asset_filter_options() -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    project_options = [{"label": "全部项目", "value": ""}]
    project_options.extend(
        {"label": f"{project.project_id} - {project.role}", "value": project.project_id}
        for project in PROJECT_REGISTRY
    )
    source_options = [
        {"label": "全部来源", "value": ""},
        {"label": "注册资产", "value": "registry"},
        {"label": "自动发现", "value": "discovered"},
    ]
    status_options = [
        {"label": "全部状态", "value": ""},
        {"label": "存在", "value": "存在"},
        {"label": "缺失", "value": "缺失"},
    ]
    return project_options, source_options, status_options


def _filter_asset_rows(
    rows: list[dict[str, Any]],
    project_id: str | None = None,
    source: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    filtered = rows
    if project_id:
        filtered = [row for row in filtered if row.get("项目") == project_id]
    if source:
        filtered = [row for row in filtered if row.get("来源") == source]
    if status:
        filtered = [row for row in filtered if row.get("状态") == status]
    return filtered


def _core_schema_signal(name: str, path_text: str | None) -> tuple[str, str]:
    path = TP_ROOT / path_text if path_text else None
    schema = _schema_names(path) if path else ()
    if not schema:
        return "N/A", "schema unavailable"
    if name in {item[0] for item in CORE_SCHEMA_ASSETS}:
        base_schema = _schema_names(CORE_SCHEMA_ASSETS[0][1])
        missing = sorted(set(base_schema) - set(schema))
        added = sorted(set(schema) - set(base_schema))
        status = "OK" if not missing and not added else "CHECK"
        evidence = "matches screen_aggregate"
        if missing or added:
            evidence = f"missing {len(missing)}, added {len(added)}"
        return status, f"{len(schema)} columns; {evidence}"
    sample = ", ".join(schema[:4])
    return "BASELINE", f"{len(schema)} columns; sample {sample}"


def _core_database_rows(asset_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    assets = asset_rows if asset_rows is not None else _asset_rows()
    by_name = {row.get("数据/产物"): row for row in assets}
    rows: list[dict[str, Any]] = []
    for name in CORE_DATABASE_NAMES:
        row = by_name.get(name, {})
        date_range = row.get("日期范围", "")
        latest_date = date_range.split(" -> ")[-1] if date_range else ""
        exists = row.get("状态") == "存在"
        duplicate_count = None
        try:
            duplicate_count = int(str(row.get("重复键") or "").replace(",", ""))
        except ValueError:
            duplicate_count = None
        status = "OK" if exists and latest_date and duplicate_count in (None, 0) else "CHECK"
        if not exists:
            status = "缺失"
        schema_status, schema_evidence = _core_schema_signal(name, row.get("路径"))
        if schema_status == "CHECK":
            status = "CHECK"
        quality_parts = [
            f"null {row.get('空值率') or 'N/A'}",
            f"dup {row.get('重复键') or 'N/A'}",
            row.get("质量口径") or "",
        ]
        rows.append(
            {
                "数据资产": name,
                "更新状态": status,
                "最新日期": latest_date,
                "行": row.get("行", ""),
                "列": row.get("列", ""),
                "日期范围": date_range,
                "更新时间": row.get("更新时间", ""),
                "大小": row.get("大小", ""),
                "质量信号": "; ".join(part for part in quality_parts if part),
                "Schema": schema_status,
                "Schema 证据": schema_evidence,
                "路径": row.get("路径", ""),
            }
        )
    return rows


def _command_text(command: Any) -> str:
    if isinstance(command, list):
        return _quote_command([str(item) for item in command])
    return str(command or "")


def _pipeline_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in PIPELINE_STEPS:
        payload = _latest_manifest(step)
        failed = []
        if payload:
            failed = [
                item.get("name", "")
                for item in payload.get("validations", [])
                if item.get("status") != "passed"
            ]
        rows.append(
            {
                "步骤": step,
                "状态": _status_label(payload.get("status") if payload else None),
                "最近完成": payload.get("finished_at", "") if payload else "",
                "秒数": payload.get("duration_seconds", "") if payload else "",
                "未通过校验": ", ".join(failed),
                "manifest": _rel(PIPELINE_MANIFESTS_DIR / step / f"{step}_latest.json")
                if payload
                else "",
            }
        )
    return rows


def _alert_rows(
    core_rows: list[dict[str, Any]],
    check_rows: list[dict[str, Any]],
    pipeline_rows: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
    production_rows: list[dict[str, Any]],
    limit: int = 12,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for item in core_rows:
        status = str(item.get("更新状态") or "")
        if status == "OK":
            continue
        rows.append(
            {
                "级别": "P1" if status == "缺失" else "P2",
                "模块": "核心数据库",
                "对象": item.get("数据资产", ""),
                "状态": status,
                "证据": "; ".join(
                    part
                    for part in (
                        item.get("质量信号", ""),
                        f"schema {item.get('Schema', '')}: {item.get('Schema 证据', '')}",
                    )
                    if part
                )[:700],
            }
        )

    for item in check_rows:
        status = str(item.get("状态") or "")
        status_key = status.lower()
        if status_key in {"success", "ok", "passed"}:
            continue
        rows.append(
            {
                "级别": "P1" if status_key in {"failed", "error"} else "P2",
                "模块": "子项目检查",
                "对象": item.get("项目", ""),
                "状态": status or "N/A",
                "证据": (item.get("stdout/stderr") or item.get("输出概况") or item.get("命令") or "")[:700],
            }
        )

    for item in pipeline_rows:
        status = str(item.get("状态") or "")
        if status == "OK":
            continue
        rows.append(
            {
                "级别": "P1" if status == "FAIL" else "P2",
                "模块": "Pipeline",
                "对象": item.get("步骤", ""),
                "状态": status or "N/A",
                "证据": (item.get("未通过校验") or item.get("manifest") or "")[:700],
            }
        )

    for item in quality_rows:
        status = str(item.get("状态") or "")
        if status.upper() in {"OK", "PASSED"} or status.lower() in {"passed", "success"}:
            continue
        if status.upper() == "N/A":
            continue
        rows.append(
            {
                "级别": "P2",
                "模块": "数据质量",
                "对象": item.get("检查项", ""),
                "状态": status,
                "证据": "; ".join(
                    part for part in (item.get("异常/缺口", ""), item.get("证据", "")) if part
                )[:700],
            }
        )

    for item in production_rows:
        status = str(item.get("状态") or "")
        if status == "OK":
            continue
        rows.append(
            {
                "级别": "P2",
                "模块": "投资生产",
                "对象": item.get("产物", ""),
                "状态": status or "N/A",
                "证据": (item.get("质量") or item.get("覆盖/数量") or "")[:700],
            }
        )

    if not rows:
        return [
            {
                "级别": "INFO",
                "模块": "系统总览",
                "对象": "all clear",
                "状态": "OK",
                "证据": "核心库、项目检查、pipeline、数据质量和生产产物未发现阻断项",
            }
        ]
    return rows[:limit]


def _read_frame(path: Path) -> pd.DataFrame | None:
    return _system_repository().read_frame(path)


@lru_cache(maxsize=4)
def _score_ml_screen_cached(path_text: str, mtime_ns: int) -> pd.DataFrame:
    del mtime_ns
    frame = pd.read_parquet(path_text, columns=SCORE_ML_COMPONENT_COLUMNS)
    if "ISIN" not in frame.columns:
        frame = frame.reset_index()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    return frame


def _score_ml_screen_frame() -> pd.DataFrame | None:
    if not SCORE_ML_SCREEN_PATH.exists():
        return None
    try:
        return _score_ml_screen_cached(str(SCORE_ML_SCREEN_PATH), SCORE_ML_SCREEN_PATH.stat().st_mtime_ns)
    except Exception:
        return None


@lru_cache(maxsize=2)
def _technical_screen_cached(path_text: str, mtime_ns: int) -> pd.DataFrame:
    del mtime_ns
    frame = pd.read_parquet(path_text)
    if "ISIN" not in frame.columns:
        frame = frame.reset_index()
    if "Date" in frame.columns:
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    return frame


def _technical_screen_frame() -> pd.DataFrame | None:
    if not TECHNICAL_SCREEN_PATH.exists():
        return None
    try:
        return _technical_screen_cached(str(TECHNICAL_SCREEN_PATH), TECHNICAL_SCREEN_PATH.stat().st_mtime_ns)
    except Exception:
        return None


@lru_cache(maxsize=2)
def _company_des_cached(path_text: str, mtime_ns: int) -> pd.DataFrame:
    del mtime_ns
    frame = pd.read_parquet(path_text)
    if "Date" in frame.columns:
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    return frame


@lru_cache(maxsize=2)
def _company_news_cached(path_text: str, mtime_ns: int) -> pd.DataFrame:
    del mtime_ns
    frame = pd.read_parquet(path_text)
    if "Date" in frame.columns:
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    return frame


def _company_frame(path: Path, loader: Any) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return loader(str(path), path.stat().st_mtime_ns)
    except Exception:
        return None


def _json_text(value: Any, default: str = "") -> str:
    if value is None or pd.isna(value):
        return default
    result = str(value).strip()
    return result or default


def _company_detail_payload(isin: str) -> dict[str, Any]:
    isin = str(isin or "").strip()
    payload: dict[str, Any] = {
        "status": "missing",
        "isin": isin,
        "identity": {},
        "description": {},
        "news": [],
        "message": "",
    }
    if not isin:
        payload["message"] = "missing ISIN"
        return payload

    des = _company_frame(COMPANY_DES_PATH, _company_des_cached)
    news = _company_frame(COMPANY_NEWS_PATH, _company_news_cached)
    if des is None or des.empty or "ISIN" not in des.columns:
        payload["message"] = "company description parquet missing or unreadable"
        return payload

    desc_rows = des[des["ISIN"].astype(str).eq(isin)].copy()
    if desc_rows.empty:
        payload["message"] = f"no company description for {isin}"
    else:
        desc_rows = desc_rows.sort_values("Date", ascending=False, na_position="last")
        row = desc_rows.iloc[0]
        payload["identity"] = {
            "name": _json_text(row.get("NAME"), _json_text(row.get("Company"), isin)),
            "company": _json_text(row.get("COMPANY"), _json_text(row.get("Company"), "")),
            "country": _json_text(row.get("COUNTRY")),
            "sector": _json_text(row.get("SECTOR")),
        }
        payload["description"] = {
            "date": _fmt_date(row.get("Date")),
            "title": _json_text(row.get("Title"), "Description"),
            "body": _json_text(row.get("HTMLbody")),
        }

    if news is not None and not news.empty and "ISIN" in news.columns:
        news_rows = news[news["ISIN"].astype(str).eq(isin)].copy()
        if not news_rows.empty:
            news_rows = news_rows.sort_values("Date", ascending=False, na_position="last").head(8)
            payload["news"] = [
                {
                    "date": _fmt_date(row.get("Date")),
                    "title": _json_text(row.get("Title"), "Actualité"),
                    "body": _json_text(row.get("HTMLbody")),
                }
                for _, row in news_rows.iterrows()
            ]

    if payload["description"] or payload["news"]:
        payload["status"] = "ok"
        payload["message"] = f"{len(payload['news'])} recent news"
    return payload


def _latest_score_ml_run(side: str) -> Path | None:
    if side not in {"top", "worst"} or not SCORE_ML_BACKTEST_RUN_ROOT.exists():
        return None
    expected_top = side == "top"
    candidates: list[Path] = []
    for run_dir in SCORE_ML_BACKTEST_RUN_ROOT.iterdir():
        if not run_dir.is_dir():
            continue
        manifest = run_dir / "manifest.yaml"
        config = run_dir / "config_snapshot.yaml"
        sec_list = run_dir / "sec_list.parquet"
        if not manifest.exists() or not config.exists() or not sec_list.exists():
            continue
        manifest_text = manifest.read_text(encoding="utf-8", errors="ignore")
        if "status: success" not in manifest_text or "- Score ML\n" not in manifest_text:
            continue
        text = config.read_text(encoding="utf-8", errors="ignore")
        if f"top: {str(expected_top).lower()}" not in text:
            continue
        candidates.append(run_dir)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _score_ml_date_options() -> list[str]:
    dates: set[str] = set()
    for side in ("top", "worst"):
        run_dir = _latest_score_ml_run(side)
        if run_dir is None:
            continue
        try:
            sec_list = pd.read_parquet(run_dir / "sec_list.parquet", columns=["Date"])
        except Exception:
            continue
        values = pd.to_datetime(sec_list["Date"], errors="coerce").dropna()
        dates.update(value.date().isoformat() for value in values)
    return sorted(dates, reverse=True)


def _score_ml_components_payload(date: str | None = None, side: str = "top") -> dict[str, Any]:
    side = side if side in {"top", "worst"} else "top"
    date_options = _score_ml_date_options()
    selected_date = date if date in date_options else (date_options[0] if date_options else "")
    payload: dict[str, Any] = {
        "status": "missing",
        "title": "Score ML portfolio components",
        "default_side": "top",
        "selected_side": side,
        "default_date": date_options[0] if date_options else "",
        "selected_date": selected_date,
        "date_options": date_options,
        "rows": [],
        "run_dir": "",
        "screen_date": "",
        "message": "",
    }
    run_dir = _latest_score_ml_run(side)
    if run_dir is None:
        payload["message"] = "Score ML backtest sec_list missing"
        return payload
    payload["run_dir"] = _rel(run_dir)
    if not selected_date:
        payload["message"] = "Score ML backtest has no available dates"
        return payload
    screen = _score_ml_screen_frame()
    if screen is None or screen.empty:
        payload["message"] = "screen_aggregate parquet missing or unreadable"
        return payload
    try:
        sec_list = pd.read_parquet(run_dir / "sec_list.parquet")
    except Exception as exc:
        payload.update({"status": "error", "message": str(exc)})
        return payload

    sec = sec_list.copy()
    sec["Date"] = pd.to_datetime(sec["Date"], errors="coerce")
    selected_ts = pd.Timestamp(selected_date)
    sec = sec[sec["Date"].eq(selected_ts)].copy()
    if sec.empty:
        payload["message"] = f"no portfolio components for {selected_date}"
        return payload
    screen_dates = screen.loc[screen["Date"].le(selected_ts), "Date"].dropna()
    if screen_dates.empty:
        payload["message"] = f"no screen date available before {selected_date}"
        return payload
    screen_date = screen_dates.max()
    snapshot = screen[screen["Date"].eq(screen_date)].copy()
    merged = sec.merge(snapshot, on="ISIN", how="left", suffixes=("", "_screen"))
    merged["Weight"] = pd.to_numeric(merged["Weight"], errors="coerce").fillna(0.0)
    merged = merged.sort_values("Weight", ascending=False, na_position="last")

    def row_payload(row: pd.Series) -> dict[str, str]:
        return {
            "Name": str(row.get("Name") or row.get("ISIN") or "N/A"),
            "ISIN": str(row.get("ISIN") or ""),
            "SEDOL": str(row.get("Company SEDOL") or ""),
            "Weight": f"{float(row.get('Weight') or 0) * 100:.2f}%",
            "Score ML": _fmt_number(row.get("Score ML"), 2),
            "Score ML_IF": _fmt_number(row.get("Score ML_IF"), 2),
            "Div": _fmt_number(row.get("Dividend Avg Percentile"), 2),
            "Value": _fmt_number(row.get("Value Avg Percentile"), 2),
            "Quality": _fmt_number(row.get("Quality Avg Percentile"), 2),
            "Momentum": _fmt_number(row.get("Mom Avg Percentile"), 2),
            "Growth": _fmt_number(row.get("Growth Avg Percentile"), 2),
            "LowVol": _fmt_number(row.get("LowVol Avg Percentile"), 2),
            "Size": _fmt_number(row.get("Size Avg Percentile"), 2),
            "PE LTM": _fmt_number(row.get("PE LTM"), 1),
            "PE FY1": _fmt_number(row.get("PE FY1"), 1),
            "PE NTM": _fmt_number(row.get("PE NTM"), 1),
            "EPS Growth FY1": _fmt_number(row.get("EPS Growth FY1"), 1),
            "ROE": _fmt_number(row.get("ROE avg FY0"), 1),
            "Dividend Yield": _fmt_number(row.get("DVD Yield FY1"), 2),
            "Earnings Yield": _fmt_number(row.get("Earns Yield FY0"), 2),
            "Mkt Cap EURm": _fmt_number(row.get("Benchmark Market Value Millions in EUR"), 0),
            "Country": str(row.get("Benchmark Country English") or ""),
            "Region": str(row.get("Exchange Country Region") or ""),
            "Sector": _fmt_int(row.get(" Benchmark ICB Supersector ")),
        }

    rows = [row_payload(row) for _, row in merged.iterrows()]
    payload.update(
        {
            "status": "ok",
            "selected_date": selected_date,
            "screen_date": _fmt_date(screen_date),
            "rows": rows,
            "message": f"{len(rows)} {side} components",
        }
    )
    return payload


def _technical_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    result = str(value).strip()
    return result or default


def _technical_market_rule(market: str, metric: str) -> dict[str, str]:
    action, evidence, side, note = TECHNICAL_MARKET_RULES.get(market, {}).get(
        metric,
        ("弱辅助", "弱证据", "高分端", "该市场缺少明确稳健证据，只作辅助观察"),
    )
    return {"处理": action, "证据": evidence, "推荐端": side, "说明": note}


def _latest_technical_metric_frame(signal_frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    required = {"Date", "signal_name", "Company SEDOL", "score", "raw_value"}
    if signal_frame.empty or not required.issubset(signal_frame.columns):
        return pd.DataFrame(), None

    data = signal_frame.copy()
    data["_Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["_Date"])
    if data.empty:
        return pd.DataFrame(), None

    latest_date = data["_Date"].max()
    latest = data[data["_Date"].eq(latest_date)].copy()
    latest["Company SEDOL"] = latest["Company SEDOL"].astype("string").str.strip()
    latest = latest[latest["Company SEDOL"].notna() & latest["Company SEDOL"].ne("")]
    if latest.empty:
        return pd.DataFrame(), latest_date

    base_columns = ["Company SEDOL"]
    if "ISIN" in latest.columns:
        base_columns.append("ISIN")
    for column in ["technical_pattern_date", "technical_period_end", "technical_available_date", "effective_date", "as_of_date"]:
        if column in latest.columns:
            base_columns.append(column)
    base = latest[base_columns].drop_duplicates("Company SEDOL").set_index("Company SEDOL")
    metrics = base.copy()

    def assign_metric(source: str, metric: str, values: pd.Series) -> None:
        part = latest[latest["signal_name"].eq(source)].copy()
        if part.empty:
            metrics[metric] = pd.NA
            return
        part["_technical_metric"] = pd.to_numeric(values.loc[part.index], errors="coerce")
        series = (
            part.dropna(subset=["_technical_metric"])
            .groupby("Company SEDOL", dropna=False)["_technical_metric"]
            .mean()
        )
        metrics[metric] = series

    score = pd.to_numeric(latest["score"], errors="coerce")
    assign_metric("structure_signal", "technical_structure_score", score)
    assign_metric("momentum_10", "technical_momentum_10", score)
    assign_metric("MACDh_12_26_9", "technical_macdh_12_26_9", score)
    assign_metric("rsi_14", "technical_rsi_14_midpoint", -(score - 50.0).abs())

    raw_text = latest["raw_value"].astype("string").str.strip()
    assign_metric(
        "triangle_pattern",
        "technical_triangle_score",
        raw_text.map({"Ascending Triangle": 1.0, "Descending Triangle": -1.0}),
    )
    assign_metric(
        "wedge_pattern",
        "technical_wedge_score",
        raw_text.map({"Wedge Down": 1.0, "Wedge Up": -1.0}),
    )
    assign_metric(
        "double_pattern",
        "technical_double_score",
        raw_text.map({"Double Bottom": 1.0, "Double Top": -1.0}),
    )

    for metric in TECHNICAL_PATTERN_SCORE_COLUMNS:
        if metric in metrics.columns:
            metrics[metric] = pd.to_numeric(metrics[metric], errors="coerce").fillna(0.0)

    base_metric_columns = [
        item["metric"]
        for item in TECHNICAL_METRIC_DEFINITIONS
        if item["metric"] != "technical_composite"
    ]
    for metric in base_metric_columns:
        if metric not in metrics.columns:
            metrics[metric] = pd.NA

    numeric_metrics = metrics[base_metric_columns].apply(pd.to_numeric, errors="coerce")
    valid_count = numeric_metrics.notna().sum(axis=1)
    rank_frame = numeric_metrics.rank(method="average", pct=True)
    metrics["technical_composite"] = rank_frame.mean(axis=1).where(valid_count >= 3)
    metrics["technical_valid_metrics"] = valid_count
    return metrics.reset_index(), latest_date


def _technical_signal_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "technical_latest_metrics",
        "title": "Latest Technical metrics by market",
        "status": "missing",
        "latest_date": "",
        "screen_date": "",
        "pattern_date": "",
        "period_end": "",
        "available_date": "",
        "updated_at": "",
        "signal_path": _rel(TECHNICAL_SIGNAL_PATH),
        "screen_path": _rel(TECHNICAL_SCREEN_PATH),
        "availability_note": (
            "展示源为 availability-safe production technical_signals：Date/effective_date 使用 weekly pattern 完整后的下一交易日，"
            "as_of_date/technical_pattern_date 保留原始周初标签。"
        ),
        "metric_definitions": [
            {
                "metric": item["metric"],
                "label": item["label"],
                "source": item["source"],
                "description": item["description"],
            }
            for item in TECHNICAL_METRIC_DEFINITIONS
        ],
        "markets": [],
        "metric_rows": [],
        "security_rows": [],
        "message": "",
    }
    signal_frame = _read_frame(TECHNICAL_SIGNAL_PATH)
    screen = _technical_screen_frame()
    if signal_frame is None or signal_frame.empty:
        payload["message"] = "technical_signals parquet missing or empty"
        return payload
    if screen is None or screen.empty or "Date" not in screen.columns:
        payload["message"] = "last_screen parquet missing or unreadable"
        return payload

    metric_frame, latest_date = _latest_technical_metric_frame(signal_frame)
    if metric_frame.empty or latest_date is None:
        payload["message"] = "no latest technical metrics could be reconstructed"
        return payload

    def metric_dates(column: str) -> pd.Series:
        if column not in metric_frame.columns:
            return pd.Series(dtype="datetime64[ns]")
        return pd.to_datetime(metric_frame[column], errors="coerce").dropna()

    pattern_date = metric_dates("technical_pattern_date")
    period_end = metric_dates("technical_period_end")
    available_date = metric_dates("technical_available_date")

    screen_data = screen.copy()
    screen_data["_Date"] = pd.to_datetime(screen_data["Date"], errors="coerce")
    screen_data = screen_data.dropna(subset=["_Date"])
    if screen_data.empty:
        payload["message"] = "last_screen has no valid Date"
        return payload
    screen_date = screen_data["_Date"].max()
    screen_latest = screen_data[screen_data["_Date"].eq(screen_date)].copy()
    screen_latest["Company SEDOL"] = screen_latest["Company SEDOL"].astype("string").str.strip()
    screen_latest = screen_latest[screen_latest["Company SEDOL"].notna() & screen_latest["Company SEDOL"].ne("")]

    metric_columns = [item["metric"] for item in TECHNICAL_METRIC_DEFINITIONS]
    metric_lookup = {item["metric"]: item for item in TECHNICAL_METRIC_DEFINITIONS}
    market_rows: list[dict[str, str]] = []
    metric_rows: list[dict[str, Any]] = []
    security_rows: list[dict[str, str]] = []

    def clean_sector(value: Any) -> str:
        return _fmt_int(value) or _technical_text(value, "N/A")

    for market in TECHNICAL_MARKETS:
        weight_column = f"Weight in {market}"
        if weight_column not in screen_latest.columns:
            continue
        constituents = screen_latest.copy()
        constituents["_technical_weight"] = pd.to_numeric(constituents[weight_column], errors="coerce").fillna(0.0)
        constituents = constituents[constituents["_technical_weight"].gt(0)].copy()
        if constituents.empty:
            continue
        merged = constituents.merge(metric_frame, on="Company SEDOL", how="left", suffixes=("", "_technical"))
        available_metrics = merged[metric_columns].apply(pd.to_numeric, errors="coerce")
        covered = int(available_metrics.notna().any(axis=1).sum())
        universe = int(len(merged))
        rules = TECHNICAL_MARKET_RULES.get(market, {})
        positive = [
            TECHNICAL_METRIC_LABELS.get(metric, metric)
            for metric, rule in rules.items()
            if rule[0] in {"正向保留", "弱正向"}
        ]
        reverse = [
            TECHNICAL_METRIC_LABELS.get(metric, metric)
            for metric, rule in rules.items()
            if rule[0] == "反向使用"
        ]
        auxiliary = [
            TECHNICAL_METRIC_LABELS.get(metric, metric)
            for metric, rule in rules.items()
            if rule[0] in {"弱辅助", "风险过滤"}
        ]
        market_rows.append(
            {
                "market": market,
                "screen_date": _fmt_date(screen_date),
                "signal_date": _fmt_date(latest_date),
                "universe": _fmt_int(universe),
                "covered": _fmt_int(covered),
                "coverage": _fmt_pct(covered / universe if universe else None, 1),
                "positive": ", ".join(positive) or "N/A",
                "reverse": ", ".join(reverse) or "N/A",
                "auxiliary": ", ".join(auxiliary) or "N/A",
            }
        )

        for metric in metric_columns:
            info = metric_lookup[metric]
            rule = _technical_market_rule(market, metric)
            series = pd.to_numeric(merged.get(metric), errors="coerce")
            valid = series.dropna()
            valid_count = int(valid.shape[0])
            coverage = valid_count / universe if universe else None
            tie_rate = float(valid.value_counts(normalize=True, dropna=True).iloc[0]) if valid_count else None
            event_rate = ""
            if metric in TECHNICAL_PATTERN_SCORE_COLUMNS and valid_count:
                event_rate = _fmt_pct(float(valid.ne(0).mean()), 1)
            metric_rows.append(
                {
                    "市场": market,
                    "metric": info["label"],
                    "metric_code": metric,
                    "处理": rule["处理"],
                    "证据": rule["证据"],
                    "推荐端": rule["推荐端"],
                    "覆盖": f"{_fmt_int(valid_count)} / {_fmt_int(universe)}",
                    "覆盖率": _fmt_pct(coverage, 1),
                    "均值": _fmt_number(valid.mean(), 3) if valid_count else "",
                    "中位数": _fmt_number(valid.median(), 3) if valid_count else "",
                    "最小": _fmt_number(valid.min(), 3) if valid_count else "",
                    "最大": _fmt_number(valid.max(), 3) if valid_count else "",
                    "并列率": _fmt_pct(tie_rate, 1) if tie_rate is not None else "",
                    "事件率": event_rate,
                    "说明": rule["说明"],
                }
            )

            if not valid_count:
                continue
            side_is_low = rule["推荐端"] == "低分端"
            sample = merged.loc[valid.index].copy()
            sample["_technical_metric_value"] = valid
            sample = sample.sort_values(
                ["_technical_metric_value", "_technical_weight"],
                ascending=[side_is_low, False],
                na_position="last",
            ).head(3)
            for _, row in sample.iterrows():
                security_rows.append(
                    {
                        "市场": market,
                        "metric": info["label"],
                        "处理": rule["处理"],
                        "推荐端": rule["推荐端"],
                        "Name": _technical_text(row.get("Name"), _technical_text(row.get("ISIN"), "N/A")),
                        "score": _fmt_number(row.get("_technical_metric_value"), 3),
                        "Weight": _fmt_pct(row.get("_technical_weight"), 2),
                        "Country": _technical_text(row.get("Benchmark Country English")),
                        "Region": _technical_text(row.get("Exchange Country Region")),
                        "Sector": clean_sector(row.get(" Benchmark ICB Supersector ")),
                        "ISIN": _technical_text(row.get("ISIN")),
                    }
                )

    latest_updated = max(
        TECHNICAL_SIGNAL_PATH.stat().st_mtime if TECHNICAL_SIGNAL_PATH.exists() else 0,
        TECHNICAL_SCREEN_PATH.stat().st_mtime if TECHNICAL_SCREEN_PATH.exists() else 0,
    )
    payload.update(
        {
            "status": "ok",
            "latest_date": _fmt_date(latest_date),
            "screen_date": _fmt_date(screen_date),
            "pattern_date": _fmt_date(pattern_date.max()) if not pattern_date.empty else "",
            "period_end": _fmt_date(period_end.max()) if not period_end.empty else "",
            "available_date": _fmt_date(available_date.max()) if not available_date.empty else "",
            "updated_at": datetime.fromtimestamp(latest_updated).isoformat(timespec="seconds"),
            "markets": market_rows,
            "metric_rows": metric_rows,
            "security_rows": security_rows,
            "message": f"{len(market_rows)} markets / {len(metric_rows)} metric rows / {len(security_rows)} current samples",
        }
    )
    return payload


def _date_range_text(frame: pd.DataFrame, column: str) -> str:
    if column not in frame.columns:
        return ""
    values = pd.to_datetime(frame[column], errors="coerce").dropna()
    if values.empty:
        return ""
    return f"{values.min().date().isoformat()} -> {values.max().date().isoformat()}"


def _top_counts(frame: pd.DataFrame, column: str, limit: int = 3) -> str:
    if column not in frame.columns:
        return ""
    counts = frame[column].dropna().value_counts().head(limit)
    return "; ".join(f"{index}: {_fmt_int(value)}" for index, value in counts.items())


def _fmt_float(value: Any, digits: int = 2) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def _quality_text(frame: pd.DataFrame, keys: list[str]) -> str:
    null_rate = float(frame.isna().sum().sum() / (frame.shape[0] * frame.shape[1])) if frame.size else 0.0
    duplicate_rows = ""
    if keys and all(column in frame.columns for column in keys):
        duplicate_rows = f", dup {_fmt_int(frame.duplicated(keys).sum())}"
    return f"null {_fmt_pct(null_rate)}{duplicate_rows}"


def _top_row_text(frame: pd.DataFrame, score_column: str, name_column: str = "Name") -> str:
    if score_column not in frame.columns or frame[score_column].dropna().empty:
        return ""
    top = frame.sort_values(score_column, ascending=False).iloc[0]
    label = ""
    for column in (name_column, "Company SEDOL", "region"):
        value = top.get(column)
        if pd.notna(value) and value not in ("", None):
            label = str(value)
            break
    return f"{label} ({score_column} {_fmt_float(top.get(score_column), 3)})"


def _signal_summary_row(label: str, path: Path) -> dict[str, Any]:
    frame = _read_frame(path)
    if frame is None or frame.empty:
        return {
            "产物": label,
            "状态": "缺失/空",
            "日期范围": "",
            "覆盖/数量": "",
            "分布": "",
            "Top": "",
            "质量": "",
        }
    score_column = "score_pct" if "score_pct" in frame.columns and frame["score_pct"].notna().any() else "score"
    security_count = frame["Company SEDOL"].dropna().nunique() if "Company SEDOL" in frame.columns else 0
    region_count = frame["region"].dropna().nunique() if "region" in frame.columns else 0
    coverage = f"{_fmt_int(security_count)} securities" if security_count else f"{_fmt_int(region_count)} regions"
    distribution = _top_counts(frame, "signal_name")
    if "region" in frame.columns and frame["region"].notna().any():
        distribution = f"{distribution}; {_top_counts(frame, 'region')}" if distribution else _top_counts(frame, "region")
    return {
        "产物": label,
        "状态": "OK",
        "日期范围": _date_range_text(frame, "Date"),
        "覆盖/数量": f"{_fmt_int(len(frame))} rows / {coverage}",
        "分布": distribution,
        "Top": _top_row_text(frame, score_column),
        "质量": _quality_text(frame, list(QUALITY_KEYS.get(path.stem, ()))),
    }


def _candidate_summary_row(path: Path) -> dict[str, Any]:
    frame = _read_frame(path)
    if frame is None or frame.empty:
        return {"产物": "latest_candidates", "状态": "缺失/空", "日期范围": "", "覆盖/数量": "", "分布": "", "Top": "", "质量": ""}
    selected = frame[frame["selected"].fillna(False)] if "selected" in frame.columns else frame
    return {
        "产物": "latest_candidates",
        "状态": "OK",
        "日期范围": _date_range_text(frame, "candidate_date"),
        "覆盖/数量": f"{_fmt_int(len(frame))} candidates / {_fmt_int(len(selected))} selected",
        "分布": _top_counts(frame, "region") or _top_counts(frame, "Exchange Country Region"),
        "Top": _top_row_text(selected if not selected.empty else frame, "composite_score"),
        "质量": _quality_text(frame, list(QUALITY_KEYS.get("latest_candidates", ()))),
    }


def _portfolio_summary_row(path: Path) -> dict[str, Any]:
    frame = _read_frame(path)
    if frame is None or frame.empty:
        return {"产物": "latest_target_weights", "状态": "缺失/空", "日期范围": "", "覆盖/数量": "", "分布": "", "Top": "", "质量": ""}
    weight_sum = frame["target_weight"].sum() if "target_weight" in frame.columns else None
    region_text = ""
    if {"region", "target_weight"} <= set(frame.columns):
        region_weights = frame.groupby("region", dropna=True)["target_weight"].sum().sort_values(ascending=False).head(4)
        region_text = "; ".join(f"{region}: {_fmt_pct(weight, 1)}" for region, weight in region_weights.items())
    return {
        "产物": "latest_target_weights",
        "状态": "OK",
        "日期范围": _date_range_text(frame, "candidate_date"),
        "覆盖/数量": f"{_fmt_int(len(frame))} holdings / sum {_fmt_float(weight_sum, 4)}",
        "分布": region_text,
        "Top": _top_row_text(frame, "target_weight"),
        "质量": _quality_text(frame, list(QUALITY_KEYS.get("latest_target_weights", ()))),
    }


def _sector_summary_row() -> dict[str, Any]:
    frames: list[pd.DataFrame] = []
    for region, path in SECTOR_SIGNAL_PATHS:
        latest_path = next((item for market, item in SECTOR_RECOMMENDATION_PATHS if market == region), path)
        if not latest_path.exists():
            continue
        frame = pd.read_csv(latest_path, encoding="utf-8-sig")
        if frame.empty:
            continue
        copy = frame.copy()
        copy["region"] = region
        frames.append(copy)
    if not frames:
        return {"产物": "sector_score_model", "状态": "缺失/空", "日期范围": "", "覆盖/数量": "", "分布": "", "Top": "", "质量": ""}
    frame = pd.concat(frames, ignore_index=True)
    score_column = "score_final" if "score_final" in frame.columns else "rank"
    sector_count = frame["sector_code"].dropna().nunique() if "sector_code" in frame.columns else 0
    return {
        "产物": "sector_score_model",
        "状态": "OK",
        "日期范围": _date_range_text(frame, "Date"),
        "覆盖/数量": f"{_fmt_int(len(frame))} rows / {_fmt_int(sector_count)} sectors",
        "分布": _top_counts(frame, "region"),
        "Top": _top_row_text(frame, score_column),
        "质量": _quality_text(frame, list(QUALITY_KEYS.get("sector_score_model", ()))),
    }


def _production_rows() -> list[dict[str, Any]]:
    return [
        _signal_summary_row("ml_signals", SIGNALS_DIR / "ml_signals.parquet"),
        _signal_summary_row("technical_signals", SIGNALS_DIR / "technical_signals.parquet"),
        _signal_summary_row("regime_risk_budget", SIGNALS_DIR / "regime_risk_budget.parquet"),
        _signal_summary_row("country_model_signals", COUNTRY_SIGNAL_PATH),
        _signal_summary_row("small_cap_model_signals", SMALL_CAP_SIGNAL_PATH),
        _sector_summary_row(),
        _candidate_summary_row(CANDIDATES_DIR / "latest_candidates.parquet"),
        _portfolio_summary_row(PORTFOLIOS_DIR / "latest_target_weights.parquet"),
    ]


def _read_regime_dashboard_data() -> dict[str, Any]:
    if not REGIME_DASHBOARD_DATA_PATH.exists():
        return {}
    try:
        text = REGIME_DASHBOARD_DATA_PATH.read_text(encoding="utf-8").strip()
        prefix = "window.DASHBOARD_DATA = "
        if text.startswith(prefix):
            text = text[len(prefix):]
        if text.endswith(";"):
            text = text[:-1]
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _latest_regime_output_row(region: str, filename: str, model_name: str) -> dict[str, Any] | None:
    path = REGIME_OUTPUT_DIR / filename
    frame = _read_frame(path)
    if frame is None or frame.empty:
        return None
    data = frame.copy()
    if "Date" not in data.columns:
        data = data.reset_index()
    if "Date" not in data.columns:
        return None
    data["_Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["_Date"]).sort_values("_Date")
    if data.empty:
        return None
    row = data.iloc[-1]
    return {
        "region": region,
        "model": model_name,
        "as_of": _fmt_date(row.get("_Date")),
        "regime": str(row.get("label") or "N/A"),
        "state": _fmt_int(row.get("state")),
        "source": _rel(path),
    }


def _regime_state_model_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_region: dict[str, dict[str, dict[str, Any]]] = {}
    for region in ("EU", "US"):
        full = _latest_regime_output_row(region, f"regime_{region}.parquet", "HMM full-sample")
        oos = _latest_regime_output_row(region, f"regime_oos_{region}.parquet", "HMM walk-forward OOS")
        region_rows = [row for row in (full, oos) if row]
        by_region[region] = {row["model"]: row for row in region_rows}
        rows.extend(region_rows)
    for region_rows in by_region.values():
        full = region_rows.get("HMM full-sample")
        oos = region_rows.get("HMM walk-forward OOS")
        if full and oos:
            agree = full["state"] == oos["state"] and full["regime"] == oos["regime"]
            full["agreement"] = "一致" if agree else "分歧"
            oos["agreement"] = "一致" if agree else "分歧"
    return rows


def _regime_risk_model_rows(dashboard_data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for region in ("EU", "US"):
        current = (dashboard_data.get(region) or {}).get("current") or {}
        contrib = (dashboard_data.get(region) or {}).get("contrib") or []
        if not current:
            continue
        top_driver = contrib[0] if contrib else {}
        pred_vol = current.get("pred_vol")
        target_vol = current.get("target_vol")
        equity_weight = current.get("equity_weight")
        rows.append(
            {
                "region": region,
                "model": "Ridge volatility",
                "as_of": str((dashboard_data.get(region) or {}).get("as_of") or ""),
                "regime": str(current.get("label") or ""),
                "pred_vol": pred_vol,
                "target_vol": target_vol,
                "equity_weight": equity_weight,
                "pred_vol_pct": _fmt_pct(pred_vol, 1),
                "target_vol_pct": _fmt_pct(target_vol, 1),
                "equity_weight_pct": _fmt_pct(equity_weight, 0),
                "state_mult": _fmt_number(current.get("state_mult"), 2),
                "top_driver": str(top_driver.get("feat") or ""),
                "top_driver_contrib": _fmt_number(top_driver.get("contrib"), 4),
                "source": _rel(REGIME_DASHBOARD_DATA_PATH),
            }
        )
    return rows


def _regime_model_rank_rows(diagnostics: dict[str, Any], family: str, metric: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    regions = diagnostics.get("regions") if isinstance(diagnostics, dict) else {}
    if not isinstance(regions, dict):
        return rows
    for region in ("EU", "US"):
        model_rows = (regions.get(region) or {}).get(family) or []
        for rank, item in enumerate(model_rows[:4], start=1):
            score = item.get(metric)
            rows.append(
                {
                    "region": region,
                    "rank": rank,
                    "model": str(item.get("model") or ""),
                    "metric": metric,
                    "score": score,
                    "score_text": _fmt_number(score, 3),
                    "secondary": _fmt_number(item.get("Pearson") or item.get("AUC") or item.get("R2"), 3),
                    "annual_return": _fmt_number(item.get("年化收益%"), 2),
                    "sharpe": _fmt_number(item.get("夏普"), 2),
                }
            )
    return rows


def _regime_models_payload() -> dict[str, Any]:
    diagnostics = _read_json(REGIME_MODEL_DIAGNOSTICS_PATH) or {}
    dashboard_data = _read_regime_dashboard_data()
    updated_candidates = [
        REGIME_MODEL_DIAGNOSTICS_PATH.stat().st_mtime if REGIME_MODEL_DIAGNOSTICS_PATH.exists() else None,
        REGIME_DASHBOARD_DATA_PATH.stat().st_mtime if REGIME_DASHBOARD_DATA_PATH.exists() else None,
    ]
    latest_updated = max((item for item in updated_candidates if item is not None), default=None)
    return {
        "status": "ok" if dashboard_data or diagnostics else "missing",
        "updated_at": datetime.fromtimestamp(latest_updated).isoformat(timespec="seconds") if latest_updated else "",
        "state_models": _regime_state_model_rows(),
        "risk_models": _regime_risk_model_rows(dashboard_data),
        "direction_models": _regime_model_rank_rows(diagnostics, "direction_models", "准确率"),
        "volatility_models": _regime_model_rank_rows(diagnostics, "volatility_models", "高波动AUC"),
        "drawdown_models": _regime_model_rank_rows(diagnostics, "drawdown_models", "高波动AUC"),
        "diagnostics_path": _rel(REGIME_MODEL_DIAGNOSTICS_PATH),
        "dashboard_data_path": _rel(REGIME_DASHBOARD_DATA_PATH),
    }


def _regime_signal_payload() -> dict[str, Any]:
    path = REGIME_SIGNAL_PATH
    payload: dict[str, Any] = {
        "name": "regime_risk_budget",
        "title": "Regime detector",
        "status": "missing",
        "latest_date": "",
        "updated_at": "",
        "signal_path": _rel(path),
        "rows": [],
        "history": [],
        "models": _regime_models_payload(),
        "refresh_endpoint": "/api/dashboard/jobs/signals/regime",
    }
    if not path.exists():
        payload["message"] = "regime signal parquet missing"
        return payload
    try:
        frame = _read_frame(path)
    except Exception as exc:
        payload.update({"status": "error", "message": str(exc)})
        return payload
    if frame is None or frame.empty or "Date" not in frame.columns:
        payload["message"] = "regime signal parquet empty or missing Date"
        return payload

    data = frame.copy()
    data["_Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["_Date"])
    if data.empty:
        payload["message"] = "regime signal parquet has no valid Date"
        return payload

    latest_date = data["_Date"].max()
    latest = data[data["_Date"].eq(latest_date)].sort_values(["region", "signal_name"], na_position="last")
    history = data.sort_values(["region", "_Date"]).groupby("region", dropna=False).tail(12)
    history = history.sort_values(["_Date", "region"], ascending=[False, True], na_position="last")

    def row_payload(row: pd.Series) -> dict[str, str]:
        return {
            "region": str(row.get("region") or "N/A"),
            "最新月份": _fmt_date(row.get("_Date")),
            "regime": str(row.get("raw_value") or "N/A"),
            "risk_budget": _fmt_number(row.get("score"), 2),
            "state": _fmt_int(row.get("regime_state")),
            "direction": str(row.get("direction") or ""),
            "model": str(row.get("model_version") or ""),
            "source": _rel(row.get("source_file")),
        }

    payload.update(
        {
            "status": "ok",
            "latest_date": _fmt_date(latest_date),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            "rows": [row_payload(row) for _, row in latest.iterrows()],
            "history": [row_payload(row) for _, row in history.iterrows()],
            "message": f"{len(latest)} latest regime rows",
        }
    )
    return payload


def _country_signal_payload() -> dict[str, Any]:
    path = COUNTRY_SIGNAL_PATH
    payload: dict[str, Any] = {
        "name": "country_model_signals",
        "title": "Country model",
        "status": "missing",
        "latest_date": "",
        "updated_at": "",
        "signal_path": _rel(path),
        "database_path": _rel(COUNTRY_DATABASE_PATH),
        "single_country_path": _rel(COUNTRY_SINGLE_COUNTRY_SCORE_PATH),
        "rows": [],
        "history": [],
        "single_country_rows": [],
        "single_country_history": [],
        "refresh_endpoint": "/api/dashboard/jobs/signals/country",
    }
    if not path.exists():
        payload["message"] = "country model signal parquet missing"
        return payload
    try:
        frame = _read_frame(path)
    except Exception as exc:
        payload.update({"status": "error", "message": str(exc)})
        return payload
    if frame is None or frame.empty or "Date" not in frame.columns:
        payload["message"] = "country model signal parquet empty or missing Date"
        return payload

    data = frame.copy()
    data["_Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["_Date"])
    if data.empty:
        payload["message"] = "country model signal parquet has no valid Date"
        return payload

    latest_date = data["_Date"].max()
    sort_columns = ["rank", "region"] if "rank" in data.columns else ["region"]
    latest = data[data["_Date"].eq(latest_date)].sort_values(sort_columns, na_position="last")
    history = data.sort_values(["region", "_Date"]).groupby("region", dropna=False).tail(12)
    history = history.sort_values(["_Date", "rank", "region"], ascending=[False, True, True], na_position="last")

    def row_payload(row: pd.Series) -> dict[str, str]:
        return {
            "region": str(row.get("region") or "N/A"),
            "country_label": str(row.get("country_label") or row.get("region") or "N/A"),
            "最新月份": _fmt_date(row.get("_Date")),
            "score": _fmt_number(row.get("score"), 3),
            "rank": _fmt_number(row.get("rank"), 0),
            "recommendation": str(row.get("recommendation") or row.get("raw_value") or ""),
            "rank_delta": _fmt_number(row.get("rank_delta"), 0),
            "margin": _fmt_number(row.get("margin_score"), 2),
            "profitability": _fmt_number(row.get("profitability_score"), 2),
            "growth": _fmt_number(row.get("growth_score"), 2),
            "value": _fmt_number(row.get("value_score"), 2),
            "momentum": _fmt_number(row.get("momentum_score"), 2),
            "excel_diff": _fmt_number(row.get("score_diff_vs_excel"), 6),
            "model": str(row.get("model_version") or ""),
        }

    single_country_rows: list[dict[str, str]] = []
    single_country_history_rows: list[dict[str, str]] = []
    if COUNTRY_SINGLE_COUNTRY_SCORE_PATH.exists():
        try:
            single_country = _read_frame(COUNTRY_SINGLE_COUNTRY_SCORE_PATH)
            if single_country is not None and not single_country.empty and "Date" in single_country.columns:
                single_data = single_country.copy()
                single_data["_Date"] = pd.to_datetime(single_data["Date"], errors="coerce")
                single_data = single_data.dropna(subset=["_Date"])
                if not single_data.empty:
                    single_latest_date = single_data["_Date"].max()
                    single_sort_columns = ["rank", "country"] if "rank" in single_data.columns else ["country"]
                    single_latest = single_data[single_data["_Date"].eq(single_latest_date)].sort_values(
                        single_sort_columns,
                        na_position="last",
                    )
                    single_history = single_data.sort_values(["country", "_Date"]).groupby(
                        "country",
                        dropna=False,
                    ).tail(12)
                    single_history = single_history.sort_values(
                        ["_Date", *single_sort_columns],
                        ascending=[False, *([True] * len(single_sort_columns))],
                        na_position="last",
                    )

                    def single_country_row_payload(row: pd.Series) -> dict[str, str]:
                        return {
                            "country": str(row.get("country") or "N/A"),
                            "country_label": str(row.get("country_label") or row.get("country") or "N/A"),
                            "最新月份": _fmt_date(row.get("_Date")),
                            "score": _fmt_number(row.get("score"), 3),
                            "rank": _fmt_number(row.get("rank"), 0),
                            "margin": _fmt_number(row.get("margin_score"), 2),
                            "profitability": _fmt_number(row.get("profitability_score"), 2),
                            "growth": _fmt_number(row.get("growth_score"), 2),
                            "value": _fmt_number(row.get("value_score"), 2),
                            "momentum": _fmt_number(row.get("momentum_score"), 2),
                            "model": str(row.get("model_version") or ""),
                        }

                    single_country_rows = [single_country_row_payload(row) for _, row in single_latest.iterrows()]
                    single_country_history_rows = [
                        single_country_row_payload(row) for _, row in single_history.iterrows()
                    ]
        except Exception as exc:
            payload["single_country_message"] = str(exc)
    else:
        payload["single_country_message"] = "single country score parquet missing"

    payload.update(
        {
            "status": "ok",
            "latest_date": _fmt_date(latest_date),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            "rows": [row_payload(row) for _, row in latest.iterrows()],
            "history": [row_payload(row) for _, row in history.iterrows()],
            "single_country_rows": single_country_rows,
            "single_country_history": single_country_history_rows,
            "message": f"{len(latest)} latest country rows / {len(single_country_rows)} single-country rows",
        }
    )
    return payload


def _small_cap_signal_payload() -> dict[str, Any]:
    path = SMALL_CAP_SIGNAL_PATH
    payload: dict[str, Any] = {
        "name": "small_cap_model_signals",
        "title": "Europe small-cap defensive tilt",
        "status": "missing",
        "latest_date": "",
        "updated_at": "",
        "signal_path": _rel(path),
        "panel_path": _rel(SMALL_CAP_PANEL_PATH),
        "summary_path": _rel(SMALL_CAP_SUMMARY_PATH),
        "rows": [],
        "worst_rows": [],
        "factor_rows": [],
        "summary": {},
        "refresh_endpoint": "/api/dashboard/jobs/signals/small-cap",
    }
    if not path.exists():
        payload["message"] = "small-cap model signal parquet missing"
        return payload
    try:
        frame = _read_frame(path)
    except Exception as exc:
        payload.update({"status": "error", "message": str(exc)})
        return payload
    if frame is None or frame.empty or "Date" not in frame.columns:
        payload["message"] = "small-cap model signal parquet empty or missing Date"
        return payload

    data = frame.copy()
    data["_Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["_Date"])
    if data.empty:
        payload["message"] = "small-cap model signal parquet has no valid Date"
        return payload

    latest_date = data["_Date"].max()
    latest = data[data["_Date"].eq(latest_date)].copy()
    if latest.empty:
        payload["message"] = "small-cap model has no latest rows"
        return payload
    latest["_score"] = pd.to_numeric(latest["score"], errors="coerce")
    latest["_rank"] = pd.to_numeric(latest.get("rank"), errors="coerce")
    top = latest.sort_values(["_rank", "_score"], ascending=[True, False], na_position="last").head(20)
    worst = latest.sort_values(["_score", "_rank"], ascending=[True, False], na_position="last").head(20)

    factor_columns = [
        ("lowvol_score", "LowVol"),
        ("quality_score", "Quality"),
        ("value_score", "Value"),
        ("momentum_score", "Momentum"),
        ("growth_score", "Growth"),
        ("dividend_score", "Dividend"),
    ]
    factor_rows = []
    for column, label in factor_columns:
        if column not in latest.columns:
            continue
        values = pd.to_numeric(latest[column], errors="coerce")
        if not values.notna().any():
            continue
        factor_rows.append(
            {
                "factor": label,
                "avg": _fmt_number(values.mean(), 2),
                "coverage": _fmt_pct(values.notna().mean(), 1),
                "top_avg": _fmt_number(pd.to_numeric(top[column], errors="coerce").mean(), 2) if column in top.columns else "",
                "worst_avg": _fmt_number(pd.to_numeric(worst[column], errors="coerce").mean(), 2) if column in worst.columns else "",
            }
        )

    def row_payload(row: pd.Series) -> dict[str, str]:
        return {
            "Name": str(row.get("Name") or row.get("ISIN") or row.get("Company SEDOL") or "N/A"),
            "ISIN": str(row.get("ISIN") or ""),
            "SEDOL": str(row.get("Company SEDOL") or ""),
            "最新月份": _fmt_date(row.get("_Date")),
            "score": _fmt_number(row.get("score"), 2),
            "rank": _fmt_number(row.get("rank"), 0),
            "bucket": str(row.get("bucket") or row.get("raw_value") or ""),
            "LowVol": _fmt_number(row.get("lowvol_score"), 2),
            "Quality": _fmt_number(row.get("quality_score"), 2),
            "Value": _fmt_number(row.get("value_score"), 2),
            "Momentum": _fmt_number(row.get("momentum_score"), 2),
            "Growth": _fmt_number(row.get("growth_score"), 2),
            "Dividend": _fmt_number(row.get("dividend_score"), 2),
            "Weight": _fmt_pct(row.get("weight_in_benchmark"), 3),
            "Country": str(row.get("country") or ""),
            "Sector": str(row.get("sector") or ""),
        }

    summary = _read_json(SMALL_CAP_SUMMARY_PATH) or {}
    payload.update(
        {
            "status": "ok",
            "latest_date": _fmt_date(latest_date),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            "rows": [row_payload(row) for _, row in top.iterrows()],
            "worst_rows": [row_payload(row) for _, row in worst.iterrows()],
            "factor_rows": factor_rows,
            "summary": summary,
            "message": f"{len(latest)} latest Europe small-cap rows / coverage {_fmt_pct(latest['score'].notna().mean(), 1)}",
        }
    )
    return payload


def _sector_monthly_report_candidates(month: str) -> list[Path]:
    candidates: list[Path] = []
    if month:
        candidates.append(SECTOR_MONTHLY_VIEW_DIR / f"{month} TP 行业观点.md")
        candidates.append(SECTOR_QUALITATIVE_OUTPUT_DIR / f"{month}_all_ready" / "final_commentary_no_citations.md")
        candidates.append(SECTOR_QUALITATIVE_OUTPUT_DIR / f"{month}_all_ready" / "report.md")
        candidates.append(SECTOR_QUALITATIVE_OUTPUT_DIR / month / "final_commentary_no_citations.md")
        candidates.append(SECTOR_QUALITATIVE_OUTPUT_DIR / month / "report.md")
    return candidates


def _clean_sector_markdown(value: str) -> str:
    text_value = WIKILINK_RE.sub(lambda match: match.group(2) or match.group(1), value)
    return " ".join(text_value.replace("**", "").strip().split())


def _clean_brief_markdown(value: str) -> str:
    text_value = WIKILINK_RE.sub(lambda match: match.group(2) or match.group(1), value)
    return text_value.replace("**", "").strip()


def _latest_market_brief_candidates() -> list[Path]:
    if not NEWS_ROOM_DIR.exists():
        return []
    candidates = list(NEWS_ROOM_DIR.glob("Market Briefings/*欧美金融市场*.md"))
    candidates.extend(NEWS_ROOM_DIR.glob("*_Clippings/*欧美金融市场日内复盘.md"))
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)


def _okf_market_brief_path(path: Path) -> str:
    try:
        relative = path.relative_to(NEWS_ROOM_DIR)
    except ValueError:
        return ""
    bundled = NEWS_OKF_BUNDLE_DIR / relative
    return _rel(bundled) if bundled.exists() else ""


@lru_cache(maxsize=8)
def _parse_market_brief(path_text: str, mtime: float) -> dict[str, Any]:
    path = Path(path_text)
    if not path.exists():
        return {"status": "missing", "sections": []}

    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    frontmatter: dict[str, str] = {}
    body_start = 0
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                body_start = index + 1
                break
            match = FRONTMATTER_LINE_RE.match(line.strip())
            if match:
                frontmatter[match.group(1)] = match.group(2)

    title = frontmatter.get("title") or path.stem
    body_lines = lines[body_start:]
    for line in body_lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    sections: list[dict[str, str]] = []
    current: dict[str, Any] | None = None

    def finish_section() -> None:
        nonlocal current
        if not current:
            return
        text = _clean_brief_markdown("\n".join(current.pop("_lines", [])).strip())
        if text:
            sections.append({"heading": str(current["heading"]), "body": text[:2600]})
        current = None

    for line in body_lines:
        if line.startswith("## "):
            finish_section()
            current = {"heading": line[3:].strip(), "_lines": []}
            continue
        if current is None:
            continue
        if line.startswith("# "):
            continue
        current["_lines"].append(line)
    finish_section()

    for target_heading in ("对股票仓位的直接影响",):
        current_lines: list[str] = []
        collecting = False
        for line in body_lines:
            if line.startswith("### ") and line[4:].strip() == target_heading:
                collecting = True
                continue
            if collecting and (line.startswith("## ") or line.startswith("### ")):
                break
            if collecting:
                current_lines.append(line)
        text = _clean_brief_markdown("\n".join(current_lines).strip())
        if text:
            sections.append({"heading": target_heading, "body": text[:2600]})

    preferred = ("摘要", "发生了什么", "对股票仓位的直接影响", "OKF 解释框架", "股票交易框架")
    ordered_sections = [
        section
        for heading in preferred
        for section in sections
        if section["heading"] == heading
    ]
    if len(ordered_sections) < 3:
        ordered_sections = sections[:5]

    return {
        "status": "ok",
        "title": title,
        "created": frontmatter.get("created", ""),
        "source_scope": frontmatter.get("source_scope", ""),
        "okf_refresh": frontmatter.get("okf_refresh", ""),
        "path": _rel(path),
        "okf_path": _okf_market_brief_path(path),
        "updated_at": datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
        "sections": ordered_sections[:5],
        "section_count": _fmt_int(len(sections)),
    }


def _latest_market_brief_payload() -> dict[str, Any]:
    for path in _latest_market_brief_candidates():
        return _parse_market_brief(str(path), path.stat().st_mtime)
    return {
        "status": "missing",
        "title": "",
        "created": "",
        "source_scope": "",
        "okf_refresh": "",
        "path": "",
        "okf_path": "",
        "updated_at": "",
        "sections": [],
        "section_count": "0",
    }


@lru_cache(maxsize=8)
def _parse_sector_monthly_report(path_text: str, mtime: float) -> dict[tuple[str, str], dict[str, Any]]:
    path = Path(path_text)
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    blocks: dict[tuple[str, str], dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    mode = "summary"

    def finish_block() -> None:
        nonlocal current
        if not current:
            return
        summary = _clean_sector_markdown(" ".join(current.pop("_summary_lines", [])))
        evidence = [_clean_sector_markdown(item[2:]) for item in current.pop("_evidence_lines", []) if item.startswith("- ")]
        key = (str(current["market"]), str(current["sector_name"]))
        blocks[key] = {
            **current,
            "summary": summary,
            "evidence_block": evidence,
            "evidence_count": _fmt_int(len(evidence)),
            "report_path": _rel(path),
            "report_updated_at": datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
        }
        current = None

    for line in lines:
        heading = SECTOR_MONTHLY_HEADING_RE.match(line)
        if heading:
            finish_block()
            current = {
                "market": heading.group("region"),
                "sector_name": heading.group("sector"),
                "note_title": f"{heading.group('region')} {heading.group('sector')}",
                "view": heading.group("view"),
                "_summary_lines": [],
                "_evidence_lines": [],
            }
            mode = "summary"
            continue
        if current is None:
            continue
        if line.startswith("##### Evidence block"):
            mode = "evidence"
            continue
        if line.startswith("#### [["):
            finish_block()
            mode = "summary"
            continue
        if not line.strip():
            continue
        if mode == "summary":
            current["_summary_lines"].append(line.strip())
        elif line.startswith("- "):
            current["_evidence_lines"].append(line.strip())

    finish_block()
    return blocks


def _sector_monthly_analysis_payload(month: str) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, str]]:
    for path in _sector_monthly_report_candidates(month):
        if path.exists():
            parsed = _parse_sector_monthly_report(str(path), path.stat().st_mtime)
            return parsed, {
                "status": "ok" if parsed else "empty",
                "month": month,
                "path": _rel(path),
                "sectors": _fmt_int(len(parsed)),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            }
    return {}, {"status": "missing", "month": month, "path": "", "sectors": "0", "updated_at": ""}


def _sector_rotation_market_payload(
    market: str,
    path: Path,
    *,
    strength_months: int = 12,
    momentum_months: int = 3,
    trail_months: int = 12,
) -> dict[str, Any]:
    columns = [
        "next_date",
        "sector_code",
        "sector_name",
        "sector_weight",
        "sector_forward_return",
    ]
    frame = pd.read_parquet(path, columns=columns)
    if frame.empty:
        raise ValueError("empty sector panel")

    data = frame.copy()
    data["_date"] = pd.to_datetime(data["next_date"], errors="coerce")
    data["_return"] = pd.to_numeric(data["sector_forward_return"], errors="coerce")
    data["_weight"] = pd.to_numeric(data["sector_weight"], errors="coerce")
    data = data.dropna(subset=["_date", "_return", "sector_code", "sector_name"])
    data = data[data["_return"].gt(-1.0)].copy()
    if data.empty:
        raise ValueError("no valid realized sector returns")

    data["_weight"] = data["_weight"].where(data["_weight"].gt(0.0), 0.0)
    weight_total = data.groupby("_date")["_weight"].transform("sum")
    sector_count = data.groupby("_date")["_return"].transform("count")
    data["_normalized_weight"] = np.where(
        weight_total.gt(0.0),
        data["_weight"] / weight_total,
        1.0 / sector_count,
    )
    benchmark = (
        (data["_return"] * data["_normalized_weight"])
        .groupby(data["_date"])
        .sum()
        .rename("_benchmark_return")
    )
    data = data.join(benchmark, on="_date")
    data["_active_log_return"] = np.log1p(data["_return"]) - np.log1p(data["_benchmark_return"])
    data = data.sort_values(["sector_code", "_date"], kind="stable")

    min_strength_periods = max(6, strength_months // 2)
    data["_strength_raw"] = (
        data.groupby("sector_code", sort=False)["_active_log_return"]
        .rolling(strength_months, min_periods=min_strength_periods)
        .sum()
        .reset_index(level=0, drop=True)
    )
    data["_momentum_raw"] = data["_strength_raw"] - data.groupby("sector_code", sort=False)[
        "_strength_raw"
    ].shift(momentum_months)

    def normalized_coordinate(values: pd.Series) -> pd.Series:
        mean = values.mean()
        std = values.std(ddof=0)
        if pd.isna(std) or std <= 0.0:
            return pd.Series(100.0, index=values.index)
        zscore = ((values - mean) / std).clip(-2.5, 2.5)
        return 100.0 + 2.0 * zscore

    data["_relative_strength"] = data.groupby("_date", group_keys=False)["_strength_raw"].transform(
        normalized_coordinate
    )
    data["_relative_momentum"] = data.groupby("_date", group_keys=False)["_momentum_raw"].transform(
        normalized_coordinate
    )
    data = data.dropna(subset=["_relative_strength", "_relative_momentum"])
    if data.empty:
        raise ValueError("insufficient history for rotation coordinates")

    chart_dates = sorted(data["_date"].unique())[-trail_months:]
    chart = data[data["_date"].isin(chart_dates)].copy()

    def quadrant(strength: float, momentum: float) -> str:
        if strength >= 100.0 and momentum >= 100.0:
            return "Leading"
        if strength >= 100.0:
            return "Weakening"
        if momentum >= 100.0:
            return "Improving"
        return "Lagging"

    sectors: list[dict[str, Any]] = []
    for (sector_code, sector_name), sector_data in chart.groupby(
        ["sector_code", "sector_name"], sort=True
    ):
        sector_data = sector_data.sort_values("_date", kind="stable")
        points = []
        for _, row in sector_data.iterrows():
            strength = round(float(row["_relative_strength"]), 3)
            momentum = round(float(row["_relative_momentum"]), 3)
            points.append(
                {
                    "date": _fmt_date(row["_date"]),
                    "relative_strength": strength,
                    "relative_momentum": momentum,
                    "quadrant": quadrant(strength, momentum),
                }
            )
        if points:
            sectors.append(
                {
                    "sector_code": _fmt_int(sector_code),
                    "sector_name": str(sector_name),
                    "points": points,
                }
            )

    return {
        "market": market,
        "status": "ok",
        "latest_date": _fmt_date(max(chart_dates)),
        "path": _rel(path),
        "strength_months": strength_months,
        "momentum_months": momentum_months,
        "trail_months": trail_months,
        "sectors": sectors,
    }


def _sector_rotation_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "missing",
        "latest_date": "",
        "methodology": (
            "横轴：过去12个月行业相对市场收益；纵轴：该相对强度过去3个月的变化。"
            "两轴均按当月行业横截面标准化至100附近，仅使用实现日及以前数据。"
        ),
        "benchmark": "当月行业权重加权市场收益",
        "markets": [],
    }
    markets: list[dict[str, Any]] = []
    errors: list[str] = []
    latest_dates: list[pd.Timestamp] = []
    for market, path in SECTOR_SIGNAL_PATHS:
        if not path.exists():
            errors.append(f"{market}: missing")
            continue
        try:
            market_payload = _sector_rotation_market_payload(market, path)
        except Exception as exc:
            errors.append(f"{market}: {exc}")
            continue
        markets.append(market_payload)
        latest_dates.append(pd.Timestamp(market_payload["latest_date"]))

    if markets:
        payload.update(
            {
                "status": "ok",
                "latest_date": _fmt_date(max(latest_dates)),
                "markets": markets,
            }
        )
    if errors:
        payload["warning"] = "; ".join(errors)
    return payload


def _sector_signal_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "sector_recommendation",
        "title": "Sector recommendation",
        "status": "missing",
        "latest_date": "",
        "updated_at": "",
        "paths": {market: _rel(path) for market, path in SECTOR_RECOMMENDATION_PATHS},
        "monthly_report": {"status": "missing", "month": "", "path": "", "sectors": "0", "updated_at": ""},
        "rotation": _sector_rotation_payload(),
        "markets": [],
        "rows": [],
    }
    frames: list[pd.DataFrame] = []
    updated_times: list[float] = []
    errors: list[str] = []
    for market, path in SECTOR_RECOMMENDATION_PATHS:
        if not path.exists():
            errors.append(f"{market}: missing")
            continue
        try:
            frame = pd.read_csv(path, encoding="utf-8-sig")
        except Exception as exc:
            errors.append(f"{market}: {exc}")
            continue
        if frame.empty or "Date" not in frame.columns:
            errors.append(f"{market}: empty or missing Date")
            continue
        data = frame.copy()
        data["market"] = market
        data["_Date"] = pd.to_datetime(data["Date"], errors="coerce")
        data = data.dropna(subset=["_Date"])
        if data.empty:
            errors.append(f"{market}: no valid Date")
            continue
        frames.append(data)
        updated_times.append(path.stat().st_mtime)

    if not frames:
        payload["message"] = "; ".join(errors) or "sector recommendation csv missing"
        return payload

    def text(value: Any, default: str = "") -> str:
        if value is None or pd.isna(value):
            return default
        result = str(value).strip()
        return result or default

    monthly_analysis: dict[tuple[str, str], dict[str, Any]] = {}

    def row_payload(row: pd.Series) -> dict[str, Any]:
        market = text(row.get("market"), "N/A")
        sector_name = text(row.get("sector_name"), text(row.get("sector_code"), "N/A"))
        analysis = monthly_analysis.get((market, sector_name), {})
        return {
            "market": market,
            "sector_code": _fmt_int(row.get("sector_code")),
            "sector_name": sector_name,
            "最新月份": _fmt_date(row.get("_Date")),
            "rank": _fmt_number(row.get("rank"), 0),
            "recommendation": text(row.get("recommendation"), "Neutral"),
            "score": _fmt_number(row.get("score_final"), 3),
            "fs_score": _fmt_number(row.get("score_final_fs_sector"), 3),
            "factor_score": _fmt_number(row.get("fs_sector_factor_score"), 3),
            "leverage": _fmt_number(row.get("leverage"), 2),
            "margin": _fmt_number(row.get("margin"), 2),
            "valuation": _fmt_number(row.get("valuation"), 2),
            "momentum": _fmt_number(row.get("momentum"), 2),
            "growth": _fmt_number(row.get("growth"), 2),
            "lowvol": _fmt_number(row.get("lowvol"), 2),
            "sector_weight": _fmt_pct(row.get("sector_weight"), 1),
            "constituents": _fmt_int(row.get("constituents")),
            "forward_return": _fmt_pct(row.get("sector_forward_return"), 1),
            "monthly_analysis": analysis,
        }

    data = pd.concat(frames, ignore_index=True)
    markets: list[dict[str, str]] = []
    rows: list[dict[str, str]] = []
    latest_dates: list[pd.Timestamp] = []
    for market, path in SECTOR_RECOMMENDATION_PATHS:
        market_data = data[data["market"].eq(market)]
        if market_data.empty:
            continue
        latest_date = market_data["_Date"].max()
        latest_dates.append(latest_date)
        month = _fmt_date(latest_date)[:7]
        if not monthly_analysis:
            monthly_analysis, monthly_report = _sector_monthly_analysis_payload(month)
            payload["monthly_report"] = monthly_report
        latest = market_data[market_data["_Date"].eq(latest_date)].copy()
        latest["_rank_sort"] = pd.to_numeric(latest.get("rank"), errors="coerce")
        latest = latest.sort_values(["_rank_sort", "sector_name"], na_position="last")
        recommendation_counts = latest["recommendation"].fillna("N/A").astype(str).value_counts()
        markets.append(
            {
                "market": market,
                "latest_date": _fmt_date(latest_date),
                "path": _rel(path),
                "sectors": _fmt_int(len(latest)),
                "positive": _fmt_int(recommendation_counts.get("Positive", 0)),
                "neutral": _fmt_int(recommendation_counts.get("Neutral", 0)),
                "negative": _fmt_int(recommendation_counts.get("Negative", 0)),
            }
        )
        rows.extend(row_payload(row) for _, row in latest.iterrows())

    payload.update(
        {
            "status": "ok",
            "latest_date": _fmt_date(max(latest_dates)) if latest_dates else "",
            "updated_at": datetime.fromtimestamp(max(updated_times)).isoformat(timespec="seconds") if updated_times else "",
            "markets": markets,
            "rows": rows,
            "message": f"{len(rows)} latest sector rows / {len(markets)} markets",
        }
    )
    if errors:
        payload["warning"] = "; ".join(errors)
    return payload


def _backtest_context() -> BacktestDashboardContext:
    return BacktestDashboardContext(
        run_roots=(BACKTEST_OUTPUT_RUNS_DIR, HISTORICAL_RESEARCH_RUNS_DIR),
        validation_path=FULL_BACKTEST_VALIDATION_PATH,
        manifest_dir=PIPELINE_MANIFESTS_DIR,
        read_json=_read_json,
        latest_manifest=_latest_manifest,
        read_frame=_read_frame,
        relative_path=_rel,
        status_label=_status_label,
        format_int=_fmt_int,
        format_float=_fmt_float,
        format_pct=_fmt_pct,
    )


def _backtest_rows() -> list[dict[str, Any]]:
    return build_backtest_rows(_backtest_context())


def _audit_filter_options() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    steps = [{"label": "全部 step", "value": ""}]
    steps.extend({"label": step, "value": step} for step in PIPELINE_STEPS)
    statuses = [
        {"label": "全部状态", "value": ""},
        {"label": "success", "value": "success"},
        {"label": "failed", "value": "failed"},
        {"label": "running", "value": "running"},
    ]
    return steps, statuses


def _parse_filter_date(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    try:
        return pd.Timestamp(value).normalize()
    except Exception:
        return None


def _audit_rows(
    limit: int = 80,
    step: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    as_of: str | None = None,
    input_month: str | None = None,
) -> list[dict[str, Any]]:
    manifests = [
        path
        for path in PIPELINE_MANIFESTS_DIR.rglob("*.json")
        if not path.name.endswith("_latest.json")
    ]
    manifests.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    rows: list[dict[str, Any]] = []
    start = _parse_filter_date(date_from)
    end = _parse_filter_date(date_to)
    for path in manifests:
        payload = _read_json(path) or {}
        params = payload.get("parameters") or {}
        time_text = payload.get("finished_at") or payload.get("generated_at") or datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        row_step = payload.get("step") or path.parent.name
        row_status = payload.get("status", "")
        if step and row_step != step:
            continue
        if status and row_status != status:
            continue
        row_date = _parse_filter_date(time_text)
        if start is not None and row_date is not None and row_date < start:
            continue
        if end is not None and row_date is not None and row_date > end:
            continue
        if as_of and str(params.get("as_of") or "") != str(as_of):
            continue
        if input_month and str(params.get("input_month") or "") != str(input_month):
            continue
        focus_params = []
        for key in ("as_of", "input_month", "profile", "update_mode", "top_pct", "method"):
            if params.get(key) not in (None, ""):
                focus_params.append(f"{key}={params.get(key)}")
        rows.append(
            {
                "时间": time_text,
                "step": row_step,
                "状态": row_status,
                "秒数": payload.get("duration_seconds", ""),
                "参数": "; ".join(focus_params),
                "输出": _outputs_summary(payload),
                "校验": _validation_summary(payload),
                "manifest": _rel(path),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _manifest_path_from_row(row: dict[str, Any] | None) -> Path | None:
    if not row:
        return None
    manifest = row.get("manifest")
    if not manifest:
        return None
    path = Path(str(manifest))
    if not path.is_absolute():
        path = TP_ROOT / path
    try:
        resolved = path.resolve(strict=False)
        manifests_root = PIPELINE_MANIFESTS_DIR.resolve(strict=False)
        resolved.relative_to(manifests_root)
    except Exception:
        return None
    return resolved if resolved.exists() and resolved.suffix.lower() == ".json" else None


def _compact_mapping(value: Any, limit: int = 6) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    parts: list[str] = []
    for key, item in list(value.items())[:limit]:
        if isinstance(item, dict):
            status = "exists" if item.get("exists") is True else "missing" if item.get("exists") is False else ""
            bits = [str(key)]
            if item.get("path"):
                bits.append(_rel(item.get("path")))
            if item.get("rows") is not None:
                bits.append(f"{_fmt_int(item.get('rows'))} rows")
            if item.get("columns") is not None:
                bits.append(f"{_fmt_int(item.get('columns'))} cols")
            if status:
                bits.append(status)
            parts.append(" / ".join(bits))
        else:
            parts.append(f"{key}={item}")
    if len(value) > limit:
        parts.append(f"+{len(value) - limit} more")
    return "; ".join(parts)


def _compact_parameters(value: Any, limit: int = 12) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    parts = [
        f"{key}={item}"
        for key, item in list(value.items())[:limit]
        if item not in (None, "")
    ]
    if len(value) > limit:
        parts.append(f"+{len(value) - limit} more")
    return "; ".join(parts)


def _compact_validations(payload: dict[str, Any]) -> str:
    validations = payload.get("validations")
    if isinstance(validations, list):
        parts = []
        for item in validations[:8]:
            name = item.get("name", "")
            status = item.get("status", "")
            message = item.get("message", "")
            parts.append(" / ".join(bit for bit in (name, status, message) if bit))
        if len(validations) > 8:
            parts.append(f"+{len(validations) - 8} more")
        return "; ".join(parts)
    checks = payload.get("acceptance_checks")
    if isinstance(checks, dict):
        return "; ".join(f"{key}={value}" for key, value in list(checks.items())[:8])
    return ""


def _compact_child_manifests(payload: dict[str, Any]) -> str:
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    child_manifests = details.get("child_manifests")
    if not isinstance(child_manifests, list) or not child_manifests:
        return ""
    rels = [_rel(path) for path in child_manifests[:8]]
    if len(child_manifests) > 8:
        rels.append(f"+{len(child_manifests) - 8} more")
    return "; ".join(rels)


def _audit_detail_payload(row: dict[str, Any] | None) -> dict[str, str]:
    path = _manifest_path_from_row(row)
    if path is None:
        return {
            "title": "审计详情",
            "manifest": "点击审计表中的一行查看 manifest 输入、输出、校验和回滚线索。",
        }
    payload = _read_json(path) or {}
    idempotency = payload.get("idempotency") if isinstance(payload.get("idempotency"), dict) else {}
    backup_text = "; ".join(
        bit
        for bit in (
            _compact_mapping(payload.get("backups")),
            _compact_mapping(payload.get("backup")),
            _compact_mapping(payload.get("qa")),
        )
        if bit
    )
    return {
        "title": f"{payload.get('step') or path.parent.name} / {_status_label(payload.get('status'))}",
        "manifest": _rel(path),
        "time": f"{payload.get('started_at', '')} -> {payload.get('finished_at') or payload.get('generated_at', '')}".strip(" ->"),
        "parameters": _compact_parameters(payload.get("parameters")),
        "inputs": _compact_mapping(payload.get("inputs")),
        "outputs": _compact_mapping(payload.get("outputs") or payload.get("artifacts")),
        "validations": _compact_validations(payload),
        "child_manifests": _compact_child_manifests(payload),
        "rollback": backup_text or _compact_mapping(payload.get("outputs")) or "无显式 backup；按 manifest 路径追溯固定 latest 产物",
        "idempotency": "; ".join(f"{key}={value}" for key, value in idempotency.items()),
    }


def _audit_detail(row: dict[str, Any] | None = None) -> Any:
    payload = _audit_detail_payload(row)
    lines = [
        ("manifest", payload.get("manifest", "")),
        ("time", payload.get("time", "")),
        ("parameters", payload.get("parameters", "")),
        ("inputs", payload.get("inputs", "")),
        ("outputs", payload.get("outputs", "")),
        ("validations / QA", payload.get("validations", "")),
        ("child manifests", payload.get("child_manifests", "")),
        ("rollback", payload.get("rollback", "")),
        ("idempotency", payload.get("idempotency", "")),
    ]
    return html.Div(
        className="tp-audit-detail",
        children=[
            html.Div(payload.get("title", "审计详情"), className="tp-audit-detail-title"),
            *[
                html.Div(
                    [html.Span(f"{label}: ", className="tp-audit-detail-label"), value],
                    className="tp-audit-detail-line",
                )
                for label, value in lines
                if value
            ],
        ],
    )


def _status_from_bool(ok: bool | None) -> str:
    if ok is True:
        return "OK"
    if ok is False:
        return "CHECK"
    return "N/A"


def _data_quality_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    monthly_qa = _latest_json_by_glob("monthly_update*.json") or {}
    profile = _read_json(DATABASE_PROFILE_PATH) or {}
    returns_audit = _read_json(RETURNS_AUDIT_PATH) or {}
    input_inventory = _read_json(PRODUCTION_INPUTS_DIR / "manifests" / "input_inventory_latest.json") or {}
    ciq_merge = _read_json(PRODUCTION_INPUTS_DIR / "manifests" / "ciq_merge_column_check_latest.json") or {}
    ciq_content = _read_json(PRODUCTION_INPUTS_DIR / "manifests" / "ciq_content_update_check_latest.json") or {}

    base_schema = _schema_names(CORE_SCHEMA_ASSETS[0][1])
    for name, path in CORE_SCHEMA_ASSETS:
        schema = _schema_names(path)
        missing = sorted(set(base_schema) - set(schema))
        added = sorted(set(schema) - set(base_schema))
        rows.append(
            {
                "检查项": f"{name} schema",
                "状态": _status_from_bool(bool(schema) and not missing and not added),
                "范围/资产": _rel(path),
                "指标": f"{_fmt_int(len(schema))} columns",
                "异常/缺口": f"missing {len(missing)}, added {len(added)}",
                "证据": "schemas match"
                if not missing and not added
                else f"sample missing: {', '.join(missing[:3])}; sample added: {', '.join(added[:3])}",
            }
        )

    profile_screen = profile.get("screen_aggregate") or {}
    current_schema_count = len(base_schema)
    profile_columns = profile_screen.get("columns")
    rows.append(
        {
            "检查项": "database profile freshness",
            "状态": _status_from_bool(profile_columns in (None, current_schema_count)),
            "范围/资产": _rel(DATABASE_PROFILE_PATH),
            "指标": f"profile {profile_columns}, live {current_schema_count}",
            "异常/缺口": "" if profile_columns == current_schema_count else "profile/schema count mismatch",
            "证据": f"generated {profile.get('generated_at', '')}",
        }
    )

    gap_specs = [
        ("screen monthly dates", TP_ROOT / "00_screen" / "screen_aggregate.parquet", "Date", "month_end"),
        ("screen_aggregate_5Y monthly dates", TP_ROOT / "00_screen" / "screen_aggregate_5Y.parquet", "Date", "month_end"),
        ("returns business-day proxy", TP_ROOT / "00_screen" / "returns.parquet", "__index_level_0__", "business_day"),
    ]
    for label, path, column, frequency in gap_specs:
        gap = _date_gap_profile(path, column, frequency)
        missing = gap.get("missing")
        rows.append(
            {
                "检查项": label,
                "状态": _status_from_bool(missing == 0 if isinstance(missing, int) else None),
                "范围/资产": _rel(path),
                "指标": f"observed {_fmt_int(gap.get('observed'))} / expected {_fmt_int(gap.get('expected'))}",
                "异常/缺口": f"missing {_fmt_int(missing)}" if missing not in (None, "") else gap.get("error", ""),
                "证据": gap.get("sample", ""),
            }
        )

    rows.append(
        {
            "检查项": "returns anomaly audit",
            "状态": returns_audit.get("governance_status", "N/A"),
            "范围/资产": _rel(RETURNS_AUDIT_PATH),
            "指标": f"{_fmt_int(returns_audit.get('flagged_cells'))} cells / {_fmt_int(returns_audit.get('flagged_unique_sedol'))} sedols",
            "异常/缺口": ", ".join(f"{key}: {_fmt_int(value)}" for key, value in (returns_audit.get("severity_counts") or {}).items()),
            "证据": f"min {_fmt_float(returns_audit.get('min_return'), 4)}, max {_fmt_float(returns_audit.get('max_return'), 4)}",
        }
    )

    sedol = monthly_qa.get("latest_sedol_coverage") or profile.get("sedol_coverage_latest") or {}
    missing_sedol = sedol.get("missing_in_returns_count", sedol.get("missing_count"))
    rows.append(
        {
            "检查项": "latest SEDOL coverage",
            "状态": _status_from_bool(missing_sedol == 0 if missing_sedol is not None else None),
            "范围/资产": "last_screen vs returns",
            "指标": f"valid {_fmt_int(sedol.get('valid_sedol_count'))}",
            "异常/缺口": f"missing {_fmt_int(missing_sedol)}",
            "证据": ", ".join(map(str, sedol.get("missing_sample", [])[:5])) if isinstance(sedol.get("missing_sample"), list) else "",
        }
    )

    update_result = monthly_qa.get("update_result") or {}
    ciq_result = update_result.get("ciq_result") or {}
    rows.append(
        {
            "检查项": "CIQ merge coverage",
            "状态": _status_from_bool((ciq_result or ciq_merge) != {}),
            "范围/资产": _rel(update_result.get("ciq_path") or ciq_merge.get("after_path") or ciq_content.get("after_path")),
            "指标": f"matched {_fmt_int(ciq_result.get('matched_screen_rows') or ciq_merge.get('matched_screen_rows'))}; filled {_fmt_int(ciq_result.get('filled_cells_total') or ciq_merge.get('filled_cells_total') or ciq_content.get('filled_cells_total'))}",
            "异常/缺口": f"overwritten {_fmt_int(ciq_merge.get('overwritten_non_null_cells') or ciq_content.get('overwritten_non_null_cells_total'))}; cleared {_fmt_int(ciq_merge.get('cleared_non_null_cells') or ciq_content.get('cleared_non_null_cells_total'))}",
            "证据": ciq_merge.get("conclusion", "")[:260],
        }
    )

    inventory_summary = input_inventory.get("summary") or {}
    rows.append(
        {
            "检查项": "production input inventory",
            "状态": _status_from_bool((inventory_summary.get("error_records") or 0) == 0),
            "范围/资产": _rel(input_inventory.get("production_inputs_dir") or PRODUCTION_INPUTS_DIR),
            "指标": f"total {_fmt_int(inventory_summary.get('total_records'))}; eligible {_fmt_int(inventory_summary.get('eligible_records'))}",
            "异常/缺口": f"errors {_fmt_int(inventory_summary.get('error_records'))}; skipped {_fmt_int(inventory_summary.get('skipped_records'))}",
            "证据": f"run {input_inventory.get('run_id', '')} / {input_inventory.get('mode', '')}",
        }
    )

    backups = [update_result.get("backup_path"), update_result.get("returns_backup_path")]
    backup_exists = [Path(path).exists() for path in backups if path]
    rows.append(
        {
            "检查项": "monthly update backups",
            "状态": _status_from_bool(bool(backup_exists) and all(backup_exists)),
            "范围/资产": "screen + returns backups",
            "指标": f"{sum(1 for ok in backup_exists if ok)}/{len(backup_exists)} present",
            "异常/缺口": "" if backup_exists and all(backup_exists) else "backup path missing",
            "证据": "; ".join(_rel(path) for path in backups if path),
        }
    )

    weight_sums = monthly_qa.get("weight_sums") or profile_screen.get("weight_sums_latest") or {}
    for name, detail in list(weight_sums.items())[:6]:
        total = detail.get("sum") if isinstance(detail, dict) else detail
        rows.append(
            {
                "检查项": "benchmark weight sum",
                "状态": _status_from_bool(abs(float(total) - 1.0) < 0.001 if total is not None else None),
                "范围/资产": name,
                "指标": _fmt_float(total, 6),
                "异常/缺口": "",
                "证据": f"non_null {_fmt_int(detail.get('non_null'))}" if isinstance(detail, dict) else "",
            }
        )

    return rows


def _config_rows() -> list[dict[str, Any]]:
    run_all = _latest_manifest("run_all") or {}
    params = run_all.get("parameters") or {}
    saved_payload = _read_json(DASHBOARD_CONFIG_PATH) or {}
    saved_values = saved_payload.get("values") if isinstance(saved_payload.get("values"), dict) else {}
    config_items = [
        ("input_month", params.get("input_month"), "run_all_latest", "月更输入批次"),
        ("as_of", params.get("as_of"), "run_all_latest", "信号/候选/组合目标日期"),
        ("update_mode", params.get("update_mode"), "run_all_latest", "refresh_data 更新范围"),
        ("top_pct", params.get("top_pct"), "run_all_latest", "候选池入选比例"),
        ("ml_weight", params.get("ml_weight"), "run_all_latest", "候选池 ML 权重"),
        ("technical_weight", params.get("technical_weight"), "run_all_latest", "候选池技术信号权重"),
        ("optimizer_method", params.get("optimizer_method"), "run_all_latest", "组合优化方法"),
        ("max_weight", params.get("max_weight"), "run_all_latest", "单股权重上限"),
        ("backtest_profile", params.get("backtest_profile"), "run_all_latest", "回测 profile"),
        ("sector_neutral", params.get("sector_neutral"), "run_all_latest", "回测行业中性开关"),
        ("skip_refresh_data", params.get("skip_refresh_data"), "run_all_latest", "总流水线是否跳过数据刷新"),
        ("skip_backtest", params.get("skip_backtest"), "run_all_latest", "总流水线是否跳过回测"),
        ("dashboard_default_flags", "dry_run_data, skip_refresh, skip_backtest, inspect_backtest", "UI default", "控制台默认安全模式"),
        ("dashboard_config_saved_at", saved_payload.get("saved_at"), "dashboard_config", "控制台保存配置时间"),
        ("dashboard_config_path", _rel(DASHBOARD_CONFIG_PATH) if DASHBOARD_CONFIG_PATH.exists() else "", "dashboard_config", "控制台配置文件"),
        ("saved_step", saved_values.get("step"), "dashboard_config", "默认 pipeline step"),
        ("saved_input_month", saved_values.get("input_month"), "dashboard_config", "默认月更输入批次"),
        ("saved_as_of", saved_values.get("as_of"), "dashboard_config", "默认目标日期"),
        ("saved_benchmark", saved_values.get("bench"), "dashboard_config", "默认 benchmark"),
        ("saved_universe", saved_values.get("universe"), "dashboard_config", "默认 universe 标签；当前不传给 pipeline CLI"),
        ("saved_project", saved_values.get("project_id"), "dashboard_config", "默认子项目"),
        ("saved_project_mode", saved_values.get("project_mode"), "dashboard_config", "默认子项目运行模式"),
    ]
    return [
        {
            "配置项": name,
            "当前值": "N/A" if value in (None, "") else str(value),
            "来源": source,
            "影响": impact,
            "状态": "active" if value not in (None, "") else "unset",
        }
        for name, value, source, impact in config_items
    ]


def _launch_log_tail(log_path: Path, limit: int = 700) -> str:
    try:
        resolved = log_path.resolve(strict=False)
        launch_root = LAUNCH_DIR.resolve(strict=False)
        if launch_root not in (resolved, *resolved.parents):
            return ""
        if not resolved.exists() or not resolved.is_file():
            return ""
        return resolved.read_text(encoding="utf-8", errors="replace")[-limit:].strip()
    except Exception:
        return ""


def _launch_evidence(step: str) -> tuple[Path | None, dict[str, Any] | None]:
    if step in PIPELINE_STEPS:
        return PIPELINE_MANIFESTS_DIR / step / f"{step}_latest.json", _latest_manifest(step)
    if step == "system_checks":
        return CHECK_LATEST, _checks_payload()
    if step.startswith("project:"):
        parts = step.split(":", 2)
        project_id = parts[1] if len(parts) > 1 else ""
        mode = parts[2] if len(parts) > 2 else ""
        try:
            project = _project_by_id(project_id)
        except ValueError:
            return None, None
        if mode == "safe_check":
            return CHECK_LATEST, _checks_payload()
        if project.pipeline_step:
            return (
                PIPELINE_MANIFESTS_DIR / project.pipeline_step / f"{project.pipeline_step}_latest.json",
                _latest_manifest(project.pipeline_step),
            )
    return None, None


def _timestamp(value: Any) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        parsed = pd.Timestamp(value)
    except Exception:
        return None
    return None if pd.isna(parsed) else parsed


def _evidence_status(
    evidence_path: Path | None,
    payload: dict[str, Any] | None,
    started_at: str,
    running: bool,
) -> str:
    if evidence_path is None:
        return "N/A"
    if not evidence_path.exists():
        return "等待" if running else "缺失"
    status = _status_label(str(payload.get("status")) if payload else None)
    started = _timestamp(started_at)
    evidence_time = _timestamp((payload or {}).get("finished_at") or (payload or {}).get("generated_at"))
    if evidence_time is None:
        try:
            evidence_time = pd.Timestamp.fromtimestamp(evidence_path.stat().st_mtime)
        except Exception:
            evidence_time = None
    if started is not None and evidence_time is not None and evidence_time < started:
        return "等待" if running else "未更新"
    return status


def _pid_is_running(pid: Any) -> bool:
    if pid in (None, ""):
        return False
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            return str(pid) in completed.stdout
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
    except Exception:
        return False
    return True


def _latest_launch_record() -> dict[str, Any] | None:
    return system_jobs.latest_launch_record(LAUNCH_DIR)


def _launch_record_by_job_id(job_id: str) -> dict[str, Any] | None:
    return system_jobs.launch_record_by_job_id(job_id, LAUNCH_DIR)


def _job_payload_from_record(payload: dict[str, Any] | None) -> dict[str, str]:
    return job_payload_from_record(
        payload,
        context=JobViewModelContext(
            launch_dir=LAUNCH_DIR,
            relpath=_rel,
            log_tail=_launch_log_tail,
            launch_evidence=_launch_evidence,
            evidence_status=_evidence_status,
            pid_is_running=_pid_is_running,
        ),
    )

def _active_job_payload() -> dict[str, str]:
    return _job_payload_from_record(_latest_launch_record())


def _job_payload(job_id: str | None = None) -> dict[str, str] | None:
    if job_id:
        record = _launch_record_by_job_id(job_id)
        return _job_payload_from_record(record) if record else None
    return _active_job_payload()


def _job_event_stream(job_id: str, interval_seconds: float = 2.0, limit: int | None = None):
    emitted = 0
    while True:
        payload = _job_payload(job_id)
        if payload is None:
            return
        yield f"event: job\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        emitted += 1
        if (limit is not None and emitted >= limit) or payload["status"] in {"completed", "failed"}:
            return
        time.sleep(interval_seconds)


def _queue_event_stream(interval_seconds: float = 3.0, limit: int | None = None):
    emitted = 0
    while True:
        payload = system_jobs.queue_status(LAUNCH_DIR)
        yield f"event: queue\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        emitted += 1
        if limit is not None and emitted >= limit:
            return
        time.sleep(interval_seconds)


def _active_job_card() -> html.Div:
    job = _active_job_payload()
    title = f"当前任务: {job['step']} [{job['status_label']}]"
    detail = f"job_id: {job['job_id'] or 'N/A'} / PID: {job['pid'] or 'N/A'} / started: {job['started_at'] or 'N/A'}"
    evidence = f"manifest: {job['manifest_status']} / {job['manifest'] or 'N/A'}"
    log_line = f"log: {job['log_path'] or 'N/A'}"
    tail = job["log_tail"] or "暂无日志摘要"
    phases = [
        ("submitted", "已提交"),
        ("running", "运行中"),
        ("evidence", "等证据"),
        ("done", "完成"),
    ]
    active_index = next((index for index, (phase, _) in enumerate(phases) if phase == job["phase"]), 0)
    return html.Div(
        className=f"tp-job-status tp-job-status-{job['status']}",
        **{"data-job-id": job["job_id"], "data-job-status": job["status"]},
        children=[
            html.Div(title, id="tp-job-title", className="tp-job-title"),
            html.Div(detail, id="tp-job-detail", className="tp-job-line"),
            html.Div(
                className="tp-job-progress",
                children=[
                    html.Div(
                        label,
                        className="tp-job-phase tp-job-phase-active" if index <= active_index else "tp-job-phase",
                    )
                    for index, (_, label) in enumerate(phases)
                ],
            ),
            html.Div(evidence, id="tp-job-evidence", className="tp-job-line"),
            html.Div(log_line, id="tp-job-log-path", className="tp-job-line"),
            html.Pre(tail, id="tp-job-log-tail", className="tp-job-log"),
        ],
    )


def _launch_rows(limit: int = 20) -> list[dict[str, Any]]:
    if not LAUNCH_DIR.exists():
        return [
            {
                "时间": "",
                "job_id": "",
                "step": "暂无 dashboard 启动记录",
                "PID": "",
                "命令": "",
                "日志": _rel(LAUNCH_DIR),
                "日志摘要": "",
                "manifest状态": "N/A",
                "manifest/证据": "",
                "状态": "N/A",
            }
        ]
    records: list[dict[str, Any]] = []
    paths = sorted(LAUNCH_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    history_paths = [path for path in paths if path.name != "launch_latest.json"]
    if not history_paths and (LAUNCH_DIR / "launch_latest.json").exists():
        history_paths = [LAUNCH_DIR / "launch_latest.json"]
    for path in history_paths[:limit]:
        payload = _read_json(path) or {}
        started_at = payload.get("started_at", "")
        log_path = Path(payload.get("log_path", ""))
        pid = payload.get("pid")
        running = _pid_is_running(pid)
        evidence_path, evidence_payload = _launch_evidence(str(payload.get("step", "")))
        manifest_status = _evidence_status(evidence_path, evidence_payload, started_at, running)
        if running:
            row_status = "running"
        elif manifest_status == "OK":
            row_status = "completed"
        elif manifest_status == "FAIL":
            row_status = "failed"
        else:
            row_status = "evidence_waiting"
        records.append(
            {
                "时间": started_at,
                "job_id": payload.get("job_id") or path.stem,
                "step": payload.get("step", ""),
                "PID": pid or "",
                "命令": _command_text(payload.get("command"))[-360:],
                "日志": _rel(log_path),
                "日志摘要": _launch_log_tail(log_path),
                "manifest状态": manifest_status,
                "manifest/证据": _rel(evidence_path),
                "状态": row_status,
            }
        )
    return records or [
        {
            "时间": "",
            "job_id": "",
            "step": "暂无 dashboard 启动记录",
            "PID": "",
            "命令": "",
            "日志": _rel(LAUNCH_DIR),
            "日志摘要": "",
            "manifest状态": "N/A",
            "manifest/证据": "",
            "状态": "N/A",
        }
    ]


def _latest_project_launch(project_id: str) -> dict[str, Any] | None:
    if not LAUNCH_DIR.exists():
        return None
    prefix = f"project:{project_id}:"
    paths = sorted(LAUNCH_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    history_paths = [path for path in paths if path.name != "launch_latest.json"]
    if not history_paths and (LAUNCH_DIR / "launch_latest.json").exists():
        history_paths = [LAUNCH_DIR / "launch_latest.json"]
    for path in history_paths:
        payload = _read_json(path) or {}
        step = str(payload.get("step") or "")
        if not step.startswith(prefix):
            continue
        return {
            "started_at": payload.get("started_at", ""),
            "step": step,
            "pid": payload.get("pid", ""),
            "log_path": _rel(payload.get("log_path")),
        }
    return None


def _checks_payload() -> dict[str, Any] | None:
    return _read_json(CHECK_LATEST)


def _check_status_by_project() -> dict[str, dict[str, Any]]:
    payload = _checks_payload() or {}
    statuses: dict[str, dict[str, Any]] = {}
    for item in payload.get("results", []):
        if item.get("project"):
            statuses[item["project"]] = item
        if item.get("project_id"):
            statuses[item["project_id"]] = item
    return statuses


def _check_rows() -> list[dict[str, Any]]:
    payload = _checks_payload()
    generated_at = payload.get("generated_at", "") if payload else ""
    check_defs = {check.project_id: check for check in project_checks()}
    raw_results: dict[str, dict[str, Any]] = {}
    for item in (payload or {}).get("results", []):
        if item.get("project"):
            raw_results[item["project"]] = item
        if item.get("project_id"):
            raw_results[item["project_id"]] = item
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def append_result_row(item: dict[str, Any], fallback_project_id: str = "") -> None:
        outputs = []
        for output in item.get("outputs", []):
            if not output.get("exists"):
                outputs.append(f"{_rel(output.get('path'))}: missing")
                continue
            bits = [_rel(output.get("path"))]
            if output.get("rows") is not None:
                bits.append(f"{_fmt_int(output.get('rows'))} rows")
            if output.get("columns") is not None:
                bits.append(f"{_fmt_int(output.get('columns'))} cols")
            if output.get("bytes") is not None:
                bits.append(_format_bytes(output.get("bytes")))
            outputs.append(" / ".join(filter(None, bits)))
        project_id = str(item.get("project") or item.get("project_id") or fallback_project_id)
        check = check_defs.get(project_id)
        rows.append(
            {
                "项目": project_id,
                "状态": item.get("status", ""),
                "检查批次": generated_at,
                "必需": "是" if item.get("required", check.required if check else True) else "否",
                "退出码": item.get("returncode", ""),
                "输出类型": item.get("data_kind", ""),
                "秒数": item.get("duration_seconds", ""),
                "命令": _command_text(item.get("command"))[-360:],
                "输出概况": "; ".join(outputs),
                "stdout/stderr": (item.get("stdout_tail") or item.get("stderr_tail") or "").strip()[-700:],
            }
        )

    for project in PROJECT_REGISTRY:
        item = raw_results.get(project.project_id)
        if item:
            append_result_row(item, project.project_id)
            seen.add(project.project_id)
            continue
        check = check_defs.get(project.project_id)
        required = check.required if check else project.status == "active"
        rows.append(
            {
                "项目": project.project_id,
                "状态": "未检查" if check else "未定义",
                "检查批次": generated_at,
                "必需": "是" if required else "否",
                "退出码": "",
                "输出类型": check.data_kind if check else "",
                "秒数": "",
                "命令": _command_text(check.command if check else project.smoke_test)[-360:],
                "输出概况": (
                    "最近检查批次未包含该项目；点击运行全部检查刷新完整覆盖"
                    if payload and check
                    else "尚未生成检查证据；点击运行全部检查"
                    if check
                    else "system_checks.py 未登记该项目检查"
                ),
                "stdout/stderr": "",
            }
        )
        seen.add(project.project_id)

    for item in (payload or {}).get("results", []):
        project_id = str(item.get("project") or item.get("project_id") or "")
        if project_id and project_id in seen:
            continue
        append_result_row(item)
    return rows


def _project_context_payload(project_id: str | None) -> dict[str, str]:
    project = _project_by_id(project_id or PROJECT_REGISTRY[0].project_id)
    check = _check_status_by_project().get(project.project_id, {})
    manifest = _latest_manifest(project.pipeline_step) if project.pipeline_step else None
    launch = _latest_project_launch(project.project_id)
    asset_names = set(project.data_assets)
    asset_rows = [
        row
        for row in _asset_rows()
        if row.get("项目") == project.project_id and (not asset_names or row.get("数据/产物") in asset_names)
    ]
    asset_summary = "; ".join(
        " / ".join(
            item
            for item in (
                row.get("数据/产物", ""),
                row.get("状态", ""),
                row.get("日期范围", ""),
                f"{row.get('行', '')}x{row.get('列', '')}".strip("x"),
                row.get("大小", ""),
            )
            if item
        )
        for row in asset_rows[:5]
    )
    if len(asset_rows) > 5:
        asset_summary = f"{asset_summary}; +{len(asset_rows) - 5} more"

    check_status = check.get("status") or "N/A"
    check_note = check.get("data_kind") or ""
    if check.get("duration_seconds") not in (None, ""):
        check_note = f"{check_note} / {check.get('duration_seconds')}s".strip(" /")

    return {
        "title": f"{project.project_id} / {project.status}",
        "role": project.role,
        "root": _rel(project.root_path),
        "inputs": ", ".join(project.inputs) or "N/A",
        "outputs": ", ".join(project.outputs) or "N/A",
        "assets": asset_summary or ", ".join(project.data_assets) or "N/A",
        "smoke_test": project.smoke_test,
        "registered_command": project.commands[0] if project.commands else "N/A",
        "latest_check": f"{check_status} {check_note}".strip(),
        "manifest": (
            f"{_status_label(manifest.get('status'))} {manifest.get('finished_at', '')} / "
            f"{_rel(PIPELINE_MANIFESTS_DIR / project.pipeline_step / f'{project.pipeline_step}_latest.json')}"
            if manifest and project.pipeline_step
            else ("required but missing" if project.manifest_required else "not required")
        ),
        "latest_launch": (
            f"{launch.get('started_at', '')} / PID {launch.get('pid', '')} / {launch.get('log_path', '')}"
            if launch
            else "N/A"
        ),
    }


def _project_context(project_id: str | None = None) -> Any:
    try:
        payload = _project_context_payload(project_id)
    except ValueError:
        payload = _project_context_payload(PROJECT_REGISTRY[0].project_id)
    lines = [
        ("role", payload["role"]),
        ("root", payload["root"]),
        ("inputs", payload["inputs"]),
        ("outputs", payload["outputs"]),
        ("data assets", payload["assets"]),
        ("smoke test", payload["smoke_test"]),
        ("registered command", payload["registered_command"]),
        ("latest check", payload["latest_check"]),
        ("latest manifest", payload["manifest"]),
        ("latest launch", payload["latest_launch"]),
    ]
    return html.Div(
        className="tp-audit-detail",
        children=[
            html.Div(payload["title"], className="tp-audit-detail-title"),
            *[
                html.Div(
                    [html.Span(f"{label}: ", className="tp-audit-detail-label"), value],
                    className="tp-audit-detail-line",
                )
                for label, value in lines
                if value
            ],
        ],
    )


def _project_card_button_id(project_id: str, mode: str) -> dict[str, str]:
    return {"type": "tp-project-card-select", "project": project_id, "mode": mode}


def _project_card_selection(triggered_id: Any) -> tuple[str, str]:
    if not isinstance(triggered_id, dict):
        raise ValueError("未识别的项目卡操作")
    project_id = triggered_id.get("project")
    mode = triggered_id.get("mode")
    if not project_id or mode not in {"safe_check", "registered_command"}:
        raise ValueError("未识别的项目卡操作")
    _project_by_id(str(project_id))
    return str(project_id), str(mode)


def _project_has_registered_command(project: Any) -> bool:
    if not project.commands:
        return False
    try:
        _parse_registered_command(project.commands[0])
    except ValueError:
        return False
    return True


def _project_cards() -> list[Any]:
    cards: list[Any] = []
    checks = _check_status_by_project()
    for project in PROJECT_REGISTRY:
        result = checks.get(project.project_id)
        manifest = _latest_manifest(project.pipeline_step) if project.pipeline_step else None
        status = result.get("status") if result else manifest.get("status") if manifest else None
        seconds = result.get("duration_seconds") if result else None
        asset_text = project.status
        if seconds not in (None, ""):
            asset_text = f"最近检查 {seconds}s"
        command_text = project.commands[0] if project.commands else project.smoke_test
        launch = _latest_project_launch(project.project_id)
        launch_text = ""
        if launch:
            launch_text = f"最近启动: {launch['step']} / PID {launch['pid']} / {_rel(launch['log_path'])}"
        has_registered_command = _project_has_registered_command(project)
        cards.append(
            html.Div(
                className="tp-card tp-project-card",
                children=[
                    html.Div(
                        className="tp-project-top",
                        children=[
                            html.Span(project.project_id, className="tp-project-id"),
                            html.Span(
                                _status_label(status),
                                className=f"tp-status-chip {_status_class(status)}",
                            ),
                        ],
                    ),
                    html.Div(project.project_id, className="tp-project-name"),
                    html.Div(project.role, className="tp-project-role"),
                    html.Div(f"输入: {', '.join(project.inputs)}", className="tp-project-detail"),
                    html.Div(f"输出: {', '.join(project.outputs)}", className="tp-project-detail"),
                    html.Div(f"命令: {command_text}", className="tp-project-command"),
                    html.Div(asset_text, className="tp-card-note"),
                    html.Div(launch_text, className="tp-project-detail") if launch_text else None,
                    html.Div(
                        className="tp-project-actions",
                        children=[
                            html.Button(
                                "检查",
                                id=_project_card_button_id(project.project_id, "safe_check"),
                                n_clicks=0,
                                className="tp-project-action",
                                title="填入右侧子项目运行面板的安全检查模式",
                            ),
                            html.Button(
                                "登记命令",
                                id=_project_card_button_id(project.project_id, "registered_command"),
                                n_clicks=0,
                                className="tp-project-action",
                                disabled=not has_registered_command,
                                title="填入右侧子项目运行面板的登记命令模式",
                            ),
                        ],
                    ),
                ],
            )
        )
    return cards


def _project_health_card_payload(check_rows: list[dict[str, Any]] | None = None) -> tuple[str, str, str, str]:
    if check_rows is None:
        statuses = _check_status_by_project()
        status_by_project = {
            project.project_id: str((statuses.get(project.project_id) or {}).get("status") or "")
            for project in PROJECT_REGISTRY
        }
    else:
        status_by_project = {
            str(row.get("项目") or row.get("project") or row.get("project_id") or ""): str(row.get("状态") or row.get("status") or "")
            for row in check_rows
        }
    active_projects = [project for project in PROJECT_REGISTRY if project.status == "active"]
    total = len(active_projects)
    passed = 0
    pending = 0
    needs_review = 0
    for project in active_projects:
        status = status_by_project.get(project.project_id, "").lower()
        if status in {"success", "ok", "passed"}:
            passed += 1
        elif status in {"", "n/a", "na", "未检查"}:
            pending += 1
        elif status:
            needs_review += 1
    note = "; ".join(
        part
        for part in (
            f"通过 {passed}",
            f"待处理 {needs_review}" if needs_review else "",
            f"未检查 {pending}" if pending else "",
        )
        if part
    )
    css_class = "tp-status-success" if total and passed == total else "tp-status-warning"
    return ("项目健康度", f"{passed}/{total}", note, css_class)


def _latest_date_from_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "->" in text:
        text = text.split("->")[-1].strip()
    return _fmt_date(text)


def _date_timestamp(value: Any) -> pd.Timestamp | None:
    text = _latest_date_from_text(value)
    if not text:
        return None
    try:
        timestamp = pd.Timestamp(text)
    except Exception:
        return None
    if pd.isna(timestamp):
        return None
    return timestamp.normalize()


def _row_latest_date(rows: list[dict[str, Any]], key: str, label: str) -> str:
    row = next((item for item in rows if item.get(key) == label), {})
    return _latest_date_from_text(row.get("日期范围"))


def _freshness_overview_card_payload(
    production_rows: list[dict[str, Any]] | None,
    backtest_rows: list[dict[str, Any]] | None,
    assets: dict[str, dict[str, Any]],
) -> tuple[str, str, str, str]:
    production = production_rows if production_rows is not None else _production_rows()
    del backtest_rows
    backtest_manifest = _latest_manifest("run_backtest") or {}
    report_manifest = _latest_manifest("generate_report") or {}
    signal_dates = [
        _row_latest_date(production, "产物", label)
        for label in ("ml_signals", "technical_signals", "regime_risk_budget", "country_model_signals", "sector_score_model")
    ]
    signal_timestamps = [timestamp for timestamp in (_date_timestamp(item) for item in signal_dates) if timestamp is not None]
    signal_date = min(signal_timestamps).date().isoformat() if signal_timestamps else ""
    dates = {
        "数据": _latest_date_from_text(assets.get("screen_aggregate", {}).get("日期范围")),
        "信号": signal_date,
        "候选池": _row_latest_date(production, "产物", "latest_candidates"),
        "组合": _row_latest_date(production, "产物", "latest_target_weights"),
        "回测": _latest_date_from_text(backtest_manifest.get("finished_at")),
        "报告": _latest_date_from_text(report_manifest.get("finished_at")),
    }
    anchor = _date_timestamp(dates["数据"])
    stale: list[str] = []
    if anchor is None:
        stale.append("数据")
    else:
        for label, value in dates.items():
            timestamp = _date_timestamp(value)
            if timestamp is None or abs((timestamp - anchor).days) > 7:
                stale.append(label)
    value = "OK" if not stale else f"过期 {len(stale)}"
    note = " / ".join(f"{label} {date or 'N/A'}" for label, date in dates.items())
    css_class = "tp-status-success" if not stale else "tp-status-warning"
    return ("链路新鲜度", value, note, css_class)


def _latest_portfolio_card_payload(production_rows: list[dict[str, Any]] | None = None) -> tuple[str, str, str, str]:
    rows = production_rows if production_rows is not None else _production_rows()
    portfolio = next((row for row in rows if row.get("产物") == "latest_target_weights"), {})
    status = str(portfolio.get("状态") or "")
    date_range = str(portfolio.get("日期范围") or "")
    value = date_range.split(" -> ")[-1] if status == "OK" and date_range else status
    note = portfolio.get("覆盖/数量") or portfolio.get("分布") or portfolio.get("质量") or ""
    css_class = "tp-status-success" if status == "OK" else "tp-status-warning"
    return ("最新组合", value or "N/A", str(note), css_class)


def _latest_report_card_payload(backtest_rows: list[dict[str, Any]] | None = None) -> tuple[str, str, str, str]:
    rows = backtest_rows if backtest_rows is not None else _backtest_rows()
    report = next((row for row in rows if str(row.get("报告状态") or "").upper() != "N/A"), rows[0] if rows else {})
    report_status = str(report.get("报告状态") or "")
    status = str(report.get("状态") or "")
    report_status_upper = report_status.upper()
    ok = bool(report_status) and report_status_upper != "N/A" and "FAIL" not in report_status_upper
    value = "OK" if ok else report_status or status or "N/A"
    note = "; ".join(str(part) for part in (report_status if value != report_status else "", report.get("来源", ""), report.get("区间/日期", "")) if part)
    css_class = "tp-status-success" if ok else "tp-status-warning"
    return ("报告状态", value, note, css_class)


def _overview_card_payloads(
    production_rows: list[dict[str, Any]] | None = None,
    backtest_rows: list[dict[str, Any]] | None = None,
    check_rows: list[dict[str, Any]] | None = None,
) -> list[tuple[str, str, str, str]]:
    assets = {row["数据/产物"]: row for row in _asset_rows()}
    run_all = _latest_manifest("run_all")
    returns_audit = _read_json(RETURNS_AUDIT_PATH) or {}
    screen = assets.get("screen_aggregate", {})
    returns = assets.get("returns", {})
    last_screen = assets.get("last_screen", {})
    audit_status = returns_audit.get("governance_status", "unknown")
    audit_class = "tp-status-success" if audit_status == "passed" else "tp-status-warning"
    return [
        _freshness_overview_card_payload(production_rows, backtest_rows, assets),
        ("核心 Screen", last_screen.get("日期范围", "").split(" -> ")[-1], screen.get("行", ""), "tp-status-muted"),
        ("Returns 更新", returns.get("日期范围", "").split(" -> ")[-1], returns.get("行", ""), "tp-status-muted"),
        _project_health_card_payload(check_rows),
        (
            "Pipeline",
            _status_label(run_all.get("status") if run_all else None),
            run_all.get("finished_at", "") if run_all else "",
            "tp-status-success" if run_all and run_all.get("status") == "success" else "tp-status-warning",
        ),
        _latest_portfolio_card_payload(production_rows),
        _latest_report_card_payload(backtest_rows),
        (
            "Returns 审计",
            audit_status,
            f"{_fmt_int(returns_audit.get('flagged_cells'))} flagged cells",
            audit_class,
        ),
    ]


def _database_cards(
    production_rows: list[dict[str, Any]] | None = None,
    backtest_rows: list[dict[str, Any]] | None = None,
    check_rows: list[dict[str, Any]] | None = None,
) -> list[Any]:
    cards = _overview_card_payloads(production_rows, backtest_rows, check_rows)
    return [
        html.Div(
            className="tp-card",
            children=[
                html.Div(label, className="tp-card-label"),
                html.Div(value or "N/A", className=f"tp-card-value {css_class}"),
                html.Div(note or "", className="tp-card-note"),
            ],
        )
        for label, value, note, css_class in cards
    ]


def _qa_items() -> list[Any]:
    returns_audit = _read_json(RETURNS_AUDIT_PATH) or {}
    monthly_qa = _latest_json_by_glob("monthly_update*.json") or {}
    profile = _read_json(DATABASE_PROFILE_PATH) or {}
    input_inventory = _read_json(
        PRODUCTION_INPUTS_DIR / "manifests" / "input_inventory_latest.json"
    ) or {}

    items = [
        (
            "月更 QA",
            "passed" if monthly_qa.get("qa_passed") else "check",
            _rel(monthly_qa.get("_path", "")),
        ),
        (
            "输入批次",
            input_inventory.get("run_id", "N/A"),
            f"incoming: {_rel(PRODUCTION_INCOMING_DIR)}",
        ),
        (
            "数据库 profile",
            _fmt_date(profile.get("generated_at")),
            "profile mtime 与 live parquet 分开展示",
        ),
        (
            "SEDOL 覆盖",
            _fmt_int(
                (monthly_qa.get("latest_sedol_coverage") or {}).get("missing_in_returns_count")
                or (profile.get("sedol_coverage_latest") or {}).get("missing_count")
            )
            or "0",
            "missing in returns",
        ),
        (
            "Returns 异常",
            _fmt_int(returns_audit.get("flagged_cells")) or "0",
            returns_audit.get("governance_status", "unknown"),
        ),
        (
            "核心权重",
            "OK",
            "MSCI WORLD / SP500 / STOXX 600 权重和接近 1",
        ),
    ]
    return [
        html.Div(
            className="tp-qa-item",
            children=[
                html.Div(name, className="tp-qa-name"),
                html.Div(value, className="tp-qa-value"),
                html.Div(note, className="tp-qa-note"),
            ],
        )
        for name, value, note in items
    ]


def _flow_figure() -> go.Figure:
    node_index = {name: index for index, name in enumerate(FLOW_NODES)}
    source = [node_index[src] for src, _, _ in FLOW_EDGES]
    target = [node_index[dst] for _, dst, _ in FLOW_EDGES]
    value = [amount for _, _, amount in FLOW_EDGES]
    colors = [
        "#d9dde4",
        "#315d9f",
        "#187d72",
        "#5e7ea8",
        "#aa741c",
        "#6f8f84",
        "#b23a50",
        "#4f5661",
    ]
    fig = go.Figure(
        data=[
            go.Sankey(
                arrangement="snap",
                node={
                    "label": FLOW_NODES,
                    "pad": 18,
                    "thickness": 14,
                    "line": {"color": "#d8d6d4", "width": 1},
                    "color": colors,
                },
                link={
                    "source": source,
                    "target": target,
                    "value": value,
                    "color": [
                        "rgba(49,93,159,.18)",
                        "rgba(24,125,114,.18)",
                        "rgba(24,125,114,.22)",
                        "rgba(170,116,28,.18)",
                        "rgba(111,143,132,.20)",
                        "rgba(178,58,80,.17)",
                        "rgba(79,86,97,.15)",
                        "rgba(94,126,168,.14)",
                        "rgba(49,93,159,.12)",
                    ],
                },
            )
        ]
    )
    fig.update_layout(
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        height=330,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, Segoe UI, sans-serif", "size": 12, "color": "#20242a"},
    )
    return fig


def _lineage_node_from_click(click_data: dict[str, Any] | None) -> str:
    if not click_data:
        return "核心数据库"
    point = (click_data.get("points") or [{}])[0]
    label = point.get("label") or point.get("customdata")
    if label in FLOW_NODES:
        return str(label)
    for key in ("nodeIndex", "pointIndex", "pointNumber"):
        try:
            index = int(point.get(key))
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(FLOW_NODES):
            return FLOW_NODES[index]
    return "核心数据库"


def _lineage_node_payload(node_label: str = "核心数据库") -> dict[str, Any]:
    if node_label not in FLOW_NODES:
        node_label = "核心数据库"
    upstream = [src for src, dst, _ in FLOW_EDGES if dst == node_label]
    downstream = [dst for src, dst, _ in FLOW_EDGES if src == node_label]
    projects: list[dict[str, Any]] = []
    for project_id in LINEAGE_NODE_PROJECTS.get(node_label, ()):
        project = _project_by_id(project_id)
        manifest = _latest_manifest(project.pipeline_step) if project.pipeline_step else None
        command = project.commands[0] if project.commands else project.smoke_test
        projects.append(
            {
                "project_id": project.project_id,
                "role": project.role,
                "inputs": ", ".join(project.inputs),
                "outputs": ", ".join(project.outputs),
                "command": command,
                "smoke_test": project.smoke_test,
                "status": project.status,
                "manifest_step": project.pipeline_step or "",
                "manifest_status": manifest.get("status", "") if manifest else "",
                "manifest_finished_at": manifest.get("finished_at", "") if manifest else "",
                "manifest_path": _rel(PIPELINE_MANIFESTS_DIR / project.pipeline_step / f"{project.pipeline_step}_latest.json")
                if project.pipeline_step
                else "",
            }
        )
    return {
        "node": node_label,
        "upstream": ", ".join(upstream) or "无",
        "downstream": ", ".join(downstream) or "无",
        "projects": projects,
    }


def _lineage_edge_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source, target, weight in FLOW_EDGES:
        project_ids = list(
            dict.fromkeys(
                (*LINEAGE_NODE_PROJECTS.get(source, ()), *LINEAGE_NODE_PROJECTS.get(target, ()))
            )
        )
        evidence: list[dict[str, str]] = []
        registry_outputs: list[str] = []
        seen_steps: set[str] = set()
        for project_id in project_ids:
            project = _project_by_id(project_id)
            registry_outputs.extend(project.outputs)
            if not project.pipeline_step or project.pipeline_step in seen_steps:
                continue
            seen_steps.add(project.pipeline_step)
            manifest = _latest_manifest(project.pipeline_step)
            manifest_path = PIPELINE_MANIFESTS_DIR / project.pipeline_step / f"{project.pipeline_step}_latest.json"
            evidence.append(
                {
                    "step": project.pipeline_step,
                    "status": _status_label(manifest.get("status") if manifest else None),
                    "finished_at": str(manifest.get("finished_at", "")) if manifest else "",
                    "manifest": _rel(manifest_path),
                    "outputs": _outputs_summary(manifest) if manifest else "",
                }
            )
        latest = max(evidence, key=lambda item: item["finished_at"]) if evidence else {}
        statuses = {item["status"] for item in evidence if item["status"]}
        edge_status = "FAIL" if "FAIL" in statuses else "OK" if "OK" in statuses else ", ".join(sorted(statuses)) or "N/A"
        manifest_outputs = [f"{item['step']}: {item['outputs']}" for item in evidence if item["outputs"]]
        key_outputs = manifest_outputs or list(dict.fromkeys(registry_outputs))[:8]
        rows.append(
            {
                "上游": source,
                "下游": target,
                "权重": weight,
                "负责项目": ", ".join(project_ids),
                "最近状态": edge_status,
                "最近完成": latest.get("finished_at", ""),
                "manifest": latest.get("manifest", ""),
                "关键输出": "; ".join(key_outputs)[:700],
            }
        )
    return rows


def _factor_recommendation_empty_payload() -> dict[str, Any]:
    """Return the stable, cheap default contract for the research panel."""

    paths = {
        "panel": _rel(FACTOR_RECOMMENDATION_PANEL_PATH),
        "history": _rel(FACTOR_RECOMMENDATION_HISTORY_PATH),
        "manifest": _rel(FACTOR_RECOMMENDATION_MANIFEST_PATH),
        "signal": _rel(FACTOR_RECOMMENDATION_SIGNAL_PATH),
        "summary": _rel(FACTOR_RECOMMENDATION_SUMMARY_PATH),
        "validation": _rel(FACTOR_RECOMMENDATION_VALIDATION_PATH),
        "output_manifest": _rel(FACTOR_RECOMMENDATION_OUTPUT_MANIFEST_PATH),
    }
    return {
        "name": "factor_recommendation",
        "title": "Factor Recommendation",
        "status": "research_only",
        "research_only": True,
        "production_eligible": False,
        "model_status": "research_only",
        "affects_security_candidates": False,
        "affects_optimizer": False,
        "missing": True,
        "stale": True,
        "latest_date": "",
        "updated_at": "",
        "regions": list(FACTOR_RECOMMENDATION_REGIONS),
        "asia_approved": False,
        "paths": paths,
        "artifact_states": {
            "panel": "missing",
            "history": "missing",
            "signal": "missing",
            "manifest": "missing",
            "summary": "missing",
            "validation": "missing",
            "output_manifest": "missing",
        },
        "region_status": {"US": "missing", "EU": "missing", "ASIA": "unapproved"},
        "region_details": {
            "US": {"status": "missing", "production_eligible": True, "benchmark_approved": True},
            "EU": {"status": "missing", "production_eligible": True, "benchmark_approved": True},
            "ASIA": {
                "status": "unapproved",
                "production_eligible": False,
                "benchmark_approved": False,
                "approval_status": "research_only_benchmark_unapproved",
            },
        },
        "asia_definition": {
            "status": "research_only_benchmark_unapproved",
            "components": ["JAPAN", "ASIA_EX_JAPAN"],
            "aggregation_weights": {"JAPAN": 0.5, "ASIA_EX_JAPAN": 0.5},
        },
        "panel_path": paths["panel"],
        "history_path": paths["history"],
        "manifest_path": paths["manifest"],
        "signal_path": paths["signal"],
        "summary_path": paths["summary"],
        "validation_path": paths["validation"],
        "output_manifest_path": paths["output_manifest"],
        "effective_date": "",
        "data_fingerprint": {},
        "rows": [],
        "history": [],
        "evidence": [],
        "backtest": [],
        "baselines": [],
        "gates": [],
        "benchmark_definition": {},
        "warnings": ["research_only", "missing", "stale", "ASIA", "asian_unapproved"],
        "refresh_endpoint": "/api/dashboard/jobs/signals/factor-recommendation",
        "message": "factor recommendation is research-only and has no readable latest artifact",
    }


def _factor_recommendation_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _factor_recommendation_frame_rows(
    frame: pd.DataFrame | None, limit: int = 500
) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return [
        {
            str(key): _factor_recommendation_value(value)
            for key, value in record.items()
        }
        for record in frame.head(limit).to_dict(orient="records")
    ]


def _factor_recommendation_date_column(frame: pd.DataFrame | None) -> str | None:
    if frame is None:
        return None
    for column in (
        "Date",
        "date",
        "as_of",
        "as_of_date",
        "effective_date",
        "recommendation_date",
    ):
        if column in frame.columns:
            return column
    return None


def _factor_recommendation_latest_date(frame: pd.DataFrame | None) -> pd.Timestamp | None:
    column = _factor_recommendation_date_column(frame)
    if column is None:
        return None
    values = pd.to_datetime(frame[column], errors="coerce").dropna()
    return values.max().normalize() if not values.empty else None


def _factor_recommendation_region(value: Any) -> str:
    if value is None:
        text = ""
    else:
        try:
            missing = pd.isna(value)
        except (TypeError, ValueError):
            missing = False
        text = "" if isinstance(missing, (bool, np.bool_)) and bool(missing) else str(value)
        text = text.strip().upper()
    if text in FACTOR_RECOMMENDATION_REGIONS:
        return text
    if text in {"JP", "JAPAN"}:
        return "JAPAN"
    if text in {"WORLD", "GLOBAL"}:
        return "GLOBAL"
    if any(token in text for token in ("ASIA", "JAPAN", "CHINA", "HONG KONG", "INDIA")):
        return "ASIA"
    if any(token in text for token in ("EUROPE", "EU", "EMU", "UK", "UNITED KINGDOM")):
        return "EU"
    if any(token in text for token in ("US", "USA", "NORTH AMERICA", "UNITED STATES")):
        return "US"
    return text


def _factor_recommendation_has_asia(frame: pd.DataFrame | None) -> bool:
    if frame is None or frame.empty:
        return False
    for column in ("region", "Region", "market", "universe", "Exchange Country Region"):
        if column in frame.columns:
            return bool(frame[column].map(_factor_recommendation_region).eq("ASIA").any())
    return False


def _factor_recommendation_manifest() -> dict[str, Any] | None:
    payload = _read_json(FACTOR_RECOMMENDATION_MANIFEST_PATH)
    if payload is not None:
        return payload
    return _latest_manifest("refresh_factor_recommendation")


def _factor_recommendation_payload() -> dict[str, Any]:
    """Read factor artifacts through the dashboard repository boundary."""

    payload = _factor_recommendation_empty_payload()
    paths = {
        "panel": FACTOR_RECOMMENDATION_PANEL_PATH,
        "history": FACTOR_RECOMMENDATION_HISTORY_PATH,
        "signal": FACTOR_RECOMMENDATION_SIGNAL_PATH,
    }
    sidecar_paths = {
        "summary": FACTOR_RECOMMENDATION_SUMMARY_PATH,
        "validation": FACTOR_RECOMMENDATION_VALIDATION_PATH,
        "output_manifest": FACTOR_RECOMMENDATION_OUTPUT_MANIFEST_PATH,
    }
    frames: dict[str, pd.DataFrame] = {}
    artifact_states: dict[str, str] = {}
    errors: list[str] = []
    empty: list[str] = []
    updated_times: list[float] = []
    for name, path in paths.items():
        if not path.exists():
            artifact_states[name] = "missing"
            continue
        frame = _read_frame(path)
        if frame is None:
            artifact_states[name] = "corrupt"
            errors.append(f"{name}: unreadable")
            continue
        if frame.empty:
            artifact_states[name] = "empty"
            empty.append(name)
            continue
        artifact_states[name] = "ok"
        frames[name] = frame
        try:
            updated_times.append(path.stat().st_mtime)
        except OSError:
            pass

    sidecars: dict[str, dict[str, Any]] = {}
    for name, path in sidecar_paths.items():
        sidecar = _read_json(path)
        if sidecar is None:
            artifact_states[name] = "missing" if not path.exists() else "corrupt"
        else:
            artifact_states[name] = "ok"
            sidecars[name] = sidecar

    manifest = _factor_recommendation_manifest()
    direct_manifest = _read_json(FACTOR_RECOMMENDATION_MANIFEST_PATH)
    latest_manifest_path = (
        PIPELINE_MANIFESTS_DIR
        / "refresh_factor_recommendation"
        / "refresh_factor_recommendation_latest.json"
    )
    manifest_corrupt = (
        FACTOR_RECOMMENDATION_MANIFEST_PATH.exists() and direct_manifest is None
    ) or (
        not FACTOR_RECOMMENDATION_MANIFEST_PATH.exists()
        and latest_manifest_path.exists()
        and manifest is None
    )
    artifact_states["manifest"] = (
        "corrupt" if manifest_corrupt else "ok" if manifest else "missing"
    )
    payload["artifact_states"] = artifact_states
    if manifest_corrupt:
        errors.append("manifest: unreadable")
    model_manifest = sidecars.get("output_manifest") or {}
    manifest_details: dict[str, Any] = {}
    if isinstance(sidecars.get("summary"), dict):
        manifest_details.update(sidecars["summary"])
    if isinstance(manifest, dict) and isinstance(manifest.get("details"), dict):
        manifest_details.update(manifest["details"])
    if isinstance(model_manifest, dict):
        manifest_details = {**manifest_details, **model_manifest}

    if not frames:
        if errors:
            payload.update(
                {
                    "status": "error",
                    "missing": False,
                    "warnings": [
                        "research_only",
                        "corrupt",
                        "ASIA",
                        "asian_unapproved",
                    ],
                    "message": "; ".join(errors),
                }
            )
        elif empty:
            payload.update(
                {
                    "status": "missing",
                    "missing": True,
                    "warnings": [
                        "research_only",
                        "empty",
                        "stale",
                        "ASIA",
                        "asian_unapproved",
                    ],
                    "message": f"factor recommendation artifacts empty: {', '.join(empty)}",
                }
            )
        return payload

    panel = frames.get("panel")
    if panel is None:
        panel = frames.get("history")
    if panel is None:
        panel = frames.get("signal")
    history = frames.get("history")
    if history is None:
        history = frames.get("panel")
    if history is None:
        history = frames.get("signal")
    signal = frames.get("signal")
    latest_dates = [
        value
        for value in (
            _factor_recommendation_latest_date(frames.get("panel")),
            _factor_recommendation_latest_date(frames.get("history")),
            _factor_recommendation_latest_date(frames.get("signal")),
        )
        if value is not None
    ]
    latest_date = max(latest_dates) if latest_dates else None
    stale = latest_date is None or latest_date < pd.Timestamp.now().normalize() - pd.Timedelta(
        days=FACTOR_RECOMMENDATION_STALE_DAYS
    )

    asia_present = any(_factor_recommendation_has_asia(frame) for frame in frames.values())
    approved_regions = manifest_details.get("approved_regions") or manifest_details.get(
        "regions_approved"
    ) or []
    if isinstance(approved_regions, str):
        approved_regions = [approved_regions]
    asia_approved = "ASIA" in {
        _factor_recommendation_region(value) for value in approved_regions
    }
    if manifest_details.get("asia_approved") is True:
        asia_approved = True

    warnings = ["research_only"]
    if stale:
        warnings.append("stale")
    if errors:
        warnings.append("corrupt")
    if empty:
        warnings.append("empty")
    missing_artifacts = [name for name, state in artifact_states.items() if state == "missing"]
    if missing_artifacts:
        warnings.append("missing")
    if asia_present and not asia_approved:
        warnings.extend(["ASIA", "asian_unapproved"])
    elif not asia_approved:
        warnings.append("ASIA")
    warnings.extend(["benchmark_unapproved", "forward_shadow_pending", "not_promoted"])

    status = (
        "error"
        if errors
        else "stale"
        if stale
        else "missing"
        if empty or missing_artifacts
        else "research_only"
    )
    region_status = {}
    region_details: dict[str, dict[str, Any]] = {}
    for region in FACTOR_RECOMMENDATION_REGIONS:
        present = any(
            any(
                column in frame.columns
                and frame[column].map(_factor_recommendation_region).eq(region).any()
                for column in ("region", "Region", "market", "universe", "Exchange Country Region")
            )
            for frame in frames.values()
        )
        if region == "ASIA" and not asia_approved:
            region_status[region] = "unapproved"
            region_details[region] = {
                "status": "unapproved" if present else "missing_unapproved",
                "production_eligible": False,
                "benchmark_approved": False,
                "approval_status": "research_only_benchmark_unapproved",
            }
        else:
            region_status[region] = "available" if present else "missing"
            region_details[region] = {
                "status": region_status[region],
                "production_eligible": False,
                "benchmark_approved": asia_approved if region == "ASIA" else True,
                "approval_status": "approved" if region != "ASIA" else "research_only_benchmark_unapproved",
            }
    date_column = _factor_recommendation_date_column(panel)
    latest_panel = panel
    if date_column is not None and latest_date is not None:
        parsed_dates = pd.to_datetime(panel[date_column], errors="coerce").dt.normalize()
        latest_panel = panel[parsed_dates.eq(latest_date)]
    effective_date = ""
    as_of_date = ""
    if latest_panel is not None and not latest_panel.empty:
        for column, target in (("effective_date", "effective_date"), ("as_of_date", "as_of_date")):
            if column in latest_panel.columns:
                values = pd.to_datetime(latest_panel[column], errors="coerce").dropna()
                if not values.empty:
                    if target == "effective_date":
                        effective_date = values.max().date().isoformat()
                    else:
                        as_of_date = values.max().date().isoformat()
    payload.update(
        {
            "status": status,
            "model_status": str(manifest_details.get("model_status", "research_only")),
            "production_eligible": False,
            "missing": bool(empty or missing_artifacts),
            "stale": stale,
            "latest_date": latest_date.date().isoformat() if latest_date is not None else "",
            "updated_at": datetime.fromtimestamp(max(updated_times)).isoformat(
                timespec="seconds"
            )
            if updated_times
            else "",
            "asia_approved": asia_approved,
            "artifact_states": artifact_states,
            "region_status": region_status,
            "region_details": region_details,
            "warnings": list(dict.fromkeys(warnings)),
            "rows": _factor_recommendation_frame_rows(latest_panel),
            "history": _factor_recommendation_frame_rows(history),
            "signal_rows": _factor_recommendation_frame_rows(signal),
            "manifest": manifest or {},
            "evidence": manifest_details.get("evidence", []),
            "backtest": manifest_details.get("backtest", []),
            "baselines": manifest_details.get("baselines", []),
            "gates": manifest_details.get("gates", []),
            "benchmark_definition": manifest_details.get("benchmark_definition", {}),
            "asia_definition": manifest_details.get("benchmark_definition", {}).get("asia", {})
            if isinstance(manifest_details.get("benchmark_definition", {}), dict)
            else {},
            "summary_path": _rel(FACTOR_RECOMMENDATION_SUMMARY_PATH),
            "validation_path": _rel(FACTOR_RECOMMENDATION_VALIDATION_PATH),
            "output_manifest_path": _rel(FACTOR_RECOMMENDATION_OUTPUT_MANIFEST_PATH),
            "effective_date": effective_date,
            "as_of_date": as_of_date,
            "data_fingerprint": manifest_details.get("data_fingerprint", {}),
            "message": f"{len(panel)} panel rows / {len(history)} history rows",
        }
    )
    return payload


def _deferred_signal_payloads() -> dict[str, dict[str, Any]]:
    return {
        "regime": {"status": "deferred", "endpoint": "/api/dashboard/signals/regime"},
        "country": {"status": "deferred", "endpoint": "/api/dashboard/signals/country"},
        "small_cap": {
            "status": "deferred",
            "endpoint": "/api/dashboard/signals/small-cap",
        },
        "sector": {"status": "deferred", "endpoint": "/api/dashboard/signals/sector"},
        "factor_recommendation": _factor_recommendation_empty_payload(),
        "technical": {
            "status": "deferred",
            "endpoint": "/api/dashboard/signals/technical",
        },
        "score_ml_components": {
            "status": "deferred",
            "endpoint": "/api/dashboard/score-ml-components",
        },
    }


def _dashboard_state_payload(
    *,
    include_signals: bool = False,
    include_backtest: bool = False,
) -> dict[str, Any]:
    assets = _asset_rows()
    pipeline = _pipeline_rows()
    checks = _check_rows()
    core_database = _core_database_rows(assets)
    quality = _data_quality_rows()
    production = _production_rows()
    backtest = _backtest_rows() if include_backtest else []
    overview = [
        {"label": label, "value": value or "N/A", "note": note or "", "className": css_class}
        for label, value, note, css_class in _overview_card_payloads(production, backtest, checks)
    ]
    signals = _deferred_signal_payloads()
    if include_signals:
        signals = {
            "regime": _regime_signal_payload(),
            "country": _country_signal_payload(),
            "small_cap": _small_cap_signal_payload(),
            "sector": _sector_signal_payload(),
            "factor_recommendation": _factor_recommendation_payload(),
            "technical": _technical_signal_payload(),
            "score_ml_components": _score_ml_components_payload(),
        }
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": _rel(TP_ROOT),
        "manifest_dir": _rel(PIPELINE_MANIFESTS_DIR),
        "overview": overview,
        "latest_market_brief": _latest_market_brief_payload(),
        "alerts": _alert_rows(core_database, checks, pipeline, quality, production),
        "projects": _project_asset_summary_rows(assets),
        "lineage_edges": _lineage_edge_rows(),
        "checks": checks,
        "assets": assets,
        "core_database": core_database,
        "quality": quality,
        "production": production,
        "backtest": backtest,
        "signals": signals,
        "config": _config_rows(),
        "launches": _launch_rows(),
        "pipeline": pipeline,
        "queue": system_jobs.queue_status(LAUNCH_DIR),
    }


def _lineage_detail(node_label: str = "核心数据库") -> Any:
    payload = _lineage_node_payload(node_label)
    project_cards = [
        html.Div(
            className="tp-lineage-project",
            children=[
                html.Div(project["project_id"], className="tp-lineage-project-name"),
                html.Div(project["role"], className="tp-lineage-project-note"),
                html.Div(f"输入: {project['inputs']}", className="tp-lineage-project-note"),
                html.Div(f"输出: {project['outputs']}", className="tp-lineage-project-note"),
                html.Div(f"命令: {project['command']}", className="tp-lineage-project-note"),
                html.Div(
                    f"manifest: {project['manifest_status'] or 'N/A'} {project['manifest_finished_at']}".strip(),
                    className="tp-lineage-project-note",
                ),
            ],
        )
        for project in payload["projects"]
    ]
    return html.Div(
        className="tp-lineage-detail",
        children=[
            html.Div(f"节点: {payload['node']}", className="tp-lineage-title"),
            html.Div(f"上游: {payload['upstream']}", className="tp-lineage-meta"),
            html.Div(f"下游: {payload['downstream']}", className="tp-lineage-meta"),
            html.Div(project_cards, className="tp-lineage-projects"),
        ],
    )


def _command_options() -> list[dict[str, str]]:
    return [
        {"label": "总 pipeline", "value": "run_all"},
        {"label": "数据刷新", "value": "refresh_data"},
        {"label": "ML 刷新", "value": "refresh_ml"},
        {"label": "因子推荐研究刷新", "value": "refresh_factor_recommendation"},
        {"label": "信号导出", "value": "export_signals"},
        {"label": "候选池", "value": "build_candidates"},
        {"label": "组合优化", "value": "optimize_portfolio"},
        {"label": "回测", "value": "run_backtest"},
        {"label": "报告", "value": "generate_report"},
    ]


def _project_options() -> list[dict[str, str]]:
    return [
        {"label": f"{project.project_id} - {project.role}", "value": project.project_id}
        for project in PROJECT_REGISTRY
    ]


def _add_option(command: list[str], flag: str, value: Any) -> None:
    if value not in (None, ""):
        command.extend([flag, str(value)])


def _build_pipeline_command(
    step: str,
    input_month: str | None,
    as_of: str | None,
    update_mode: str,
    dry_run_data: bool,
    inspect_refresh: bool,
    skip_refresh: bool,
    skip_backtest: bool,
    skip_report: bool,
    all_history_signals: bool,
    regime_oos: bool,
    top_pct: float | None,
    ml_weight: float | None,
    technical_weight: float | None,
    by_region: bool,
    optimizer_method: str,
    max_weight: float | None,
    portfolio_region: str | None,
    backtest_profile: str | None,
    inspect_backtest: bool,
    bench: str | None,
    start_date: str | None,
    percentile: float | None,
    sector_neutral: bool,
) -> list[str]:
    command = [sys.executable, "-m", f"tp_pipelines.{step}"]
    if step == "run_all":
        _add_option(command, "--input-month", input_month)
        _add_option(command, "--as-of", as_of)
        _add_option(command, "--update-mode", update_mode)
        if dry_run_data:
            command.append("--dry-run-data")
        if inspect_refresh:
            command.append("--inspect-only-refresh-data")
        if skip_refresh:
            command.append("--skip-refresh-data")
        if skip_backtest:
            command.append("--skip-backtest")
        if skip_report:
            command.append("--skip-report")
        if all_history_signals:
            command.append("--all-history-signals")
        if regime_oos:
            command.append("--regime-oos")
        _add_option(command, "--top-pct", top_pct)
        _add_option(command, "--ml-weight", ml_weight)
        _add_option(command, "--technical-weight", technical_weight)
        if by_region:
            command.append("--by-region")
        _add_option(command, "--optimizer-method", optimizer_method)
        _add_option(command, "--max-weight", max_weight)
        _add_option(command, "--portfolio-region", portfolio_region)
        _add_option(command, "--backtest-profile", backtest_profile)
        if inspect_backtest:
            command.append("--inspect-only-backtest")
        _add_option(command, "--bench", bench)
        _add_option(command, "--start-date", start_date)
        _add_option(command, "--percentile", percentile)
        if sector_neutral:
            command.append("--sector-neutral")
        return command

    if step == "refresh_data":
        _add_option(command, "--input-month", input_month)
        _add_option(command, "--update-mode", update_mode)
        if dry_run_data:
            command.append("--dry-run")
        if inspect_refresh:
            command.append("--inspect-only")
        return command

    if step == "refresh_ml":
        if inspect_refresh:
            command.append("--inspect-only")
        return command

    if step == "refresh_factor_recommendation":
        command = _build_factor_recommendation_signal_command()
        _add_option(command, "--as-of", as_of)
        if inspect_refresh and "--inspect-only" not in command:
            command.append("--inspect-only")
        return command

    if step == "export_signals":
        _add_option(command, "--as-of", as_of)
        if all_history_signals:
            command.append("--all-history")
        if regime_oos:
            command.append("--regime-oos")
        return command

    if step == "build_candidates":
        _add_option(command, "--as-of", as_of)
        _add_option(command, "--top-pct", top_pct)
        _add_option(command, "--ml-weight", ml_weight)
        _add_option(command, "--technical-weight", technical_weight)
        if by_region:
            command.append("--by-region")
        return command

    if step == "optimize_portfolio":
        _add_option(command, "--method", optimizer_method)
        _add_option(command, "--max-weight", max_weight)
        _add_option(command, "--region", portfolio_region)
        return command

    if step == "run_backtest":
        _add_option(command, "--profile", backtest_profile)
        if inspect_backtest:
            command.append("--inspect-only")
        _add_option(command, "--bench", bench)
        _add_option(command, "--start-date", start_date)
        _add_option(command, "--percentile", percentile)
        if sector_neutral:
            command.append("--sector-neutral")
        return command

    return command


def _quote_command(command: list[str]) -> str:
    return " ".join(f'"{item}"' if " " in str(item) else str(item) for item in command)


def _project_by_id(project_id: str) -> Any:
    for project in PROJECT_REGISTRY:
        if project.project_id == project_id:
            return project
    raise ValueError(f"Unknown project_id: {project_id}")


def _parse_registered_command(command_text: str) -> list[str]:
    tokens = shlex.split(command_text)
    if not tokens or tokens[0].lower() in {"manual", "create_app()"}:
        raise ValueError("该项目没有可直接启动的登记命令")
    if tokens[0].lower() in {"python", "python.exe", "py"}:
        tokens[0] = sys.executable
    return tokens


def _build_project_command(project_id: str, mode: str) -> list[str]:
    project = _project_by_id(project_id)
    if mode == "registered_command":
        if not project.commands:
            raise ValueError("该项目没有登记命令")
        return _parse_registered_command(project.commands[0])
    return [sys.executable, "-m", "presentation_layer.cli", "system-checks", "--project", project.project_id]


def _build_system_checks_command() -> list[str]:
    return [sys.executable, "-m", "presentation_layer.cli", "system-checks"]


def _build_regime_signal_command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "tp_pipelines.refresh_regime",
        "--regime-output",
        str(REGIME_SIGNAL_PATH),
    ]


def _build_country_signal_command() -> list[str]:
    return [
        sys.executable,
        str(TP_ROOT / "14_country_model" / "src" / "country_model.py"),
        "--database-output",
        str(COUNTRY_DATABASE_PATH),
        "--signal-output",
        str(COUNTRY_SIGNAL_PATH),
    ]


def _build_small_cap_signal_command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "tp_pipelines.refresh_small_cap",
        "--signal-output",
        str(SMALL_CAP_SIGNAL_PATH),
    ]


def _build_factor_recommendation_signal_command() -> list[str]:
    """Use the registry command so the dashboard cannot invent a runner."""

    return _build_project_command(
        "16_factor_recommendation_model",
        "registered_command",
    )


def _launch(command: list[str], step: str) -> dict[str, Any]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return system_jobs.launch_job(
        command,
        step,
        LAUNCH_DIR,
        TP_ROOT,
        popen_factory=subprocess.Popen,
        creationflags=flags,
    )


def _submit_job(command: list[str], step: str) -> dict[str, Any]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return system_jobs.submit_job(
        command,
        step,
        LAUNCH_DIR,
        TP_ROOT,
        popen_factory=subprocess.Popen,
        creationflags=flags,
    )


def _client_job_api_fallback_message(action: str) -> str:
    return f"{action} 已由前端 API job 模式接管；Dash 回调未重复启动。"


def _control_panel() -> html.Div:
    config = _read_dashboard_config()
    project_ids = {project.project_id for project in PROJECT_REGISTRY}
    project_id = config.get("project_id") if config.get("project_id") in project_ids else PROJECT_REGISTRY[0].project_id
    return html.Div(
        className="tp-panel",
        children=[
            html.Div(
                className="tp-panel-head",
                children=[
                    html.H2("Pipeline 控制", className="tp-panel-title"),
                    html.Span("现有入口", className="tp-panel-meta"),
                ],
            ),
            html.Div(
                className="tp-control-grid",
                children=[
                    _field(
                        "step",
                        "运行目标",
                        dcc.Dropdown(
                            id="tp-step",
                            options=_command_options(),
                            value=config.get("step") or DEFAULT_DASHBOARD_CONFIG["step"],
                            clearable=False,
                        ),
                    ),
                    _field("input_month", "输入批次", dcc.Input(id="tp-input-month", value=config.get("input_month") or "", placeholder="YYYYMM")),
                    _field("as_of", "目标日期", dcc.Input(id="tp-as-of", value=config.get("as_of") or "", placeholder="YYYY-MM-DD")),
                    _field(
                        "update_mode",
                        "月更模式",
                        dcc.Dropdown(
                            id="tp-update-mode",
                            options=[
                                {"label": "both", "value": "both"},
                                {"label": "screen_only", "value": "screen_only"},
                                {"label": "returns_only", "value": "returns_only"},
                            ],
                            value=config.get("update_mode") or DEFAULT_DASHBOARD_CONFIG["update_mode"],
                            clearable=False,
                        ),
                    ),
                ],
            ),
            html.Div(
                className="tp-checks",
                children=[
                    dcc.Checklist(
                        id="tp-flags",
                        options=[
                            {"label": "数据 dry-run", "value": "dry_run_data"},
                            {"label": "数据 inspect-only", "value": "inspect_refresh"},
                            {"label": "跳过数据刷新", "value": "skip_refresh"},
                            {"label": "跳过回测", "value": "skip_backtest"},
                            {"label": "跳过报告", "value": "skip_report"},
                            {"label": "信号全历史", "value": "all_history_signals"},
                            {"label": "Regime OOS", "value": "regime_oos"},
                            {"label": "候选按区域", "value": "by_region"},
                            {"label": "回测 inspect-only", "value": "inspect_backtest"},
                            {"label": "行业中性回测", "value": "sector_neutral"},
                        ],
                        value=config.get("flags") or DEFAULT_DASHBOARD_CONFIG["flags"],
                    )
                ],
            ),
            html.Div(id="tp-command-preview", className="tp-command"),
            html.Div(
                className="tp-run-row",
                children=[
                    html.Button("启动", id="tp-run", n_clicks=0, className="tp-button"),
                    html.Button("保存配置", id="tp-save-config", n_clicks=0, className="tp-button tp-button-secondary"),
                    html.Div(id="tp-run-result", className="tp-run-result"),
                ],
            ),
            html.Div(id="tp-config-save-result", className="tp-run-result"),
            html.Div(id="tp-active-job", children=_active_job_card()),
            html.Div(
                className="tp-subcontrol",
                children=[
                    html.Div("子项目启动", className="tp-subcontrol-title"),
                    html.Div(
                        className="tp-control-grid",
                        children=[
                            _field(
                                "project",
                                "子项目",
                                dcc.Dropdown(
                                    id="tp-project",
                                    options=_project_options(),
                                    value=project_id,
                                    clearable=False,
                                ),
                            ),
                            _field(
                                "project-mode",
                                "运行模式",
                                dcc.Dropdown(
                                    id="tp-project-mode",
                                    options=[
                                        {"label": "安全检查", "value": "safe_check"},
                                        {"label": "登记命令", "value": "registered_command"},
                                    ],
                                    value=config.get("project_mode") or DEFAULT_DASHBOARD_CONFIG["project_mode"],
                                    clearable=False,
                                ),
                            ),
                        ],
                    ),
                    html.Div(id="tp-project-context", children=_project_context(project_id)),
                    html.Div(id="tp-project-command-preview", className="tp-command"),
                    html.Div(
                        className="tp-run-row",
                        children=[
                            html.Button("启动子项目", id="tp-project-run", n_clicks=0, className="tp-button"),
                            html.Div(id="tp-project-run-result", className="tp-run-result"),
                        ],
                    ),
                ],
            ),
            html.Details(
                className="tp-advanced",
                children=[
                    html.Summary("高级设置"),
                    html.Div(
                        className="tp-control-grid",
                        children=[
                            _field("top_pct", "候选比例", dcc.Input(id="tp-top-pct", type="number", value=config.get("top_pct"), step=0.01)),
                            _field("ml_weight", "ML 权重", dcc.Input(id="tp-ml-weight", type="number", value=config.get("ml_weight"), step=0.05)),
                            _field(
                                "technical_weight",
                                "技术权重",
                                dcc.Input(id="tp-technical-weight", type="number", value=config.get("technical_weight"), step=0.05),
                            ),
                            _field(
                                "max_weight",
                                "单股上限",
                                dcc.Input(id="tp-max-weight", type="number", value=config.get("max_weight"), step=0.01),
                            ),
                            _field(
                                "optimizer_method",
                                "优化方法",
                                dcc.Dropdown(
                                    id="tp-optimizer-method",
                                    options=[
                                        {"label": "constrained", "value": "constrained"},
                                        {"label": "score_weight", "value": "score_weight"},
                                        {"label": "equal_weight", "value": "equal_weight"},
                                    ],
                                    value=config.get("optimizer_method") or DEFAULT_DASHBOARD_CONFIG["optimizer_method"],
                                    clearable=False,
                                ),
                            ),
                            _field("portfolio_region", "组合区域", dcc.Input(id="tp-portfolio-region", value=config.get("portfolio_region") or "")),
                            _field("backtest_profile", "回测 profile", dcc.Input(id="tp-backtest-profile", value=config.get("backtest_profile") or "default")),
                            _field("bench", "Benchmark", dcc.Input(id="tp-bench", value=config.get("bench") or "")),
                            _field("universe", "Universe", dcc.Input(id="tp-universe", value=config.get("universe") or "", placeholder="记录用途，当前不传给 CLI")),
                            _field("start_date", "回测起点", dcc.Input(id="tp-start-date", value=config.get("start_date") or "", placeholder="YYYY-MM-DD")),
                            _field(
                                "percentile",
                                "选股分位",
                                dcc.Input(id="tp-percentile", type="number", value=config.get("percentile"), step=0.01),
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def _field(name: str, label: str, control: Any) -> html.Div:
    return html.Div(
        className="tp-field",
        children=[html.Label(label, htmlFor=f"tp-{name}", className="tp-label"), control],
    )


def _audit_filter_controls() -> html.Div:
    step_options, status_options = _audit_filter_options()
    return html.Div(
        className="tp-control-grid",
        children=[
            _field(
                "audit-step",
                "Step",
                dcc.Dropdown(id="tp-audit-step", options=step_options, value="", clearable=False),
            ),
            _field(
                "audit-status",
                "状态",
                dcc.Dropdown(id="tp-audit-status", options=status_options, value="", clearable=False),
            ),
            _field("audit-date-from", "开始日期", dcc.Input(id="tp-audit-date-from", value="", placeholder="YYYY-MM-DD")),
            _field("audit-date-to", "结束日期", dcc.Input(id="tp-audit-date-to", value="", placeholder="YYYY-MM-DD")),
            _field("audit-as-of", "as-of", dcc.Input(id="tp-audit-as-of", value="", placeholder="YYYY-MM-DD")),
            _field("audit-input-month", "input month", dcc.Input(id="tp-audit-input-month", value="", placeholder="YYYYMM")),
        ],
    )


def _asset_filter_controls() -> html.Div:
    project_options, source_options, status_options = _asset_filter_options()
    return html.Div(
        className="tp-control-grid",
        children=[
            _field(
                "asset-project",
                "项目",
                dcc.Dropdown(id="tp-asset-project", options=project_options, value="", clearable=False),
            ),
            _field(
                "asset-source",
                "来源",
                dcc.Dropdown(id="tp-asset-source", options=source_options, value="", clearable=False),
            ),
            _field(
                "asset-status",
                "状态",
                dcc.Dropdown(id="tp-asset-status", options=status_options, value="", clearable=False),
            ),
        ],
    )


def _data_table(table_id: str, columns: list[str], page_size: int = 10) -> dash_table.DataTable:
    return dash_table.DataTable(
        id=table_id,
        columns=[{"name": column, "id": column} for column in columns],
        data=[],
        page_size=page_size,
        sort_action="native",
        filter_action="native",
        style_as_list_view=True,
        style_table={"overflowX": "auto", "width": "100%"},
        style_header={
            "backgroundColor": "#f1f0ef",
            "borderBottom": "1px solid #d8d6d4",
            "fontWeight": "700",
            "fontSize": "12px",
            "color": "#20242a",
        },
        style_cell={
            "backgroundColor": "#ffffff",
            "border": "0",
            "borderBottom": "1px solid #e3e1df",
            "fontSize": "12px",
            "fontFamily": "Inter, Segoe UI, sans-serif",
            "padding": "8px",
            "minWidth": "88px",
            "maxWidth": "340px",
            "whiteSpace": "normal",
            "height": "auto",
            "textAlign": "left",
        },
    )


def _layout() -> html.Div:
    return html.Div(
        className="tp-dashboard",
        children=[
            dcc.Interval(id="tp-refresh", interval=30_000, n_intervals=0),
            dcc.Interval(id="tp-job-refresh", interval=2_000, n_intervals=0),
            html.Div(id="tp-job-api-state", style={"display": "none"}),
            html.Div(
                id="tp-action-feedback",
                className="tp-action-feedback",
                role="status",
                **{"aria-live": "polite"},
            ),
            html.Header(
                className="tp-header",
                children=[
                    html.Div(
                        className="tp-brand",
                        children=[
                            html.Div(className="tp-mark"),
                            html.Div(
                                children=[
                                    html.H1("TP System Dashboard", className="tp-title"),
                                    html.Div("trading pipeline / data estate / run control", className="tp-subtitle"),
                                ]
                            ),
                        ],
                    ),
                    html.Div(
                        className="tp-header-actions",
                        children=[
                            html.A("React 交互版", href="/client/", className="tp-client-link"),
                            html.Div(id="tp-header-meta", className="tp-header-meta"),
                        ],
                    ),
                ],
            ),
            html.Main(
                className="tp-main",
                children=[
                    html.Section(id="tp-stats", className="tp-grid-stats"),
                    html.Section(
                        className="tp-section tp-panel tp-table",
                        children=[
                            html.Div(
                                className="tp-panel-head",
                                children=[
                                    html.H2("异常提醒", className="tp-panel-title"),
                                    html.Span("core / checks / pipeline / quality / production", className="tp-panel-meta"),
                                ],
                            ),
                            _data_table(
                                "tp-alerts",
                                ["级别", "模块", "对象", "状态", "证据"],
                                page_size=8,
                            ),
                        ],
                    ),
                    html.Section(
                        className="tp-workbench",
                        children=[
                            html.Div(
                                className="tp-panel",
                                children=[
                                    html.Div(
                                        className="tp-panel-head",
                                        children=[
                                            html.H2("数据传输", className="tp-panel-title"),
                                            html.Span("点击节点查看 lineage", className="tp-panel-meta"),
                                        ],
                                    ),
                                    dcc.Graph(
                                        id="tp-flow",
                                        figure=_flow_figure(),
                                        config={"displayModeBar": False, "responsive": True},
                                    ),
                                    html.Div(id="tp-lineage-detail", children=_lineage_detail("核心数据库")),
                                    html.Div(
                                        className="tp-table",
                                        children=[
                                            _data_table(
                                                "tp-lineage-edges",
                                                ["上游", "下游", "权重", "负责项目", "最近状态", "最近完成", "manifest", "关键输出"],
                                            )
                                        ],
                                    ),
                                ],
                            ),
                            _control_panel(),
                        ],
                    ),
                    html.Section(
                        className="tp-section",
                        children=[
                            html.Div(
                                className="tp-panel-head",
                                children=[
                                    html.H2("子项目状态", className="tp-panel-title"),
                                    html.Span("按主线编号", className="tp-panel-meta"),
                                ],
                            ),
                            html.Div(id="tp-projects", className="tp-project-grid"),
                        ],
                    ),
                    html.Section(
                        className="tp-section tp-panel tp-table",
                        children=[
                            html.Div(
                                className="tp-panel-head",
                                children=[
                                    html.H2("项目验证", className="tp-panel-title"),
                                    html.Span("smoke / inspect / output profile", className="tp-panel-meta"),
                                ],
                            ),
                            html.Div(
                                className="tp-run-row",
                                children=[
                                    html.Button("运行全部检查", id="tp-checks-run", n_clicks=0, className="tp-button tp-button-secondary"),
                                    html.Div(id="tp-checks-run-result", className="tp-run-result"),
                                ],
                            ),
                            _data_table(
                                "tp-checks",
                                ["项目", "状态", "检查批次", "必需", "退出码", "输出类型", "秒数", "命令", "输出概况", "stdout/stderr"],
                            ),
                        ],
                    ),
                    html.Section(
                        className="tp-section tp-panel tp-table",
                        children=[
                            html.Div(
                                className="tp-panel-head",
                                children=[
                                    html.H2("核心数据库监控", className="tp-panel-title"),
                                    html.Span("screen / returns / last screen / 5Y", className="tp-panel-meta"),
                                ],
                            ),
                            _data_table(
                                "tp-core-db",
                                [
                                    "数据资产",
                                    "更新状态",
                                    "最新日期",
                                    "行",
                                    "列",
                                    "日期范围",
                                    "更新时间",
                                    "大小",
                                    "质量信号",
                                    "Schema",
                                    "Schema 证据",
                                    "路径",
                                ],
                            ),
                        ],
                    ),
                    html.Section(
                        className="tp-section tp-panel tp-table",
                        children=[
                            html.Div(
                                className="tp-panel-head",
                                children=[
                                    html.H2("数据质量监控", className="tp-panel-title"),
                                    html.Span("schema / gaps / QA / CIQ", className="tp-panel-meta"),
                                ],
                            ),
                            _data_table(
                                "tp-quality",
                                ["检查项", "状态", "范围/资产", "指标", "异常/缺口", "证据"],
                            ),
                        ],
                    ),
                    html.Section(
                        className="tp-section tp-panel tp-table",
                        children=[
                            html.Div(
                                className="tp-panel-head",
                                children=[
                                    html.H2("项目数据概况", className="tp-panel-title"),
                                    html.Span("registered / discovered / required missing", className="tp-panel-meta"),
                                ],
                            ),
                            _data_table(
                                "tp-asset-project-summary",
                                [
                                    "项目",
                                    "项目状态",
                                    "资产状态",
                                    "注册资产",
                                    "自动发现",
                                    "存在",
                                    "缺失",
                                    "必需缺失",
                                    "总大小",
                                    "最新更新时间",
                                    "关键资产",
                                ],
                            ),
                        ],
                    ),
                    html.Section(
                        className="tp-section tp-panel tp-table",
                        children=[
                            html.Div(
                                className="tp-panel-head",
                                children=[
                                    html.H2("数据资产", className="tp-panel-title"),
                                    html.Span("parquet / manifest / report", className="tp-panel-meta"),
                                ],
                            ),
                            _asset_filter_controls(),
                            _data_table(
                                "tp-assets",
                                [
                                    "项目",
                                    "数据/产物",
                                    "类型",
                                    "状态",
                                    "行",
                                    "列",
                                    "日期范围",
                                    "空值率",
                                    "重复键",
                                    "质量口径",
                                    "更新时间",
                                    "大小",
                                    "来源",
                                    "路径",
                                ],
                            ),
                        ],
                    ),
                    html.Section(
                        className="tp-section tp-panel tp-table",
                        children=[
                            html.Div(
                                className="tp-panel-head",
                                children=[
                                    html.H2("配置中心", className="tp-panel-title"),
                                    html.Span("latest parameters / safe defaults", className="tp-panel-meta"),
                                ],
                            ),
                            _data_table(
                                "tp-config",
                                ["配置项", "当前值", "来源", "影响", "状态"],
                                page_size=24,
                            ),
                        ],
                    ),
                    html.Section(
                        className="tp-section tp-panel tp-table",
                        children=[
                            html.Div(
                                className="tp-panel-head",
                                children=[
                                    html.H2("信号与组合监控", className="tp-panel-title"),
                                    html.Span("signals / candidates / target weights", className="tp-panel-meta"),
                                ],
                            ),
                            _data_table(
                                "tp-production",
                                ["产物", "状态", "日期范围", "覆盖/数量", "分布", "Top", "质量"],
                            ),
                        ],
                    ),
                    html.Section(
                        className="tp-section tp-panel tp-table",
                        children=[
                            html.Div(
                                className="tp-panel-head",
                                children=[
                                    html.H2("运行日志", className="tp-panel-title"),
                                    html.Span("dashboard-launched commands", className="tp-panel-meta"),
                                ],
                            ),
                            _data_table(
                                "tp-launches",
                                ["时间", "job_id", "step", "PID", "命令", "日志", "日志摘要", "manifest状态", "manifest/证据", "状态"],
                            ),
                        ],
                    ),
                    html.Section(
                        className="tp-section tp-panel tp-table",
                        children=[
                            html.Div(
                                className="tp-panel-head",
                                children=[
                                    html.H2("回测与报告", className="tp-panel-title"),
                                    html.Span("latest validation / summaries", className="tp-panel-meta"),
                                ],
                            ),
                            _data_table(
                                "tp-backtest",
                                ["来源", "状态", "区间/日期", "Benchmark", "组合/结果", "收益/Alpha", "TE/IR", "风险/回撤", "报告状态", "报告/路径"],
                            ),
                        ],
                    ),
                    html.Section(
                        className="tp-section tp-panel tp-table",
                        children=[
                            html.Div(
                                className="tp-panel-head",
                                children=[
                                    html.H2("审计日志", className="tp-panel-title"),
                                    html.Span("timestamped manifests", className="tp-panel-meta"),
                                ],
                            ),
                            _audit_filter_controls(),
                            _data_table(
                                "tp-audit",
                                ["时间", "step", "状态", "秒数", "参数", "输出", "校验", "manifest"],
                            ),
                            html.Div(id="tp-audit-detail", children=_audit_detail()),
                        ],
                    ),
                    html.Section(
                        className="tp-section tp-panel tp-table",
                        children=[
                            html.Div(
                                className="tp-panel-head",
                                children=[
                                    html.H2("运行证据", className="tp-panel-title"),
                                    html.Span("latest manifests", className="tp-panel-meta"),
                                ],
                            ),
                            _data_table(
                                "tp-pipeline",
                                ["步骤", "状态", "最近完成", "秒数", "未通过校验", "manifest"],
                            ),
                        ],
                    ),
                    html.Section(
                        className="tp-section tp-panel",
                        children=[
                            html.Div(
                                className="tp-panel-head",
                                children=[
                                    html.H2("核心数据库更新", className="tp-panel-title"),
                                    html.Span("QA / profile / governance", className="tp-panel-meta"),
                                ],
                            ),
                            html.Div(id="tp-qa", className="tp-qa-list"),
                        ],
                    ),
                ],
            ),
        ],
    )


def _flags(values: list[str] | None) -> set[str]:
    return set(values or [])


def _command_from_callback(
    step: str,
    input_month: str | None,
    as_of: str | None,
    update_mode: str,
    top_pct: float | None,
    ml_weight: float | None,
    technical_weight: float | None,
    max_weight: float | None,
    optimizer_method: str,
    portfolio_region: str | None,
    backtest_profile: str | None,
    bench: str | None,
    start_date: str | None,
    percentile: float | None,
    flag_values: list[str] | None,
) -> list[str]:
    flags = _flags(flag_values)
    return _build_pipeline_command(
        step=step,
        input_month=input_month,
        as_of=as_of,
        update_mode=update_mode,
        dry_run_data="dry_run_data" in flags,
        inspect_refresh="inspect_refresh" in flags,
        skip_refresh="skip_refresh" in flags,
        skip_backtest="skip_backtest" in flags,
        skip_report="skip_report" in flags,
        all_history_signals="all_history_signals" in flags,
        regime_oos="regime_oos" in flags,
        top_pct=top_pct,
        ml_weight=ml_weight,
        technical_weight=technical_weight,
        by_region="by_region" in flags,
        optimizer_method=optimizer_method,
        max_weight=max_weight,
        portfolio_region=portfolio_region,
        backtest_profile=backtest_profile,
        inspect_backtest="inspect_backtest" in flags,
        bench=bench,
        start_date=start_date,
        percentile=percentile,
        sector_neutral="sector_neutral" in flags,
    )


def _register_clientside_callbacks(app: Dash) -> None:
    app.clientside_callback(
        """
        function(runClicks, saveClicks, projectRunClicks, checksClicks, projectCardClicks, projectId, projectMode, step) {
            const callbackContext = dash_clientside.callback_context;
            if (!callbackContext.triggered.length) {
                return [dash_clientside.no_update, dash_clientside.no_update];
            }
            const triggered = callbackContext.triggered_id;
            const timeText = new Date().toLocaleTimeString("zh-CN", { hour12: false });
            let title = "";
            let note = "";
            if (triggered === "tp-run") {
                if (!runClicks) {
                    return [dash_clientside.no_update, dash_clientside.no_update];
                }
                title = "已提交 pipeline 启动请求";
                note = (step || "pipeline") + " 正在交给后端启动；运行证据会在刷新后更新。";
            } else if (triggered === "tp-save-config") {
                if (!saveClicks) {
                    return [dash_clientside.no_update, dash_clientside.no_update];
                }
                title = "配置保存请求已收到";
                note = "保存结果会显示在控制面板下方。";
            } else if (triggered === "tp-project-run") {
                if (!projectRunClicks) {
                    return [dash_clientside.no_update, dash_clientside.no_update];
                }
                title = "已提交子项目启动请求";
                note = (projectId || "子项目") + " / " + (projectMode || "safe_check") + " 正在交给后端启动。";
            } else if (triggered === "tp-checks-run") {
                if (!checksClicks) {
                    return [dash_clientside.no_update, dash_clientside.no_update];
                }
                title = "已提交全部项目检查";
                note = "检查会在后台运行，项目验证表稍后刷新。";
            } else if (triggered && typeof triggered === "object" && triggered.type === "tp-project-card-select") {
                title = "已选择子项目";
                note = triggered.project + " / " + (triggered.mode === "registered_command" ? "登记命令" : "安全检查") + " 已填入右侧运行面板。";
            } else {
                return [dash_clientside.no_update, dash_clientside.no_update];
            }
            return [
                "tp-action-feedback tp-action-feedback-active",
                timeText + "  " + title + "\\n" + note
            ];
        }
        """,
        Output("tp-action-feedback", "className"),
        Output("tp-action-feedback", "children"),
        Input("tp-run", "n_clicks"),
        Input("tp-save-config", "n_clicks"),
        Input("tp-project-run", "n_clicks"),
        Input("tp-checks-run", "n_clicks"),
        Input({"type": "tp-project-card-select", "project": ALL, "mode": ALL}, "n_clicks"),
        State("tp-project", "value"),
        State("tp-project-mode", "value"),
        State("tp-step", "value"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(
            step,
            inputMonth,
            asOf,
            updateMode,
            topPct,
            mlWeight,
            technicalWeight,
            maxWeight,
            optimizerMethod,
            portfolioRegion,
            backtestProfile,
            bench,
            startDate,
            percentile,
            flags,
            projectId,
            projectMode
        ) {
            return JSON.stringify({
                step: step,
                input_month: inputMonth || "",
                as_of: asOf || "",
                update_mode: updateMode,
                top_pct: topPct,
                ml_weight: mlWeight,
                technical_weight: technicalWeight,
                max_weight: maxWeight,
                optimizer_method: optimizerMethod,
                portfolio_region: portfolioRegion || "",
                backtest_profile: backtestProfile || "",
                bench: bench || "",
                start_date: startDate || "",
                percentile: percentile,
                flags: flags || [],
                project_id: projectId,
                project_mode: projectMode
            });
        }
        """,
        Output("tp-job-api-state", "children"),
        Input("tp-step", "value"),
        Input("tp-input-month", "value"),
        Input("tp-as-of", "value"),
        Input("tp-update-mode", "value"),
        Input("tp-top-pct", "value"),
        Input("tp-ml-weight", "value"),
        Input("tp-technical-weight", "value"),
        Input("tp-max-weight", "value"),
        Input("tp-optimizer-method", "value"),
        Input("tp-portfolio-region", "value"),
        Input("tp-backtest-profile", "value"),
        Input("tp-bench", "value"),
        Input("tp-start-date", "value"),
        Input("tp-percentile", "value"),
        Input("tp-flags", "value"),
        Input("tp-project", "value"),
        Input("tp-project-mode", "value"),
    )



def _register_monitoring_callbacks(app: Dash) -> None:
    @app.callback(Output("tp-lineage-detail", "children"), Input("tp-flow", "clickData"))
    def update_lineage_detail(click_data: dict[str, Any] | None):
        return _lineage_detail(_lineage_node_from_click(click_data))

    @app.callback(
        Output("tp-header-meta", "children"),
        Output("tp-stats", "children"),
        Output("tp-alerts", "data"),
        Output("tp-projects", "children"),
        Output("tp-lineage-edges", "data"),
        Output("tp-checks", "data"),
        Output("tp-asset-project-summary", "data"),
        Output("tp-assets", "data"),
        Output("tp-core-db", "data"),
        Output("tp-quality", "data"),
        Output("tp-production", "data"),
        Output("tp-backtest", "data"),
        Output("tp-config", "data"),
        Output("tp-launches", "data"),
        Output("tp-pipeline", "data"),
        Output("tp-qa", "children"),
        Input("tp-refresh", "n_intervals"),
        Input("tp-asset-project", "value"),
        Input("tp-asset-source", "value"),
        Input("tp-asset-status", "value"),
    )
    def refresh_status(_: int, asset_project: str | None, asset_source: str | None, asset_status: str | None):
        now = datetime.now().isoformat(timespec="seconds")
        assets = _asset_rows()
        pipeline = _pipeline_rows()
        checks = _check_rows()
        core_database = _core_database_rows(assets)
        quality = _data_quality_rows()
        production = _production_rows()
        backtest = _backtest_rows()
        meta = [
            html.Span(f"root: {_rel(TP_ROOT)}", className="tp-pill"),
            html.Span(f"refresh: {now}", className="tp-pill"),
            html.Span(f"manifests: {_rel(PIPELINE_MANIFESTS_DIR)}", className="tp-pill"),
        ]
        return (
            meta,
            _database_cards(production, backtest, checks),
            _alert_rows(core_database, checks, pipeline, quality, production),
            _project_cards(),
            _lineage_edge_rows(),
            checks,
            _project_asset_summary_rows(assets),
            _filter_asset_rows(assets, asset_project, asset_source, asset_status),
            core_database,
            quality,
            production,
            backtest,
            _config_rows(),
            _launch_rows(),
            pipeline,
            _qa_items(),
        )

    @app.callback(
        Output("tp-audit", "data"),
        Input("tp-refresh", "n_intervals"),
        Input("tp-audit-step", "value"),
        Input("tp-audit-status", "value"),
        Input("tp-audit-date-from", "value"),
        Input("tp-audit-date-to", "value"),
        Input("tp-audit-as-of", "value"),
        Input("tp-audit-input-month", "value"),
    )
    def refresh_audit(
        _: int,
        step: str | None,
        status: str | None,
        date_from: str | None,
        date_to: str | None,
        as_of: str | None,
        input_month: str | None,
    ):
        return _audit_rows(
            step=step,
            status=status,
            date_from=date_from,
            date_to=date_to,
            as_of=as_of,
            input_month=input_month,
        )

    @app.callback(
        Output("tp-audit-detail", "children"),
        Input("tp-audit", "active_cell"),
        State("tp-audit", "data"),
    )
    def update_audit_detail(active_cell: dict[str, Any] | None, rows: list[dict[str, Any]] | None):
        if not active_cell or not rows:
            return _audit_detail()
        row_index = active_cell.get("row")
        if not isinstance(row_index, int) or row_index < 0 or row_index >= len(rows):
            return _audit_detail()
        return _audit_detail(rows[row_index])

    @app.callback(
        Output("tp-active-job", "children"),
        Input("tp-job-refresh", "n_intervals"),
        Input("tp-run-result", "children"),
        Input("tp-project-run-result", "children"),
        Input("tp-checks-run-result", "children"),
    )
    def refresh_active_job(_: int, __: Any, ___: Any, ____: Any):
        return _active_job_card()



def _register_launch_callbacks(app: Dash) -> None:
    callback_inputs = [
        Input("tp-step", "value"),
        Input("tp-input-month", "value"),
        Input("tp-as-of", "value"),
        Input("tp-update-mode", "value"),
        Input("tp-top-pct", "value"),
        Input("tp-ml-weight", "value"),
        Input("tp-technical-weight", "value"),
        Input("tp-max-weight", "value"),
        Input("tp-optimizer-method", "value"),
        Input("tp-portfolio-region", "value"),
        Input("tp-backtest-profile", "value"),
        Input("tp-bench", "value"),
        Input("tp-start-date", "value"),
        Input("tp-percentile", "value"),
        Input("tp-flags", "value"),
    ]

    @app.callback(Output("tp-command-preview", "children"), callback_inputs)
    def preview_command(*values):
        command = _command_from_callback(*values)
        return _quote_command(command)

    @app.callback(
        Output("tp-checks-run-result", "children"),
        Input("tp-checks-run", "n_clicks"),
        prevent_initial_call=True,
    )
    def run_system_checks(n_clicks: int):
        if not n_clicks:
            return ""
        if CLIENT_JOB_API_ENABLED:
            return _client_job_api_fallback_message("全部项目检查")
        record = _launch(_build_system_checks_command(), "system_checks")
        return [
            html.Div(f"已提交全部项目检查，job_id {record['job_id']}"),
            html.Div(f"PID {record['pid']}"),
            html.Div(_rel(record["log_path"])),
        ]

    @app.callback(
        Output("tp-run-result", "children"),
        Input("tp-run", "n_clicks"),
        [
            State("tp-step", "value"),
            State("tp-input-month", "value"),
            State("tp-as-of", "value"),
            State("tp-update-mode", "value"),
            State("tp-top-pct", "value"),
            State("tp-ml-weight", "value"),
            State("tp-technical-weight", "value"),
            State("tp-max-weight", "value"),
            State("tp-optimizer-method", "value"),
            State("tp-portfolio-region", "value"),
            State("tp-backtest-profile", "value"),
            State("tp-bench", "value"),
            State("tp-start-date", "value"),
            State("tp-percentile", "value"),
            State("tp-flags", "value"),
        ],
        prevent_initial_call=True,
    )
    def run_pipeline(n_clicks: int, *values):
        if not n_clicks:
            return ""
        if CLIENT_JOB_API_ENABLED:
            return _client_job_api_fallback_message("pipeline 启动")
        step = values[0]
        command = _command_from_callback(*values)
        record = _launch(command, step)
        return [
            html.Div(f"已提交 {record['step']}，job_id {record['job_id']}"),
            html.Div(f"PID {record['pid']}"),
            html.Div(_rel(record["log_path"])),
        ]



def _register_config_project_callbacks(app: Dash) -> None:
    @app.callback(
        Output("tp-config-save-result", "children"),
        Input("tp-save-config", "n_clicks"),
        [
            State("tp-step", "value"),
            State("tp-input-month", "value"),
            State("tp-as-of", "value"),
            State("tp-update-mode", "value"),
            State("tp-top-pct", "value"),
            State("tp-ml-weight", "value"),
            State("tp-technical-weight", "value"),
            State("tp-max-weight", "value"),
            State("tp-optimizer-method", "value"),
            State("tp-portfolio-region", "value"),
            State("tp-backtest-profile", "value"),
            State("tp-bench", "value"),
            State("tp-universe", "value"),
            State("tp-start-date", "value"),
            State("tp-percentile", "value"),
            State("tp-flags", "value"),
            State("tp-project", "value"),
            State("tp-project-mode", "value"),
        ],
        prevent_initial_call=True,
    )
    def save_config(
        n_clicks: int,
        step: str,
        input_month: str | None,
        as_of: str | None,
        update_mode: str,
        top_pct: float | None,
        ml_weight: float | None,
        technical_weight: float | None,
        max_weight: float | None,
        optimizer_method: str,
        portfolio_region: str | None,
        backtest_profile: str | None,
        bench: str | None,
        universe: str | None,
        start_date: str | None,
        percentile: float | None,
        flags: list[str] | None,
        project_id: str,
        project_mode: str,
    ):
        if not n_clicks:
            return ""
        payload = _write_dashboard_config(
            {
                "step": step,
                "input_month": input_month or "",
                "as_of": as_of or "",
                "update_mode": update_mode,
                "top_pct": top_pct,
                "ml_weight": ml_weight,
                "technical_weight": technical_weight,
                "max_weight": max_weight,
                "optimizer_method": optimizer_method,
                "portfolio_region": portfolio_region or "",
                "backtest_profile": backtest_profile or "",
                "bench": bench or "",
                "universe": universe or "",
                "start_date": start_date or "",
                "percentile": percentile,
                "flags": flags or [],
                "project_id": project_id,
                "project_mode": project_mode,
            }
        )
        return f"已保存配置 {payload['saved_at']} -> {_rel(DASHBOARD_CONFIG_PATH)}"

    @app.callback(
        Output("tp-project-command-preview", "children"),
        Input("tp-project", "value"),
        Input("tp-project-mode", "value"),
    )
    def preview_project_command(project_id: str, mode: str):
        try:
            return _quote_command(_build_project_command(project_id, mode))
        except ValueError as exc:
            return str(exc)

    @app.callback(
        Output("tp-project-context", "children"),
        Input("tp-project", "value"),
    )
    def update_project_context(project_id: str):
        return _project_context(project_id)

    @app.callback(
        Output("tp-project", "value"),
        Output("tp-project-mode", "value"),
        Input({"type": "tp-project-card-select", "project": ALL, "mode": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def select_project_from_card(_: list[int | None]):
        try:
            return _project_card_selection(ctx.triggered_id)
        except ValueError as exc:
            raise PreventUpdate from exc

    @app.callback(
        Output("tp-project-run-result", "children"),
        Input("tp-project-run", "n_clicks"),
        State("tp-project", "value"),
        State("tp-project-mode", "value"),
        prevent_initial_call=True,
    )
    def run_project(n_clicks: int, project_id: str, mode: str):
        if not n_clicks:
            return ""
        if CLIENT_JOB_API_ENABLED:
            return _client_job_api_fallback_message("子项目启动")
        try:
            command = _build_project_command(project_id, mode)
        except ValueError as exc:
            return str(exc)
        record = _launch(command, f"project:{project_id}:{mode}")
        return [
            html.Div(f"已提交 {project_id}，job_id {record['job_id']}"),
            html.Div(f"PID {record['pid']}"),
            html.Div(_rel(record["log_path"])),
        ]

def _dashboard_domain_service() -> DashboardDomainService:
    """Bind domain providers once per app so tests and deployments can override paths."""

    return DashboardDomainService(
        defaults=DEFAULT_DASHBOARD_CONFIG,
        state_provider=_dashboard_state_payload,
        backtest_provider=_backtest_rows,
        latest_job_provider=_active_job_payload,
        queue_provider=lambda: system_jobs.queue_status(LAUNCH_DIR),
        regime_provider=_regime_signal_payload,
        country_provider=_country_signal_payload,
        small_cap_provider=_small_cap_signal_payload,
        sector_provider=_sector_signal_payload,
        technical_provider=_technical_signal_payload,
        factor_recommendation_provider=_factor_recommendation_payload,
        score_ml_provider=_score_ml_components_payload,
        company_provider=_company_detail_payload,
        job_provider=_job_payload,
        queue_event_provider=_queue_event_stream,
        job_event_provider=_job_event_stream,
        submit_job=_submit_job,
        job_view_model=_job_payload_from_record,
        system_checks_command=_build_system_checks_command,
        regime_command=_build_regime_signal_command,
        country_command=_build_country_signal_command,
        small_cap_command=_build_small_cap_signal_command,
        factor_recommendation_command=_build_factor_recommendation_signal_command,
        project_command=_build_project_command,
        pipeline_command=_command_from_callback,
    )


def create_app() -> Dash:
    app = Dash(
        __name__,
        title="TP System Dashboard",
        update_title=None,
        suppress_callback_exceptions=True,
        routes_pathname_prefix="/dash/",
        requests_pathname_prefix="/dash/",
    )
    app.server.json.ensure_ascii = False
    app.index_string = f"""<!DOCTYPE html>
<html>
    <head>
        {{%metas%}}
        <title>{{%title%}}</title>
        {{%favicon%}}
        {{%css%}}
        <style>{STYLE}</style>
    </head>
    <body>
        {{%app_entry%}}
        <footer>
            {{%config%}}
            {{%scripts%}}
            {{%renderer%}}
            <script>{TP_JOB_EVENT_SCRIPT}</script>
        </footer>
    </body>
</html>"""
    app.layout = _layout()
    server = app.server

    register_dashboard_routes(
        server,
        domain=_dashboard_domain_service(),
        assets=DashboardStaticAssets(
            client_dist_dir=CLIENT_DIST_DIR,
            client_assets_dir=CLIENT_ASSETS_DIR,
            factor_explorer_path=FACTOR_EXPLORER_PATH,
            factor_research_app_path=FACTOR_RESEARCH_APP_PATH,
        ),
    )
    _register_clientside_callbacks(app)
    _register_monitoring_callbacks(app)
    _register_launch_callbacks(app)
    _register_config_project_callbacks(app)
    return app


def run(host: str = "127.0.0.1", port: int = PORT, debug: bool = False) -> None:
    app = create_app()
    app.run(host=host, port=port, debug=debug)


__all__ = ["PORT", "create_app", "run"]

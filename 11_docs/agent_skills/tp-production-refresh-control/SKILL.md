---
name: tp-production-refresh-control
description: Use this skill for TP production refreshes, pipeline jobs, manifests, control-tower coverage audits, project health checks, docs alignment, and production artifact validation, including refresh_data, export_signals, run_all, regime refreshes, country-model refreshes, supplemental Score ML/Score ML_IF joins, dashboard launch actions, dry-run flags, targeted system-checks, and freshness checks in C:\GoogleDrive\TP.
---

# TP Production Refresh Control

## Scope

Use this skill when the task is production execution or production artifact maintenance. Do not broaden a refresh into research, model redesign, or dashboard UX work unless the user explicitly asks.

Key files:
- `src/tp_pipelines/run_all.py`
- `src/tp_pipelines/refresh_data.py`
- `src/tp_pipelines/refresh_regime.py`
- `src/tp_pipelines/export_signals.py`
- `00_screen/screen_aggregate.parquet`
- `00_screen/last_screen.parquet`
- `00_screen/screen_aggregate_5Y.parquet`
- `03_regime_model/output/`
- `03_regime_model/webapp/data.js`
- `artifacts/signals/`
- `artifacts/pipeline_runs/manifests/`
- `src/tp_models/country.py`
- `08_presentation_layer/apps/system_registry.py`
- `08_presentation_layer/apps/system_checks.py`
- `11_docs/INVESTMENT_PLATFORM_MAINLINE.md`

## Workflow

1. Identify whether the request is a full pipeline run, targeted refresh, signal export, production data join, model artifact refresh, or freshness audit.
2. Inspect existing entrypoints and flags before adding new arguments.
3. Prefer existing pipeline commands over new runners.
4. Use dry-run or targeted flags when validating one segment.
5. Write manifests under the existing `artifacts/pipeline_runs/manifests/<step>/` pattern.
6. Archive or clean consumed incoming production data after a successful run unless the user asks to keep it.
7. Never reset or clean unrelated dirty outputs.

## Common Branches

### Standard Pipeline

Use the installed `tp_pipelines` entrypoints. Do not bootstrap imports with `sitecustomize.py` or path injection.

### Regime Refresh

Use when the user wants latest regime detector outputs or webapp data:

```powershell
.\.venv_tp\Scripts\python.exe -m tp_pipelines.refresh_regime
.\.venv_tp\Scripts\python.exe -m tp_pipelines.run_all --refresh-regime --regime-oos
```

Verify `artifacts/signals/regime_risk_budget.parquet`, `03_regime_model/output/model_diagnostics.json`, and `03_regime_model/webapp/data.js`. A React rebuild is not required for data-only refreshes.

### Country Model Refresh

Keep regional Country signals and single-country detail separate:

- regional signal: `artifacts/signals/country_model_signals.parquet`
- single-country detail: `14_country_model/outputs/country_model_single_country_scores.parquet`

Use the cheap existing-database path when enough:

```powershell
python -m tp_models.country --use-existing-database
python -m tp_core.signals C:\GoogleDrive\TP\artifacts/signals\country_model_signals.parquet
```

Do not replace EMU/regional signal behavior with single-country detail unless the user explicitly asks for a methodology change.

### Supplemental Screen Data

Use for production supplemental scores such as `Score ML_IF`.

- Join by `ISIN + month-end Date`.
- Normalize raw trading dates to month end before joining.
- If `ISIN` is an index, call `reset_index()` before joining.
- Preserve canonical row count and date coverage unless the user asks to filter.
- Add new columns rather than overwriting existing canonical signals when the user names a new signal.

### Control Tower Health Audit

Use when the task is coverage, freshness, docs drift, or lightweight test triage rather than a production recompute.

- Read `11_docs/INVESTMENT_PLATFORM_MAINLINE.md` for stage context when the task is repo-wide.
- Inspect exact project files before claiming a project is missing, stale, or unhealthy.
- Check registry coverage in `src/presentation_layer/apps/system_registry.py`.
- Check health-check logic in `src/presentation_layer/apps/system_checks.py`.
- Compare docs, project READMEs, dashboard/control-tower entries, and existing output artifacts for drift.
- Identify freshness gaps across signals, candidates, portfolios, backtests, and reports using existing outputs first.
- Prefer targeted project checks over broad `system-checks` runs when broad checks may update latest manifests.
- If imports fail, verify the editable installation and package metadata; do not inject paths.

Example targeted check:

```powershell
python -m presentation_layer.cli system-checks --project 13_sector_score_model --project 14_country_model
```

## Validation

Choose the smallest validation set that proves the branch:

```powershell
python -m py_compile src/tp_pipelines\run_all.py src/tp_pipelines\refresh_data.py src/tp_pipelines\export_signals.py
python -m tp_pipelines.export_signals --skip-ml --skip-technical --skip-regime
python -m pytest tests\presentation\test_presentation_layer_entrypoints.py -q
python -m tp_core.signals C:\GoogleDrive\TP\artifacts/signals\<signal>.parquet
```

For data updates, validate rows, dates, missing keys, representative latest values, and output paths. Do not use file timestamps alone as proof.

## Reporting

Report:
- branch used
- commands run and pass/fail result
- manifest path
- output files refreshed
- latest data/signal date
- row/date/schema checks
- whether incoming data was archived or intentionally left in place
- for control-tower audits, files inspected, exact missing coverage or failure cause, smallest safe fix, and downstream impact

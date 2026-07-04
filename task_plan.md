# TP pipeline optimization task plan

Goal: implement the highest-priority production-safety improvements with minimal, contained changes.

## Scope interpretation

This task is treated as a phased implementation, not a broad redesign. The first deliverable must protect the pipeline from stale artifacts and smoke-check side effects. Signal-layer and optimizer upgrades should reuse existing project outputs and engines where they already exist.

## Success criteria

- `run_all` blocks or clearly fails when canonical data, signals, candidates, weights, reports, and backtest artifacts are outside the allowed freshness window.
- `system-checks` no longer overwrites production latest manifests during smoke or inspect checks.
- `07_backtest_code` inspect health check avoids loading the full wide screen aggregate.
- Candidate and portfolio decisions consume existing Regime, Country, and Sector signals through the narrowest existing insertion points.
- Optimizer routing uses the existing `06_optimiser` engine where feasible, with audit output preserved.

## Phases

| Phase | Status | Files to inspect first | Expected edit boundary | Verification |
|---|---|---|---|---|
| 1. Locate insertion points | completed | `02_pipelines/run_all.py`, `02_pipelines/*manifest*`, `08_presentation_layer/apps/system_checks.py`, `07_backtest_code/run_backtest.py` | No business edits | line-level plan completed |
| 2. Freshness gate | completed | pipeline manifests and report generation paths | `02_pipelines/run_all.py` | targeted CLI failure path verified |
| 3. Smoke manifest separation | completed | manifest writer/callers | `02_pipelines/common.py` and system-check call path | smoke/inspect latest pointers separated |
| 4. Backtest inspect memory fix | completed | `07_backtest_code` inspect command | inspect validator implementation only | targeted inspect command passed |
| 5. Candidate signal integration | completed | `02_pipelines/build_candidates.py`, `04_signals`, sector/country outputs | candidate scoring only | candidate build smoke run passed |
| 6. Optimizer routing | completed | `02_pipelines/optimize_portfolio.py`, `06_optimiser/optimizer_engine.py` | portfolio optimizer wrapper only | constrained optimizer smoke run passed |
| 7. Dashboard/report freshness display | completed | `08_presentation_layer`, `09_reports` paths | existing display/report surface only | presentation tests and report render passed |

## Constraints

- No broad refactor.
- No new dependency unless the current code already requires it.
- No unrelated formatting or cleanup.
- Any production manifest behavior must preserve existing production runs.

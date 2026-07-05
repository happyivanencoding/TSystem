# TP pipeline optimization progress

## 2026-07-04

- Activated relevant skills: `planning-with-files`, `karpathy-guidelines`, and `ponytail`.
- Confirmed the thread already has the requested optimization goal active.
- Ran planning session catchup; no unsynced context was reported.
- Checked git status; worktree started clean.
- Created persistent planning files before business-code edits.
- Implemented `run_type=production|smoke|inspect` manifest separation across pipeline CLIs and system-check callers.
- Added `run_all` freshness gate and report freshness table.
- Reworked backtest inspect parquet profiling to use metadata and narrow columns.
- Integrated Regime, Country, and Sector inputs into candidate scoring and explanations.
- Added constrained optimizer routing with benchmark, country, sector, turnover, transaction-cost, max/min holding, risk-budget, and audit support.
- Added dashboard overview freshness card and updated optimizer defaults to `constrained`.
- Verified with compile checks, candidate/optimizer/report smoke runs, backtest inspect, targeted system-checks, dashboard state payload, and presentation-layer entrypoint tests.

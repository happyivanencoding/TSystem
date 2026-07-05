# TP pipeline optimization findings

## Memory-derived context

- Prior repo audit found a freshness gap: canonical data and some signals were current to late June / early July, but candidates and portfolio artifacts were still `2026-03-31`.
- Prior system-check run showed `run_backtest.py inspect` tried to read the full wide `screen_aggregate` and failed with a `501 MiB` object array allocation.
- Prior system-check run also wrote into `10_pipeline_runs/manifests/*_latest.json`, so smoke checks can pollute production latest pointers.
- `export_signals` already includes `14_country_model`; `build_candidates` only combines ML and Technical as the known candidate bottleneck.

## Current-session findings

- Git worktree was clean at the start of this session.
- No existing `task_plan.md`, `findings.md`, or `progress.md` planning files were present in the project root.
- `run_all` freshness gate now correctly flags the current production chain as stale: ML `2026-03-31`, Technical `2026-03-30`, Sector `2026-04-30`, candidates `2026-03-31`, and target weights `2026-03-31` are outside the 7-day window from canonical screen `2026-06-30`.
- Smoke and inspect manifests can now be written as `<step>_<run_type>_latest.json`, leaving production `<step>_latest.json` untouched.
- Backtest inspect can profile the wide screen and returns parquet files without loading the full table into memory.
- Candidate scoring now uses a layered structure: security alpha, Country/Sector allocation tilt, and Regime risk-budget multiplier.
- The constrained optimizer attempts the existing `06_optimiser` cvxpy path first; in the current shell environment cvxpy is unavailable, so validation used the scipy SLSQP fallback.
- Dashboard overview now exposes a `链路新鲜度` card. Current state is `过期 3`: data `2026-06-30`, signal floor `2026-03-30`, candidates `2026-03-31`, portfolio `2026-03-31`, backtest `2026-06-30`, report `2026-07-03`.

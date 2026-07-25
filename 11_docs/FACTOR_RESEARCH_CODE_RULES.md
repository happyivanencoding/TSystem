# Factor Research Code Rules

本文档约束 TP 中因子研究 runner 的实现方式。它是 `11_docs/RESEARCH_METHODS.md` 和 `agent_skills/tp-quant-research-workflow` 的代码侧补充。

## Scope

适用于：

- `07_backtest_code/scripts/run_*_multifactor_research.py`
- raw variable gate runner
- relative variable research runner
- pair synergy / family subset / leave-one-out runner
- official Top/Worst batch launcher

不适用于 production refresh，除非用户明确要求把研究结果提升到生产。

## Required Artifacts

每个可复跑研究目录至少写：

- `manifest.json`
- `metric_definitions.json`
- `data_construction_checks.csv`
- `metric_diagnostics.csv`
- `official_run_results.csv`
- `performance_summary.csv`
- `plots/*.html`
- Chinese markdown report

raw gate 研究还要写：

- `raw_validation_gate.csv`

relative raw variable 研究还要写：

- `relative_variable_definitions.csv`
- `relative_validation_gate.csv`
- `relative_vs_level_comparison.csv`

synergy 研究按范围写：

- `pair_synergy_results.csv`
- `family_subset_results.csv`
- `leave_one_out_results.csv`
- `synergy_claims.csv`

historical out-of-period / LOPO 研究还要写：

- `regime_definitions.csv`
- `candidate_registry.csv`
- `candidate_period_metrics.csv`
- `all_leave_one_period_out_results.csv`
- `single_lopo_results.csv` and `single_lopo_selection_summary.csv`
- `combination_lopo_results.csv` and `combination_lopo_selection_summary.csv`
- `single_pre_post_2020_metrics.csv`
- `synergy_lopo_evidence.csv` and `synergy_lopo_summary.csv`
- `deflated_sharpe_results.csv`

## Raw And Relative Variable Rules

- All candidate raw variables must be direction-normalized so higher score means better.
- Every raw variable, including CIQ, FactSet, database, and local derived fields, must pass the same official Top/Worst gate before family inclusion.
- `core` and `supplement` are diagnostic labels only.
- Absolute level variables should get same-security relative variants before family construction:
  - `directional_delta`: direction-normalized level change, then winsorize and neutral rank.
  - `score_delta`: neutralized score change, then neutral rank.
  - default lags: `1,3,6,12` screen observations. Preserve historical
    `1,3,12` runs and add lag 6 in a new immutable run.
- Different lags of the same raw field are mutually exclusive alternatives by
  default. Sparse candidates must not stack them unless a lag-term-structure
  interaction was explicitly preregistered.
- Do not mechanically relative-transform growth, revision, price momentum, total return, CAGR, or other change-like fields unless researching second-order changes.
- A relative variant is a new raw variable. It does not inherit the original level variable's pass/fail status.

## Synergy Rules

- Do not write a synergy claim unless there is individual raw evidence plus pair, subset, bucket leave-one-out, or individual-variable leave-one-out official evidence.
- Compare a pair/subset against the stronger leg, not only against benchmark.
- Classify results as `synergistic`, `additive`, `redundant`, or `harmful`.
- Keep rejected pairs and leave-one-out failures in the report.

## Historical Out-Of-Period Rules

- Use contiguous, preregistered economic periods. Never random-shuffle monthly
  financial observations.
- A holdout fold may not influence its training gate, rank, threshold, weights,
  or candidate selection.
- Require both real benchmark/signal snapshots and actual candidate portfolio
  formation dates inside the holdout. NAV produced only by prior-holding drift
  is not validation evidence.
- Persist period eligibility, snapshot counts, formation counts, minimum
  coverage, and exclusion reasons.
- Freeze the candidate definition, source run, input fingerprint, and
  documented trial ledger before scoring folds.
- If candidates were discovered on full history, label the result historical
  blocked validation with selection bias, not true future OOS.
- DSR trial count must use all recoverable documented candidates in scope.
  Keep an explicit caveat for unrecorded manual trials.
- A cross-period synergy claim additionally requires training-only selection
  and repeatable positive holdout uplift versus the strongest individual leg.

## Official Batch Execution

- Use the official engine path for conclusions.
- Keep Top, Worst, Benchmark, and Top/Worst ratio together.
- Long runners must support `--metrics`, `--max-runs`, and `--resume`.
- Batch runners must flush incrementally to CSV after each run.
- Use `backtest_code.research.executor` for gate evaluation, same-security
  relative construction, pair/subset/LOO candidate construction, completed-run
  dedupe, gap detection, shard allocation, and unique-wave paths. Market
  scripts may supply universe metadata and scoring callbacks, but must not
  reimplement these semantics.
- A requested metric with no result rows remains in the gate and fails both
  official sides; missing work must never disappear from the gate table.
- When no month meets both minimum coverage and disjoint Top/Worst construction,
  write coverage-blocked/skipped records for both sides and retain the failed
  metric in the gate. Never force overlapping Top/Worst portfolios.
- For large matrices, prefer process-level sharding, not Python threads.
- Each worker must write an independent shard CSV and official run root.
- Parent process must merge and dedupe shard results, then regenerate summary, gate, plots, report, and manifest.
- Every restart must use a unique wave directory for shard CSVs; never overwrite previous shard outputs.
- Keep official run roots short on Windows to avoid path-length failures from long metric names.
- If a scheduled rebalance month has no real benchmark or signal snapshot,
  do not forward-fill scores, copy target weights as a new rebalance, or
  synthesize a portfolio. Existing holdings must remain unchanged in name and
  drift with realized returns until the next real snapshot. Before the first
  valid portfolio, remain uninvested. Record the missing date and policy in the
  audit and manifest.
- Prune Parquet inputs before materialization: load only the shard's metric columns plus official technical columns, then load only return columns whose SEDOL appears in the benchmark research screen.
- Prepare immutable screen and returns objects once per worker. Reuse monthly technical bases and benchmark NAV only inside that worker, with cache keys that cover every portfolio-construction parameter that can change the result.
- Disable monthly-base reuse for state-dependent recommendation frames, `Multi Avg Percentile`, financial filters, or any configuration not represented in the cache key.
- Keep several metrics in each shard when possible so Top/Worst and later metrics amortize input preparation and benchmark work. Never create more non-empty workers than metrics.
- Choose process count from an end-to-end benchmark on the target workstation. STOXX600 defaults to 8 workers on the current 32-logical-CPU, 64GB host and remains CLI-overridable.
- Schedule multiple markets from one explicit memory budget. Do not run the
  sum of all market worker counts concurrently. On the current host, execute
  markets sequentially and use the measured stable per-market caps
  (Nasdaq/S&P 500/Europe Small: 4/4/3) unless a new full-artifact benchmark
  proves a higher setting safe.
- Before accepting an official-engine optimization, require exact DataFrame equality for representative cached and uncached `sec_list`, `perf_ptf`, and `perf_bench` artifacts, including Top and Worst. CAGR-level agreement is insufficient.
- Record wall time, successful run count, input dimensions, and per-worker memory for the benchmark. Performance changes must preserve the official artifact schema and research gate.

### Shared Engine Defaults

- Use `backtest_code.runner.input_loader.load_pruned_backtest_inputs` instead of market-local Parquet pruning code. Restrict returns to historical positive-weight benchmark members while retaining both securities in configured dual-listing pairs.
- `BacktestService` must plan a single run from its metric, benchmark, and start date. For a batch, it must load the metric/benchmark union once from the earliest requested start date.
- Treat shared DataFrames as immutable. `OfficialPortfolioBacktest`,
  `SecurityListConstructor`, and `SecurityNavEngine` must not mutate
  caller-owned inputs.
- Build one monthly date-position index per filtered screen. Do not rescan the full screen with a date mask inside every monthly iteration.
- Direct official runners for every market must reuse the service's prepared screen, prepared returns, monthly-base cache, and benchmark cache.
- Do not enable compact float dtypes, reordered compounding, approximate ranks, or incomplete cache keys by default. Each requires exact Top/Worst artifact evidence before promotion.
- Import the public workflow only from `tp_core.backtesting`. Use
  `SecurityNavEngine` / `calculate_security_nav()` for security-level NAV.
  `SecurityListConstructor` constructs security lists,
  `OfficialPortfolioBacktest` orchestrates official artifacts, and
  `OptimizerBacktestAdapter` only converts optimizer output. None may implement
  separate compounding semantics.
- Use `calculate_return_series_nav()` for already-aggregated sector, regime, or
  news returns.
- Use `tp_core.portfolio_weights` as the sole implementation of long-only
  normalization, hard-cap redistribution, weighting transforms, and
  sector-target matching. A cap followed by naive renormalization is forbidden.
- Use only `optimizer.optimize_portfolio()` for portfolio optimization. Every
  optimizer artifact must include `optimizer_id`, `optimizer_version`,
  `optimizer_objective`, solver, objective policy, and constraint policy.
- Every official manifest must record `engine_id`, `engine_version`, and the date execution policy.
- Missing-rebalance validation must compare security sets before and after the
  gap, prove that weights changed through drift while remaining normalized,
  and persist the check as an artifact. NAV continuity alone is insufficient.
- Legacy engine modules and class names must not exist in active code or public exports. Any old import found by repository scan is a release blocker.

## Reporting Rules

Reports must separate:

- official exact evidence;
- screening evidence;
- economic interpretation;
- untested hypotheses;
- missing tests and comparability gaps.

For relative variables, reports must state whether the signal is a marginal improvement effect, a peer-rank improvement effect, or both.

For synergy, reports must explicitly say when evidence is insufficient and avoid phrases such as "family synergy" unless the evidence table supports it.

## Promotion Rule

Research scripts do not change production screen, signal, dashboard, model, or portfolio contracts. Promotion requires a separate user request and a production-refresh/control workflow.

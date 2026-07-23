---
name: tp-quant-research-workflow
description: Use this skill for TP quantitative research workflows, including factor research, region/size/universe multifactor rebuilds, raw-variable validation gates before family construction, regime-feature research, available-data audits beyond existing factor columns, qualitative hypothesis narrowing, creative but explainable candidate signal construction, official top/worst backtests, fast-screen versus official evidence separation, and Chinese research reports with Plotly comparison artifacts.
---

# TP Quant Research Workflow

## Scope

Use this skill when the task is research, not production refresh. Research means forming hypotheses, auditing data, constructing candidate signals, screening variants, running official backtests, and producing decision-ready conclusions.

Primary locations:
- `00_screen/screen_aggregate.parquet`
- `03_regime_model/` for regime-feature research
- `07_backtest_code/run_backtest.py`
- `07_backtest_code/scripts/`
- `07_backtest_code/runs/`
- `07_backtest_code/runs/ad_hoc/`
- `C:\GoogleDrive\笔记\卡片盒子\60_Papers` for research inspiration

## Research Workflow

1. Clarify the question: target universe, benchmark, factor or model target, date range, direction hypothesis, weighting, neutralization, and evaluation metric.
2. Audit available data before selecting variables. Include screen columns, linked databases, returns, fundamentals, estimates, risk fields, country/sector fields, ML scores, macro workbooks, and existing model outputs.
3. Use qualitative finance reasoning and paper-inspired priors to narrow candidates. Do not brute-force large grids without an ex ante rationale.
4. Construct only explainable candidate signals: ranks, z-scores, historical percentiles, rolling changes, lagged values, residualized variables, spreads, and simple combinations with a clear story. For absolute level variables, explicitly consider same-security relative variants before family construction.
5. Separate fast or approximate screening from official exact evidence.
6. Use official exact runs for conclusions. Label screening output clearly.
7. For rebuilt factor families, validate raw variables with official Top/Worst evidence before allowing them into a family composite.
8. Keep Top, Worst, Benchmark, and Top/Worst ratio evidence together unless the user narrows the scope.
9. Generate Plotly Top / Worst / Benchmark and Top/Worst ratio comparisons by default for factor backtests unless the user opts out.

## Region/Size Factor Rebuild Playbook

Use this template when the user asks for a reusable factor model across a region, country, benchmark, size bucket, or universe such as Europe small cap, US large cap, Japan mid cap, or a sector-specific universe.

1. Define the exact universe rule and benchmark first. Prefer benchmark weight columns such as `Weight in <BENCHMARK> > 0`; verify first date, last date, monthly name count, and SEDOL overlap with `00_screen/returns.parquet`.
2. Rebuild factors from raw variables before comparing with database factor columns. Treat existing style scores as comparison anchors, not as the research starting point.
3. Organize variables by economic family, such as growth, value, quality, lowvol, momentum, dividend, revision, liquidity, leverage, profitability, or sector-specific fundamentals. Mark each variable as `core` or `supplement` for diagnostics, but do not let that label alone decide family membership.
4. Convert every raw variable into "higher is better" before aggregation. For each month, winsorize the cross-section, then rank within the neutralization bucket. Default to ICB 19 sector-neutral percentile rank scaled to `0-10`; consider country-neutral or country+sector neutral versions when the universe has strong country bias.
5. Run official Top/Worst backtests for every candidate raw variable before building family composites. CIQ, FactSet, database, and locally-derived fields use the same evidence gate; no source gets automatic inclusion or exclusion.
6. Build validated family composites only from raw variables that pass the gate. Use explicit thresholds for coverage, Top/Benchmark ratio CAGR, robust score, and Top/Worst ratio. Write `raw_validation_gate.csv` or an equivalent audit table. If no raw variable in a family passes, exclude that family from candidate composites instead of creating a misleading empty family.
7. Do not fill missing fundamentals with arbitrary values. Build each validated subfactor from passing variables with a minimum-count rule, and write coverage diagnostics. If a factor only has short history or low coverage, label its backtest as weak evidence.
8. Build explainable composites from validated families: equal-weight full validated model, value+quality, quality+momentum, growth+value+quality, growth+quality+momentum, and other subsets justified by passed family coverage. Optionally add a trailing-IC adaptive blend that uses only past information.
9. Before claiming interaction effects, test pair, subset, or leave-one-out evidence among passed raw variables. Good economic stories such as revision plus margin improvement are hypotheses, not synergy evidence.
10. Run official Top/Worst backtests for validated subfactors, existing database factors, pair/subset/leave-one-out candidates, and final candidates. Use fast screening only to decide what deserves exact runs; do not use it for conclusions.
11. Select the final model by robustness first: Top/Benchmark ratio drawdown, tracking error, rolling 3-year failure, annual hit rate, Top/Worst ratio, Worst underperformance, turnover, and average holdings. Do not mechanically pick the highest CAGR.
12. Explain final weights from the evidence gate upward: raw variable pass/fail, relative-variable pass/fail where relevant, family composition, synergy evidence, family combination, then final model economics.

## Raw Validation Gate

Use this mandatory gate for family rebuild work unless the user explicitly requests a looser exploratory run:

- First construct and save all raw variable scores with directions normalized to higher-is-better.
- Run official exact Top/Worst backtests for each raw score before aggregating it into a family.
- Require at minimum positive Top/Benchmark ratio CAGR, positive Top/Worst ratio return, positive robust score, and acceptable coverage. A practical default is `coverage >= 0.75`, `ratio_cagr > 0`, `top_worst_ratio_return > 0`, and `robust_score > 0`.
- Treat CIQ fields exactly like other fields. Include CIQ only when it passes the same raw gate; exclude it when it fails, even if it is economically plausible.
- Exclude any family with zero passing raw variables from downstream combination tests. Do not generate candidate names that imply exposure to a family whose validated score is empty.
- Keep rejected raw variables in diagnostics and reports so the user can see what failed and why.

## Relative Raw Variable Expansion

Use this step when a raw candidate is an absolute level variable such as a valuation multiple, profitability margin, leverage ratio, dividend yield, payout ratio, volatility, beta, or drawdown field.

- Treat every relative variant as a new raw variable, not as an automatically approved supplement.
- Default relative variants:
  - `directional_delta`: direction-normalized raw level minus same-security lagged raw level, then winsorize and neutral-bucket rank.
  - `score_delta`: current neutralized raw score minus same-security lagged score, then neutral-bucket rank.
- Default lags are `1`, `3`, and `12` screen observations unless the data frequency or availability lag requires a different choice.
- Do not mechanically apply relative transforms to variables that are already growth rates, estimate revisions, price momentum, total returns, CAGR fields, or other change-like fields unless the explicit hypothesis is second-order change.
- Require the same official Top/Worst gate as other raw variables before a relative variant enters any family.
- Write `relative_variable_definitions.csv`, `relative_validation_gate.csv`, and `relative_vs_level_comparison.csv`.
- Compare each relative variant against its original level variable; do not claim relative variables are generally superior unless official evidence supports that claim in the selected market.
- Prefer `directional_delta` only when the economic meaning is clear, for example margin improvement, leverage decline, valuation becoming cheaper, payout pressure falling, or volatility declining.
- If a relative variable passes but its original level variable fails, describe the economic mechanism as a marginal improvement effect, not as evidence that the whole family is validated.

## Synergy Evidence Protocol

Use this protocol after raw and relative raw variables pass their individual gates.

- Do not claim synergy from economic intuition, family labels, or a composite backtest alone.
- Minimum evidence for a synergy claim:
  - each individual leg has official raw Top/Worst evidence;
  - the pair, subset, or leave-one-out candidate has official Top/Worst evidence;
  - the pair/subset improves robustness versus the best individual leg or versus the relevant simple benchmark composite;
  - leave-one-out shows the added variable contributes positively or reduces drawdown, tracking error, turnover instability, or rolling failure;
  - coverage, turnover, and holding overlap remain acceptable.
- Classify relationships explicitly:
  - `additive`: pair works but does not materially beat the best leg;
  - `synergistic`: pair beats the best leg on robust score and risk evidence;
  - `redundant`: pair adds little and leave-one-out contribution is weak;
  - `harmful`: pair lowers robustness or materially worsens drawdown, turnover, or coverage.
- Write `pair_synergy_results.csv`, `family_subset_results.csv`, `leave_one_out_results.csv`, and `synergy_claims.csv` when those tests are in scope.
- Good hypotheses to test include cheap plus improving earnings, revision plus margin improvement, momentum plus quality improvement, and deleveraging plus risk decline; they still need official evidence.

Implementation pattern:

- Put one-off research scripts under `07_backtest_code/scripts/` and outputs under `07_backtest_code/runs/ad_hoc/`.
- Import the public workflow only from `tp_core.backtesting`. Use
  `SecurityNavEngine` / `calculate_security_nav()` for security-level NAV,
  `SecurityListConstructor` for security lists, and
  `OfficialPortfolioBacktest` for official artifacts.
- Use `tp_core.portfolio_weights` for normalization, hard-cap redistribution,
  weighting transforms, and sector target matching.
- Use `optimizer.optimize_portfolio()` as the sole optimization API and retain
  optimizer identity, version, objective, solver, objective policy, and
  constraint policy in artifacts.
- Never prune small optimizer weights and renormalize after solving. Validate
  every configured constraint on the final weights before writing artifacts.
- Use `backtest_code.research.executor` for raw/relative gates,
  same-security relative variants, pair/subset/bucket and individual
  leave-one-out candidates,
  completed Top/Worst detection, dedupe, sharding, and unique-wave paths.
- Requested metrics with no result rows remain in the gate as failed Top/Worst
  evidence; missing work must never disappear from the gate table.
- Write `metric_definitions.json`, `data_construction_checks.csv`, `metric_diagnostics.csv`, `official_run_results.csv`, `performance_summary.csv`, Plotly HTML files, and a Chinese markdown report.
- Add `--metrics`, `--max-runs`, and `--resume` to long official-run scripts so multi-hour Top/Worst matrices can be resumed without repeating successful runs.
- For reusable universe runners, add or use a two-stage interface like `--raw-only` followed by `--validated-from <raw_run_dir_or_summary>` so raw evidence gates family construction.
- For large official run matrices, use resumable process-level sharding rather than Python threads. Each worker must write its own shard result file and official run root; the parent process merges and deduplicates results. Use unique wave directories on restart so shard CSVs are not overwritten.
- Keep Windows run paths short for official artifacts; long metric names plus nested shard directories can exceed path limits before `config_snapshot.yaml` is written.
- If the GUI `BacktestService` logger relay fails or recurses during batch runs,
  call the same official engine path directly while preserving
  `OfficialPortfolioBacktest`, `build_historical_security_lists`,
  `run_portfolio_nav`, benchmark performance, and artifact outputs.
- Do not modify production screen, signal, dashboard, model, or portfolio contracts unless the user explicitly asks to promote the research result.

## Data Audit And Idea Generation

Before proposing tests, inspect what usable data exists rather than limiting candidates to existing factor columns.

- List relevant sources and files: screen columns, linked databases, returns, fundamentals, estimates, risk fields, country/sector fields, macro fields, ML scores, and model outputs.
- Check variable meaning, frequency, date alignment, coverage, missingness, outliers, survivorship risk, and look-ahead risk.
- Identify whether variables are levels, changes, ranks, estimates, realized values, raw accounting fields, market data, or model outputs.
- Consider sector, country, size, liquidity, and market-cap biases before interpreting a raw signal.
- Use `C:\GoogleDrive\笔记\卡片盒子\60_Papers` for research inspiration when useful. Start with `index.md` and paper titles, then open only the most relevant notes.
- Prefer a short candidate list with clear economic, behavioral, operational, or paper-inspired priors over broad data mining.

Generate research ideas proactively after understanding the data:

- If low-volatility research has returns but no residual-volatility field, propose residual volatility from market, sector, country, or known-factor regressions.
- Use lagged variables when realistic data availability implies delay, such as one-month lag, quarter-end lag, or fixed-month differences.
- Convert raw levels into cross-sectional ranks, z-scores, historical percentiles, rolling changes, or deviations from each security's own history.
- Build interpretable spreads such as quality minus leverage, earnings revision minus valuation, short-term volatility minus long-term volatility, or margin improvement versus sector peers.
- Use regime-aware variants when the mechanism plausibly depends on macro, volatility, liquidity, or market-trend states.
- Combine variables only when the combination has a simple story, such as cheap plus improving quality, low risk plus positive revision, or high profitability adjusted for valuation.
- Compare country or sector neutralized versions against raw versions when allocation bias may dominate the result.

## Official Backtest Defaults

Use these unless the user overrides them:

- Benchmark/universe: user-selected; common default is `STOXX EUROPE 600`
- Percentile: `0.2`
- Weighting: `Market cap`
- `max_weight`: `1.0`
- ESG exclusion: `0.0`
- Top and Worst both required
- NAV windows aligned across candidates

Before answering engine behavior questions, inspect the actual runner/config/portfolio builder. Do not infer factor direction from the factor name; verify `nlargest` / `nsmallest` behavior.

## Regime Research

Use this path when testing whether a candidate variable improves regime models. Keep it as research unless the user explicitly asks for production integration.

Candidate sources:
- macro columns from `03_regime_model/maj cycle macro2.xlsx`
- bottom-up stock volatility aggregates from `00_screen`
- `Score ML_IF` or related stock-level ML score aggregates
- regime-break or post-2020 research variants

Rules:
- Keep US and EU tests separate.
- Treat K4 production HMM, K3 regime-break research, direction diagnostics, volatility diagnostics, and drawdown diagnostics as separate models.
- Use `03_regime_model.data_loader.get_region_panel` for point-in-time stock panels.
- Interpolate sparse macro series only inside the observed range; do not extrapolate unless asked.
- Write temporary research artifacts under `.codex_tmp/regime_feature_research/<yyyymmdd_slug>/`.

## Reporting Contract

For decision-ready research, produce:

- Chinese Markdown conclusion when the user asks in Chinese
- available data audit and candidate data sources
- qualitative rationale for each proposed signal
- files and artifacts inspected
- exact backtest or model comparison table
- requirement or hypothesis audit table
- Plotly NAV / ratio comparison when backtests are involved
- metric comparison chart
- clear classification of evidence as screening or official exact
- missing tests or comparability gaps
- links or paths to run directories and final artifacts

## Guardrails

- Do not overwrite historical run directories.
- Do not present screening output as final official performance.
- Do not claim exhaustive search unless every subset was tested.
- Do not claim a family has internal synergy unless raw variables, leave-one-out tests, or family-subset tests support that claim.
- Do not include a raw variable in a final rebuilt family merely because it is a known data source, a `core` label, or an economically plausible field.
- Do not change production screen, signal, dashboard, model, or portfolio contracts during research unless asked.
- Do not brute-force large variable grids without an ex ante qualitative rationale.
- Do not use transformations that cannot be explained economically, operationally, or behaviorally.
- Do not use current-period information when a realistic signal requires lagged availability.
- If adding research code, keep it under the relevant research/scripts area and keep changes narrowly scoped.

---
name: tp-quant-research-workflow
description: Use this skill for TP quantitative research workflows, including factor research, regime-feature research, available-data audits beyond existing factor columns, qualitative hypothesis narrowing, creative but explainable candidate signal construction, official top/worst backtests, fast-screen versus official evidence separation, and Chinese research reports with Plotly comparison artifacts.
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
4. Construct only explainable candidate signals: ranks, z-scores, historical percentiles, rolling changes, lagged values, residualized variables, spreads, and simple combinations with a clear story.
5. Separate fast or approximate screening from official exact evidence.
6. Use official exact runs for conclusions. Label screening output clearly.
7. Keep Top, Worst, Benchmark, and Top/Worst ratio evidence together unless the user narrows the scope.
8. Generate Plotly Top / Worst / Benchmark and Top/Worst ratio comparisons by default for factor backtests unless the user opts out.

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
- Do not change production screen, signal, dashboard, model, or portfolio contracts during research unless asked.
- Do not brute-force large variable grids without an ex ante qualitative rationale.
- Do not use transformations that cannot be explained economically, operationally, or behaviorally.
- Do not use current-period information when a realistic signal requires lagged availability.
- If adding research code, keep it under the relevant research/scripts area and keep changes narrowly scoped.

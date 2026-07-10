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

## Raw And Relative Variable Rules

- All candidate raw variables must be direction-normalized so higher score means better.
- Every raw variable, including CIQ, FactSet, database, and local derived fields, must pass the same official Top/Worst gate before family inclusion.
- `core` and `supplement` are diagnostic labels only.
- Absolute level variables should get same-security relative variants before family construction:
  - `directional_delta`: direction-normalized level change, then winsorize and neutral rank.
  - `score_delta`: neutralized score change, then neutral rank.
  - default lags: `1,3,12` screen observations.
- Do not mechanically relative-transform growth, revision, price momentum, total return, CAGR, or other change-like fields unless researching second-order changes.
- A relative variant is a new raw variable. It does not inherit the original level variable's pass/fail status.

## Synergy Rules

- Do not write a synergy claim unless there is individual raw evidence plus pair, subset, or leave-one-out official evidence.
- Compare a pair/subset against the stronger leg, not only against benchmark.
- Classify results as `synergistic`, `additive`, `redundant`, or `harmful`.
- Keep rejected pairs and leave-one-out failures in the report.

## Official Batch Execution

- Use the official engine path for conclusions.
- Keep Top, Worst, Benchmark, and Top/Worst ratio together.
- Long runners must support `--metrics`, `--max-runs`, and `--resume`.
- Batch runners must flush incrementally to CSV after each run.
- For large matrices, prefer process-level sharding, not Python threads.
- Each worker must write an independent shard CSV and official run root.
- Parent process must merge and dedupe shard results, then regenerate summary, gate, plots, report, and manifest.
- Every restart must use a unique wave directory for shard CSVs; never overwrite previous shard outputs.
- Keep official run roots short on Windows to avoid path-length failures from long metric names.

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


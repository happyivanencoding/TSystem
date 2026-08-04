# Monthly Factor Recommendation Model

本目录只记录 `monthly-factor-recommendation-v1` 的研究入口和证据边界。核心实现位于 `src/tp_models/factor_recommendation`，研究 workflow 不复制或修改核心包，也不写入 pipeline、presentation 或 frontend。

## Core calling boundary

研究 runner 通过 public lazy boundary 调用：

```python
tp_models.factor_recommendation.load_research_inputs(mode="full", seed=1729)
```

返回值应为 mapping，至少包含：

- `screen`：canonical monthly screen DataFrame 或 `.parquet` 路径；必须包含日期、证券 ID 和预注册 factor 列。
- `returns`：canonical returns DataFrame 或 `.parquet` 路径；支持 wide index-date 或 long `Date`/ID/`Return` 形态。
- `universe`：`date_column`、`security_id_column`、可选 `weight_column`、`group_column`、sample/PIT scope。
- `factors`：按声明顺序的 `name`、`column`、`direction`、`family/source` 与可选 availability/PIT 字段。
- `model`：候选 `models`、training-only selection 参数、`cost_assumptions`、`effective_trial_count` 和可选 `lopo_periods`。
- `components`：至少描述 `ASIA` 组件与 `synthetic` 状态；二者会原样写入报告和 manifest。

也可以返回 `canonical: {screen, returns}`，以及可选 `features`、`target`、`target_config`。调用边界只读，不接受 workflow 输出路径，也不生成 synthetic 数据作为 fallback。

## Run modes

Registry 管理 Run Card 和 `results/`，用户参数在 `--` 后传给 runner：

```powershell
python -m tp_research.cli validate
python -m tp_research.cli run monthly-factor-recommendation-v1 -- --smoke --max-months 6 --max-factors 2
python -m tp_research.cli run monthly-factor-recommendation-v1 -- --full
```

`--inspect` 只检查 core contract；`--smoke` 或任何资源上限都会在 manifest/report 标记为非 full；`--full` 不能和 `--max-months`/`--max-factors` 混用。workflow 只接受 Registry 注入的 `--output-dir`，`run_definition` 会拒绝用户覆盖它。

## Evidence contract

每个成功结果至少保留内部 runner 工件以及 prompt 级审计包：

`config_snapshot.json`、`component_status.json`、`target_definition.json`、`feature_definitions.csv`、`feature_matrix.parquet`、`target_frame.parquet`、`pit_audit.csv`、`walk_forward_folds.csv`、`grouped_folds.csv`、`fold_predictions.parquet`、`model_selection.csv`、`lopo_loro_results.csv`、`cost_assumptions.json`、`cost_adjusted_metrics.csv`、`dsr_results.csv`、`bootstrap_results.csv`、`promotion_gate.csv`、`research_report.md` 与 `manifest.json`。

审计包的固定文件名为：`repository_data_audit.json`、`universe_definitions.csv`、`factor_definitions.csv`、`raw_variable_gate.csv`、`relative_variable_gate.csv`、`factor_sleeve_metrics.csv`、`factor_sleeve_monthly_returns.parquet`、`feature_coverage.csv`、`model_candidate_registry.csv`、`walk_forward_predictions.parquet`、`walk_forward_metrics.csv`、`period_definitions.csv`、`lopo_results.csv`、`loro_results.csv`、`strategy_monthly_returns.parquet`、`strategy_metrics.csv`、`cost_sensitivity.csv`、`block_bootstrap_results.csv`、`deflated_sharpe_results.csv`、`trial_ledger.csv`、`selection_audit.csv` 和 `promotion_gate.csv`。这些文件是已计算 frame 的稳定别名，不是第二条计算路径。

target 只使用 decision date 之后的同证券收益；features 记录方向、winsorize、neutralization 和 PIT。walk-forward 与 grouped folds 按连续月份建立，LOPO/LORO 只允许 training periods 选择模型，成本进入 net return；DSR 使用所有已声明候选的 trial count，bootstrap 使用固定 seed。报告明确区分 exact evidence、缺失测试、synthetic/ASIA 状态与经济解释。

成功的 Registry Run Card 默认是 `review_required`。任何 evidence pass 都不能把研究结果自动 promotion；生产晋升必须是独立授权和独立 workflow。

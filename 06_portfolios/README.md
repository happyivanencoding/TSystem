# 06_portfolios

组合目录保存由候选池生成的标准目标权重。

当前标准产物：

| 文件 | 说明 |
| --- | --- |
| `latest_target_weights.parquet` | 最新目标权重，来自 `python -m pipelines.optimize_portfolio` |

当前实现是 baseline 版本：根据候选池 `composite_score` 生成权重，并应用单股上限。更复杂的行业、国家、风险预算、换手率和交易成本约束后续继续收敛到 `06_optimiser/`。

每次运行的输入、输出、权重合计、单股上限和主键校验见：

```text
10_pipeline_runs/manifests/optimize_portfolio/optimize_portfolio_latest.json
```

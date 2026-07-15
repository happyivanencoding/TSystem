# Sector 模型改进研究报告（2026-07-11）

## 结论

- EU：上线 `score_final_raw_rank` 的 6 个月尾随均值。
- US：保留原模型。
- 拒绝：直接行业趋势、12/24 个月 factor-momentum rotation、EU/US 机械共用同一平滑规则。
- 统计边界：EU 留出期 bootstrap 95% 区间跨零；结论属于经济与实施稳健化，不声称已证明新 alpha。

## 关键证据

| 市场/时期 | 旧主动年化 | 新/候选主动年化 | 旧 Sharpe | 新/候选 Sharpe | 决定 |
| --- | ---: | ---: | ---: | ---: | --- |
| EU 2018–2021 | 1.15% | 1.28% | 0.72 | 0.70 | 通过验证底线 |
| EU 2022–最新 | 1.70% | 1.94% | 0.86 | 1.07 | 改善 |
| EU 全期 | 1.21% | 1.28% | 0.73 | 0.72 | 收益/回撤/换手改善 |
| US 2018–2021 | 1.38% | 1.16% | 0.76 | 0.64 | overlay 验证受损，拒绝 |
| US 2022–最新 | 1.30% | 1.47% | 0.60 | 0.69 | 仅留出期改善，不足以上线 |

EU 月均单边换手由 9.40% 降至 6.81%，全期主动最大回撤由 -2.73% 改善至 -2.44%。

## 产物

- `official_run_results.csv`：17 候选 × 2 市场 × 5 时期的 exact 结果。
- `backtest_monthly_returns.csv`：候选月度组合、基准与主动收益。
- `rotation_schedule.csv`：每月 rotation 选择及 trailing window。
- `data_construction_checks.csv`：时点、target、holdout 与成本检查。
- `paired_block_bootstrap.json`：6 个月区块 bootstrap。
- `nav_comparison_eu.html` / `nav_comparison_us.html`：Plotly 主动 NAV。
- `selection_audit.csv`：EU promote、US keep baseline。

完整论文：`C:\GoogleDrive\笔记\卡片盒子\60_Papers\2026-07-11 行业模型跨时期稳健化研究 - 尾随集成、改善扩散与 rotation 失败证据.md`


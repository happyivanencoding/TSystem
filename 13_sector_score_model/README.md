# 13_sector_score_model

## 定位

本项目把 `Score_Sectoriel_US.xlsm` / `Score_Sectoriel_EU.xlsm` 行业打分方法论沉淀为 Python 模型，并用 TP canonical 数据重建 US / EU 两个版本的行业打分与行业权重偏离回测模型。

## 数据来源

默认读取：

- `C:\GoogleDrive\TP\00_screen\screen_aggregate.parquet`
- `C:\GoogleDrive\TP\00_screen\returns.parquet`
- `C:\GoogleDrive\TP\00_screen\factset_icb_mapping.xlsx`

US 模型使用 `Weight in SP500 > 0` 定义 S&P 500 universe；EU 模型使用 `Weight in STOXX EUROPE 600 > 0` 定义 STOXX Europe 600 universe。两个版本都使用 `Benchmark ICB Supersector` 映射 19 个 ICB 超级行业，并优先使用已补入 `screen_aggregate.parquet` 的 `_FS_SECTOR` 行业历史字段。

## 运行入口

```powershell
python C:\GoogleDrive\TP\13_sector_score_model\src\sector_score_model.py
```

主要参数：

```powershell
python C:\GoogleDrive\TP\13_sector_score_model\src\sector_score_model.py `
  --market US `
  --start-date 2010-01-01 `
  --top-n 3 `
  --bottom-n 3
```

EU 版本：

```powershell
python C:\GoogleDrive\TP\13_sector_score_model\src\sector_score_model.py --market EU
```

EU 变量研究复跑：

```powershell
python C:\GoogleDrive\TP\13_sector_score_model\src\eu_variable_research.py
```

无前视改进研究（固定集成、成分股改善扩散与 factor-momentum rotation）：

```powershell
python C:\GoogleDrive\TP\13_sector_score_model\src\sector_model_improvement_research.py
```

## 输出

US 默认写入 `13_sector_score_model\outputs\`；EU 默认写入 `13_sector_score_model\outputs_eu\`：

- `sector_scores_panel.parquet`：行业月度因子分、综合分和下一月行业收益面板。
- `sector_scores_latest.csv`：最新一期行业分数、排名、推荐和行业权重。
- `factor_effectiveness.csv`：单变量和组合变量的 IC、Top-Bottom 表现、命中率。
- `backtest_monthly_returns.csv`：最终模型行业偏离组合、基准和主动收益月度序列。
- `backtest_summary.json`：全样本、前半段、后半段、2020 年后的长期回测指标。

EU 变量研究额外输出：

- `eu_raw_variable_tests_all.csv`：EU 每个候选变量的 high/low 两个方向逐一测试结果。
- `eu_raw_variable_tests_best_direction.csv`：每个 EU 变量表现较好的方向。
- `eu_combo_tests.csv`：只用 EU 单变量测试通过的变量构造的组合候选对比。

## 当前验证结果：US

默认 `score_final` 使用 screen 风格质量/估值与 `_FS_SECTOR` 行业因子分的混合。成分股改善扩散和 rotation 经过验证后没有稳定胜过原分数，因此 US 保留原模型。2010-01-31 至 2026-05-31 共 197 个月：

| 指标 | 模型行业偏离组合 | SP500 行业权重基准 |
| --- | ---: | ---: |
| 年化收益 | 17.04% | 15.95% |
| 年化波动 | 14.18% | 14.10% |
| Sharpe | 1.20 | 1.13 |
| 最大回撤 | -17.15% | -19.31% |
| 月度胜率 | 64.97% | 65.99% |

相对基准年化收益约 0.94%，主动收益月度命中率 56.85%。详见 `outputs_fs_sector_default/backtest_summary.json`。

## 当前验证结果：EU

EU 没有直接复用 US 的质量/估值默认组合。`eu_variable_research.py` 对 162 个 EU 候选变量逐个测试 high/low 方向，共 324 个单变量方向测试；最终默认 `score_final` 使用 EU 单独筛出的修正/动量组合：

- `PCT ERR`
- `PMOM 12M1M`
- `MOM Score`
- `EPS Revision Ratio`

四个变量均按 EU universe 每月横截面排名转为 0-10 分，再按行业权重聚合。最终分数使用当前及过去最多 5 个月的行业横截面排名做 6 个月尾随均值，降低单月噪音且不读取未来数据。2010-01-31 至 2026-05-31 共 197 个月：

| 指标 | 模型行业偏离组合 | STOXX Europe 600 行业权重基准 |
| --- | ---: | ---: |
| 年化收益 | 12.59% | 11.14% |
| 年化波动 | 13.14% | 13.24% |
| Sharpe | 0.96 | 0.84 |
| 最大回撤 | -20.55% | -22.68% |
| 月度胜率 | 65.48% | 64.47% |

相对基准年化收益约 1.31%，主动收益月度命中率 58.38%。相对旧分数，全期主动最大回撤从 -2.73% 改善到 -2.44%，月均单边换手从 9.40% 降到 6.81%；2022 年后的主动 Sharpe 从 0.86 提高到 1.07。详见 `outputs_eu/backtest_summary.json` 和 `runs/ad_hoc/sector_improvement_20260711/`。

## 改进研究结论

- 接受：EU 6 个月尾随排名集成；它跨验证期与留出期保持正主动收益，并显著降低换手。
- 保留原样：US 原模型；25% 成分股改善扩散在留出期有增量，但验证期和回撤证据不足。
- 拒绝：EU/US 直接行业价格动量与 12/24 个月 factor-momentum rotation；等权 revision/price breadth 仅停留在探索性筛选，不进入正式证据或生产。
- 统计边界：EU 留出期相对旧分数的 6 个月区块 bootstrap 95% 区间仍跨零，因此改进属于经济与实施层面的增强，不宣称已证明新的 alpha。

## 维护状态

活跃研究。当前模型不修改 canonical 数据，只读取 `00_screen` 的 parquet 并在本项目目录生成派生结果。

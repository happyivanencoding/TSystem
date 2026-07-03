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

默认 `score_final` 使用 screen 风格质量/估值与 `_FS_SECTOR` 行业因子分的混合，2010-01-31 至 2026-04-30 共 196 个月：

| 指标 | 模型行业偏离组合 | SP500 行业权重基准 |
| --- | ---: | ---: |
| 年化收益 | 17.12% | 15.96% |
| 年化波动 | 14.22% | 14.13% |
| Sharpe | 1.20 | 1.13 |
| 最大回撤 | -17.15% | -19.31% |
| 月度胜率 | 64.80% | 65.82% |

相对基准年化超额约 1.00%，主动收益月度命中率 57.14%。详见 `outputs_fs_sector_default/backtest_summary.json`。

## 当前验证结果：EU

EU 没有直接复用 US 的质量/估值默认组合。`eu_variable_research.py` 对 162 个 EU 候选变量逐个测试 high/low 方向，共 324 个单变量方向测试；最终默认 `score_final` 使用 EU 单独筛出的修正/动量组合：

- `PCT ERR`
- `PMOM 12M1M`
- `MOM Score`
- `EPS Revision Ratio`

四个变量均按 EU universe 每月横截面排名转为 0-10 分，再按行业权重聚合。2010-01-31 至 2026-04-30 共 196 个月：

| 指标 | 模型行业偏离组合 | STOXX Europe 600 行业权重基准 |
| --- | ---: | ---: |
| 年化收益 | 12.43% | 11.02% |
| 年化波动 | 13.21% | 13.27% |
| Sharpe | 0.94 | 0.83 |
| 最大回撤 | -21.98% | -22.68% |
| 月度胜率 | 65.31% | 64.29% |

相对基准年化超额约 1.27%，主动收益月度命中率 58.67%。详见 `outputs_eu/backtest_summary.json`、`outputs_eu/score_candidate_comparison.csv`、`outputs_eu/eu_raw_variable_tests_best_direction.csv` 和 `outputs_eu/eu_combo_tests.csv`。

## 维护状态

活跃研究。当前模型不修改 canonical 数据，只读取 `00_screen` 的 parquet 并在本项目目录生成派生结果。

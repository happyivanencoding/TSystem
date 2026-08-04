# TP 生产流水线运行手册

最后更新：2026-08-04

本文档是月更数据、主流水线命令、标准产物和运行证据的唯一操作手册。所有生产操作从已安装的 `tp-*` 控制台入口进入，不执行编号资源目录中的 Python 文件。

## Canonical 数据

| 数据集 | 路径 |
| --- | --- |
| Screen 历史面板 | `00_screen/screen_aggregate.parquet` |
| 最新月度快照 | `00_screen/last_screen.parquet` |
| 日频收益矩阵 | `00_screen/returns.parquet` |
| 近五年 Screen | `00_screen/screen_aggregate_5Y.parquet` |

路径声明见根目录 `DATA_SOURCES.md`，主键和字段语义见根目录 `DATA_CONTRACT.md`。

## 月更输入

新输入只放入：

```text
00_screen/production_inputs/incoming/YYYYMM/
├── screen/
├── returns/
└── ciq/
```

旧 `00_screen/monthly`、`00_screen/returns` 和 `00_screen/ciq` 只属于 quarantine/archive，不再读取。

标准顺序：

1. 将本月原始文件放入 `incoming/YYYYMM/` 对应子目录。
2. 运行 `.\.venv_tp\Scripts\tp-organize-inputs.exe`。
3. 检查 `00_screen/production_inputs/manifests/input_inventory_latest.json`。
4. 先 dry-run：

```powershell
.\.venv_tp\Scripts\tp-pipeline-refresh-data.exe --input-month YYYYMM --update-mode both --dry-run
```

5. 确认输入、目标月份和 QA 后，去掉 `--dry-run` 正式运行。
6. 检查月更 QA、`artifacts/pipeline_runs/manifests/refresh_data/refresh_data_latest.json` 及最新数据库 profile。
7. 成功消费的 incoming 输入按清单归档；不要长期把已消费文件留在 incoming。

`tp_data.monthly_update` 是当前包内实现和诊断入口，不是资源目录脚本。生产运行应优先经过 `tp-pipeline-refresh-data`，以确保写入统一 manifest 和 Run Card。

## 单环入口

| 环节 | 控制台命令 | 主要输入 | 标准输出 |
| --- | --- | --- | --- |
| 数据刷新 | `tp-pipeline-refresh-data` | `production_inputs/incoming/YYYYMM/` | Canonical parquet、QA |
| 补充数据 | `tp-pipeline-refresh-supplemental-data` | 官方 API、字段配置、标识映射 | `00_screen/supplemental/`、QA |
| 行业模型 | `python -m tp_pipelines.refresh_sector_model` | Canonical screen、returns、ICB mapping | EU/US 行业评分与回测产物 |
| 国家模型 | `python -m tp_pipelines.refresh_country_model` | `modele_pays.xlsb` | 国家数据库、评分面板及 country signal |
| ML 刷新 | `python -m tp_pipelines.refresh_ml --inspect-only` | Canonical screen、ML 公共 API | Score ML 覆盖及 ML signal |
| 信号导出 | `tp-pipeline-export-signals` | Canonical 数据、模型专项结果 | `artifacts/signals/` |
| 候选池 | `tp-pipeline-build-candidates` | Signals、latest screen | `artifacts/candidates/` |
| 组合优化 | `tp-pipeline-optimize-portfolio` | Candidates、约束、旧组合可选 | `artifacts/portfolios/` |
| 回测 | `tp-pipeline-run-backtest --inspect-only` | Canonical 数据、backtest profile | `artifacts/backtests/runs/` |
| 报告 | `tp-pipeline-generate-report` | 最新 manifest 和标准产物 | `artifacts/reports/` |

命令名均位于 `.\.venv_tp\Scripts\`。也可以使用等价的当前包模块入口进行开发诊断，例如 `python -m tp_pipelines.export_signals`；`01_tp_core`、`02_pipelines`、`pipelines` 等旧模块名无效。

## 总入口

```powershell
.\.venv_tp\Scripts\tp-pipeline-run-all.exe --input-month YYYYMM --as-of YYYY-MM-DD
```

安全调试示例：

```powershell
.\.venv_tp\Scripts\tp-pipeline-run-all.exe --skip-refresh-data --skip-backtest
.\.venv_tp\Scripts\tp-pipeline-run-all.exe --dry-run-data --inspect-only-backtest
```

`run_all` 只做 typed step config、registry/DAG 和顺序编排；业务规则仍由各公共包负责。默认在 `refresh_data` 后刷新行业、国家、Regime、technical，并重新导出信号；需要临时跳过时使用对应的 `--skip-refresh-*` 参数。

## 幂等与写入规则

- `returns.parquet` 按日期索引合并；同日期增量覆盖旧值，不追加重复日期。
- `screen_aggregate.parquet` 只替换目标月份切片，非目标月份不得变化。
- CIQ 按 `(ISIN, Date)` 对齐，只填补空值，不覆盖已有非空值。
- Canonical 写入前必须通过唯一键和 schema 校验，并生成可回滚备份。
- `refresh_data` 会更新 Score ML；`run_all` 随后自动刷新行业、国家、Regime、technical 和标准信号，不隐式访问外部 API，也不把补充数据自动晋升为 Canonical 字段。
- Stable latest 产物可以覆盖；时间戳运行证据不得被覆盖。

## 补充数据影子层

- 至少显式传入一个 `--source`，否则不访问外部 API。
- 密钥和用户代理只从环境变量读取，不写入 manifest 或文档。
- Raw 响应不可变保存；标准化记录按 payload hash 幂等落盘。
- 月末解析只使用 `available_at <= Date` 的记录。
- 默认只更新 shadow/sidecar 和 QA；晋升 Canonical 需要连续 QA 和显式 promotion 配置。

## Manifest 与 Run Card

每个 step 写入：

```text
artifacts/pipeline_runs/manifests/<step>/
├── <step>_YYYYMMDD_HHMMSS.json
└── <step>_latest.json
```

Smoke/inspect 使用独立 latest 指针，不覆盖 production latest。记录至少包括配置与代码版本、输入 fingerprint、PIT 截止时间、universe、样本与成本假设、引擎/信号/优化器版本、指标、产物、状态、lineage 和决定理由。

## QA、备份与保留策略

| 类型 | 位置 |
| --- | --- |
| 月更 QA | `00_screen/qa/` |
| 输入清单与数据库 profile | `00_screen/production_inputs/manifests/`、`profiles/` |
| Canonical 备份 | `00_screen/backups/` |
| Pipeline manifest | `artifacts/pipeline_runs/manifests/` |
| Experiment/Run Card | `artifacts/pipeline_runs/experiments/` |

运行 `.\.venv_tp\Scripts\tp-prune-artifacts.exe` 只会预览保留策略；必须显式传入 `--apply` 才会清理。

## 禁止事项

- 不从 quarantine、archive、项目私有 Screen/returns 副本或 `.pkl` 读取生产数据。
- 不执行编号资源目录中的旧 wrapper。
- 不依赖 `sitecustomize`、`.pth` 或业务代码路径注入。
- 不以时间戳、退出码或文件存在性单独证明刷新成功；必须检查日期、行数、schema、关键缺失率和 manifest 状态。

## Research-only 月度因子推荐

`refresh_factor_recommendation` 是独立、默认关闭的 research-only step。它只写
`16_factor_recommendation_model/outputs/` 和
`artifacts/signals/factor_recommendation_signals.parquet`，不进入
`export_signals`，不改变 security candidates 或 optimizer。默认配置使用版本化
`region_universes_v1.json`、`factor_definitions_v1.json` 和 `model_v1.json`；运行
时必须核对 `factor_recommendation_manifest.json`、`factor_recommendation_validation.json`
以及 pipeline manifest 的 `production_effects` 全为 false。

```powershell
python -m tp_pipelines.refresh_factor_recommendation --inspect-only
python -m tp_pipelines.refresh_factor_recommendation --as-of 2026-07-31 --minimum-coverage 0.8
```

ASIA 永远显示为 `research_only_benchmark_unapproved`；其缺少 benchmark approval 或
12 个月 forward shadow 时不得 promotion。完整研究使用已注册
`monthly-factor-recommendation-v1` Run Card，smoke 结果不能冒充 full evidence。

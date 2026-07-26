# Screen 月度数据边界

`00_screen/` 保存 TP 的 Canonical Screen/returns、月更原始输入、QA、备份和人工检查 notebook。活跃实现位于 `src/tp_data/` 和 `src/tp_pipelines/`；本目录不再提供 Python 脚本入口。

## Canonical 文件

| 文件 | 粒度与用途 |
| --- | --- |
| `screen_aggregate.parquet` | 证券 × 月末历史宽表 |
| `last_screen.parquet` | 最新月末快照 |
| `returns.parquet` | 交易日 × SEDOL 日频收益矩阵 |
| `screen_aggregate_5Y.parquet` | 近五年轻量 Screen 子集 |
| `Transco_FactSet_ICB.xlsx` | 月更行业映射 |

主键、日期和字段规则见根目录 `DATA_CONTRACT.md`；路径声明见根目录 `DATA_SOURCES.md`。

## 输入目录

```text
production_inputs/incoming/YYYYMM/
├── screen/
├── returns/
└── ciq/
```

详细归档与命名规则见 `production_inputs/README.md`。已消费输入不得长期留在 incoming。

## 公共运行入口

在 TP 根目录执行：

```powershell
.\.venv_tp\Scripts\tp-organize-inputs.exe
.\.venv_tp\Scripts\tp-pipeline-refresh-data.exe --input-month YYYYMM --update-mode both --dry-run
```

确认输入清单、目标月份和 dry-run QA 后，去掉 `--dry-run` 正式运行。完整顺序和参数见 `11_docs/PIPELINE_OPERATIONS.md`。

`tp_data.monthly_update` 是当前包内实现；`monthly_prod.ipynb` 直接导入该包，用作人工检查面板。不得恢复或执行 `00_screen` 下的本地兼容脚本。

## 输出与证据

| 类型 | 位置 |
| --- | --- |
| 月更 QA | `qa/` |
| 输入清单 | `production_inputs/manifests/` |
| 数据库 profile | `production_inputs/profiles/` |
| 写入前备份 | `backups/` |
| Pipeline manifest | `artifacts/pipeline_runs/manifests/refresh_data/` |
| Run Card | `artifacts/pipeline_runs/experiments/` |

正式验收必须检查目标日期、行数变化、唯一键、schema、关键缺失率和 manifest 状态，不能只看退出码或文件时间。

## 详细说明

- `说明文档/Screen_Agg数据库字典.md`：FactSet 模板字段和公式口径。
- `说明文档/screen_returns_context.md`：Screen/returns 语义、连接键和 PIT 注意事项。
- `production_inputs/README.md`：输入目录、命名和归档规则。

旧流程图和旧实时统计已归档，不再作为运行说明。

## 维护状态

生产数据边界。活跃源码、测试和跨项目产物分别位于 `src/`、`tests/` 和 `artifacts/`。

# 数据与生产流程

最后更新：2026-06-30

`00_screen/` 是 TP 的核心数据生产层。所有下游项目应读取同一套 canonical 数据文件，并通过 `tp_core` 或统一环境变量覆盖路径。

## Canonical 数据文件

| 数据集 | 路径 | 说明 |
| --- | --- | --- |
| Screen 全历史主表 | `C:\GoogleDrive\TP\00_screen\screen_aggregate.parquet` | 月度证券横截面宽表 |
| 最新月度快照 | `C:\GoogleDrive\TP\00_screen\last_screen.parquet` | 主表中最新 `Date` 的切片 |
| 日频收益矩阵 | `C:\GoogleDrive\TP\00_screen\returns.parquet` | 行为交易日、列为 `Company SEDOL` |
| 近 5 年 Screen | `C:\GoogleDrive\TP\00_screen\screen_aggregate_5Y.parquet` | 给轻量下游使用的派生子集 |

详细路径规则见 [`../DATA_SOURCES.md`](../DATA_SOURCES.md)，主键和字段语义见 [`../DATA_CONTRACT.md`](../DATA_CONTRACT.md)。

## 月更输入入口

新的月度输入只放在：

```text
00_screen/production_inputs/incoming/YYYYMM/
├── screen/
├── returns/
└── ciq/
```

旧入口 `00_screen/monthly`、`00_screen/returns`、`00_screen/ciq` 已进入 `00_screen/_quarantine_20260629/`，只作为短期回滚参考，不再作为生产读取目录。

## 标准月更顺序

1. 把当月原始输入放入 `00_screen/production_inputs/incoming/YYYYMM/`。
2. 运行输入整理：

```powershell
python -m tp_core.production_inputs
```

3. 检查 `00_screen/production_inputs/manifests/input_inventory_latest.json`，确认文件内容日期、命名不一致和重复来源。
4. 运行月更。推荐通过 pipeline 包装入口执行，这样会额外生成统一 manifest：

```powershell
python -m tp_pipelines.refresh_data --input-month YYYYMM --update-mode both
```

底层脚本仍可直接运行，用于排错或兼容 notebook：

```powershell
python -m tp_data.monthly_update --input-month YYYYMM --update-mode both
```

5. 检查 QA JSON、`artifacts/pipeline_runs/manifests/refresh_data/refresh_data_latest.json`、`*_latest.md` 摘要和最新数据概况。

## 幂等规则

- `returns.parquet` 按日期索引合并；同日期增量覆盖同日期旧值，不追加重复日期。
- `screen_aggregate.parquet` 按目标月份替换对应月度切片；非目标月份不应被误删。
- CIQ merge 按 `(ISIN, Date)` 对齐，只用 CIQ 值填补主表空值，不覆盖已有非空值。
- 主表写入前会生成带时间戳和操作名的备份。


## 备份目录

所有 screen 月更相关备份统一放在 `00_screen/backups/`：

| 子目录 | 内容 |
| --- | --- |
| `backups/screen_aggregate/` | `screen_aggregate.parquet` 主表写入前备份 |
| `backups/returns/` | `returns.parquet` 写入前备份 |
| `backups/derived/` | `last_screen`、`screen_aggregate_5Y` 等派生表快照 |
| `backups/maintenance/` | 字段清理、结构迁移等维护操作前备份 |

旧 `backup_screen/` 与 `bk/` 已合并到 `backups/`；备份只用于回滚，不作为生产读取入口。详细说明见 [`../00_screen/backups/README.md`](../00_screen/backups/README.md)。

## QA 与证据

| 类型 | 位置 | 说明 |
| --- | --- | --- |
| 月更 QA | `00_screen/qa/monthly_update_*.json` | 机器可读审计证据 |
| returns 异常收益治理 | `00_screen/qa/returns_anomaly_governance/` | 极端收益摘要、完整异常明细和人工复核模板 |
| 输入清单 | `00_screen/production_inputs/manifests/input_inventory_latest.json` | 最新输入识别和归档记录 |
| 数据概况 | `00_screen/production_inputs/profiles/latest_database_profile_latest.json` | canonical 数据集概况 |
| 人类可读最新结论 | `00_screen/production_inputs/manifests/*_latest.md` | 只维护 latest，不再创建时间戳 Markdown |
| 流水线 manifest | `artifacts/pipeline_runs/manifests/<step>/*_latest.json` | 数据刷新、信号、候选池、组合、回测、报告的统一运行证据 |

历史产物的保留期限和安全清理命令见 [`../artifacts/pipeline_runs/README.md`](../artifacts/pipeline_runs/README.md)。清理必须先运行默认 dry-run，确认清单后再显式传入 `--apply`。

## 不允许作为生产源的数据

- `screen_aggregate.pkl`、`returns.pkl`。
- 各项目目录下的旧 00_screen/returns 副本。
- `00_screen/_quarantine_20260629/` 中的历史入口。
- notebook 里写死的旧路径。

如果某个旧项目必须临时读取历史副本，应在项目 README 中明确标注“历史复现用途”，并优先迁移到 `tp_core.io`。

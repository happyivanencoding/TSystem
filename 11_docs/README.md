# TP 文档中枢

本文档是 `C:\GoogleDrive\TP` 的固定文档入口。原则是：少数权威文档维护当前事实，历史审计和实验记录只作为参考，不再反向决定生产流程。

## 文档分层

| 层级 | 位置 | 职责 |
| --- | --- | --- |
| 工作区入口 | [`../README.md`](../README.md) | 告诉读者先读哪些文档 |
| 对话接手层 | [`../_context/`](../_context/) | 当前接手状态、handoff、子项目提示和 skill 审视 |
| 文档中枢 | `11_docs/` | 已部署架构、运行手册、研究方法和文档治理 |
| 数据权威文档 | [`../DATA_SOURCES.md`](../DATA_SOURCES.md)、[`../DATA_CONTRACT.md`](../DATA_CONTRACT.md) | canonical 路径、主键、日期、字段族、共享 API |
| Screen 生产文档 | [`../00_screen/README.md`](../00_screen/README.md)、[`../00_screen/production_inputs/README.md`](../00_screen/production_inputs/README.md) | 数据边界、输入归档、QA、回滚边界 |
| 流水线文档 | [`PIPELINE_OPERATIONS.md`](PIPELINE_OPERATIONS.md) | 单环入口、总入口、manifest 和标准产物 |
| V2 数据架构 | [`DATA_ARCHITECTURE_V2.md`](DATA_ARCHITECTURE_V2.md) | Canonical Lake、catalog、mart、artifact、Run Card 与存储边界 |
| DuckDB 运维 | [`DUCKDB_OPERATIONS.md`](DUCKDB_OPERATIONS.md) | release、marts、writer、并发、回滚和 retention |
| DuckDB 迁移 runbook | [`DUCKDB_MIGRATION_RUNBOOK.md`](DUCKDB_MIGRATION_RUNBOOK.md) | Phase 状态、authority evidence、activation 与 retirement 门禁 |
| 项目文档 | 各项目 `README.md` 或 `11_docs/README.md` | 只描述本项目用途、入口和与 canonical 数据的关系 |
| 历史审计 | `11_docs/archive/`、旧 summary、quarantine 中的 manifest | 只保留证据，不作为当前操作步骤 |
| 根目录文件规则 | [`DOCUMENTATION_GOVERNANCE.md`](DOCUMENTATION_GOVERNANCE.md) | 规定根目录允许保留哪些非文件夹文件 |

## 常用入口

| 问题 | 去哪里看 |
| --- | --- |
| 新对话接手当前 TP 工作 | [`../_context/README.md`](../_context/README.md)、[`../_context/active_work.md`](../_context/active_work.md) |
| TP skill 触发词、边界和定期审视 | [`../_context/skill_review.md`](../_context/skill_review.md) |
| 当前架构和每个项目是做什么的 | [`INVESTMENT_PLATFORM_MAINLINE.md`](INVESTMENT_PLATFORM_MAINLINE.md) |
| TP 专用 Python 环境怎么用 | [`ENVIRONMENT.md`](ENVIRONMENT.md) |
| 按生产主线看数据、信号、组合、回测和报告 | [`INVESTMENT_PLATFORM_MAINLINE.md`](INVESTMENT_PLATFORM_MAINLINE.md) |
| 月更 00_screen/returns/CIQ 应该怎么跑 | [`PIPELINE_OPERATIONS.md`](PIPELINE_OPERATIONS.md) |
| 主流水线和单环入口怎么跑 | [`PIPELINE_OPERATIONS.md`](PIPELINE_OPERATIONS.md) |
| 当前 canonical 数据到底是哪几份 | [`../DATA_SOURCES.md`](../DATA_SOURCES.md) |
| `screen_aggregate` 和 `returns` 的主键、日期、SEDOL 规则是什么 | [`../DATA_CONTRACT.md`](../DATA_CONTRACT.md) |
| 研究和回测方法怎么记录 | [`RESEARCH_METHODS.md`](RESEARCH_METHODS.md) |
| 已部署的 Provider、Run Card、执行模拟、News 和 Copilot 能力 | [`PLATFORM_CAPABILITIES.md`](PLATFORM_CAPABILITIES.md) |
| 当前统一回测引擎和旧版本处理 | [`BACKTEST_ENGINE.md`](BACKTEST_ENGINE.md) |
| 已部署架构与项目职责 | [`INVESTMENT_PLATFORM_MAINLINE.md`](INVESTMENT_PLATFORM_MAINLINE.md) |
| 哪些旧目录已经冻结、如何防止新代码引用 | [`LEGACY_POLICY.md`](LEGACY_POLICY.md) |
| 统一信号表字段和导出规则 | [`SIGNAL_SCHEMA.md`](SIGNAL_SCHEMA.md) |
| 以后新文档怎么命名、哪些文档不要再新建 | [`DOCUMENTATION_GOVERNANCE.md`](DOCUMENTATION_GOVERNANCE.md) |
| 根目录为什么还有 md、哪些文件能留在根目录 | [`DOCUMENTATION_GOVERNANCE.md`](DOCUMENTATION_GOVERNANCE.md) |
| 历史 documentation 计划、旧 cartographie、旧月更审计、零散 md 归档在哪里 | [`archive/`](archive/) |

## 当前注意事项

- 不再从旧目录 `00_screen/monthly`、`00_screen/returns`、`00_screen/ciq` 读取生产输入；这些历史入口已经进入 `00_screen/_quarantine_20260629/`。
- 不再维护多个生产版 `screen_aggregate` 或 `returns`。旧 `.pkl`、旧 parquet 和 notebook 内硬编码路径只允许作为历史参考。
- 冻结目录统一进入 `99_archive/`；当前入口检查使用 `tp-check-legacy-references`。
- 展示/报告项目共享 `presentation_layer` repository；模型信号统一进入 `artifacts/signals/`；主流水线通过 `tp-pipeline-*` 控制台入口运行。
- 外部参考模板库 `08_company_analysis/Inspiration_Claude` 已归档到 `99_archive/external_references_20260705/Inspiration_Claude`，不纳入 TP 生产文档体系。
- 文档描述默认使用中文；项目里已有英文或法文技术注释可以保留，但面向使用者的说明应逐步中文化。
- 根目录非文件夹文件只保留入口、数据契约和工程配置；普通说明文档归入 `11_docs/` 或项目 README，历史材料归入 `11_docs/archive/`。

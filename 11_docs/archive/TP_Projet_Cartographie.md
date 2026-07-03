# TP 项目 Cartographie（历史审计快照）

审查日期：2026-06-29  
状态：历史审计材料，不再作为当前项目地图或运行手册。

当前项目地图请使用：[`11_docs/PROJECTS.md`](../PROJECTS.md)。  
当前数据与生产流程请使用：[`11_docs/DATA_AND_PRODUCTION.md`](../DATA_AND_PRODUCTION.md)。

## 本文件为何保留

本文件最初用于记录 `C:\GoogleDrive\TP` 的一次全目录实测 cartographie，其中包含项目规模、核心数据形状和当时的 P0/P1/P2 建议。后续已经完成多项修复，因此旧正文中的部分判断不再适合作为当前事实来源。

为避免误导，本文件只保留历史上下文和跳转入口；当前事实统一维护在 `11_docs/` 中枢、`DATA_SOURCES.md`、`DATA_CONTRACT.md` 和 `00_screen/README.md`。

## 已更新的重要结论

| 原审计问题 | 当前状态 |
| --- | --- |
| 月更依赖旧 `00_screen/monthly`、`00_screen/returns`、`00_screen/ciq` | 已切换到 `00_screen/production_inputs/incoming/YYYYMM/screen|returns|ciq` |
| CIQ merge 依赖 notebook 手动 cell | 已移入 `run_monthly_update()`；可用 `--ciq-dir` 或 `--skip-ciq` 控制 |
| 备份文件可能同日覆盖 | 已改为带时间戳和操作名的备份文件 |
| 月更 QA 分散在 notebook 输出 | 已生成机器可读 QA JSON，并保留固定 `*_latest.md` 摘要 |
| VaR/Beta 风险列未落库 | 已修复并验证最新月非空；包括 VaR、SXXP Beta 和 Regional Benchmark Beta |
| EM Cluster 字段继续存在 | 已清理停用；后续不再作为生产字段 |
| 多版本 00_screen/returns 容易混用 | 已建立 `DATA_SOURCES.md`、`tp_core.io` 和统一 canonical 路径 |

## 当前权威文档

| 主题 | 文档 |
| --- | --- |
| 全工作区入口 | [`README.md`](../../README.md) |
| 小项目 cartographie | [`11_docs/PROJECTS.md`](../PROJECTS.md) |
| 数据与月更生产流程 | [`11_docs/DATA_AND_PRODUCTION.md`](../DATA_AND_PRODUCTION.md) |
| 统一数据源 | [`DATA_SOURCES.md`](../../DATA_SOURCES.md) |
| 数据契约 | [`DATA_CONTRACT.md`](../../DATA_CONTRACT.md) |
| Screen 月更手册 | [`00_screen/README.md`](../../00_screen/README.md) |
| 生产输入规范 | [`00_screen/production_inputs/README.md`](../../00_screen/production_inputs/README.md) |
| 文档维护规则 | [`11_docs/DOCUMENTATION_GOVERNANCE.md`](../DOCUMENTATION_GOVERNANCE.md) |

## 历史审计材料

如果需要追溯 2026-06-29 当天的详细处理笔记，可查看：

- [`screen_monthly_update_audit.md`](screen_monthly_update_audit.md)：月更管线历史审计。
- [`00_screen/production_inputs/manifests/workflow_switch_verification_latest.md`](../../00_screen/production_inputs/manifests/workflow_switch_verification_latest.md)：入口切换验证。
- [`00_screen/production_inputs/manifests/ciq_content_update_check_latest.md`](../../00_screen/production_inputs/manifests/ciq_content_update_check_latest.md)：CIQ 内容更新验证。
- [`00_screen/production_inputs/manifests/screen_cleanup_audit_latest.md`](../../00_screen/production_inputs/manifests/screen_cleanup_audit_latest.md)：screen 目录清理审计。

## 维护规则

不要在本文件继续追加新的生产结论。后续 cartographie 变更应更新 `11_docs/PROJECTS.md`；数据生产变更应更新 `11_docs/DATA_AND_PRODUCTION.md`、`DATA_SOURCES.md`、`DATA_CONTRACT.md` 或 `00_screen/README.md`。


# Documentation 更新计划

最后更新：2026-06-29  
状态：当前计划索引。详细规则已经迁入 `11_docs/` 中枢，本文件只保留执行路线和待办清单。

## 当前文档体系

| 职责 | 当前文件 |
| --- | --- |
| 文档中枢 | [`11_docs/README.md`](../README.md) |
| 小项目地图 | [`11_docs/PROJECTS.md`](../PROJECTS.md) |
| 数据与生产流程 | [`11_docs/DATA_AND_PRODUCTION.md`](../DATA_AND_PRODUCTION.md) |
| 研究方法 | [`11_docs/RESEARCH_METHODS.md`](../RESEARCH_METHODS.md) |
| 文档治理规则 | [`11_docs/DOCUMENTATION_GOVERNANCE.md`](../DOCUMENTATION_GOVERNANCE.md) |
| 数据源统一规则 | [`DATA_SOURCES.md`](../../DATA_SOURCES.md) |
| 数据契约 | [`DATA_CONTRACT.md`](../../DATA_CONTRACT.md) |

## 已完成

- 建立根目录 `README.md` 作为工作区入口。
- 建立 `11_docs/` 中枢，覆盖项目地图、数据生产、研究方法和文档治理。
- 将 `TP_Projet_Cartographie.md` 降级为历史审计快照，当前 cartographie 迁入 `11_docs/PROJECTS.md`。
- 将 `screen_monthly_update_audit.md` 标注为历史审计，并修正已经过期的 P0 状态、生产输入、VaR/Beta 和 EM Cluster 描述。
- 更新 `00_screen/README.md` 与 `00_screen/说明文档/monthly_update_workflow.md`，使其指向新生产入口和中枢文档。
- 保留 `00_screen/production_inputs/manifests/*_latest.md`，时间戳 Markdown 已进入 quarantine。
- 建立 `07_backtest_code/` 作为传统代码版回测主线，原 Web/API/GUI 前端入口和旧项目重复核心已隔离。
- 冻结 `ML/`、`ML第一版/`、`回测第一版/`、`factsetProd第一版/`、`技术分析_V1/` 到 `99_archive/frozen_20260629/`。
- 建立统一信号表 schema，并导出 `ml_signals`、`technical_signals`、`regime_risk_budget`。
- 建立 `08_presentation_layer/` 共享数据 repository。
- 建立 `02_pipelines/` 主流水线第一版，并输出 `05_candidates/`、`06_portfolios/`、`09_reports/` 和 `10_pipeline_runs/manifests/`。
- 建立 `00_项目主线索引/` 作为不破坏代码路径的编号视图。
- 完成 notebook 清理第一轮：根目录测试 notebook、早期 `backtest/`、早期 `cyc/`、旧深度学习 pipeline 已归档或冻结；`03_ml_enhanced` Monitoring 已合并。

## 当前仍需跟进

| 优先级 | 事项 | 建议动作 |
| --- | --- | --- |
| P1 | 回测入口统一 | 已建立 `07_backtest_code/`；`backtest_wep_app` 的 Web/API/Streamlit/Docker 入口、重复回测核心、`Backtest_GUI` 的 PySide6 入口和源码副本已隔离，旧 `.pkl` 数据副本也已隔离 |
| P1 | `03_ml_enhanced` 与 `03_technical_analysis` 的 00_screen/returns 副本 | 已隔离到各自 `_quarantine_20260629/legacy_data_copies/`；notebook 默认改为 canonical 读取；`03_ml_enhanced/test_bench.ipynb` 已隔离到 `legacy_notebooks/` |
| P1 | `06_optimiser/`、`99_optimiseur_legacy/`、`cyc/` 缺少最小 README | `06_optimiser/` 已成为唯一 Python 优化器并补 README；`99_optimiseur_legacy/` 文件已冻结，只留历史说明；`cyc/` 待定 |
| P1 | 部分项目 README 仍有英文或法文描述 | 面向使用者的说明逐步中文化，代码注释可保留原语言 |
| P2 | `03_technical_analysis/data/screen_returns_context.md` 与 screen 文档部分重复 | 保留技术分析特有 `patterns.parquet` 内容，00_screen/returns 语义链接到 canonical 文档 |
| P2 | pipeline 后续增强 | 已建立第一版单环/总入口；下一步补 ML 训练/预测 CLI、复杂优化约束和正式报告模板 |
| P2 | 剩余 notebook 审视 | 已处理明显旧实验；保留 `00_screen/monthly_prod.ipynb`、`03_ml_enhanced/Pipeline.ipynb`、`03_ml_enhanced/Monitoring.ipynb`、`03_technical_analysis` notebooks、`08_company_analysis/日常分析模板.ipynb`，后续按使用频率再决定是否脚本化 |
| P2 | backtest UI 专题文档较多 | 已不作为主线；后续只保留必要历史说明，避免继续维护 UI 专题文档 |

## 以后不要做的事

- 不要再新增带时间戳的 Markdown 审计文件。
- 不要让历史审计文件承担当前运行手册职责。
- 不要在小项目中复制 `screen_aggregate` / `returns` 的数据契约说明；统一链接到 `DATA_SOURCES.md` 和 `DATA_CONTRACT.md`。


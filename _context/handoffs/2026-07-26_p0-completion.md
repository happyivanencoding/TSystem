# P0 基础边界完成任务

> 后续状态：本 handoff 是 P0 验收时快照。兼容 facade 已在同日后续工作区整理中退役；当前事实以 `11_docs/INVESTMENT_PLATFORM_MAINLINE.md` 和 `2026-07-26_workspace-cleanup.md` 为准。

## 日期

2026-07-26

## 任务目标

完成用户定义的全部 P0：规范 Python 包边界、拆分指定热点、建立默认且完整的 Experiment Recorder，并通过代码扫描、CI、Code Review Graph、全量测试和运行检查逐项验收。

## 验收清单

- [x] 活跃源码通过 `src/` 正常包和 console entry point 暴露。
- [x] 活跃代码没有 `sitecustomize`、`sys.path` 注入或按文件路径导入。
- [x] 跨包关系由显式公共 API、类型和协议表达。
- [x] archive、runs、outputs 和生成资产已从 CRG、ruff、mypy、pytest discovery 与 CI 主路径排除。
- [x] CRG 社区和跨社区依赖可见且可解释。
- [x] Dashboard 后端拆为 repository、domain service、API router、job controller、view model。
- [x] React 前端拆为 page、hook、API client、domain component。
- [x] SecurityListConstructor 拆出 universe、neutralization、weighting、optimizer adapter、drift、persistence。
- [x] Optimizer 拆出 problem builder、objective、constraint、solver、audit，并保留 `optimize_portfolio`。
- [x] Pipeline 使用 typed step config 与 registry/DAG，不再手工拼装 `Namespace`。
- [x] 每个生产/研究运行默认写入完整 Run Card，并包含用户要求的全部字段、lineage 和决定。

## 当前基线

- `src/` 已有规范边界 `tp_core`、`tp_data`、`tp_pipelines`、`tp_research`、`tp_portfolio`、`tp_backtest`、`tp_reporting`；`backtest_code` 只保留弃用兼容 facade。
- 活跃业务源码和测试中的路径注入、按文件路径导入、tracked `sitecustomize.py` 已清零。
- 4 个旧研究 Notebook 的 `sys.path.insert` 启动片段也已移除；冗余的 paused `.bak` 研究脚本已删除。
- 共享研究执行器已迁入 `tp_research`，因子研究报告与可视化渲染已迁入 `tp_reporting`。
- 46 个研究 workflow 已迁入 `tp_research.workflows`，编号目录保留薄兼容入口。
- Dashboard 后端已有实际 repository/domain/API/jobs/view-model 模块；React `App.jsx` 已成为薄 page 入口，并拆出 hooks/API/domain components。
- `SecurityListConstructor` facade 只保留主编排；Optimizer 与 Pipeline 已按目标职责拆分。
- Recorder schema v2 已强制覆盖 run-all、独立步骤、Backtest 和 46 个 research workflow；smoke Run Card 已逐字段验收。
- CRG 独立环境补齐 `igraph` 后，用 Leiden 完整重建：157 communities、15 条跨社区边、0 warning；数据库中被排除路径的 node/edge 命中均为 0。
- P1 清理改动尚未提交，必须保留并在其上继续。

## 关键决策

- 编号目录继续作为数据、配置、测试、Notebook、前端和产物边界；规范 Python 实现只放 `src/`。
- 兼容入口在完成两个连续生产周期验证前继续保留，但仓库内部不得新增调用。
- 架构完成以全文件职责和默认运行路径为准，不以单个 facade 函数变短为准。

## 验证方式

- `rg` 扫描路径注入、文件路径导入和旧入口引用。
- `pytest`、Vitest、Vite build、安装包边界检查和 live Dashboard API/static 检查。
- Code Review Graph 增量更新、架构社区和热点检查。
- 生成至少一个完整 smoke Run Card，并逐字段检查。

## 产物路径

- 本文件持续记录跨轮状态；正式代码和测试位于仓库现有主线。

## 风险/未完成

- P0 验收项全部完成。完整 Python 回归为 175 passed；Vitest、Vite build、live Dashboard API/static、规范包导入、console entry point、ruff 新增模块检查、pytest discovery、mypy 排除样例和 `git diff --check` 均通过。
- 旧兼容 facade 仍按既定 P1 策略保留两个连续生产周期；它们不再承载活跃实现，也不构成 P0 未完成项。

## 下次建议

- 运行两个连续生产周期验证后，按 P1 计划退役剩余兼容 facade；不要自动 commit/push。

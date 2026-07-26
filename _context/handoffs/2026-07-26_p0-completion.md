# P0 基础边界完成任务

## 日期

2026-07-26

## 任务目标

完成用户定义的全部 P0：规范 Python 包边界、拆分指定热点、建立默认且完整的 Experiment Recorder，并通过代码扫描、CI、Code Review Graph、全量测试和运行检查逐项验收。

## 验收清单

- [ ] 活跃源码通过 `src/` 正常包和 console entry point 暴露。
- [ ] 活跃代码没有 `sitecustomize`、`sys.path` 注入或按文件路径导入。
- [ ] 跨包关系由显式公共 API、类型和协议表达。
- [x] archive、runs、outputs 和生成资产已从 CRG、ruff、mypy、pytest discovery 与 CI 主路径排除。
- [ ] CRG 社区和跨社区依赖与包边界一致且可解释。
- [ ] Dashboard 后端拆为 repository、domain service、API router、job controller、view model。
- [ ] React 前端拆为 page、hook、API client、domain component。
- [ ] SecurityListConstructor 拆出 universe、neutralization、weighting、optimizer adapter、drift、persistence。
- [ ] Optimizer 拆出 problem builder、objective、constraint、solver、audit，并保留 `optimize_portfolio`。
- [ ] Pipeline 使用 typed step config 与 registry/DAG，不再手工拼装 `Namespace`。
- [ ] 每个生产/研究运行默认写入完整 Run Card，并包含用户要求的全部字段、lineage 和决定。

## 当前基线

- `src/` 已有 `tp_core`、`tp_data`、`tp_pipelines`、`tp_portfolio`、`tp_experiments`、`tp_models`、`backtest_code`、`presentation_layer`。
- 活跃范围仍有 35 个路径注入文件和 5 个按文件路径导入文件。
- `system_dashboard.py` 7036 行，React `App.jsx` 2927 行。
- `SecurityListConstructor` 1134 行；Pipeline registry 仍构造大量 `argparse.Namespace`。
- Recorder schema 已建立，但独立步骤和普通 Backtest 默认不强制记录，当前没有生产 Run Card。
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

- 当前任务处于基线阶段，除工具排除外其余清单仍需完成。

## 下次建议

- 先读取本文件和 `git status --short`，从第一个未完成验收项继续，不重复已通过检查。

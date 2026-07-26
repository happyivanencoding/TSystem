# 2026-07-26 工作区整理交接

> 状态说明：本文已合并同日后续实施结果。当前入口和安全边界以
> `11_docs/INVESTMENT_PLATFORM_MAINLINE.md` 与
> `11_docs/PLATFORM_CAPABILITIES.md` 为准。

## 已完成

- 活跃 Python 源码统一到 `src/`，测试统一到 `tests/`。
- 删除纯兼容空壳：`01_tp_core/`、`02_pipelines/`、`06_optimiser/`、`src/backtest_code/`。
- 删除模型资源目录中的薄 Python wrapper；旧研究脚本和 quarantine 归档到 `99_archive/compatibility_retirement_20260726/`。
- 标准产物迁入 `artifacts/signals`、`artifacts/candidates`、`artifacts/portfolios`、`artifacts/reports`、`artifacts/pipeline_runs`。
- 回测 YAML profile 迁入 `config/backtest`；应用日志迁入 `artifacts/logs`。
- Dashboard runtime 与 scratch 分别迁入 `artifacts/dashboard_work` 和 `artifacts/scratch/codex_tmp`。
- Python、Dashboard registry/checks、CI、pytest、ruff、mypy、CRG ignore 和活跃文档已同步。
- 保留策略覆盖 manifests、experiments、backtests、Dashboard smoke 输出、launch records 与 scratch 工作区；默认 dry-run。

## 后续已完成

- 约 74 GB、约 9.3 万文件的旧研究库已按逐文件 inventory 和抽样内容哈希无损迁入 `artifacts/research/runs/historical/`。
- 迁移清单位于 `artifacts/research/migrations/`；历史库只读并受保留策略保护。
- 配置化研究统一通过 `tp-research` 运行，新结果写入 `artifacts/research/runs/<hypothesis-id>/<run-id>/`。

## 后续状态

- Dashboard 主/子进程已停止，8060 端口已释放，`.tmp_dashboard_work/` 已清除。
- 标准回测产物写入 `artifacts/backtests/runs/`；配置化研究和 Run Card 写入 `artifacts/research/runs/`；历史库只作为显式只读输入。
- 重复架构/生产文档已合并，资源目录兼容入口已完成后续退役。

## 验证

- Python：251 passed、3 skipped。
- Dashboard frontend：Vitest 通过，Vite production build 通过。
- `tp-backtest inspect`：canonical screen/returns 验证通过。
- `tp-check-legacy-references`：活跃代码、配置和文档 0 命中。
- `git diff --check`：通过。
- 活跃 Markdown 相对链接：0 个断链。
- CRG 排除检查：artifacts、退役空壳和历史 runs 的节点/边命中均为 0。
- 未 commit、未 push。

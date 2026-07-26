# TP 生成产物

本目录统一保存可再生成的运行产物，不放活跃 Python 源码。

| 目录 | 内容 |
| --- | --- |
| `signals/` | 标准化信号表 |
| `candidates/` | 最新候选池 |
| `portfolios/` | 最新目标权重 |
| `reports/` | 稳定命名的报告与可视化 |
| `pipeline_runs/` | manifest、Experiment/Recorder 运行证据 |
| `backtests/` | 小型回测辅助产物 |
| `dashboard_work/` | Dashboard 配置、任务队列、日志和 smoke 输出 |
| `logs/` | 应用运行日志 |
| `scratch/` | 临时研究和视觉验收材料 |

这些目录已从 pytest、ruff、mypy、Code Review Graph 和 CI discovery 中排除。历史大体积回测库 `07_backtest_code/runs/` 约 74 GB，因 Google Drive 同步风险暂缓物理迁移；活跃代码只能通过 `tp_core.workspace.BACKTEST_RUNS_DIR` 访问。

运行 `python -m tp_core.artifact_retention` 只会预览保留策略；只有显式增加 `--apply` 才会清理。Dashboard smoke 输出保留 30 天、临时 scratch 工作区保留 90 天，latest 指针和 Git 跟踪文件受保护。

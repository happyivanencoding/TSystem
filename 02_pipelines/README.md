# 02_pipelines

`02_pipelines/` 是 TP 主线的薄编排层。它不重新实现各项目的业务逻辑，只负责把已有入口按统一规则串起来，并为每一步写入机器可读 manifest。

## 设计原则

- 每一环都可以单独运行、重跑和调试。
- 每一环都有明确输入、标准输出、校验和 manifest。
- 标准产物使用固定 latest 路径覆盖写入，避免重复数据累积。
- 时间戳证据写入 `10_pipeline_runs/manifests/<step>/`，不生成临时 Markdown 审计文件。
- `run_all` 只做顺序编排，不把业务逻辑揉成一个大脚本。

## 单环入口

| 环节 | 命令 | 主要输入 | 标准输出 |
| --- | --- | --- | --- |
| 数据刷新 | `python -m 02_pipelines.refresh_data --input-month YYYYMM` | `00_screen/production_inputs/incoming/YYYYMM/` | `00_screen/screen_aggregate.parquet`、`00_screen/returns.parquet`、QA JSON |
| 信号导出 | `python -m 02_pipelines.export_signals --as-of YYYY-MM-DD` | canonical screen、技术 patterns、regime output | `04_signals/*.parquet` |
| 候选池 | `python -m 02_pipelines.build_candidates --as-of YYYY-MM-DD` | `04_signals/*.parquet`、`00_screen/last_screen.parquet` | `05_candidates/latest_candidates.parquet` |
| 组合优化 | `python -m 02_pipelines.optimize_portfolio --as-of YYYY-MM-DD` | 候选池、旧组合可选 | `06_portfolios/latest_target_weights.parquet` |
| 回测 | `python -m 02_pipelines.run_backtest --inspect-only` | canonical screen/returns、backtest profile | `07_backtest_code/runs/` |
| 报告 | `python -m 02_pipelines.generate_report` | 最新 manifest 和标准产物 | `09_reports/latest_pipeline_report.md` |

## 总入口

月更主线可以一键运行：

```powershell
python -m 02_pipelines.run_all --input-month YYYYMM --as-of YYYY-MM-DD
```

调试时可以跳过较重或有写主库风险的环节：

```powershell
python -m 02_pipelines.run_all --skip-refresh-data --skip-backtest
python -m 02_pipelines.run_all --dry-run-data --inspect-only-backtest
```

## Manifest

每次运行都会写两份 JSON：

- `10_pipeline_runs/manifests/<step>/<step>_YYYYMMDD_HHMMSS.json`
- `10_pipeline_runs/manifests/<step>/<step>_latest.json`

manifest 记录参数、输入文件概况、输出文件概况、校验结果、运行耗时和错误栈。日常先看 latest；排查历史问题时再看时间戳文件。

## 当前实现边界

- `refresh_data` 调用 `00_screen/monthly_update.py::run_monthly_update()`。
- `export_signals` 调用 `03_ml_enhanced`、`03_technical_analysis`、`03_regime_model` 的现有导出函数。
- `build_candidates` 当前使用 ML 与技术信号 percentile 的可解释组合分数。
- `optimize_portfolio` 当前是 baseline 权重生成器，支持分数加权、等权、单股上限和旧组合换手估算；更复杂的行业/国家/风险约束后续继续收敛到 `06_optimiser/` 或 `tp_core.optimization`。
- `run_backtest` 包装 `07_backtest_code/run_backtest.py`，默认可用 `--inspect-only` 做轻量校验。

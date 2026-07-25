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
| 补充数据 | `python -m 02_pipelines.refresh_supplemental_data --source fred --dry-run` | 官方免费 API、字段级配置、证券标识映射 | `00_screen/supplemental/` 影子分区、覆盖率与供应商门槛 |
| ML 刷新 | `python -m 02_pipelines.refresh_ml --inspect-only` | canonical screen、ML_Enhanced CLI | `Score ML` 覆盖检查；显式运行时更新 screen 和 `04_signals/ml_signals.parquet` |
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
python -m 02_pipelines.run_all --skip-refresh-data --refresh-supplemental-data --supplemental-source fred --supplemental-dry-run --skip-export-signals --skip-build-candidates --skip-optimize-portfolio --skip-backtest --skip-report
```

## 补充数据影子层

- `refresh_supplemental_data` 必须显式传入至少一个 `--source`，不会隐式访问外部 API。
- FRED、Alpha Vantage 分别从 `FRED_API_KEY`、`ALPHA_VANTAGE_API_KEY` 读取密钥。
- SEC 要求设置包含联系邮箱的 `SEC_USER_AGENT`；例如 `TP research name@example.com`。
- 可选证券映射 CSV 位于 `00_screen/supplemental/identifiers/security_identifiers.csv`，字段为
  `ISIN,CIK,LEI,AlphaSymbol,Currency`。美国普通 ticker 可通过 SEC 官方映射自动解析 CIK。
  Alpha Vantage 仅自动采用美国标准 ticker；非美市场必须显式填写其支持的 ticker，运行时会
  忽略直接复制的 FactSet 内部 `Symbol`。
- 原始响应不可变保存，标准化 Parquet 按 payload hash 幂等落盘；`--resume` 从来源 checkpoint
  继续。月末解析只使用 `available_at <= Date` 的记录。
- 默认只写 `resolved/*_latest.parquet`、`screen_sidecar_latest.parquet` 和 `qa/`，不会修改
  `screen_aggregate.parquet`。独立入口的 `--promote-to-canonical` 还必须满足连续三期 QA，
  且字段配置显式设置 `promote_enabled=true`；`run_all` 永不传递 promotion。

## Manifest

每次 production 运行都会写两份 JSON：

- `10_pipeline_runs/manifests/<step>/<step>_YYYYMMDD_HHMMSS.json`
- `10_pipeline_runs/manifests/<step>/<step>_latest.json`

`--run-type smoke|inspect` 会写到 `<step>_<run_type>_YYYYMMDD_HHMMSS.json` 和 `<step>_<run_type>_latest.json`，不覆盖 production latest 指针。

manifest 记录参数、run_type、输入文件概况、输出文件概况、校验结果、运行耗时和错误栈。日常先看 production latest；排查历史问题或健康检查时再看对应 run_type 的时间戳文件。

## 当前实现边界

- `refresh_data` 调用 `00_screen/monthly_update.py::run_monthly_update()`。
- `refresh_ml` 调用 `03_ml_enhanced.cli`，默认可用 `--inspect-only` 做轻量检查；写主库的 Score ML 刷新必须显式运行。
- `export_signals` 调用 `03_ml_enhanced`、`03_technical_analysis`、`03_regime_model` 的现有导出函数。
- `build_candidates` 当前使用证券 alpha、国家/行业配置倾斜和 Regime 风险预算乘数的分层可解释组合分数。
- `optimize_portfolio` 只调用 `06_optimiser/optimizer.py::optimize_portfolio()`；目标函数、持仓与换手约束、TE/score 边界、分组及一般线性约束、求解器回退和 optimizer metadata 均由这一公开 API 负责。
- `run_backtest` 包装 `07_backtest_code/run_backtest.py`，默认可用 `--inspect-only` 做轻量校验。

# TP 流水线最新状态报告

生成时间：2026-06-30T06:09:04

## 步骤状态

| 步骤 | 状态 | 最近完成时间 | 秒数 | 未通过校验 |
| --- | --- | --- | ---: | --- |
| `refresh_data` | OK | 2026-06-30T00:45:48 | 0.184 |  |
| `export_signals` | OK | 2026-06-30T00:53:45 | 1.057 |  |
| `build_candidates` | OK | 2026-06-30T00:53:45 | 0.153 |  |
| `optimize_portfolio` | OK | 2026-06-30T00:53:45 | 0.018 |  |
| `run_backtest` | OK | 2026-06-30T06:07:54 | 121.803 |  |
| `generate_report` | OK | 2026-06-30T00:53:45 | 0.003 |  |
| `run_all` | OK | 2026-06-30T00:53:45 | 1.24 |  |

## 标准产物

| 产物 | 状态 | 说明 |
| --- | --- | --- |
| `04_signals/` | 存在 | 统一信号表目录 |
| `05_candidates/latest_candidates.parquet` | 存在 | 最新候选池 |
| `06_portfolios/latest_target_weights.parquet` | 存在 | 最新目标权重 |

## 使用原则

- 每个步骤可以单独运行和重跑。
- 标准产物使用固定 latest 路径覆盖写入，避免重复数据累积。
- 每次运行的证据写入 `10_pipeline_runs/manifests/<step>/`。
- 旧目录和 quarantine 内容只作为历史参考，不参与新代码引用。

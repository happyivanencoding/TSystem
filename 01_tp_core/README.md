# 01_tp_core

## 定位

`tp_core` 是 TP 工作区的共享基础包，用来集中维护 canonical 数据路径、读取函数、数据契约、生产输入整理、returns 审计和共享回测入口。

## 数据来源

默认读取 `00_screen/` 下的 canonical 数据文件：

- `00_screen/screen_aggregate.parquet`
- `00_screen/returns.parquet`
- `00_screen/last_screen.parquet`
- `00_screen/screen_aggregate_5Y.parquet`

路径规则见 [`../DATA_SOURCES.md`](../DATA_SOURCES.md)，数据契约见 [`../DATA_CONTRACT.md`](../DATA_CONTRACT.md)。

## 主要模块

| 模块 | 作用 |
| --- | --- |
| `data_sources.py` | canonical 路径和环境变量覆盖 |
| `io.py` | 统一读取 `screen` / `returns` 的函数 |
| `data_contract.py` | 主键、日期、SEDOL 和字段契约校验 |
| `production_inputs.py` | 月更输入识别、标准化命名和归档 |
| `returns_audit.py` | 极端收益审计 |
| `backtesting.py` | 共享 `PtfBuilder` 入口，当前指向 `07_backtest_code` |
| `general_backtest.py` | 通用目标权重表回测核心，返回净值、日收益、执行权重、指标和 manifest |

## 常用命令

```powershell
python -m 01_tp_core.production_inputs
python -m 01_tp_core.returns_audit --report-path C:\GoogleDrive\TP\00_screen\qa\returns_anomaly_audit.json
```

## 维护状态

共享基础包。新增项目如需读取核心数据，应优先从这里导入，而不是在项目内部硬编码路径。

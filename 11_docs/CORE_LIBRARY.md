# TP Core 共享基础包

## 定位

`tp_core` 是 TP 工作区的共享基础包，用来集中维护 canonical 数据路径、读取函数、数据契约、生产输入整理、returns 审计和共享回测入口。唯一实现位于 `src/tp_core/`；原编号兼容目录已退役。

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
| `backtesting.py` | 唯一公开回测 API，导出明确职责对象 |
| `security_nav_engine.py` | 精确漂移、日收益与 NAV 内核 |
| `portfolio_weights.py` | 归一、硬封顶、权重变换和行业目标匹配 |

## 常用命令

```powershell
python -m tp_core.production_inputs
python -m tp_core.returns_audit --report-path C:\GoogleDrive\TP\00_screen\qa\returns_anomaly_audit.json
python -m tp_core.artifact_retention
```

## 维护状态

共享基础包。新增项目如需读取核心数据，应优先从这里导入，而不是在项目内部硬编码路径。

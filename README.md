# TP 工作区入口

本目录由多个量化研究、回测、公司分析和数据生产小项目组成。当前最核心的数据层是 `00_screen/`，所有仍在维护的项目应统一读取同一套 canonical 数据，而不是各自维护 `screen_aggregate` 或 `returns` 的副本。

## 先读这几份

| 目的 | 文档 |
| --- | --- |
| 全目录文档地图 | [`11_docs/README.md`](11_docs/README.md) |
| 已部署架构与项目职责 | [`11_docs/INVESTMENT_PLATFORM_MAINLINE.md`](11_docs/INVESTMENT_PLATFORM_MAINLINE.md) |
| 项目 Python 环境 | [`11_docs/ENVIRONMENT.md`](11_docs/ENVIRONMENT.md) |
| 月更、主流水线与标准产物 | [`11_docs/PIPELINE_OPERATIONS.md`](11_docs/PIPELINE_OPERATIONS.md) |
| Provider、研究治理、执行模拟、News 与 Copilot | [`11_docs/PLATFORM_CAPABILITIES.md`](11_docs/PLATFORM_CAPABILITIES.md) |
| 数据源统一规则 | [`DATA_SOURCES.md`](DATA_SOURCES.md) |
| 数据契约 | [`DATA_CONTRACT.md`](DATA_CONTRACT.md) |
| 文档维护和根目录文件规则 | [`11_docs/DOCUMENTATION_GOVERNANCE.md`](11_docs/DOCUMENTATION_GOVERNANCE.md) |

## 当前生产口径

- `00_screen/screen_aggregate.parquet`：月度 Screen 主表。
- `00_screen/returns.parquet`：日频收益矩阵。
- `00_screen/last_screen.parquet`：最新月度截面。
- `00_screen/screen_aggregate_5Y.parquet`：近 5 年子集。
- `00_screen/production_inputs/incoming/YYYYMM/`：月更输入唯一入口。

项目采用 `src/` 包布局；先执行 `python -m pip install -e .`。新代码应优先使用公开包：

```python
from tp_core.io import read_screen_aggregate, read_returns

screen = read_screen_aggregate()
returns = read_returns()
```


## 当前代码主线

- 流水线主线：`tp_pipelines`（源码位于 [`src/tp_pipelines/`](src/tp_pipelines/)）提供数据刷新、信号、候选池、组合、回测和报告入口。
- 回测主线：[`src/tp_backtest/`](src/tp_backtest/) 是唯一代码版入口；新产物写入 `artifacts/backtests/runs/`。
- 展示/报告主线：`presentation_layer` 是唯一应用入口；`08_presentation_layer/` 只保留前端和应用资源。
- 标准生成产物统一位于 [`artifacts/`](artifacts/)；历史研究证据只读保存在 `artifacts/research/runs/historical/`。
- 已退役兼容入口集中到 `99_archive/compatibility_retirement_20260726/`，不参与测试、CI 或图谱分析。

## 根目录文件规则

根目录只保留工作区入口、数据权威契约和工程配置文件。普通说明文档放入 `11_docs/`，历史审计和旧计划放入 `11_docs/archive/`。详细规则见 [`11_docs/DOCUMENTATION_GOVERNANCE.md`](11_docs/DOCUMENTATION_GOVERNANCE.md)。

## 历史材料

历史 cartographie、月更审计和旧 documentation 更新计划已经归档到 [`11_docs/archive/`](11_docs/archive/)，不再作为当前运行手册。当前入口以 `11_docs/`、`DATA_SOURCES.md`、`DATA_CONTRACT.md` 和 `00_screen/README.md` 为准。

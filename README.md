# TP 工作区入口

本目录由多个量化研究、回测、公司分析和数据生产小项目组成。当前最核心的数据层是 `00_screen/`，所有仍在维护的项目应统一读取同一套 canonical 数据，而不是各自维护 `screen_aggregate` 或 `returns` 的副本。

## 先读这几份

| 目的 | 文档 |
| --- | --- |
| 全目录文档地图 | [`11_docs/README.md`](11_docs/README.md) |
| 编号主线索引与小项目 cartographie | [`11_docs/PROJECTS.md`](11_docs/PROJECTS.md) |
| 项目 Python 环境 | [`11_docs/ENVIRONMENT.md`](11_docs/ENVIRONMENT.md) |
| 核心数据与月更生产流程 | [`11_docs/DATA_AND_PRODUCTION.md`](11_docs/DATA_AND_PRODUCTION.md) |
| 主流水线入口 | [`02_pipelines/README.md`](02_pipelines/README.md) |
| 数据源统一规则 | [`DATA_SOURCES.md`](DATA_SOURCES.md) |
| 数据契约 | [`DATA_CONTRACT.md`](DATA_CONTRACT.md) |
| 文档维护和根目录文件规则 | [`11_docs/DOCUMENTATION_GOVERNANCE.md`](11_docs/DOCUMENTATION_GOVERNANCE.md) |

## 当前生产口径

- `00_screen/screen_aggregate.parquet`：月度 Screen 主表。
- `00_screen/returns.parquet`：日频收益矩阵。
- `00_screen/last_screen.parquet`：最新月度截面。
- `00_screen/screen_aggregate_5Y.parquet`：近 5 年子集。
- `00_screen/production_inputs/incoming/YYYYMM/`：月更输入唯一入口。

新代码应优先使用 `tp_core`：

```python
from tp_core.io import read_screen_aggregate, read_returns

screen = read_screen_aggregate()
returns = read_returns()
```


## 当前代码主线

- 流水线主线：[`02_pipelines/`](02_pipelines/) 提供数据刷新、信号、候选池、组合、回测和报告的单环入口与总入口。
- 回测主线：[`07_backtest_code/`](07_backtest_code/) 是传统代码版入口，替代原 Web app 和 GUI 入口。
- 展示/报告主线：[`08_presentation_layer/`](08_presentation_layer/) 统一承载公司展示、公司分析、组合 dashboard 和报告 wrapper。
- Web/API/GUI 回测前端已进入 `_quarantine_20260629`，只作为可回滚历史参考。

## 根目录文件规则

根目录只保留工作区入口、数据权威契约和工程配置文件。普通说明文档放入 `11_docs/`，历史审计和旧计划放入 `11_docs/archive/`。详细规则见 [`11_docs/DOCUMENTATION_GOVERNANCE.md`](11_docs/DOCUMENTATION_GOVERNANCE.md)。

## 历史材料

历史 cartographie、月更审计和旧 documentation 更新计划已经归档到 [`11_docs/archive/`](11_docs/archive/)，不再作为当前运行手册。当前入口以 `11_docs/`、`DATA_SOURCES.md`、`DATA_CONTRACT.md` 和 `00_screen/README.md` 为准。



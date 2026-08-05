# TP 统一数据源

最后更新：2026-07-26

## Canonical 数据

所有活跃项目必须读取同一套数据：

| 逻辑数据源 | Canonical 路径 |
| --- | --- |
| Screen 历史面板 | `00_screen/screen_aggregate.parquet` |
| 最新 Screen 快照 | `00_screen/last_screen.parquet` |
| 日频收益矩阵 | `00_screen/returns.parquet` |
| 近五年 Screen | `00_screen/screen_aggregate_5Y.parquet` |
| FactSet/ICB 映射 | `00_screen/Transco_FactSet_ICB.xlsx`、`factset_icb_mapping.xlsx` |
| 月更输入 | `00_screen/production_inputs/incoming/YYYYMM/` |
| 补充数据影子层 | `00_screen/supplemental/` |

不要读取项目私有 Screen/returns 副本、旧 `.pkl`、quarantine 或 archive。

## 共享 API

```python
from tp_core.data_sources import (
    LAST_SCREEN_PATH,
    RETURNS_PATH,
    SCREEN_AGGREGATE_5Y_PATH,
    SCREEN_AGGREGATE_PATH,
    SUPPLEMENTAL_DIR,
)
from tp_core.io import read_returns, read_screen_aggregate
```

新代码从 `tp_core.data_sources` 取得路径，通过 `tp_core.io` 读取数据，不在业务模块中拼接 TP 目录。

## 允许的环境覆盖

临时实验只能使用统一环境变量：

| 环境变量 | 含义 |
| --- | --- |
| `TP_ROOT` | TP 工作区根目录 |
| `TP_SCREEN_DIR` | Screen 数据目录 |
| `TP_SCREEN_AGGREGATE_PATH` | Screen 历史面板 |
| `TP_RETURNS_PATH` | 日频收益矩阵 |
| `TP_LAST_SCREEN_PATH` | 最新 Screen |
| `TP_SCREEN_AGGREGATE_5Y_PATH` | 近五年 Screen |
| `TP_PRODUCTION_INPUTS_DIR` | 生产输入根目录 |
| `TP_SUPPLEMENTAL_DIR` | 补充数据根目录 |

环境覆盖必须在运行配置和 Run Card 中记录；不得以 `sys.path`、文件复制或修改源码常量实现数据分叉。

## 生产入口

| 需求 | 当前入口 |
| --- | --- |
| 整理生产输入 | `tp-organize-inputs` |
| 刷新 Canonical 数据 | `tp-pipeline-refresh-data` |
| 导出信号 | `tp-pipeline-export-signals` |
| 生成候选池 | `tp-pipeline-build-candidates` |
| 生成目标权重 | `tp-pipeline-optimize-portfolio` |
| 总流水线 | `tp-pipeline-run-all` |
| Returns 异常审计 | `tp-returns-audit` |
| 旧入口检查 | `tp-check-legacy-references` |

命令由 `python -m pip install -e .` 安装到 `.venv_tp\Scripts\`。详细参数见 `11_docs/PIPELINE_OPERATIONS.md`。

## 数据契约

主键、日期、标识符、点时点可用性和字段族见 `DATA_CONTRACT.md`。校验 API：

```python
from tp_core.data_contract import validate_returns_contract, validate_screen_contract
```

补充数据目录不是第三张 Canonical 表。默认刷新只生成不可变 raw、标准化记录、PIT 月末结果和 QA；晋升 Canonical 必须经过显式配置和连续质量门槛。

## 历史边界

- `00_screen/monthly`、`00_screen/returns`、`00_screen/ciq` 已退役。
- `artifacts/research/runs/historical/` 是只读历史研究证据库，不是 Canonical 数据源或运行入口。
- `99_archive/` 与 `_quarantine_*` 只用于复现或回滚。
- 历史 notebook 中的硬编码路径不构成当前数据源声明。

运行 `tp-check-legacy-references` 确认活跃代码、配置和文档没有恢复旧入口。

## 月度因子推荐研究源

`16_factor_recommendation_model` 只读取本表登记的 `screen_aggregate.parquet`、`returns.parquet` 和版本化配置 `config/region_universes_v1.json`、`config/factor_definitions_v1.json`、`config/model_v1.json`。成员资格按 PIT benchmark weight 选择；ASIA 仅是固定 `JAPAN(NIKKEI) + ASIA_EX_JAPAN(MSCI EM allowlist)` 的 0.5/0.5 research-only union，不把 `Univ ML OTHER` 或整张 MSCI EM 改名为 Asia。

## V2 Canonical Lake 与查询层

V2 的事实存储位于 `00_screen/datasets/screen/` 与 `00_screen/datasets/returns_wide/`，分别按
`year/month` 与 `year` 保存 immutable partition，并由 `00_screen/datasets/manifests/` 的
manifest 与 atomic `current.json` 指向。根目录下的四个宽表继续作为
`compatibility_export`，服务尚未迁移的 legacy consumer，不是新的数据源。

DuckDB release、dashboard mart、signals、candidates、portfolio 和 pipeline/run registry
属于查询或产物层，详见 [`11_docs/DATA_ARCHITECTURE_V2.md`](11_docs/DATA_ARCHITECTURE_V2.md)。
在 `WRITER_CUTOVER_READY` 阶段默认 engine 仍是 `legacy_parquet`；需要验证时显式设置
`TP_DATA_ENGINE=duckdb`、`TP_DUCKDB_PATH` 和 catalog release，不能通过复制文件制造私有
Canonical。

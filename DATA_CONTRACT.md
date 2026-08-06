# TP 数据契约

最后更新：2026-08-06

本文档定义 TP 项目中两张核心 canonical 数据集的统一契约：

- `C:\GoogleDrive\TP\00_screen\screen_aggregate.parquet`
- `C:\GoogleDrive\TP\00_screen\returns.parquet`

可执行契约位于 `tp_core.data_contract`。

## `screen_aggregate.parquet`

| 契约项 | 规则 |
| --- | --- |
| 粒度 | 每个证券、每个月末快照一行 |
| 逻辑主键 | `(ISIN, Date)` 必须唯一 |
| 索引 | `ISIN` 可能作为 parquet index 存储；读取函数必须同时兼容 index 或普通列 |
| 日期语义 | `Date` 统一归一到月末 timestamp |
| returns 连接键 | `Company SEDOL` 连接到 `returns.columns` |
| weight 空值语义 | `Weight in ...` 列为空通常表示非成分股或权重不可得，本身不等于数据错误 |
| 成分股判断 | 使用 `screen[weight_col].fillna(0) > 0` |
| 已废弃列 | `EM CountryCluster` 与 `Weight in MSCI EM - ...` 已停用，写入时必须删除 |

## `returns.parquet`

| 契约项 | 规则 |
| --- | --- |
| 粒度 | 每行一个交易日，每列一个 `Company SEDOL` |
| 索引 | 日频交易 `Date`，必须唯一且可解析为 datetime |
| 数值 | 日度简单收益率，使用小数格式，例如 `0.01` 表示 +1% |
| Screen 连接 | 列名必须匹配有效的 `screen_aggregate.Company SEDOL` |
| 异常审计 | 风险计算或回测前应检查极端收益值 |

## 字段族

| 字段族 | 示例 |
| --- | --- |
| 标识符 | `ISIN`, `Company SEDOL`, `Symbol`, `Name` |
| 地区 | `Exchange Country Name`, `Exchange Country Region`, `Benchmark Country English` |
| 行业 | ` Benchmark ICB Industry `, ` Benchmark ICB Supersector `, `ICB19 Supersector`, `FactSet Ind` |
| 权重 | `Weight in MSCI WORLD`, `Weight in SP500`, `Weight in STOXX EUROPE 600`, `Weight in MSCI EM` |
| ML universe | `Weight in Univ ML EU`, `Weight in Univ ML US`, `Weight in Univ ML OTHER` |
| 因子 | Value、Quality、Growth、Momentum、LowVol、Dividend、Size 的原始值与 percentile 字段 |
| 风险 | EWMA 波动率、VaR、最大回撤、SXXP Beta、区域 Beta 字段 |
| 表现 | `Perf5D`, `Perf1M`, `Perf3M`, `Perf6M` |
| CIQ | 通过 `(ISIN, Date)` 合并的财务报表与预测字段 |

## 共享 API

```python
from tp_core.io import read_screen_aggregate, read_returns
from tp_core.data_contract import validate_screen_contract, validate_returns_contract, sedol_coverage

screen = read_screen_aggregate()
returns = read_returns()
print(validate_screen_contract(screen))
print(validate_returns_contract(returns))
print(sedol_coverage(screen, returns))
```

## 补充数据影子契约

`00_screen/supplemental/` 是非 canonical 的 point-in-time sidecar：

| 数据族 | 逻辑主键 |
| --- | --- |
| 宏观原始记录 | `(series_id, observation_date, vintage_at, source)` |
| 财报事实 | `(ISIN, period_end, field, available_at, source)` |
| 一致预期 | `(ISIN, estimate_as_of, fiscal_period_end, horizon, field, source)` |
| 证券月末解析 | `(ISIN, Date, field)` |
| 宏观月末解析 | `(series_id, Date, field)` |

所有有效值必须包含 `source`、`unit`、`retrieved_at` 和 `available_at`；货币值还必须包含
`currency`。月末解析要求 `available_at <= Date`，宏观与财报还要求实际观察期不晚于
`Date`。影子 sidecar 保留手工商业源优先的 selected value、自动值、来源、差异和冲突标记。

合入 canonical 必须同时满足：连续三个同配置月末周期通过结构 QA，相关供应商每期覆盖率
提升至少 15 个百分点且重叠值一致率至少 90%，字段配置显式启用 promotion。合并只能补空，
不得改变 `(ISIN, Date)` 行数、日期范围或键唯一性。

## 区域 Beta

月度风险流水线保留 legacy 字段 `Beta vs SXXP (Rolling ewma 250D)`，同时写入 `Beta vs Regional Benchmark (Rolling ewma 250D)`。区域 Beta 将 US 证券映射到 SP500，West Europe 证券映射到 STOXX Europe 600，其他证券映射到 MSCI WORLD。

## Returns 异常审计

```powershell
python -m tp_core.returns_audit --report-path C:\GoogleDrive\TP\00_screen\qa\returns_anomaly_audit.json
```

默认阈值会标记 `abs(return) >= 100%`、`return >= 200%` 或 `return <= -95%` 的日收益。

## Backend routing contract

生产采用选择性 Hybrid：最新 Screen 选列使用 Partitioned Parquet/PyArrow；Company latest 使用 latest snapshot；Company History、Returns、Official Backtest 和完整 materialization 使用 Legacy Parquet；Catalog、metadata 和小型 Dashboard marts 使用 DuckDB。权威 policy 见 11_docs/DATA_BACKEND_ROUTING.md。

## Run、晋升与生产 lineage contract

运行治理链固定为：

```text
ExperimentRun -> PromotionDecision -> ModelRelease -> ProductionRunBundle
```

`ExperimentRun`/Run Card 记录研究输入和结果，完成后保持不可修改；正式批准、拒绝或撤销
必须追加独立 `PromotionDecision`。只有仍然有效的 `approved` decision 才能创建或激活
生产可用 `ModelRelease`。`ProductionRunBundle` 以唯一 `production_run_id` 绑定本次
运行的 data/model release、child manifest、输出和回滚目标；`latest` 只是指针，不是
lineage 依据。research-only 模型和月度因子推荐不得通过 candidates/optimizer 进入生产。

市场数据 freshness 必须满足 `artifact_data_date <= as_of_date` 且不超过允许 lag；报告、QA、
pipeline manifest 和回测执行证据使用 `generated_at >= production_run_started_at`。旧产物
只能通过显式 reuse manifest 复用，并记录来源、运行类型、数据日期、适用范围和批准理由。

## DuckDB V2 的存储角色

`00_screen/datasets/` 下的 Screen 月分区与 Returns 年分区是版本化 Canonical Lake；manifest 的
`dataset_version`、schema fingerprint、logical key 和日期范围属于本契约的一部分。DuckDB
catalog 只对 manifest 指定的 Parquet 分区建立 canonical view，不构成第二份事实源；
`marts.*` 是可重建的展示/模型派生表。现有 `screen_aggregate.parquet`、`returns.parquet`、
`last_screen.parquet` 和 `screen_aggregate_5Y.parquet` 在 authority switch 前均标记为
`compatibility_export`，不能被当作新的权威数据集。

任何迁移或回滚都必须保持 `(ISIN, Date)`、Returns `Date`、PIT 可用性、NaN 位置和 Pandas
宽表 index 语义；只改变存储路径或查询后端，不改变业务契约。

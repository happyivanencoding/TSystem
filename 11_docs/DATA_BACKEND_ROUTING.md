# TSystem 选择性 Backend Routing

## 最终决定

TSystem 使用按工作负载选择后端的混合架构，而不是将全部数据读取统一强制到 DuckDB。

SELECTIVE_HYBRID_PRODUCTION_READY
authority_status = not_active
default_engine = legacy_parquet
compatibility_exports = enabled

唯一 policy 文件是 config/data_backend_routing.json；Repository 根据查询类型选择后端，业务调用方不需要传递 Parquet 路径。TP_DATA_ENGINE 保留为底层 reader 的显式诊断覆盖，不作为生产全局切换。

## 生产路由

| 查询类型 | 生产后端 | 说明 |
| --- | --- | --- |
| Latest Screen selected columns（S03） | Partitioned Parquet / PyArrow | 只读取最新年月 partition 与请求列，可按 benchmark、ISIN、SEDOL 或国家过滤 |
| Company latest（M09） | Latest snapshot | 读取 00_screen/last_screen.parquet，只保留一个主路径 |
| Company history（M10） | Legacy Screen Parquet | 单次读取 screen_aggregate.parquet，按 ISIN 和可选日期过滤 |
| Returns matrix（R02/R03） | Legacy Returns Parquet | 显式 Date 与证券列 projection，不通过 DuckDB external view 重建宽矩阵 |
| Official Backtest input（R05） | Legacy Returns Parquet | Screen 可使用稳定查询，Returns 始终从 Legacy 加载 |
| Full Screen | Legacy Screen Parquet | 完整 materialization 不走 DuckDB |
| Full Returns | Legacy Returns Parquet | 完整宽矩阵不走 DuckDB |
| Dashboard small marts | DuckDB | 读取已物化的 latest signals、candidates、portfolio、model summary 和 dashboard mart |
| Catalog / metadata | DuckDB | dataset registry、pipeline/run registry、freshness 与 QA metadata |
| Monthly incremental writer | Partitioned Parquet | immutable 分区、manifest 和 compatibility export；仍需显式 writer 命令 |
| Compatibility exports | Enabled | Authority 未激活前继续保留旧宽表出口 |

## 为什么这样选

- 最新 Screen 的少量列查询受益于分区裁剪和 PyArrow projection。
- Returns 是约 12,000 列宽矩阵；Legacy Parquet 已经稳定恢复 Date index、列顺序、NaN 和数值，不应现场经 DuckDB external view 重建。
- Company History 需要完整历史，Legacy 单次 ISIN 过滤比“分区读取 + compatibility 回填”更简单且结果稳定。
- DuckDB 适合小型 catalog 和已物化 mart，不扩大为全量事实表的生产读取后端。

## 数据源与 Writer

Transco_FactSet_ICB.xlsx 由 tp_core.data_sources.TRANSCO_FACTSET_ICB_PATH 统一注册，默认位于 00_screen/，可由 TP_TRANSCO_FACTSET_ICB_PATH 覆盖。正式流程、inspect-only 和未来 scratch 都使用同一注册表；文件不进入 Git。

月度 writer 状态继续由真实月更验证，当前不启动 2026-07 replay，也不因单次 smoke 改变 Authority 状态。

## 明确边界

- 不执行 tp-duckdb-activate-authority --apply。
- 不把 TP_DATA_ENGINE=duckdb 或 TP_DATA_ENGINE=hybrid 设置为所有模块的生产默认。
- 不运行新的 benchmark、A/B/C 对比、长时间性能循环或月更 replay。
- Canonical Parquet、分区数据集、manifest/current pointer、DuckDB immutable releases、Compatibility exports 和历史 Run Cards 均保留。

# Critical Query Final Decision

## 状态

SELECTIVE_HYBRID_PRODUCTION_READY
authority_status = not_active
default_engine = legacy_parquet
compatibility_exports = enabled

本决定固化选择性 Hybrid 路由，不再追求所有数据统一进入 DuckDB，也不执行 Authority activation。

## 关键查询

上一轮受控小范围测量（6 workload、72 条记录）业务 parity 全部通过。相对 Current Legacy 的中位冷启动 speedup 为：S03 1.41x、R02 0.95x、R03 0.19x、R05 0.40x、M09 1.22x、M10 0.14x。这些数字只作为架构决策证据，不作为新的 benchmark 任务。

最终生产路由见 11_docs/DATA_BACKEND_ROUTING.md：S03 采用最新 Screen 分区选列，M09 采用 latest snapshot；Returns、Official Backtest 和 Company History 统一回到 Legacy Parquet；Catalog、metadata 和小型 Dashboard marts 继续使用 DuckDB。

## Writer 边界

此前 2026-06 bounded Writer smoke 因 scratch 使用了错误的 mapping 路径而无法解析 Transco_FactSet_ICB.xlsx；现已统一到 TP_TRANSCO_FACTSET_ICB_PATH 注册。本文不触发新的 Writer replay，2026-07 保持未启动/blocked，等待真实月更验证。

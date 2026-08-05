# TSystem V2 Data Architecture

## 当前状态

当前迁移状态是 `WRITER_CUTOVER_READY`。分区 Canonical Lake、DuckDB catalog release、只读 repositories、增量 writer、presentation marts 和回滚 CLI 已经可运行；生产默认读取仍是 legacy Parquet，旧单文件没有被删除或降级。Phase 7 的 authority switch 只有在证据门禁和外层批准同时满足后才允许执行。

## 分层与职责

| 层 | 位置/对象 | 角色 | 是否权威 |
| --- | --- | --- | --- |
| Raw / incoming | `00_screen/production_inputs/incoming/` | 原始月更输入、供应商文件、增量文件 | 否，按批次保留 |
| Canonical Lake | `00_screen/datasets/screen/`、`returns_wide/` | 不可变、按月/年分区的事实数据；由 manifest 指向 | 目标权威事实源 |
| DuckDB Catalog | `artifacts/analytics/duckdb/releases/<release_id>/tp_analytics.duckdb` | 对明确 manifest 分区建 canonical view，登记 schema、分区、QA、release、lineage | 查询 catalog，不是第二份事实源 |
| Mart | DuckDB `marts.*`、`signals.*` | latest screen、signals、candidates、portfolio、backtest、health、dashboard 汇总 | 展示/查询派生数据 |
| Compatibility Export | `00_screen/screen_aggregate.parquet`、`returns.parquet` 等 | 给尚未迁移的 legacy consumer 的兼容出口 | 不是权威 |
| Artifact | `artifacts/signals/`、`candidates/`、`portfolios/`、`reports/` | 模型、候选池、组合、报告等可复现产物 | 由 run/manifest 关联 |
| Run Card | `artifacts/pipeline_runs/experiments/` | 研究命题、配置、输入 fingerprint、指标和决定理由 | 研究审计证据 |

Canonical Lake 只保存事实分区；DuckDB 不把全量 Screen 或 Returns 导入 native table。Catalog release 通过 manifest 的精确文件列表创建 view，Mart 才持有小型派生表。

## 目录与版本

```text
00_screen/
├── datasets/
│   ├── screen/year=YYYY/month=MM/part-<sha>.parquet
│   ├── returns_wide/year=YYYY/part-<sha>.parquet
│   ├── manifests/screen/<dataset-version>.json
│   └── manifests/returns_wide/<dataset-version>.json
└── screen_aggregate.parquet / returns.parquet  # compatibility_export

artifacts/
├── analytics/duckdb/releases/<release-id>/tp_analytics.duckdb
├── analytics/duckdb/latest.json                  # 受门禁的 catalog pointer
├── pipeline_runs/manifests/<step>/*_latest.json
├── pipeline_runs/experiments/                    # Run Cards
├── signals/ candidates/ portfolios/ reports/
└── analytics/duckdb/authority_evidence.json      # 本地证据，不进入 Git
```

Dataset version 由源快照、schema fingerprint 和分区内容决定。Manifest 与 `current.json` 原子发布；旧分区不原地覆盖。Catalog release 也不可变，失败构建只清理 staging，不替换现有 pointer。

## 访问合同

- Screen 的逻辑键是 `(ISIN, Date)`，分区键是 `(year, month)`；PIT 和日期语义不改变。
- Returns 的逻辑键是 `Date`，分区键是 `year`；宽表读出时恢复为 Pandas `Date` index。
- `tp_core.io` 保留 `legacy_parquet` 默认值，可显式使用 `TP_DATA_ENGINE=duckdb` 或 `shadow_compare`。
- Dashboard/API 的 latest hot path 采用 `MartRepository` 优先；没有 current catalog release、mart 为空或请求属于 history/detail 时，才使用 allowlisted compatibility artifact fallback，且 artifact fallback 有 80MB 上限。完整 read-path 证据见 `11_docs/archive/duckdb_migration_20260804/presentation_read_path_audit.csv`。这不等同于 dashboard 已完成全量 SQL cutover。
- `company_master_latest` 构建时使用 manifest 日期对应的年/月分区谓词；Screen/Returns 全量文件不会被 overview latest 查询隐式 materialize。
- 业务模块不得接受任意 SQL；QuerySpec/repository 负责列、日期、证券和 PIT 过滤。

## 并发与存储

DuckDB release 构建和 pointer 更新是单 writer 操作，使用 file lock、staging 文件和 atomic rename；多个请求可以打开 read-only release。不得让多个进程写同一个 DuckDB 文件。Google Drive 保存代码、manifest 和 Canonical 分区时要考虑同步延迟；大 DuckDB release、temp 和 cache 默认忽略 Git，性能敏感部署可以把它们放在本地 SSD，并通过显式 `TP_DUCKDB_PATH` 指向。

## 回滚与保留

- Canonical 数据回滚：`tp-data-rollback-dataset --dataset screen|returns_wide --dataset-version <version> --apply`，同时重建 compatibility export。
- Catalog 回滚：`tp-duckdb-rollback --database <immutable-release> --catalog-release-id <release> --apply`；旧 pointer 保存为 `latest.previous.json`。
- 新 release、manifest、Run Card 和 parity evidence 在确认未被引用前不得清理。
- `tp-prune-artifacts` 仍是唯一受控清理入口；不得删除历史 Run Card 或 `artifacts/research/runs/historical/`。
- Compatibility export 在 Phase 8 之前默认开启；只有 retirement readiness 通过后，才可使用 `TP_COMPAT_EXPORTS=false` 和 `--no-compatibility-exports` 停止分区 writer 的默认出口生成。

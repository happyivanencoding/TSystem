# DuckDB Operations

本文档是 TP DuckDB catalog、marts 和分区 writer 的日常操作手册。所有写操作都必须显式 `--apply`；没有 `--apply` 的命令只检查或生成 dry-run 证据。

## 环境

```powershell
$env:TP_DATA_ROOT = 'C:\GoogleDrive\TP'
$env:TP_ARTIFACT_ROOT = 'C:\GoogleDrive\TP\artifacts'
$env:TP_DUCKDB_THREADS = '2'
$env:TP_DUCKDB_MEMORY_LIMIT = '2GB'
$env:TP_DATA_ENGINE = 'legacy_parquet'  # 当前默认；切换前不要改成 duckdb
$env:TP_COMPAT_EXPORTS = 'true'         # Phase 8 前保持开启
```

`TP_DUCKDB_PATH` 可以指向本地 SSD 上的 catalog release；不能把多个 writer 指向同一个文件。Web/API 使用 read-only connection，pipeline 构建使用自己的 staging database。

## 构建 catalog 与 marts

先确认两个 current pointer 指向通过 QA 的 manifest：

```powershell
python -c "from tp_core.analytics.cli import build_catalog_main; raise SystemExit(build_catalog_main(['--screen-manifest','00_screen/datasets/manifests/screen/current.json','--returns-manifest','00_screen/datasets/manifests/returns_wide/current.json']))"
```

创建不改变 production pointer 的 release 和 presentation marts：

```powershell
tp-duckdb-refresh-marts `
  --release-id presentation-YYYYMMDD-screen-returns-v1 `
  --screen-manifest 00_screen/datasets/manifests/screen/current.json `
  --returns-manifest 00_screen/datasets/manifests/returns_wide/current.json `
  --apply
tp-duckdb-validate-release --database artifacts/analytics/duckdb/releases/<release>/tp_analytics.duckdb
```

`tp-duckdb-refresh-marts` 会登记 `meta.artifact_registry`、`meta.run_registry` 和 `meta.materialization_registry`，并生成 `marts.dashboard_overview`、latest screen/signals、candidate/portfolio、backtest、data health 和 pipeline summaries。`latest.json` 不会被 build 命令直接更新。

## 分区 writer

月更先用 dry-run 验证受影响月份/年份：

```powershell
tp-pipeline-refresh-data --input-month YYYYMM --partition-writer --dry-run
```

确认 row count、logical key、非受影响分区 hash 和 QA 后，才执行：

```powershell
tp-pipeline-refresh-data --input-month YYYYMM --partition-writer --apply
```

当前 `refresh_data` 的 production authority 仍由 legacy compatibility export 服务；分区 writer 只在显式选项下运行。writer 使用 `00_screen/datasets/.partition-writer.lock`、immutable part、manifest 和 atomic current pointer。中断后检查 `00_screen/datasets/staging/` 与 manifest，再重新 dry-run；不要手工覆盖 part 文件。

## 回滚

```powershell
tp-data-rollback-dataset --dataset screen --dataset-version <screen-version> --apply
tp-data-rollback-dataset --dataset returns_wide --dataset-version <returns-version> --apply
tp-duckdb-rollback --database artifacts/analytics/duckdb/releases/<known-good-release>/tp_analytics.duckdb --catalog-release-id <known-good-release> --apply
```

Catalog rollback 先保存当前 `latest.json` 为 `latest.previous.json`，再写入目标 release。读进程已经打开的旧 release 不受 pointer 改变影响；新请求从 pointer 读取目标 release。

## Authority 与 retirement 门禁

只读检查：

```powershell
tp-duckdb-authority-status `
  --database artifacts/analytics/duckdb/releases/<release>/tp_analytics.duckdb `
  --catalog-release-id <release> `
  --evidence 11_docs/archive/duckdb_migration_<date>/phase7_8_readiness.json
```

没有完整 production-chain parity、两次独立月更 replay 或明确批准时，命令应以非零退出并保持 `WRITER_CUTOVER_READY`。Phase 8 检查同一证据：

```powershell
tp-duckdb-retirement-status --database <release-db> --catalog-release-id <release> --evidence <evidence-json>
```

兼容出口默认仍开启。不得以“文件存在”代替 parity、rollback 或 Run Card 证据。

## 保留策略

保留当前和仍被 Run Card、pipeline manifest、dashboard release 或 rollback evidence 引用的 manifest、part、release 和 artifact。清理只通过 `tp-prune-artifacts` dry-run/`--apply` 完成；Git 跟踪文件、历史 Run Card 和 historical research evidence 不由该命令删除。

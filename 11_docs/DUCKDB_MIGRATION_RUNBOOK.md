# DuckDB Migration Runbook

## 状态枚举

迁移报告只能使用以下状态：

```text
FOUNDATION_ONLY
SHADOW_READY
READ_CUTOVER_READY
WRITER_CUTOVER_READY
CANONICAL_V2_ACTIVE
MIGRATION_REJECTED
```

当前状态：`WRITER_CUTOVER_READY`。Phase 0-6 的实现和真实数据验证已完成；默认 engine、旧 monolith compatibility export 和 production authority 没有被提前切换。

## Phase checklist

| Phase | 交付 | 当前证据/边界 |
| --- | --- | --- |
| 0 | audit、profile、I/O inventory | `11_docs/archive/duckdb_migration_20260804/` |
| 1 | dependency、connection、catalog、contracts、CLI | foundation tests passed |
| 2 | Screen monthly / Returns yearly mirrors | full row/key/date parity passed |
| 3 | read-only catalog、shadow query、manifest release | shadow QA passed；unbounded wide Returns 仍受资源 guardrail |
| 4 | repositories、models、backtest、candidate read routing | default legacy，显式 DuckDB/shadow 可回退 |
| 5 | incremental writer、compatibility export、dataset rollback | fixture apply/rollback passed；production writer 未默认启用 |
| 6 | dashboard marts、latest payload、artifact/run registry | real release `MARTS_READY`；latest 查询读 mart |
| 7 | authority gate、activation、catalog rollback | 只有证据齐全和用户批准才可 apply |
| 8 | compatibility retirement policy、retention | 当前只提供 readiness/配置开关，不删除旧数据 |

## Authority evidence contract

`tp-duckdb-activate-authority` 只接受如下语义的 JSON；字段必须来自真实运行，不能用 smoke 结果冒充 production cycle：

```json
{
  "schema_version": "tp.duckdb-authority-evidence.v1",
  "release_id": "<catalog-release>",
  "full_real_data_parity": true,
  "complete_production_chain_parity": true,
  "rollback_drill": true,
  "monthly_cycles": [
    {"cycle_id": "2026-06-replay", "status": "passed"},
    {"cycle_id": "2026-07-replay", "status": "passed"}
  ],
  "external_approval": true
}
```

还必须能打开目标 release，`catalog_health.ok` 为 true，且 `meta.catalog_releases.validation_status = marts_ready`。CLI 会检查 release id 一致性、两次不同 cycle id、显式批准和所有布尔条件；失败时不会写 pointer。

## 正式 activation 命令

当且仅当用户已经审阅并批准上述 evidence 后执行：

```powershell
tp-duckdb-activate-authority `
  --database artifacts/analytics/duckdb/releases/<release>/tp_analytics.duckdb `
  --catalog-release-id <release> `
  --evidence 11_docs/archive/duckdb_migration_<date>/authority_evidence.json `
  --approve-authority-switch `
  --apply
```

等价的未重新安装 editable package 的调用方式：

```powershell
python -c "from tp_core.analytics.cli import activate_authority_main; raise SystemExit(activate_authority_main(['--database','<release-db>','--catalog-release-id','<release>','--evidence','<evidence-json>','--approve-authority-switch','--apply']))"
```

该命令只原子更新 catalog pointer，并保留 `latest.previous.json`；不会删除旧 monolith、历史分区、Run Card 或报告，也不会静默改写 `TP_DATA_ENGINE`。应用服务仍需显式配置 `TP_DATA_ENGINE=duckdb` 和目标 pointer，并在发布后再次运行 read-only smoke。

## Rollback drill 与实际回滚

先 dry-run：

```powershell
tp-duckdb-rollback --database artifacts/analytics/duckdb/releases/<known-good-release>/tp_analytics.duckdb --catalog-release-id <known-good-release>
```

确认 release health 后执行：

```powershell
tp-duckdb-rollback --database artifacts/analytics/duckdb/releases/<known-good-release>/tp_analytics.duckdb --catalog-release-id <known-good-release> --apply
```

Canonical 数据的回滚必须另外执行 `tp-data-rollback-dataset`，因为 catalog pointer 回滚不会改变分区 manifest 的 `current.json`。两者的结果都必须写入本次 Run Card/QA evidence。

## Phase 8 retirement

只有 `tp-duckdb-retirement-status` 返回 `RETIREMENT_READY` 后，才允许在一个明确的 production run 中设置：

```powershell
$env:TP_COMPAT_EXPORTS = 'false'
tp-pipeline-refresh-data --input-month YYYYMM --partition-writer --no-compatibility-exports --apply
```

该开关只停止分区 writer 生成兼容出口；它不删除旧 `.parquet`，不清理 historical Run Cards，也不允许在没有 rollback evidence 时执行。旧出口的 retention 清理需要独立的引用审计和用户批准。

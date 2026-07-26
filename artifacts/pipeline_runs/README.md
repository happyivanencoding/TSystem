# artifacts/pipeline_runs

`artifacts/pipeline_runs/` 保存流水线运行证据，不保存业务数据主表。

## 目录

| 路径 | 说明 |
| --- | --- |
| `manifests/<step>/<step>_latest.json` | 每个步骤的最新运行证据 |
| `manifests/<step>/<step>_YYYYMMDD_HHMMSS.json` | 每次运行的时间戳证据 |
| `experiments/<hypothesis>/<run_id>/run.json` | 统一 Experiment/Recorder Run Card |
| `experiments/<hypothesis>/latest.json` | 该命题最新 Run Card 指针 |

manifest 是机器可读 JSON，记录参数、输入、输出、校验、耗时和错误。日常排查先看 latest；需要追溯时再看时间戳文件。

## Experiment/Recorder 契约

`tp-pipeline-run-all`、独立 pipeline step、`tp-backtest run` 和
`tp_research.workflows` 下的研究入口默认写 schema v2 Run Card。每张卡必须包含：

- hypothesis ID、完整 config 与 Git 代码版本；
- 输入数据逐文件 fingerprint、聚合 fingerprint 与 PIT 截止时间；
- universe、样本区间、成本假设、trial family 与有效试验数；
- engine、signal、optimizer 版本；
- metrics、artifacts、运行状态、父运行 lineage；
- `promote`、`reject` 或 `review_required` 决定及理由。

成功运行默认标记 `review_required`，失败运行由系统标记 `reject`；只有完成研究门禁后才能显式改为 `promote`。

## 产物保留与清理

清理工具默认只预览，Git 跟踪文件、`README*`、`*_latest.*` 和 `latest_*` 永远不会被自动删除：

```powershell
python -m tp_core.artifact_retention
python -m tp_core.artifact_retention --apply
```

| 产物 | 最长保留期 | 最少保留 |
| --- | ---: | ---: |
| Notebook 执行目录 | 14 天 | 最新 3 次 |
| 各步骤时间戳 manifest | 365 天 | 最新 50 个 |
| 每个 hypothesis 的 Experiment Run Card | 730 天 | 最新 100 个 |
| 各数据集备份 | 365 天 | 最新 12 个 |
| Ad-hoc 回测目录 | 180 天 | 最新 10 个 |
| 新闻模型运行日志/目录 | 90 天 | 最新 10 个 |

Canonical 数据、标准 latest 产物、正式研究结论和 Git 跟踪证据不按此策略自动删除。冻结或隔离目录满 90 天后应先生成归档 manifest，再人工决定归档或删除。


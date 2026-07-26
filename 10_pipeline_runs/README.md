# 10_pipeline_runs

`10_pipeline_runs/` 保存流水线运行证据，不保存业务数据主表。

## 目录

| 路径 | 说明 |
| --- | --- |
| `manifests/<step>/<step>_latest.json` | 每个步骤的最新运行证据 |
| `manifests/<step>/<step>_YYYYMMDD_HHMMSS.json` | 每次运行的时间戳证据 |

manifest 是机器可读 JSON，记录参数、输入、输出、校验、耗时和错误。日常排查先看 latest；需要追溯时再看时间戳文件。

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
| 各数据集备份 | 365 天 | 最新 12 个 |
| Ad-hoc 回测目录 | 180 天 | 最新 10 个 |
| 新闻模型运行日志/目录 | 90 天 | 最新 10 个 |

Canonical 数据、标准 latest 产物、正式研究结论和 Git 跟踪证据不按此策略自动删除。冻结或隔离目录满 90 天后应先生成归档 manifest，再人工决定归档或删除。

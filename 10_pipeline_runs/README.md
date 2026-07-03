# 10_pipeline_runs

`10_pipeline_runs/` 保存流水线运行证据，不保存业务数据主表。

## 目录

| 路径 | 说明 |
| --- | --- |
| `manifests/<step>/<step>_latest.json` | 每个步骤的最新运行证据 |
| `manifests/<step>/<step>_YYYYMMDD_HHMMSS.json` | 每次运行的时间戳证据 |

manifest 是机器可读 JSON，记录参数、输入、输出、校验、耗时和错误。日常排查先看 latest；需要追溯时再看时间戳文件。

# artifacts/reports

报告目录保存稳定命名的最新状态报告和后续投资报告产物。

当前标准产物：

| 文件 | 说明 |
| --- | --- |
| `latest_pipeline_report.md` | 最新流水线状态报告，来自 `python -m tp_pipelines.generate_report` |

这里不保存临时时间戳 Markdown 审计文件。运行证据统一进入 `artifacts/pipeline_runs/manifests/`，报告只保留稳定入口，方便打开和引用。


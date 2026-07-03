# 05_candidates

候选池目录保存投资决策前的标准公司名单。

当前标准产物：

| 文件 | 说明 |
| --- | --- |
| `latest_candidates.parquet` | 最新候选池，来自 `python -m pipelines.build_candidates` |

候选池不是最终组合，也不是回测结果。它的职责是把统一信号表转换成可解释的公司名单，包含综合分数、排名、入选标记和主要来源字段。

每次运行的输入、输出、行数、主键校验和入选数量见：

```text
10_pipeline_runs/manifests/build_candidates/build_candidates_latest.json
```

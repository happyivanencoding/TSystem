# returns 异常收益治理

本目录保存 canonical `returns.parquet` 的异常收益审计产物。当前治理原则是：先审计、复核和留痕，不直接自动改写主库。

| 文件 | 用途 |
| --- | --- |
| `returns_extreme_audit_latest.json` | 最新异常收益摘要、阈值、严重程度分布和 Top 样本 |
| `returns_extreme_flags_latest.parquet` | 完整异常收益明细，供程序读取 |
| `returns_extreme_flags_latest.csv` | 完整异常收益明细，供人工查看 |
| `returns_extreme_review_template_latest.csv` | 人工复核模板，可填写 reviewer、review_notes、approved_action、corrected_return |

默认阈值：

- `abs(return) >= 1.0`
- `return >= 2.0`
- `return <= -0.95`

严重程度：

- `critical`：`abs(return) >= 10.0` 或 `return <= -0.99`
- `high`：`abs(return) >= 2.0`
- `review`：其他超过默认阈值的样本

后续如果要修正 canonical `returns.parquet`，应先基于复核模板形成明确的修正/白名单文件，再由单独的数据修复脚本生成可回滚备份和 QA 报告。

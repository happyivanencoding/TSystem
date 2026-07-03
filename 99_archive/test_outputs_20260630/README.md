# 测试输出归档

本目录保存 2026-06-30 从活跃项目目录移出的测试产物，只作回溯参考，不作为生产输入。

| 来源 | 目标 | 原因 |
| --- | --- | --- |
| `test_output/` | `root_test_output/` | pytest 从根目录运行优化器测试时产生的临时输出 |
| `06_optimiser/test_output/` | `06_optimiser_test_output/` | 历史优化器测试输出，不属于标准产物 |

后续优化器测试应使用 pytest 临时目录，不再向根目录写入 `test_output/`。

# Production Refresh 接手页

## 范围

TP 生产刷新、月更输入、pipeline 运行、manifest、incoming 归档、control tower 和系统健康检查。

## 关键入口

- Screen 生产目录：`00_screen/`
- Pipeline 目录：`src/tp_pipelines/`
- 唯一运行手册：[`../../11_docs/PIPELINE_OPERATIONS.md`](../../11_docs/PIPELINE_OPERATIONS.md)

## 当前状态

- 生产刷新步骤和数据契约以正式文档、当前代码和真实产物为准。
- 成功消费的 `incoming` 数据默认应归档或清理，除非用户明确要求保留。

## 验证方法

- 检查 manifest、输出日期、输出行数和关键 parquet/CSV 产物。
- 避免只凭命令退出码判断刷新成功。

## 相关 Skill

- `tp-production-refresh-control`
- `tp-senior-engineer-task-execution`

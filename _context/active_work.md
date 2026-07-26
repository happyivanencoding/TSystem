# 当前接手状态

本文件只记录当前接手状态，不记录长期项目事实。长期事实以 `11_docs/`、项目 README、代码和真实产物为准。

## 当前重点

- `src/` 包架构已经部署，活跃源码、测试、配置和标准产物分别位于 `src/`、`tests/`、`config/`、`artifacts/`。
- 当前架构总览只看 `11_docs/INVESTMENT_PLATFORM_MAINLINE.md`，生产运行只看 `11_docs/PIPELINE_OPERATIONS.md`。
- 编号资源目录中的兼容脚本入口已退役；新运行不得恢复旧 wrapper。

## 暂停/不要碰

- 不要把 `_context` 扩展成第二套正式文档库。
- 不要把 `artifacts/research/runs/historical/` 当成新运行输出；它是永久保护的历史只读证据库。
- 不要通过 `sitecustomize`、`.pth`、`sys.path` 或文件路径执行绕过安装包。

## 最近完成

- 已合并重复架构文档和生产手册，归档旧计划、旧流程图、硬编码实时统计及一次性视觉 QA。
- 控制塔不再把三个已合并展示应用和归档 Small Cap 片段登记为独立项目。
- `tp-check-legacy-references` 负责阻止旧入口重新进入活跃代码、配置和文档。

## 下次接手优先检查

- 先读本文件、架构总览和相关 [`subprojects/`](subprojects/) 页面。
- 再运行 `git status --porcelain`，区分已有用户改动和本次任务改动。
- 如果发现 `_context` 与当前代码或 `11_docs` 冲突，以代码和正式文档为准并修正 `_context`。

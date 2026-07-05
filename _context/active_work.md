# Active Work

本文件只记录当前接手状态，不记录长期项目事实。长期事实以 `11_docs/`、项目 README、代码和真实产物为准。

## 当前重点

- 已建立 `_context` 接手层，用于跨对话快速恢复 TP 工作区状态。
- 正式项目知识仍维护在 `11_docs/` 和各项目 README。

## 暂停/不要碰

- 不要把 `_context` 扩展成第二套正式文档库。
- 不要在普通业务任务中直接修改现有 skill；先记录到 [`skill_review.md`](skill_review.md)，再单独处理。
- 不要因为上下文治理工作改动生产代码、数据集、缓存或运行产物。

## 最近完成但需要观察

- `_context` 与 `11_docs` 的边界已定义；后续需要在实际任务 handoff 中验证是否足够好用。
- Skill review 机制已落地为记录入口；首次真实 review 应在后续 5 个较大 TP 任务后进行。

## 下次接手优先检查

- 先读本文件和相关 [`subprojects/`](subprojects/) 页面。
- 再运行 `git status --porcelain`，区分已有用户改动和本次任务改动。
- 如果发现 `_context` 与当前代码或 `11_docs` 冲突，以代码和正式文档为准并修正 `_context`。

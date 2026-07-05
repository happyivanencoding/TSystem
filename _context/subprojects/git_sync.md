# Git Sync 接手页

## 范围

TP 仓库手动同步、提交前 artifact gate、pull rebase 和 push。

## 关键入口

- Git 状态：`git status --porcelain`
- 文档治理：[`../../11_docs/DOCUMENTATION_GOVERNANCE.md`](../../11_docs/DOCUMENTATION_GOVERNANCE.md)

## 当前状态

- 当前偏好是手动同步：只有用户明确说“同步”或“同步 git”时才执行。
- 不恢复定时自动同步，除非用户明确改变这个决定。
- 同步范围只包含代码、配置、文档和小文件；不提交数据集、缓存、运行输出、大文件或嵌套 Git 元数据。

## 验证方法

- 先跑 `git status --porcelain`。
- staged 文件必须通过路径和大小 gate。
- clean tree 时应直接停止，不强行 commit 或 push。

## 相关 Skill

- `tp-manual-git-sync`
- `tp-senior-engineer-task-execution`

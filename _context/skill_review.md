# Skill Review

本文件记录 TP 相关 skill 的轻量审视状态。它不替代 skill 源文件，也不直接修改 skill；真正修改 skill 时单独执行。

## 审视频率

- 每完成 5 个较大 TP 任务后做一次轻量 review。
- 某个 skill 该触发但没触发时，立即记录。
- 某个 skill 被误触发时，立即记录。
- 用户明确修正一次执行习惯时，立即记录。
- 相关流程或目录结构发生长期变化时，立即记录。

## Review Checklist

- 触发点是否过窄。
- 是否覆盖中文自然说法和用户真实表达。
- 是否只依赖英文 skill 名或技术词。
- 是否覆盖同一任务的简称、别名和口语表达。
- 是否仍符合当前代码路径和文档路径。
- 是否重复了已经废弃的自动化或旧流程。
- 是否和 `11_docs`、`_context` 或实际代码冲突。
- 是否过宽，导致不相关任务误触发。
- 是否需要把新的高频任务沉淀成 skill。

## 当前 TP Skill 清单

| Skill | 用途 | 需要覆盖的自然触发说法 | 适用边界 | 最近审视 |
| --- | --- | --- | --- | --- |
| `tp-senior-engineer-task-execution` | TP 代码和文档任务的执行纪律 | senior engineer、生产安全、先确认范围、最小改动、中文总结 | 执行纪律，不替代具体业务 skill | 2026-07-05 初始登记 |
| `tp-dashboard-workflow` | Dashboard、presentation layer、前端可视化验证 | dashboard、页面、看板、结果页、生产页、Score ML 面板 | 仅限 `08_presentation_layer` 及相关 API/静态资源验证 | 2026-07-05 初始登记 |
| `tp-production-refresh-control` | 生产刷新、pipeline、manifest、incoming 归档和健康检查 | 刷新生产、跑生产、月更、incoming、control tower、system-checks | 生产刷新和产物验证，不用于研究性回测 | 2026-07-05 初始登记 |
| `tp-quant-research-workflow` | 因子研究、回测、中文研究报告和 Plotly 对比 | 回测、因子、策略、研究报告、中文报告、plotly 对比 | 研究和 evidence 生成，不直接改生产信号 contract | 2026-07-05 初始登记 |
| `tp-manual-git-sync` | 手动 Git 同步和严格 artifact gate | 同步、同步 git、push、提交代码、小文件同步 | 只在用户明确要求同步时使用，不恢复自动同步 | 2026-07-05 初始登记 |

## 待观察问题

- 未来 review 时重点检查中文触发说法是否足够宽，例如“同步”“刷新生产”“dashboard 页面”“回测报告”“中文报告”。
- 如果某个 skill 连续两次未触发或误触发，单独开 skill 更新任务。

# Backtest Research 接手页

## 范围

TP 因子研究、候选信号筛选、正式回测、中文研究报告和 Plotly 对比图。

## 关键入口

- 回测目录：`src/tp_backtest/`
- 正式文档：[`../../11_docs/BACKTEST_ENGINE.md`](../../11_docs/BACKTEST_ENGINE.md)
- 研究方法：[`../../11_docs/RESEARCH_METHODS.md`](../../11_docs/RESEARCH_METHODS.md)

## 当前状态

- 结论以 official exact 回测和生成产物为准；fast grid 只作为候选筛选证据。
- 默认报告语言为中文，除非用户明确要求其他语言。

## 验证方法

- 检查 run artifacts、summary JSON/CSV、最终报告和 Plotly 对比文件。
- 默认对比 Top、Worst、Bench，并包含 Top/Worst ratio，除非用户明确不要。

## 相关 Skill

- `tp-quant-research-workflow`
- `tp-senior-engineer-task-execution`

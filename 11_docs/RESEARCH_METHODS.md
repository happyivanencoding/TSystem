# 研究方法文档

本文档用于统一 TP 中研究项目的记录方式。它不替代 notebook 或代码，而是说明每类研究应保留哪些方法信息，防止未来只剩结果文件却不知道口径。

## 通用原则

- 所有研究默认使用 canonical `screen_aggregate.parquet` 和 `returns.parquet`。
- 横截面研究必须说明 universe、权重列、行业/地区中性化规则和调仓日期。
- 回测研究必须说明信号形成时间、收益持有区间、交易成本、rebalance 规则和 benchmark。
- 任何 forward return、未来收益标签或验证集都要明确标注，避免与实时可用特征混淆。
- 方法文档使用固定文件名；运行证据优先用 JSON/CSV，不生成新的时间戳 Markdown。

## 回测与组合构建

推荐文档位置：

- [`../99_backtest_web_app_legacy/README.md`](../99_backtest_web_app_legacy/README.md)
- [`../99_backtest_web_app_legacy/11_docs/README.md`](../99_backtest_web_app_legacy/11_docs/README.md)
- [`../99_backtest_gui_legacy/README.md`](../99_backtest_gui_legacy/README.md)

研究记录应至少包含：

| 项目 | 应记录内容 |
| --- | --- |
| Universe | 指数权重列、地区、行业过滤、缺失值处理 |
| Signal | 因子字段、排序方向、winsorize/neutralize 规则 |
| Portfolio | 持仓数量、权重方式、换仓频率、现金处理 |
| Returns | 使用 `returns.parquet` 的日期对齐方式 |
| Benchmark | benchmark 代码和来源 |
| Metrics | 年化收益、波动、Sharpe、最大回撤、turnover、hit ratio |

## Regime 模型

推荐文档位置：

- [`../03_regime_model/README.md`](../03_regime_model/README.md)

研究记录应说明：

- bottom-up 聚合特征的构造方式。
- HMM 或其他模型的训练窗口、状态数和状态命名。
- OOS walk-forward 是否严格只用当时可见数据。
- 状态解释是否依赖未来收益验证。

## 技术分析与形态识别

推荐文档位置：

- [`../03_technical_analysis/README.md`](../03_technical_analysis/README.md)
- [`../03_technical_analysis/docs/pattern_backtest_score_guide.md`](../03_technical_analysis/docs/pattern_backtest_score_guide.md)

研究记录应说明：

- 技术指标频率、lookback 和 resample 方式。
- `patterns.parquet` 的字段含义。
- 形态字段转成横截面 score 的规则。
- 技术信号与基本面因子混合时的权重和方向。

## ML 研究

推荐文档位置：

- [`../03_ml_enhanced/README.md`](../03_ml_enhanced/README.md)

研究记录应说明：

- 训练样本、label、区域拆分和时间切分。
- 特征清单和数据泄漏检查。
- 模型版本、参数、评估指标和输出位置。
- 回写主表或下游使用的字段名称。

## 公司分析与 Dashboard

推荐文档位置：

- [`../08_company_analysis/README.md`](../08_company_analysis/README.md)
- [`../08_web_app_des_companies/README.md`](../08_web_app_des_companies/README.md)
- [`../08_dashboard_analysis/README.md`](../08_dashboard_analysis/README.md)

研究记录应说明：

- 输入数据来自 canonical `last_screen` 还是项目派生 parquet。
- 公司筛选、新闻窗口、行业分类和指数成分口径。
- 输出报告、网页或 PDF 的生成命令。

## 研究结论的保存方式

| 内容 | 推荐保存 |
| --- | --- |
| 稳定方法说明 | 项目 `README.md` 或 `docs/*.md` |
| 每次运行的参数和结果 | JSON/CSV/Parquet |
| 临时探索 | notebook，文件名注明主题 |
| 应长期复用的发现 | 固定方法文档或项目 README |
| 过期实验记录 | 项目 archive/quarantine，不作为当前入口 |

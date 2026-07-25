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

- [`../99_archive/project_cleanup_20260707/99_backtest_web_app_legacy/README.md`](../99_archive/project_cleanup_20260707/99_backtest_web_app_legacy/README.md)
- `99_archive/project_cleanup_20260707/99_backtest_web_app_legacy/11_docs/` 已随旧 Web 回测入口归档，不作为当前研究方法入口。
- [`../99_archive/project_cleanup_20260707/99_backtest_gui_legacy/README.md`](../99_archive/project_cleanup_20260707/99_backtest_gui_legacy/README.md)

研究记录应至少包含：

| 项目 | 应记录内容 |
| --- | --- |
| Universe | 指数权重列、地区、行业过滤、缺失值处理 |
| Signal | 因子字段、排序方向、winsorize/neutralize 规则 |
| Portfolio | 持仓数量、权重方式、换仓频率、现金处理 |
| Returns | 使用 `returns.parquet` 的日期对齐方式 |
| Benchmark | benchmark 代码和来源 |
| Metrics | 年化收益、波动、Sharpe、最大回撤、turnover、hit ratio |

### 因子 raw variable gate

地区、规模、行业或 benchmark-defined universe 的因子研究必须保留 raw-variable 证据链：

- 每个 raw variable 先单独构造 higher-is-better score。
- 每个 raw variable 先跑 official Top/Worst，不得直接因为 `core`、数据源、经济直觉或 CIQ/FactSet/database 标签进入 family。
- 默认 gate 至少包括 coverage、Top/Benchmark ratio CAGR、Top/Worst ratio return、robust score。
- `core` / `supplement` 只作为诊断标签，不决定入选。
- rejected variables 必须留在 diagnostics 和报告中。

### 相对 raw variable 扩展

当 raw variable 是绝对水平值时，研究应补充 same-security relative variants，而不是只测静态 level。

默认候选：

| 变体 | 构造 | 适用含义 |
| --- | --- | --- |
| `directional_delta` | 方向调整后的 raw level 减同一证券 lagged level，再 winsorize + neutral rank | 利润率改善、ROE 改善、杠杆下降、估值变便宜、派息压力下降、波动下降 |
| `score_delta` | 当前 neutralized score 减同一证券 lagged score，再 neutral rank | 行业内排名改善 |

默认 lag 为 `1, 3, 12` 个 screen observation。变量若本身已经是 growth、revision、momentum、return、CAGR 或 change-like 字段，不应机械再做二阶变化，除非研究问题明确需要。

相对变量必须作为新的 raw variable 经过同一 official Top/Worst gate。运行产物至少包括：

- `relative_variable_definitions.csv`
- `relative_validation_gate.csv`
- `relative_vs_level_comparison.csv`
- `official_run_results.csv`
- `performance_summary.csv`
- 中文研究结论，说明经济含义和不能过度声明的边界。

### 协同证据

不能因为两个变量经济故事互补就声称 synergy。协同必须有额外证据。

最小证据链：

- 两个单变量各自有 official raw Top/Worst 证据。
- pair、family subset 或 leave-one-out 也有 official Top/Worst 证据。
- pair/subset 的 robust score、Top/Benchmark risk、Top/Worst ratio 或 drawdown 显著优于强的一条单变量或简单基准组合。
- leave-one-out 显示新增变量有正贡献，或能降低回撤、tracking error、turnover instability、rolling failure。
- coverage、turnover、持仓重叠不破坏可执行性。

协同关系应分类为：

| 分类 | 含义 |
| --- | --- |
| `synergistic` | 组合明显优于最好单腿，并改善风险证据 |
| `additive` | 组合有效，但没有明显超过最好单腿 |
| `redundant` | 组合和单腿高度重叠，leave-one-out 贡献弱 |
| `harmful` | 组合降低稳健性或恶化回撤、换手、覆盖 |

相关产物建议命名：

- `pair_synergy_results.csv`
- `family_subset_results.csv`
- `leave_one_out_results.csv`
- `synergy_claims.csv`

### 大矩阵 official 回测执行规则

长矩阵 official 回测应支持恢复和并行，但不能牺牲证据口径：

- 优先使用 process-level sharding，而不是 Python threads。
- 每个 worker 写独立 shard result file 和独立 official run root。
- 父进程负责 merge、dedupe、重新生成 summary/gate/report。
- 每次 restart 使用唯一 wave 目录，避免覆盖上一轮 shard CSV。
- Windows 下保持 official run root 短路径，防止长 metric name 导致 artifact path 过长。
- 中断后先读取主结果和所有 shard/wave 结果，再只补缺口。
- worker 应在 Parquet 读取层只加载本 shard 的 metric 列、组合构建技术列，以及历史 benchmark 成分股实际出现过的 returns 列；不得先读全宽表再裁剪。
- 同一 worker 内应只准备一次 screen/returns，并复用与 metric 无关的月度技术底表和 benchmark NAV。只有输入只读、缓存键覆盖 benchmark、日期、权重、中性化、分位数和推荐参数时才允许复用。
- shard 应尽量包含多个 metric，使 Top/Worst 和后续 metric 能复用月度底表与 benchmark；worker 数量不能超过待测 metric 数。
- 并行度必须在目标机器上用完整 official artifact 流程实测。当前 32 logical CPU / 64GB 工作站的 STOXX600 长矩阵默认使用 8 个进程，内存紧张或同时运行其他任务时应显式下调。
- 任何性能优化进入 official 路径前，必须用既有 official 产物逐值核对 `sec_list`、`perf_ptf`、`perf_bench`，至少覆盖 Top、Worst 和跨 metric 缓存命中；只比较最终 CAGR 或图形不构成等价证明。
- 性能记录至少包含端到端 wall time、成功运行数、screen/returns 裁剪前后维度和单 worker 内存。速度提升不能改变 gate、持仓、权重、净值或 artifact contract。

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

- [`../08_presentation_layer/legacy_apps/company_analysis/README.md`](../08_presentation_layer/legacy_apps/company_analysis/README.md)
- [`../08_presentation_layer/legacy_apps/web_app_des_companies/README.md`](../08_presentation_layer/legacy_apps/web_app_des_companies/README.md)
- [`../08_presentation_layer/legacy_apps/dashboard_analysis/README.md`](../08_presentation_layer/legacy_apps/dashboard_analysis/README.md)

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

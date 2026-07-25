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

默认 lag 为 `1, 3, 6, 12` 个 screen observation。历史上预注册为 `1,3,12` 的 run 保持冻结，补测 lag6 时必须新建 run，不覆盖旧结果。同一个 raw variable 的不同 lag 默认是互斥的信号定义，稀疏组合中不得同时堆叠；只有明确预注册为期限结构或自相关交互研究时才允许例外。变量若本身已经是 growth、revision、momentum、return、CAGR 或 change-like 字段，不应机械再做二阶变化，除非研究问题明确需要。

相对变量必须作为新的 raw variable 经过同一 official Top/Worst gate。运行产物至少包括：

- `relative_variable_definitions.csv`
- `relative_validation_gate.csv`
- `relative_vs_level_comparison.csv`
- `official_run_results.csv`
- `performance_summary.csv`
- 中文研究结论，说明经济含义和不能过度声明的边界。

若某变量没有任何月份同时满足最低 coverage 与 Top/Worst 组合互斥条件，
不得强行回测或把它从候选表删除。应将 Top、Worst 两侧记录为
coverage-blocked/skipped，并在 gate 中明确失败。

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
- 计划调仓月缺少真实 benchmark 或 signal snapshot 时，不得前向填充
  signal、复制上月目标权重或合成一次新调仓。若已有组合，沿用上一期证券
  并按实际收益漂移，直到下一个真实快照；若尚未形成首期组合，则保持未
  投资状态。缺失月份、处理方式和验证结果必须进入 audit/manifest。
- worker 应在 Parquet 读取层只加载本 shard 的 metric 列、组合构建技术列，以及历史 benchmark 成分股实际出现过的 returns 列；不得先读全宽表再裁剪。
- 同一 worker 内应只准备一次 screen/returns，并复用与 metric 无关的月度技术底表和 benchmark NAV。只有输入只读、缓存键覆盖 benchmark、日期、权重、中性化、分位数和推荐参数时才允许复用。
- shard 应尽量包含多个 metric，使 Top/Worst 和后续 metric 能复用月度底表与 benchmark；worker 数量不能超过待测 metric 数。
- 并行度必须在目标机器上用完整 official artifact 流程实测。当前 32 logical CPU / 64GB 工作站的 STOXX600 长矩阵默认使用 8 个进程，内存紧张或同时运行其他任务时应显式下调。
- 任何性能优化进入 official 路径前，必须用既有 official 产物逐值核对 `sec_list`、`perf_ptf`、`perf_bench`，至少覆盖 Top、Worst 和跨 metric 缓存命中；只比较最终 CAGR 或图形不构成等价证明。
- 性能记录至少包含端到端 wall time、成功运行数、screen/returns 裁剪前后维度和单 worker 内存。速度提升不能改变 gate、持仓、权重、净值或 artifact contract。

### 共享回测引擎默认优化

以下优化属于共享 official 路径，不应由单一市场脚本重复实现：

- `BacktestService` 必须通过 `load_pruned_backtest_inputs` 规划输入。单次运行按 metric、benchmark 和 start date 裁剪；batch 按全部配置的 metric/benchmark 并集和最早 start date 一次读取。
- Parquet 读取应下推 screen 和 returns 的起始日期，并只物化所需列。returns 证券列应限定为所选 benchmark 历史正权重成员，同时保留 dual-listing pair 的两条记录；CSV/XLS fallback 可以先读取再裁剪，但输出契约必须一致。
- `OfficialPortfolioBacktest`、`SecurityListConstructor`、`SecurityNavEngine`
  默认共享只读 DataFrame，不做整表 deep copy；调用方不得原地修改共享输入。
- 月度历史循环应先建立一次 date-to-row-position 索引，禁止每个月对完整 screen 重复布尔扫描。
- EU Small、S&P 500、Nasdaq、STOXX600 等直连 official runner 必须通过同一 `BacktestService` 准备 screen/returns，并传入 worker-local 月度底表和 benchmark cache。
- 不得把 float downcast、改变日收益复利顺序、近似 rank 或缓存键不完整的优化设为默认。它们必须独立通过 exact artifact gate 后才能晋级。
- 回测公开入口是 `tp_core.backtesting`；证券级净值计算唯一内核是
  `SecurityNavEngine` / `calculate_security_nav()`。
  `SecurityListConstructor` 只构造证券列表，
  `OfficialPortfolioBacktest` 只编排标准权重、benchmark 和 official
  artifacts，`OptimizerBacktestAdapter` 只转换优化器权重。
- sector、regime、news 等已有聚合收益序列的研究使用
  `calculate_return_series_nav()`，不得强行进入证券级引擎。
- official manifest 必须记录 `engine_id`、`engine_version` 和日期执行口径。活动代码不得恢复 `BacktestEngine.py`、`core.backtest_engine` 或 `BacktestEngineOptimized`。
- missing-rebalance audit 至少验证上一有效期与缺失期后的持仓证券集合相同、
  权重因实际收益发生漂移、权重和保持 1；不能只以 NAV 连续作为证明。
- 权重变换统一使用 `tp_core.portfolio_weights`。顺序为原始权重、日期内
  归一、行业目标匹配、行业内硬封顶并保持行业总权重；不可行的单股上限
  必须报错。
- raw、relative、pair、subset、bucket/individual leave-one-out 的 gate、resume、分片和
  候选矩阵统一使用 `backtest_code.research.executor`。gate 必须同时有
  official Top 与 Worst 终态证据；完全缺失结果的应测变量也必须留在
  gate 表并判定失败。
- 组合优化唯一入口是 `optimizer.optimize_portfolio()`。目标函数、线性
  约束、求解器和版本必须写入产物；不得从市场脚本调用优化器内部函数。
  求解后不得删除小权重再归一，必须复核所有约束后才可落盘。

2026-07-23 共享层验证：代表性 STOXX600 Top/Worst 的持仓、标准权重、`perf_ptf`、`perf_bench` 与既有 official 产物全部 exact；最大差异 0.0。月度取片微基准由每轮 0.0583 秒降至 0.0168 秒。

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

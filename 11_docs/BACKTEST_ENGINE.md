# TP 唯一回测 API

最后更新：2026-07-23
状态：唯一证券级净值内核已启用，旧入口已移出活动代码。

## 1. 唯一入口

所有新回测必须从 `tp_core.backtesting` 或 `tp_core.general_backtest` 导入：

| 职责 | 唯一对象 |
| --- | --- |
| 标准权重表证券级回测 | `GeneralBacktestEngine` / `backtest_weight_table()` |
| 选股、标准权重与 official artifacts | `PtfBuilder` |
| 优化器输出转标准权重 | `OptimizerBacktestAdapter` |
| sector/regime/news 聚合收益 | `backtest_return_series()` |

活动目录不再提供：

- `07_backtest_code/BacktestEngine.py`
- `07_backtest_code/core/backtest_engine.py`
- `07_backtest_code/core/backtest_engine_optimized.py`
- `03_ml_enhanced/Codes/BacktestEngine.py`
- `BacktestEngineOptimized` 旧类名

旧源码只保存在
`99_archive/backtest_engine_consolidation_20260723/`，不在 `sys.path`，
不得作为运行入口。

## 2. 标准权重契约

证券级回测输入为 long-format 权重表：

| 字段 | 含义 |
| --- | --- |
| `Date` | 信号或调仓日期 |
| `Company SEDOL` | 与 returns 列匹配的证券 ID |
| `Portfolio weight` | 目标权重 |

returns 输入为：

- index：交易日；
- columns：证券 ID；
- values：日简单收益率。

```python
from tp_core.backtesting import BacktestSchema, GeneralBacktestEngine

engine = GeneralBacktestEngine(returns)
result = engine.run_weights(
    weights,
    schema=BacktestSchema(
        date_col="Date",
        id_col="Company SEDOL",
        weight_col="Portfolio weight",
    ),
)
```

`GeneralBacktestResult` 包含 `nav`、`daily_returns`、
`rebalance_weights`、`execution_weights`、`turnover`、`metrics` 和
`manifest`。

## 3. 日期执行口径

official Top/Worst 默认口径：

- `strictly_after_rebalance=True`：映射到调仓日之后第一个 returns 交易日；
- `apply_weights_at_close=True`：该交易日收益先按旧权重计算，新权重收盘后生效；
- 初始 NAV 为 100；
- 缺失证券收益按 0 处理；
- 每个交易日按收益漂移权重。

需要“第一个交易日开盘即生效”的研究必须显式使用
`apply_weights_at_close=False`。low-vol 研究保留这一历史口径。

聚合后的 sector/regime/news 收益不得伪装成证券权重表：

```python
from tp_core.backtesting import backtest_return_series

result = backtest_return_series(
    monthly_returns,
    initial_nav=1.0,
    periods_per_year=12,
)
```

## 4. 已启用优化

唯一内核和 official runner 默认使用以下优化：

- NumPy 行循环替代 pandas `iterrows()`，但保持资产顺序和浮点运算顺序；
- Parquet 列与日期下推，只读取当前 benchmark、metric 和历史成分证券；
- screen/returns 作为 worker 内只读共享对象，不做整表 deep copy；
- 一次建立月度 date-position index；
- worker 内复用月度技术底表和 benchmark NAV；
- 大矩阵使用可 resume 的进程级分片和 unique wave 目录。

禁止默认启用 float downcast、近似 rank、改变复利顺序或缓存键不完整的
优化。新优化必须先通过 official exact artifact gate。

真实 STOXX600 Top 权重基准中，4,211 个交易日、1,144 个 returns 列、
23,256 条权重和 198 个调仓日的漂移循环，从旧 `iterrows` 中位数
1.1673 秒降至 0.0768 秒，约 15.21 倍；逐位相等，最大差异 0.0。

## 5. 产物溯源

证券级内核版本：

- `engine_id = tp.general_backtest`
- `engine_version = 2.0.0`

每个 official run 的 `manifest.yaml` 必须写入：

- `engine_id`
- `engine_version`
- `execution_policy.strictly_after_rebalance`
- `execution_policy.apply_weights_at_close`
- `execution_policy.rebalance_mapping`
- `execution_policy.weight_application`

主市场研究包的 `manifest.json` 同样写入这些字段。

## 6. 删除旧入口的门槛

2026-07-23 使用 STOXX Europe 600 官方指标
`stoxx600_syn_pair_196c20ee30b3` 完成 Top/Worst 迁移检查：

| 产物 | 结果 |
| --- | --- |
| Top/Worst 持仓与原始权重，各 23,256 行 | exact |
| Top/Worst 标准组合权重，各 23,256 行 | exact |
| Top/Worst 组合 NAV，各 4,211 日 | exact |
| Top/Worst benchmark NAV，各 4,211 日 | exact |
| benchmark 标准权重，112,568 行 | exact |

全部最大绝对差异为 `0.0`。证据位于：

- `07_backtest_code/runs/ad_hoc/engine_consolidation_exact_20260723/exact_equality.csv`
- `07_backtest_code/runs/ad_hoc/engine_consolidation_exact_20260723/kernel_benchmark.json`
- `99_archive/backtest_engine_consolidation_20260723/manifest.json`

以后修改内核时，至少重复比较 Top、Worst 的持仓、标准权重、NAV 和
benchmark NAV；只比较 CAGR、Sharpe 或曲线外观不构成发布证据。

## 7. 模块边界

- `PtfBuilder` 可以选股、过滤、生成标准权重、调用唯一内核并保存产物，
  但不能实现另一套收益复利。
- `OptimizerBacktestAdapter` 只把 `Wopt` 转成标准权重并调用唯一内核。
- 技术分析和 low-vol 脚本必须输出标准权重表。
- sector/regime/news 只在已有聚合收益时调用 `backtest_return_series()`。
- 市场脚本不得重新实现本地 `nav_from_weights`、动态加载旧
  `BacktestEngine.py`，或恢复任何已归档入口。

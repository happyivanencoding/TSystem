# TP 回测引擎唯一 API 合并报告

日期：2026-07-23

## 结论

TP 证券级回测已合并为一个活动净值内核：
`tp_core.general_backtest.GeneralBacktestEngine`。旧入口已从活动目录删除，
不可导入；`PtfBuilder` 和优化器只负责生成标准权重与 official artifacts。

## 当前 API

| 场景 | API |
| --- | --- |
| 标准证券权重 | `backtest_weight_table()` / `GeneralBacktestEngine.run_weights()` |
| official 组合构造 | `tp_core.backtesting.PtfBuilder` |
| 优化器结果 | `tp_core.backtesting.OptimizerBacktestAdapter` |
| 聚合收益序列 | `backtest_return_series()` |

所有 official manifest 记录：

- `engine_id: tp.general_backtest`
- `engine_version: 2.0.0`
- 调仓日映射和权重生效口径

## 已删除活动入口

- `07_backtest_code/BacktestEngine.py`
- `07_backtest_code/core/backtest_engine.py`
- `07_backtest_code/core/backtest_engine_optimized.py`
- `03_ml_enhanced/Codes/BacktestEngine.py`
- `BacktestEngineOptimized` 旧类名和旧式 PtfBuilder 回测 helper

源文件归档于
`99_archive/backtest_engine_consolidation_20260723/`，不在运行路径。

## Exact Equality

代表指标：`stoxx600_syn_pair_196c20ee30b3`  
市场：STOXX Europe 600  
期间：2010-01-31 至 2026-07-02

| 比较项 | 规模 | 结果 | 最大差异 |
| --- | ---: | --- | ---: |
| Top 持仓与原始权重 | 23,256 行 | exact | 0.0 |
| Worst 持仓与原始权重 | 23,256 行 | exact | 0.0 |
| Top 标准组合权重 | 23,256 行 | exact | 0.0 |
| Worst 标准组合权重 | 23,256 行 | exact | 0.0 |
| Top/Worst 组合 NAV | 各 4,211 日 | exact | 0.0 |
| Top/Worst benchmark NAV | 各 4,211 日 | exact | 0.0 |
| benchmark 标准权重 | 112,568 行 | exact | 0.0 |

证据：
`07_backtest_code/runs/ad_hoc/engine_consolidation_exact_20260723/exact_equality.csv`

## 内核性能

真实 Top 权重漂移循环：

| 指标 | 数值 |
| --- | ---: |
| 交易日 | 4,211 |
| returns 列 | 1,144 |
| 权重行 | 23,256 |
| 调仓日 | 198 |
| 旧 `iterrows` 中位数 | 1.1673 秒 |
| 新 NumPy exact 循环中位数 | 0.0768 秒 |
| 提速 | 15.21x |
| 数值比较 | exact，最大差异 0.0 |

证据：
`07_backtest_code/runs/ad_hoc/engine_consolidation_exact_20260723/kernel_benchmark.json`

## 研究路径迁移

- 技术分析原本已输出 `Portfolio weight`，继续直接调用唯一内核。
- 两个 low-vol 研究脚本已输出标准权重，并保留“首个交易日开盘生效”
  的历史口径；与旧算法最大 NAV 差异 `1.28e-13`。
- sector、regime、news 已改用 `backtest_return_series()`。
- EU Small、S&P 500、Nasdaq、STOXX600 继续共享输入裁剪、月度底表缓存、
  benchmark 缓存和进程级分片。

## 验证

- 相关测试：82 passed，1 skipped。
- skill：`quick_validate.py` 通过。
- `git diff --check` 通过。
- 旧模块导入检查：全部 `NOT_IMPORTABLE`。

# STOXX Europe 600 官方回测引擎优化报告

日期：2026-07-23

## 结论

本次优化保留官方 `PtfBuilder -> generic_histo_seclist -> backtest -> benchmark` 路径，没有改变因子 gate、组合构建规则或 artifact schema。

- 单个 Top 官方运行从 36.29 秒降至 9.18 秒，缩短 74.7%。
- 同一 metric 的 Worst 复用月度底表和 benchmark 后为 5.06 秒。
- 单 worker 输入由 118,001 x 319 的 screen 和 5,511 x 12,014 的 returns，裁剪为 118,001 x 8 和 5,511 x 1,156。
- 单 worker 实测常驻输入从约 2.60GB 降至 456MB，下降约 82.4%。
- 16 个 metric、32 个 Top/Worst official runs：4 进程 164.29 秒，8 进程 108.97 秒，8 进程加输入裁剪 82.13 秒。
- 裁剪版相对 4 进程未裁剪版缩短 50.0%，相对 8 进程未裁剪版缩短 24.6%。

## 实施内容

1. official batch worker 在 Parquet 读取层只加载本 shard 的 metric 和组合构建技术列。
2. returns 只加载 STOXX600 历史研究 screen 中实际出现过的 SEDOL。
3. screen 与 returns 在每个 worker 内只准备一次，并以只读对象传给引擎。
4. 同一 worker 内缓存与 metric 无关的月度 benchmark 成分、行业权重、市值资格和 benchmark NAV。
5. 行业内 score rank neutralization 改为等价的向量化 groupby 计算。
6. 月度历史持仓逐月生成，不再预先复制并保存全部月份切片。
7. 长矩阵继续使用可恢复的进程级 shard；STOXX600 在当前 32 logical CPU、64GB 工作站上默认 8 workers。

## 共享层下沉

第二阶段把不应只属于 STOXX600 脚本的优化下沉到共享系统：

1. 新增 `backtest_code.runner.input_loader.load_pruned_backtest_inputs`，统一处理 metric/benchmark 列并集、Multi Avg 源列、日期下推和 returns SEDOL 裁剪。
2. `BacktestService` 的单次和 batch 路径自动使用输入规划器；batch 从所有配置的最早日期一次读取共享输入。
3. `PtfBuilder`、`PortfolioBuilder`、`GeneralBacktestEngine` 默认共享只读输入；活动代码不再保留第二套 `BacktestEngine`。
4. 月度循环一次建立 date-to-row-position 索引，不再逐月扫描完整 screen。
5. EU Small、S&P 500、Nasdaq、STOXX600 直连 runner 和通用 factor pipeline 统一复用 prepared inputs、月度底表 cache 和 benchmark cache。

真实 STOXX600 单 metric 裁剪后，screen 为 116,217 x 8、returns 为 4,212 x 1,144，DataFrame 深度内存分别约 25.71MB 和 36.67MB，读取耗时 0.60 秒。月度取片微基准从每轮 0.0583 秒降至 0.0168 秒，约 3.48 倍。

### 跨市场抽样

使用各市场 2026-07-07 旧顺序运行目录的相邻 run timestamp 作为优化前中位基线，并在 2026-07-23 用同一历史 metric、同一起始日期重跑完整 official artifact 路径。Top 为冷启动；Worst 紧随 Top，命中同一 worker 的月度底表和 benchmark cache。

| 市场 | 旧 Top | 新 Top | 旧 Worst | 新 Worst | Top/Worst 合计提速 |
|---|---:|---:|---:|---:|---:|
| EU Small | 120.0s | 51.4s | 113.5s | 27.4s | 2.96x |
| Nasdaq Composite | 41.0s | 18.0s | 38.0s | 9.8s | 2.85x |
| S&P 500 | 35.0s | 26.8s | 30.0s | 12.4s | 1.66x |

抽样 metric 和起始日期不同，因此该表用于容量规划，不替代每个研究矩阵自己的端到端 benchmark。共享加载器进一步把 returns 限定为所选 benchmark 历史正权重成员，并保留 dual-listing pair 的两条证券记录；三组抽样的原始输入内存约为 EU Small 127.6MB、Nasdaq 47.3MB、S&P 500 50.9MB。

## 等价性门控

代表性已有官方 metric `stoxx600_syn_pair_56f732432d80`：

- Top `sec_list`：exact
- Top `perf_ptf`：exact
- Top `perf_bench`：exact
- Worst `sec_list`：exact
- Worst `perf_ptf`：exact
- Worst `perf_bench`：exact

批量验证使用相同 16 个 metrics、32 个 metric-side 组合，对未裁剪与裁剪 worker 的产物逐表比较：

- 32 / 32 `sec_list` exact
- 32 / 32 `perf_ptf` exact
- 32 / 32 `perf_bench` exact

比较使用 pandas exact equality，包含值、dtype、列顺序和行顺序。最终 CAGR 相似或图形相似不被视为等价证据。

共享层下沉后，另用 `stoxx600_syn_pair_196c20ee30b3` 对已有 official 产物复验：

- Top `sec_list`、`perf_ptf`、`perf_bench`：全部 exact
- Worst `sec_list`、`perf_ptf`、`perf_bench`：全部 exact

## 验证

- `python -m py_compile`：全部修改文件通过。
- `python -m pytest 07_backtest_code/tests -q`：31 passed；共享输入 batch union 测试加入后为 32 项。
- 新增测试覆盖向量化行业中性化、跨 metric/Top/Worst 月度缓存、worker 输入列裁剪、Multi Avg 依赖展开、共享只读输入和 batch metric union。

## 适用边界

- 月度底表缓存不用于 `Multi Avg Percentile`、DataFrame 型动态行业推荐、financial filter 或缓存键未覆盖的状态型配置。
- 缓存只在单 worker 内使用，不跨进程共享可变 pandas 对象。
- worker 数应小于等于待测 metric 数，并按目标机器端到端实测调整。
- 当前默认 8 workers 只代表本机 STOXX600 长矩阵的实测选择，不是所有市场和机器的固定答案。
- float downcast、改变日收益复利计算顺序和近似 rank 尚未获得 exact 证据，因此没有进入共享默认路径。

## 参考实现

优化思路对照了 `C:\Users\jingx\Downloads\公司回测插件\RAPPORT_OPTIMISATION_BACKTEST.md`，并按 TP 当前官方引擎结构重新实现和验证。TP 已经使用 `01_tp_core/general_backtest.py` 的日频路径，因此没有机械复制插件中与旧 `stack()` 路径有关的修改。

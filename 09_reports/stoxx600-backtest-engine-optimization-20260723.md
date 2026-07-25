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

## 验证

- `python -m py_compile`：全部修改文件通过。
- `python -m pytest 07_backtest_code/tests -q`：29 passed。
- 新增测试覆盖向量化行业中性化、跨 metric/Top/Worst 月度缓存和 worker 输入列裁剪。

## 适用边界

- 月度底表缓存不用于 `Multi Avg Percentile`、DataFrame 型动态行业推荐、financial filter 或缓存键未覆盖的状态型配置。
- 缓存只在单 worker 内使用，不跨进程共享可变 pandas 对象。
- worker 数应小于等于待测 metric 数，并按目标机器端到端实测调整。
- 当前默认 8 workers 只代表本机 STOXX600 长矩阵的实测选择，不是所有市场和机器的固定答案。

## 参考实现

优化思路对照了 `C:\Users\jingx\Downloads\公司回测插件\RAPPORT_OPTIMISATION_BACKTEST.md`，并按 TP 当前官方引擎结构重新实现和验证。TP 已经使用 `01_tp_core/general_backtest.py` 的日频路径，因此没有机械复制插件中与旧 `stack()` 路径有关的修改。

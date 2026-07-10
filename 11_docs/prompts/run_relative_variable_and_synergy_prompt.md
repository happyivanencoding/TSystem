# Prompt: Other-Market Relative Variable And Synergy Research

把下面这段复制到另一个 Codex 对话框，用于其他市场/benchmark 的补充分析。

```text
请使用 `tp-quant-research-workflow`，按照 TP 因子研究流水线，对 [MARKET_OR_BENCHMARK] 做 raw variable、相对变量和协同效应补充研究。目标是回答：哪些单变量有效，哪些绝对水平变量转成同一股票相对变化后更有效，哪些变量组合真正有协同。

必须先读取并遵守：
- `C:\Users\jingx\.codex\skills\tp-quant-research-workflow\SKILL.md`
- `C:\GoogleDrive\TP\11_docs\RESEARCH_METHODS.md`
- `C:\GoogleDrive\TP\11_docs\FACTOR_RESEARCH_CODE_RULES.md`

研究对象：
- Universe / Benchmark: [MARKET_OR_BENCHMARK]
- Universe rule: 优先用 `Weight in [MARKET_OR_BENCHMARK] > 0`；若该列不存在，先审计 screen columns 后提出最接近口径。
- 数据源: `C:\GoogleDrive\TP\00_screen\screen_aggregate.parquet` 和 `C:\GoogleDrive\TP\00_screen\returns.parquet`
- 输出目录: `C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\`

执行要求：
1. 先审计可用字段、benchmark 权重列、起止日期、月度样本数、returns SEDOL 覆盖率。
2. 从 raw variables 开始，不要直接使用数据库综合因子做结论；数据库已有因子只能做 comparison anchor。
3. 每个 raw variable 必须统一方向为 higher-is-better，并先单独跑 official Top/Worst。
4. CIQ、FactSet、database、本地衍生字段走同一套 evidence gate；`core/supplement` 只作为诊断标签，不能决定入选。
5. 默认 gate: coverage >= 0.75、Top/Benchmark ratio CAGR > 0、Top/Worst ratio return > 0、robust_score > 0。若覆盖或市场特征要求调整，必须明确说明原因。
6. 对绝对水平变量补充 same-security relative variants：
   - `directional_delta`: 方向调整后的 raw level 减同一股票 lagged raw level，再 winsorize + sector/neutral bucket rank。
   - `score_delta`: 当前 neutralized raw score 减同一股票 lagged score，再 neutral bucket rank。
   - 默认 lag: 1、3、12 个 screen observation。
   - 不要机械处理已经是 growth、revision、momentum、total return、CAGR、change-like 的字段，除非明确研究二阶变化。
7. 每个 relative variant 作为新的 raw variable 单独跑 official Top/Worst，并生成 `relative_validation_gate.csv` 和 `relative_vs_level_comparison.csv`。
8. 通过 raw/relative gate 后，再测试有经济逻辑的组合：
   - revision + margin improvement
   - momentum + ROE/quality improvement
   - earnings yield improvement + EPS growth/revision
   - deleveraging + low-vol / risk decline
   - 以及该市场更合理的组合
9. 不允许在没有 raw variable、pair/subset 或 leave-one-out 证据时声称 synergy。
10. 对 synergy 必须生成 pair、family subset 或 leave-one-out evidence，并分类为 `synergistic`、`additive`、`redundant`、`harmful`。
11. 全部结论必须来自 official exact Top/Worst，不得把 fast screening 当最终证据。
12. 长矩阵使用可 resume 的进程级并行分片：worker 独立 shard CSV 和 official run root，父进程 merge/dedupe；restart 使用 unique wave 目录，不覆盖旧 shard。
13. 输出中文研究报告，必须包括：
    - 数据审计
    - raw variable gate
    - relative variable gate
    - relative vs level comparison
    - pair/subset/leave-one-out synergy evidence
    - Top/Worst/Benchmark 和 Top/Worst ratio 图
    - 哪些变量有效、为什么、经济含义是什么
    - 哪些组合真有协同、为什么、经济含义是什么
    - 哪些只是待验证假设或弱证据

完成前不要只给计划；请实际跑完所有指定组合。如果矩阵很大，先做可 resume 的并行 runner，并持续补缺口直到 expected_run_count 全部完成或被明确判定为 no eligible benchmark/signal intersection。
```


# Score_Sectoriel_US.xlsm 方法论与 Python 复刻口径

## 1. 原 Excel 模型定位

`Score_Sectoriel_US.xlsm` 是一个美股行业轮动模型。工作簿以 FactSet / Bloomberg 数据为输入，按月计算美国行业的基本面、估值、动量、增长、低波和宏观周期信号，最后给出行业 `Positive / Neutral / Negative` 推荐，并通过行业组合回测验证。

原文件位于：

```text
C:\GoogleDrive\TP\99_archive\frozen_20260629\factsetProd第一版\Score_Sectoriel_US.xlsm
```

## 2. 原 Excel 工作簿结构

主要工作表职责如下：

| 工作表 | 作用 |
| --- | --- |
| `Config` | 行业指数代码、命名区域、Top/Worst 阈值、导出路径和 R 脚本路径。 |
| `SCORECARD` | 当前行业评分和推荐展示页。 |
| `Returns_EQ` | 行业指数收益序列和基准收益。 |
| `Leverage_FMA` | 杠杆相关因子。 |
| `Margin_FMA` | 利润率因子。 |
| `Valuation_FMA_hist` | 估值因子。 |
| `MOM_FMA` | 动量和盈利修正因子。 |
| `Growth_FMA` | 增长因子。 |
| `Vol_FMA` | 低波因子。 |
| `5F_FMA*` | 多因子综合分、宏观周期增强和 Top/Worst 旗标。 |
| `Ptf dev bench` | 行业推荐转为相对基准行业权重偏离后的回测。 |
| `Cycle macro` | 宏观周期和利率信号。 |

工作簿有 `__FDSCACHE__` very hidden 表和 `Module1` VBA 模块。VBA 主要用于刷新 FactSet、延展公式、导入宏观周期/基准权重、导出 CSV 和调用 R 生成图，不是每次打开自动改变结果的事件逻辑。

## 3. 原 Excel 行业池

原模型覆盖 12 个行业/板块：

- Materials
- Consumer Staples
- Retail
- Financials
- Health Care
- Industrials
- Energy
- Technology
- Telecommunications
- Utilities
- Travel & Leisure
- Media

Python 版使用 `screen_aggregate.parquet` 中覆盖完整的 `Benchmark ICB Supersector`，映射为 19 个 ICB 超级行业。这样能保留 Retail、Media、Travel & Leisure、Banks、Insurance、Financial Services 等更接近 Excel 的行业拆分。

## 4. 原 Excel 基础因子

原模型先在每个基础因子页计算行业指标，再把指标转为行业间排名或 60 个月历史分位。`SCORECARD` 中很多排名以 `13 - rank` 展示，因此数字越小通常越优。

| 支柱 | 原 Excel 主口径 |
| --- | --- |
| Low Leverage | 主要使用 Net Debt / EBITDA 与 FCF / Total Debt。低债务、高现金流覆盖更优。 |
| Margin | 主要使用 Operating Margin、Net Margin、EBITDA Margin。高利润率更优。 |
| Valuation | 主要使用 Price / FCF、EV / EBITDA、Price / Sales。低估值更优。 |
| Momentum | 主要使用 6M-1M 表现、12M 表现、EPS 上修/下修比例。高动量和正修正更优。 |
| Growth | 主要使用未来 12 个月现金流和 EBITDA 增长。高增长更优。 |
| Low Volatility | 主要使用 6 个月波动和 18 个月下行波动。低波动更优。 |

## 5. 原 Excel 综合分与推荐

`5F_FMA` 表虽然命名为 5F，但实际读取六类支柱，其中 Margin 权重为 0。基础综合权重约为：

- Leverage 20%
- Value 20%
- Momentum 20%
- Growth 20%
- Volatility 20%
- Margin 0%

`5F_FMA + macro` 加入宏观周期后，Leverage、Value、Momentum、Growth、Volatility、Cycle Macro 各约 1/6，Margin 仍为 0。

`5F_FMA_Quali + macro` 统计行业落入 Top 3 / Worst 3 支柱的次数，并用自定义函数 `_xll.tab_invest(..., "Top/Worst", 3)` 生成 Top 3 和 Worst 3 旗标。`SCORECARD` 的推荐规则是：

- Top flag = 1：`Positive`
- Worst flag = 1：`Negative`
- 否则：`Neutral`

## 6. 宏观周期与利率信号

`Cycle macro` 中的宏观周期标签为 `C / R / E / SD`。利率信号使用美国 10 年期国债收益率：

1. 对 US 10Y 做 EWMA，平滑参数为 0.715。
2. 计算当前 US 10Y 与 EWMA 的差值。
3. 对差值做历史百分位。
4. 百分位高于 0.85 时利率信号为 `On`，否则为 `Off`。

利率信号为 `On` 时，原模型会额外强化 Leverage 和 Value 在 Top/Worst 计数中的影响。

## 7. Python 复刻模型的数据口径

Python 版默认使用：

- 股票池：`Weight in SP500 > 0`
- 行业：`Benchmark ICB Supersector` 映射的 ICB19 超级行业
- 证券收益：`returns.parquet` 中与 `Company SEDOL` 匹配的日收益列
- 调仓频率：月度
- 信号日期：`screen_aggregate.parquet` 月末截面
- 持有收益：从信号日期之后到下一信号日期的日收益复利

## 8. Python 版变量设计

Python 版保留 Excel 的六大支柱，同时加入一个经长期测试支持的最终模型分数。

| Python 支柱 | 字段与方向 |
| --- | --- |
| `leverage` | `10 - PCT NBEBITDA`，低净债务/EBITDA更优。 |
| `margin` | `PCT OM FY0`，营业利润率更高更优。 |
| `valuation` | `10 - mean(PCT EVEBITDA NTM, PCT PFCF NTM, PCT EV to Sales NTM)`，低估值更优。 |
| `momentum` | `mean(PCT MOM 12M1M, PCT ERR)`，价格动量和盈利修正越高越优。 |
| `growth` | `mean(PCT EPS Growth NTM, PCT Sales Growth NTM, PCT Gross Income Growth NTM)`，增长越高越优。 |
| `lowvol` | `10 - mean(PCT DVol 60J, PCT DVol 90J, PCT DVol 260J)`，低波更优。 |

## 9. 金融行业特殊处理

金融行业确实不应机械套用普通工业企业变量。银行、保险、金融服务、地产等行业中，Net Debt / EBITDA、EV / EBITDA 往往不可比或覆盖较差。因此 Python 版对以下 ICB19 超级行业启用金融特殊处理：

- Banks
- Financial Services
- Insurance
- Real Estate

特殊处理逻辑：

| 普通变量 | 金融行业替代/补充 |
| --- | --- |
| Leverage | 使用 ROE、ROTE、Tier1、Operating Margin、Quality Avg Percentile 和低 Combined Ratio 的综合代理。 |
| Margin / Quality | 使用金融质量代理替代普通 margin。 |
| Valuation | 使用 PB NTM、PE NTM 的低估值分位，并结合 `Value_NTM Avg Percentile` 与 `Value Avg Percentile`。 |

代码中会同时输出普通 Excel-like 分数和 financial-aware 分数，最终默认模型使用 financial-aware 的质量和估值组合。

## 10. 最终默认模型

长期测试后，完整六因子复刻模型是可输出的审计口径，但更稳定的默认模型是：

```text
score_final = 50% * finaware_valuation + 50% * finaware_quality
```

选择原因：

- 估值和质量在 2010-2026 的行业横截面测试中 IC 和 Top-Bottom 表现更稳定。
- 金融行业使用 PB/PE、ROE/ROTE/Tier1/Combined Ratio 等更适配变量。
- 行业组合采用接近原 Excel 的相对基准权重偏离方式，不是孤立等权行业组合。

## 11. 回测与有效性测试

脚本会输出两类证据：

1. **变量有效性测试**：对每个变量计算月度行业横截面 Spearman IC、IC 正比例、Top 3 - Bottom 3 下一月收益、Top-Bottom 命中率。
2. **长期组合回测**：每月选 Top 3 行业加权、Bottom 3 行业减权，并与 SP500 行业权重基准比较。

行业偏离规则沿用 Excel 的思想：

- Top 行业权重取 `max(基准权重 * 1.2, 基准权重 + 5%)`
- Worst 行业权重取 `min(基准权重 * 0.8, max(0, 基准权重 - 5%))`
- 其他行业保留基准权重
- 最后归一化为 100%

## 12. 运行产物

运行后查看：

- `outputs\factor_effectiveness.csv`
- `outputs\backtest_summary.json`
- `outputs\backtest_monthly_returns.csv`
- `outputs\sector_scores_latest.csv`

这些文件是判断 Python 版模型是否长期有效的主证据。

## 13. 当前长期回测结论

已运行默认脚本，样本为 2010-01-31 至 2026-04-30，共 196 个月。

| 指标 | 最终模型 | SP500 行业权重基准 |
| --- | ---: | ---: |
| 年化收益 | 16.69% | 15.96% |
| 年化波动 | 14.22% | 14.13% |
| Sharpe | 1.17 | 1.13 |
| 最大回撤 | -18.96% | -19.31% |
| 月度正收益比例 | 66.84% | 65.82% |
| 总收益 | 1145.04% | 1022.86% |

主动收益：

- 全样本主动年化约 0.64%，相对年化约 0.63%，主动月度命中率 56.63%。
- 前半段样本 2010-01-31 至 2018-02-28，相对年化约 0.33%。
- 后半段样本 2018-03-31 至 2026-04-30，相对年化约 1.27%。
- 2020 年后样本，相对年化约 1.64%。

变量有效性测试中，`margin`、`finaware_margin`、`financial_quality_proxy`、`finaware_quality`、`quality_style` 的平均 IC 为正；最终 `score_final` 的 Top 3 - Bottom 3 年化差约 5.42%。完整表见 `outputs\factor_effectiveness.csv`。

结论：完整六因子复刻口径可以保留用于审计和解释，但长期回测支持的默认生产口径应优先使用 financial-aware 的质量 + 估值组合，并以行业权重偏离而非纯等权行业多空作为落地组合方式。

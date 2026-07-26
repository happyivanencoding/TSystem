# `patterns.parquet` 专项上下文

Screen 与 returns 的通用语义、主键和连接规则以 `../../00_screen/说明文档/screen_returns_context.md` 为准。本文只补充 Technical patterns 的长期稳定契约，不复制 Canonical 数据统计。

## 数据角色

`output/patterns.parquet` 是由历史 returns 计算的证券技术形态和指标面板，供技术研究及统一 Technical 信号导出使用。它是模型专项产物，不是 Canonical 数据源。

## 粒度与时间

- 一行表示证券在一个技术观察周期上的状态。
- `Date` 是原始 pattern 标签日期，不自动等于信号可交易时间。
- Weekly pattern 需要完整周数据形成；生产导出必须另外计算 `technical_available_date`。
- 统一信号表中的 `effective_date` 使用可用日，`as_of_date` 或 `technical_pattern_date` 保留原始标签日。
- 所有滚动指标只允许使用窗口截止时已经发生的 returns。

## 标识与连接

- 证券通过规范化 `Company SEDOL` 与 Screen/returns 对齐。
- Universe、行业、国家和指数权重来自信号当时已知的 Screen 截面，不从 patterns 反推。
- 未匹配标识、重复证券周期和数据不足窗口必须显式排除并记录。
- 不允许用最新 Screen 成分回填历史 patterns。

## 字段族

| 字段族 | 示例与用途 |
| --- | --- |
| 趋势结构 | higher high/lower low、趋势持续、突破与回撤状态 |
| K 线形态 | Doji、Hammer、Engulfing、Harami、Morning/Evening Star 等 |
| 动量与超买超卖 | RSI、ROC、stochastic 类指标 |
| 趋势与均线 | SMA/EMA 位置、交叉和斜率 |
| 风险与波动 | rolling volatility、ATR、价格区间 |
| 成交与确认 | 若输入存在可用成交字段，则作为确认特征 |
| 可用时间 | pattern 标签日、数据窗口截止日、`technical_available_date` |

具体 pattern 研究分数、方向和权重见 `../docs/pattern_backtest_score_guide.md`。字段方向不能仅凭名称推断，应在研究配置中显式声明 `higher_is_better`。

## 生成与导出

生成 patterns：

```powershell
python -m tp_models.technical.Main
```

导出标准 Technical 信号：

```powershell
python -m tp_models.technical_signals
```

生产主线优先使用：

```powershell
.\.venv_tp\Scripts\tp-pipeline-export-signals.exe
```

不得执行 `03_technical_analysis` 资源目录中的旧脚本。

## 质量门槛

- `(Company SEDOL, Date)` 或模型声明的等价键唯一。
- 输入 returns fingerprint、窗口截止日期和代码版本有记录。
- `effective_date` 不早于形成该 pattern 所需的最后输入日期。
- 最新导出日期不超过 Canonical Screen 的可用上限。
- 每个字段有明确方向、缺失处理和最短历史窗口。
- 回测必须包含交易成本、换手和 PIT universe。

## 输出边界

- 专项完整面板：`03_technical_analysis/output/patterns.parquet`。
- 跨项目标准信号：`artifacts/signals/technical_signals.parquet`。
- 运行证据：`artifacts/pipeline_runs/manifests/export_signals/` 和 Experiment Run Card。

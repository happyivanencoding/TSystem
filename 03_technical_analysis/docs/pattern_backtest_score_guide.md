# Pattern Backtest Score 指南

## 1. 先说结论

`Pattern_backtest.ipynb` 里的这三行：

```python
score_columns = ['rsi_14', 'momentum_10', 'MACDh_12_26_9']
score_weights = [0.4, 0.3, 0.3]
higher_is_better = [True, True, True]
```

本质上是在定义一个“横截面打分器”：

- `score_columns`：选哪些字段参与打分。
- `score_weights`：每个字段的权重，程序内部会自动归一化。
- `higher_is_better`：该字段是“越大越好”还是“越小越好”。

当前回测引擎的打分逻辑是：

1. 每个调仓日，在 benchmark 成分股里，对每个 `score_columns` 做横截面排序。
2. 如果 `sector_neutral = True`，则改为先在行业内排序。
3. 每个字段转换成 0 到 1 之间的分位得分。
4. 再按 `score_weights` 做加权平均，得到 `Total Score`。
5. `Total Score` 越高，越优先被选中。

这意味着：

- 只要是 **数值型列**，理论上都可以做 score。
- 但不是所有数值列都“有金融意义”。
- 形态列现在也可以放进 `score_columns`，但建议配合 `score_value_map` 明确指定目标值。
- 如果不给 `score_value_map`，形态列会默认按“是否出现 / 是否命中”转成 0/1 分数。

例如：

```python
score_columns = ['triangle_pattern', 'signal', 'rsi_14', 'momentum_10', 'MACDh_12_26_9']
score_weights = [0.15, 0.15, 0.20, 0.25, 0.25]
higher_is_better = [True, True, True, True, True]
score_value_map = {
    'triangle_pattern': 'Ascending Triangle',
    'signal': ['HH', 'HL'],
}
```

## 2. 哪些字段适合做 score

最适合直接放进 `score_columns` 的，是 `patterns.parquet` 里这些 **连续数值型技术指标**。

### 2.1 动量类

这类指标适合回答“最近强不强”。

| 字段 | 含义 | 常见理解 | 常见方向 |
| --- | --- | --- | --- |
| `momentum_10` | 10 周动量 | 短期价格变化快慢 | `True` |
| `momentum_20` | 20 周动量 | 中短期趋势强度 | `True` |
| `momentum_30` | 30 周动量 | 中期趋势强度 | `True` |
| `momentum_50` | 50 周动量 | 中长期趋势强度 | `True` |
| `momentum_100` | 100 周动量 | 长周期趋势强度 | `True` |
| `rsi_14` | 14 周 RSI | 价格强弱 | 趋势策略常用 `True`，均值回归常用 `False` |
| `rsi_21` | 21 周 RSI | 更平滑的 RSI | 同上 |
| `rsi_30` | 30 周 RSI | 更慢的 RSI | 同上 |
| `rvi_10` | 10 周 RVI | 相对波动方向强弱 | `True` |
| `rvi_14` | 14 周 RVI | 同上 | `True` |
| `rvi_20` | 20 周 RVI | 同上 | `True` |

说明：

- 如果你做 **趋势跟随**，通常偏向 `higher_is_better = True`。
- 如果你做 **超跌反弹 / 均值回归**，`rsi_*` 和部分 `momentum_*` 也可以设成 `False`。

### 2.2 趋势类

这类指标适合回答“趋势是否延续、是否加速”。

| 字段 | 含义 | 常见理解 | 常见方向 |
| --- | --- | --- | --- |
| `ema_10` | 10 周 EMA | 短周期趋势均线 | 通常不单独直接打分 |
| `ema_20` | 20 周 EMA | 中短周期趋势均线 | 通常不单独直接打分 |
| `ema_50` | 50 周 EMA | 中周期趋势均线 | 通常不单独直接打分 |
| `ema_100` | 100 周 EMA | 长周期趋势均线 | 通常不单独直接打分 |
| `fwma_10` | 10 周 FWMA | 加权移动均线 | 通常不单独直接打分 |
| `fwma_30` | 30 周 FWMA | 加权移动均线 | 通常不单独直接打分 |
| `fwma_50` | 50 周 FWMA | 加权移动均线 | 通常不单独直接打分 |
| `MACD_12_26_9` | MACD 主线 | 趋势动能 | `True` |
| `MACDh_12_26_9` | MACD 柱体 | 动能加速度 | `True` |
| `MACDs_12_26_9` | MACD 信号线 | 趋势平滑信号 | `True` |
| `MACD_20_50_18` | 更慢参数的 MACD 主线 | 中周期趋势 | `True` |
| `MACDh_20_50_18` | 更慢参数的 MACD 柱体 | 中周期动能加速度 | `True` |
| `MACDs_20_50_18` | 更慢参数的 MACD 信号线 | 中周期趋势平滑 | `True` |
| `MACD_50_100_25` | 更长参数的 MACD 主线 | 长周期趋势 | `True` |
| `MACDh_50_100_25` | 更长参数的 MACD 柱体 | 长周期动能加速度 | `True` |
| `MACDs_50_100_25` | 更长参数的 MACD 信号线 | 长周期趋势平滑 | `True` |

说明：

- `ema_*`、`fwma_*` 是价格水平本身，**跨股票直接比绝对值通常意义不强**，除非你先做相对化处理。
- `MACD_*`、`MACDh_*`、`MACDs_*` 更适合直接做横截面 score。
- 如果你只想选少量指标，`MACDh_*` 往往比单纯 `ema_*` 更实用。

### 2.3 波动和位置类

这类指标适合回答“是否太拥挤、是否接近上轨、是否波动太大”。

| 字段 | 含义 | 常见理解 | 常见方向 |
| --- | --- | --- | --- |
| `atr_14` | 14 周 ATR | 波动幅度 | 趋势里不一定越高越好，低波策略常用 `False` |
| `atr_21` | 21 周 ATR | 波动幅度 | 常见 `False` |
| `atr_30` | 30 周 ATR | 波动幅度 | 常见 `False` |
| `stdev_10` | 10 周标准差 | 收益/价格波动 | 常见 `False` |
| `stdev_20` | 20 周标准差 | 波动水平 | 常见 `False` |
| `stdev_30` | 30 周标准差 | 波动水平 | 常见 `False` |
| `BBP_5_2.0_2.0_5_2.0` | Bollinger Percent | 价格处在布林带中的相对位置 | 突破策略常用 `True`，均值回归常用 `False` |
| `BBP_20_2.0_2.0_20_2.0` | 同上 | 更常用的中期位置指标 | 同上 |
| `BBP_10_2.0_2.0_10_1.5` | 同上 | 更短参数版本 | 同上 |
| `BBB_*` | Bollinger Bandwidth | 带宽，反映波动和压缩 | 突破前压缩常见先用 `False` 再叠加动量 |

说明：

- `BBP_*` 比 `BBL_*`、`BBM_*`、`BBU_*` 更适合直接横截面排名，因为它是“相对位置”。
- `atr_*`、`stdev_*` 更像风险控制 score，而不是 alpha 主 score。

### 2.4 统计分布类

这类指标更多是补充信息，不建议一上来就重仓使用。

| 字段 | 含义 | 常见理解 | 常见方向 |
| --- | --- | --- | --- |
| `entropy` | 序列熵 | 趋势是否更“杂乱” | 需要实验，不建议直接默认 |
| `skew` | 偏度 | 收益分布偏斜 | 需要实验，不建议直接默认 |

说明：

- 这两个指标更偏研究特征。
- 可以做实验，但不建议作为第一批核心 score。

## 3. 哪些字段不建议裸放进 score

下面这些列虽然现在已经支持放进 `score_columns`，但如果 **不配 `score_value_map`**，通常不够精确：

### 3.1 字符串形态列

- `triangle_pattern`
- `wedge_pattern`
- `double_pattern`
- `head_shoulder_pattern`
- `multiple_top_bottom_pattern`
- `channel_pattern`
- `signal`

原因：

- 它们是类别型 / 字符串型，不是连续数值。
- 如果不配 `score_value_map`，默认只能按“有没有出现过”来打分，无法区分 `Ascending Triangle` 和其他形态。
- 更稳的做法是显式指定目标值，比如 `{'triangle_pattern': 'Ascending Triangle'}`。

### 3.2 K 线形态布尔列

- `BullishEngulfing`
- `BearishEngulfing`
- `Doji`
- `Hammer`
- `HangingMan`
- `InvertedHammer`
- `ShootingStar`
- `MorningStar`
- `BullishHarami`
- `BearishHarami`
- `PiercingPattern`
- `DarkCloudCover`

原因：

- 它们大多是 `True/False`。
- 虽然现在可以直接参与 score，但横截面区分度通常弱于连续数值指标。
- 更推荐把它们当成“加分项”，而不是唯一主 score。

### 3.3 形态取值含义速查

下面这张表解释的是 **本项目当前实现里的含义**。  
它们来自 `tradingpatterns/tradingpatterns.py` 的滚动窗口规则，所以更适合理解为“程序化定义下的结构信号”，不一定等同于最严格的经典图表教材定义。

| 列名 | 取值 | 大致含义 | 常见直觉 | 常见 `score_value_map` 写法 |
| --- | --- | --- | --- | --- |
| `triangle_pattern` | `Ascending Triangle` | 高点平台附近震荡、低点逐步抬高 | 偏多，常被当作上破准备形态 | `{'triangle_pattern': 'Ascending Triangle'}` |
| `triangle_pattern` | `Descending Triangle` | 低点平台附近震荡、高点逐步下移 | 偏空，常被当作下破准备形态 | `{'triangle_pattern': 'Descending Triangle'}` |
| `wedge_pattern` | `Wedge Up` | 高低点都在上移，价格楔形向上收敛 | 常被视为上涨过程中的衰竭/整理，方向要结合其他指标确认 | `{'wedge_pattern': 'Wedge Up'}` |
| `wedge_pattern` | `Wedge Down` | 高低点都在下移，价格楔形向下收敛 | 常被视为下跌过程中的衰竭/整理，可能酝酿反弹 | `{'wedge_pattern': 'Wedge Down'}` |
| `double_pattern` | `Double Top` | 两次上冲高位失败 | 偏空反转信号 | `{'double_pattern': 'Double Top'}` |
| `double_pattern` | `Double Bottom` | 两次下探低位后企稳 | 偏多反转信号 | `{'double_pattern': 'Double Bottom'}` |
| `head_shoulder_pattern` | `Head and Shoulder` | 中间头部高于两侧肩部 | 偏空反转信号 | `{'head_shoulder_pattern': 'Head and Shoulder'}` |
| `head_shoulder_pattern` | `Inverse Head and Shoulder` | 中间低点低于两侧肩部 | 偏多反转信号 | `{'head_shoulder_pattern': 'Inverse Head and Shoulder'}` |
| `multiple_top_bottom_pattern` | `Multiple Top` | 多次上冲阻力位失败 | 偏空 | `{'multiple_top_bottom_pattern': 'Multiple Top'}` |
| `multiple_top_bottom_pattern` | `Multiple Bottom` | 多次下探支撑位后企稳 | 偏多 | `{'multiple_top_bottom_pattern': 'Multiple Bottom'}` |
| `channel_pattern` | `Channel Up` | 价格在向上通道中运行 | 偏多趋势延续 | `{'channel_pattern': 'Channel Up'}` |
| `channel_pattern` | `Channel Down` | 价格在向下通道中运行 | 偏空趋势延续 | `{'channel_pattern': 'Channel Down'}` |
| `signal` | `HH` | Higher High，更高的高点 | 趋势强化，偏多 | `{'signal': ['HH', 'HL']}` |
| `signal` | `HL` | Higher Low，更高的低点 | 结构转强，偏多 | `{'signal': ['HH', 'HL']}` |
| `signal` | `LH` | Lower High，更低的高点 | 反弹转弱，偏空 | `{'signal': ['LH', 'LL']}` |
| `signal` | `LL` | Lower Low，更低的低点 | 下跌延续，偏空 | `{'signal': ['LH', 'LL']}` |

补充说明：

- 如果你做 **趋势跟随**，常见会偏好：
  - `Ascending Triangle`
  - `Double Bottom`
  - `Inverse Head and Shoulder`
  - `Channel Up`
  - `HH` / `HL`
- 如果你做 **偏空或风险规避筛查**，常见会关注：
  - `Descending Triangle`
  - `Double Top`
  - `Head and Shoulder`
  - `Channel Down`
  - `LH` / `LL`
- `Wedge Up` 和 `Wedge Down` 的解释最依赖上下文：
  - 它们更像“收敛结构”而不是单边确认信号。
  - 实盘上通常建议和 `momentum_*`、`MACDh_*`、`rsi_*` 一起使用，不建议单独重仓使用。

## 4. 我建议你优先用哪些 score

如果你现在只是想先把回测跑稳，我建议优先从这几组开始。

### 4.1 趋势跟随型

```python
score_columns = ['momentum_20', 'MACDh_12_26_9', 'rsi_14']
score_weights = [0.4, 0.4, 0.2]
higher_is_better = [True, True, True]
```

适合：

- 想找近期最强、趋势最顺的股票。

### 4.2 中周期趋势型

```python
score_columns = ['momentum_50', 'MACD_20_50_18', 'rsi_21']
score_weights = [0.4, 0.4, 0.2]
higher_is_better = [True, True, True]
```

适合：

- 想降低短噪声，偏中期持有。

### 4.3 低波动趋势型

```python
score_columns = ['momentum_20', 'MACDh_12_26_9', 'stdev_20']
score_weights = [0.4, 0.4, 0.2]
higher_is_better = [True, True, False]
```

适合：

- 想兼顾上涨趋势和波动控制。

### 4.4 突破型

```python
score_columns = ['BBP_20_2.0_2.0_20_2.0', 'momentum_10', 'MACDh_12_26_9']
score_weights = [0.3, 0.4, 0.3]
higher_is_better = [True, True, True]
```

适合：

- 想优先找靠近上轨且动能增强的标的。

### 4.5 均值回归型

```python
score_columns = ['rsi_14', 'BBP_20_2.0_2.0_20_2.0', 'momentum_10']
score_weights = [0.4, 0.3, 0.3]
higher_is_better = [False, False, False]
```

适合：

- 想找短期偏弱、可能反弹的股票。

## 5. 一个很重要的实践建议

如果你要结合形态和分数，常见有两种做法：

1. 先用形态列做筛选。
2. 直接把形态列也放进 score，并用 `score_value_map` 指定目标值。

更稳的做法通常还是：

- 先只看 `triangle_pattern == 'Ascending Triangle'`
- 再用 `momentum_20 + MACDh_12_26_9 + rsi_14` 排序

如果你想让形态作为“加分项”，可以这样写：

```python
score_columns = ['triangle_pattern', 'signal', 'rsi_14', 'momentum_10', 'MACDh_12_26_9']
score_weights = [0.15, 0.15, 0.20, 0.25, 0.25]
higher_is_better = [True, True, True, True, True]
score_value_map = {
    'triangle_pattern': 'Ascending Triangle',
    'signal': ['HH', 'HL'],
}
```

这比“直接把字符串形态裸塞进 score”更稳定，也更容易解释为什么被选中。

## 6. 当前 `patterns.parquet` 里常见可选 score 列

下面这些是当前文件里最值得优先考虑的数值列。

### 6.1 推荐优先级最高

- `rsi_14`
- `rsi_21`
- `rsi_30`
- `momentum_10`
- `momentum_20`
- `momentum_30`
- `momentum_50`
- `momentum_100`
- `MACD_12_26_9`
- `MACDh_12_26_9`
- `MACDs_12_26_9`
- `MACD_20_50_18`
- `MACDh_20_50_18`
- `MACDs_20_50_18`
- `MACD_50_100_25`
- `MACDh_50_100_25`
- `MACDs_50_100_25`
- `rvi_10`
- `rvi_14`
- `rvi_20`
- `atr_14`
- `atr_21`
- `atr_30`
- `stdev_10`
- `stdev_20`
- `stdev_30`
- `BBP_5_2.0_2.0_5_2.0`
- `BBP_20_2.0_2.0_20_2.0`
- `BBP_10_2.0_2.0_10_1.5`

### 6.2 可研究，但不建议第一版就上

- `entropy`
- `skew`
- `ema_10`
- `ema_20`
- `ema_50`
- `ema_100`
- `fwma_10`
- `fwma_30`
- `fwma_50`
- `BBB_5_2.0_2.0_5_2.0`
- `BBB_20_2.0_2.0_20_2.0`
- `BBB_10_2.0_2.0_10_1.5`
- `PSARaf_0.02_0.2_0.02_0.2`
- `PSARaf_0.02_0.2_0.01_0.1`
- `PSARaf_0.02_0.2_0.005_0.05`

## 7. 你现在最实用的做法

如果你只是想先把 notebook 用起来，我建议先在这三套里选一套：

- 趋势：`['momentum_20', 'MACDh_12_26_9', 'rsi_14']`
- 中周期：`['momentum_50', 'MACD_20_50_18', 'rsi_21']`
- 低波动趋势：`['momentum_20', 'MACDh_12_26_9', 'stdev_20']`

如果你想把“形态”也放进去，现在有两种都可行：

- 稳妥版：先加过滤条件，再用数值指标排序。
- 混合版：把形态列写进 `score_columns`，并通过 `score_value_map` 指定目标值。

`Pattern_backtest.ipynb` 里现在已经增加了“候选 score 速查表”单元，可以直接在 notebook 内查看这些候选项。

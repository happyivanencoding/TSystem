# `screen_aggregate.parquet` 与 `returns.parquet` 上下文说明

本文档是 00_screen/returns 的 canonical 语义说明之一。最新路径规则见 `C:\GoogleDrive\TP\DATA_SOURCES.md`，可执行契约见 `C:\GoogleDrive\TP\DATA_CONTRACT.md`。

---

## 1. 文档定位

本文档是给其他项目的 LLM 使用的上下文说明文件，目标不是穷举所有字段定义，而是回答下面几个关键问题：

- 这两张 parquet 分别是什么表、粒度是什么、怎么更新。
- `screen_aggregate.parquet` 和 `returns.parquet` 之间如何关联。
- 哪些空值是正常业务含义，哪些才可能是数据问题。
- 当前 live 数据和历史说明文档之间有哪些偏差，应该以什么为准。

本文档的业务语义主要来自：

- `说明文档/monthly_update_workflow.md`
- `说明文档/Screen_Agg数据库字典.md`

本文档的结构统计来自当前工作区中的 live parquet 文件实测。

## 2. 一句话结论

- `screen_aggregate.parquet` 是一张**月末截面宽表**，每行是一只证券在一个月末的特征快照。
- `returns.parquet` 是一张**日频收益宽矩阵**，索引是交易日，列是证券 ID。
- 两张表的主要连接方式不是 `ISIN`，而是：
  - `screen_aggregate.parquet['Company SEDOL']`
  - 对应 `returns.parquet` 的列名
- benchmark 权重列的空值通常表示**该证券不属于该 benchmark**，不能直接当成“数据缺失”。
- 当说明文档和 live parquet 不一致时，**以 live parquet 当前实际结构为准**。

## 3. 更新流程中的角色

根据 `monthly_update_workflow.md` 和当前代码：

1. `monthly_prod.ipynb` 调用 `monthly_update.py` 的 `run_monthly_update()`。
2. 月度 Excel 先生成最新单月 `screen` 快照：
   - `read_new_FS_screen()`
   - `FactSet_ICB_Mapping()`
   - `add_score_multifacteur()`
   - `rebalance_weight_sum_to_1()`
   - `add_univ_ml()`
3. 新月快照会替换 `screen_aggregate.parquet` 中同月份的数据。
4. `returns.parquet` 会先和最新增量收益合并。
5. 风险字段和 `Perf5D / Perf1M / Perf3M / Perf6M` 再并回 `screen_aggregate.parquet`。

需要特别注意：

- `returns.parquet` 是风险与表现计算的底表，不是最终分析宽表。
- benchmark 日收益不是直接存放在 `returns.parquet` 里，而是在 `Technicals.py` 中根据个股日收益和 `screen_aggregate.parquet` 的 benchmark 权重动态计算。
- 风险计算保留 legacy `SXXP Bench` / SXXP Beta，同时已经写入区域 Beta 字段：US 使用 SP500，West Europe 使用 STOXX Europe 600，其他地区使用 MSCI WORLD。

## 4. `screen_aggregate.parquet`

### 4.1 表的本质

- 类型：历史月度主表
- 粒度：单证券、单月末
- 逻辑主键：`(ISIN, Date)`
- 时间频率：月频，且当前所有 `Date` 都是月末

### 4.2 当前 live 文件统计

以下统计基于当前 parquet 实测：

| 指标 | 数值 |
| --- | --- |
| 行数 | `3,421,301` |
| 直接读取后的列数 | `189` |
| `reset_index()` 后字段数 | `190` |
| 日期范围 | `1999-12-31` 到 `2026-03-31` |
| 月末截面数 | `316` |
| 唯一 `ISIN` 数 | `12,279` |
| 唯一 `Company SEDOL` 数 | `12,210` |
| 每月行数最小值 | `10,566` |
| 每月行数中位数 | `10,753` |
| 每月行数最大值 | `11,227` |
| 最新月行数 | `10,943` |
| `(ISIN, Date)` 重复行数 | `0` |

### 4.3 一个很重要的技术细节

当前 `screen_aggregate.parquet` 中，`ISIN` 是以 **index** 的方式存储的，而不是普通列。

这意味着：

- `pd.read_parquet()` 直接读取时，看到的是 `189` 个数据列。
- 如果你需要按字段方式处理 `ISIN`，应先执行 `reset_index()`。
- 因此对下游 LLM 来说，最安全的读取方式通常是：

```python
screen = pd.read_parquet("screen_aggregate.parquet")
if "ISIN" not in screen.columns and screen.index.name == "ISIN":
    screen = screen.reset_index()
screen["Date"] = pd.to_datetime(screen["Date"])
```

### 4.4 当前字段家族概览

当前 live 文件中可粗分为几类：

- 标识与分类字段
  - `ISIN`
  - `Date`
  - `Company SEDOL`
  - `Symbol`
  - `Name`
  - `FactSet Ind`
  - `FactSet Economy`
  - `Exchange Country Name`
  - `Exchange Country Region`
  - `Curncy Iso`
  - ` Benchmark ICB Industry `
  - ` Benchmark ICB Supersector `
  - `ICB19 Supersector`
- benchmark 权重字段：`22` 列
- 表现字段：`4` 列
  - `Perf5D`
  - `Perf1M`
  - `Perf3M`
  - `Perf6M`
- 当前实际存在的风险相关字段：`2` 列
  - `Volatilite Rolling ewma 250D`
  - `Maximum Drawdown Rolling 250D`

字段类型分布：

- 数值列：`173`
- 字符串列：`16`
- 时间列：`1`

### 4.5 benchmark 权重字段的业务含义

这是下游 LLM 最容易误判的一类字段。

`Weight in XXX` 的含义不是“全市场每家公司都应该有值”，而是：

- 如果 `Weight in XXX > 0`，说明该证券当月属于该 benchmark，且数值是其权重。
- 如果是 `NaN` 或 `0`，通常表示该证券**不在这个 benchmark 里**。
- 因此这类字段的高空值率是**正常结构特征**，不是数据质量问题。

实际使用时，应统一用下面的规则判断 benchmark 成分：

```python
mask = screen["Weight in MSCI WORLD"].fillna(0) > 0
world_universe = screen.loc[mask]
```

当前 live 文件中的 benchmark / universe 权重列为：

- `Weight in CAC40`
- `Weight in DJ BROOKFIELD`
- `Weight in EUROSTOXX50`
- `Weight in GLOBAL INFRA`
- `Weight in GLOBAL REIT`
- `Weight in MSCI ACWI`
- `Weight in MSCI EM`
- `Weight in MSCI EMU`
- `Weight in MSCI EUR`
- `Weight in MSCI EUR HIGH DIV`
- `Weight in MSCI EUR SMALL`
- `Weight in MSCI WORLD`
- `Weight in NASDAQ COMP`
- `Weight in NIKKEI`
- `Weight in NMX`
- `Weight in RUSSELL 2000`
- `Weight in SP500`
- `Weight in STOXX EUROPE 600`
- `Weight in SP400`
- `Weight in Univ ML EU`
- `Weight in Univ ML US`
- `Weight in Univ ML OTHER`

最新月 `2026-03-31` 的代表性 benchmark 公司数如下，统计口径均为 `Weight in XXX > 0`：

| Benchmark | 公司数 |
| --- | --- |
| `MSCI ACWI` | `2254` |
| `MSCI WORLD` | `1306` |
| `MSCI EM` | `1205` |
| `STOXX EUROPE 600` | `599` |
| `SP500` | `503` |

### 4.6 因子与业务语义

字段的中文业务定义与公式语义，优先参考 `Screen_Agg数据库字典.md`。对下游 LLM 来说，可以先用下面的心智模型理解：

- 大部分 `... Percentile`、`PCT ...`、`... Avg Percentile` 是**横截面分位或聚合因子分数**
- 很多比较组是 `ICB + Region`
- `Value / Quality / Growth / Momentum / LowVol / Size / Dividend` 都属于风格因子体系
- `Perf5D / Perf1M / Perf3M / Perf6M` 是从 `returns.parquet` 推导出的表现字段
- 风险字段来自 `Technicals.py`

### 4.7 需要特别记住的字段命名坑点

1. ICB 两个字段名带有首尾空格，必须精确引用：
   - ` Benchmark ICB Industry `
   - ` Benchmark ICB Supersector `

2. 市值字段当前以无尾空格版本为主：
   - `Benchmark Market Value Millions in EUR`

3. 当前 live 文件里还存在备用列：
   - `Benchmark Market Value Millions in EUR BK`

4. 如果做下游标准化，建议将市值主列视为：
   - `Benchmark Market Value Millions in EUR`

### 4.8 live 文件与旧文档的偏差

`monthly_update_workflow.md` 中记录的旧口径提到：

- 约 `293` 列
- 截止 `2026-02-28`

但当前 live parquet 实测为：

- 直接读取约 `276` 列，`ISIN` 可能作为 parquet index 存储
- 截止 `2026-05-31`

说明历史说明文档已经滞后。  
如果 LLM 需要做字段存在性判断、行列规模判断、时间覆盖判断，应优先信任**当前 parquet 实测结果**。

另外，`VaR`、SXXP Beta 和区域 Beta 系列风险字段已经在当前主表中落库。下游仍应以文件中真实存在的列为准，不要只根据代码推断字段一定存在。

## 5. `returns.parquet`

### 5.1 表的本质

- 类型：历史日频收益矩阵
- 粒度：单交易日、单证券
- 行索引：交易日 `Date`
- 列：证券 ID，和 `screen_aggregate.parquet['Company SEDOL']` 使用同一套标识体系

列名样例：

- `VDWW59-R`
- `QQ2S55-R`
- `X5DCDV-R`

因此对下游 LLM 来说，最重要的理解是：

- `returns.parquet` 不是长表，而是**宽矩阵**
- 列名本身就是证券 ID

### 5.2 当前 live 文件统计

| 指标 | 数值 |
| --- | --- |
| 形状 | `5445 x 11836` |
| 日期范围 | `2005-01-03` 到 `2026-04-01` |
| 唯一交易日数 | `5445` |
| 日期索引是否唯一 | `True` |
| 每日非空列数最小值 | `11586` |
| 每日非空列数中位数 | `11586` |
| 每日非空列数最大值 | `11836` |
| 最新日非空列数 | `11836` |

列覆盖时长分布：

- 全历史都有值的列：`11,586`，占比约 `97.89%`
- 覆盖少于 `252` 个交易日的列：`250`
- 覆盖少于 `63` 个交易日的列：`85`
- 覆盖少于 `21` 个交易日的列：`42`

这表示：

- 大多数证券列已经有完整历史
- 少量列是最近新增证券，历史较短

### 5.3 收益值的业务含义

从 `screen_func.py` 中 `add_perf()` 的实现可以确认，`returns.parquet` 存的是**简单收益率小数**，不是百分数字符串，也不是价格。

也就是：

- `0.01` 表示 `+1%`
- `-0.02` 表示 `-2%`

因为下游逻辑直接使用：

```python
nav = (1 + returns).cumprod()
```

### 5.4 当前值域与异常值提示

对 live 文件实测后：

- 全体非空值中位数：`0.0`
- `1%` 分位数：约 `-0.0564`
- `99%` 分位数：约 `0.0611`
- 最小值：约 `-0.99999`
- 最大值：约 `168883.98`

额外统计：

- 大于 `1` 的值有 `1635` 个
- 大于 `10` 的值有 `322` 个
- 小于 `-1` 的值有 `0` 个

解释建议：

- 大多数日收益都落在合理区间内
- 但存在少量极端正收益异常值
- 这些极端值更适合作为**公司行为 / 拆分复权 / 数据异常候选**对待
- 下游如果做回测、风险统计或训练特征，建议考虑 winsorize、clip 或异常点审计

### 5.5 benchmark 收益不是原始存储列

`returns.parquet` 里并不直接保存 benchmark 日收益列。  
风险逻辑会在 `Technicals.py` 中根据个股日收益和 benchmark 权重动态生成 benchmark 收益：

1. 把个股日收益展开成长表。
2. 按地区选择 benchmark 权重：US 对 SP500，West Europe 对 STOXX Europe 600，其他地区对 MSCI WORLD。
3. 对每个交易日按权重聚合。
4. 保留 legacy `SXXP Bench`，同时生成区域 benchmark 相关 Beta。

因此：

- `returns.parquet` 是证券级底表
- benchmark 日收益是计算产物，不是主存储字段

## 6. `screen` 与 `returns` 的连接规则

### 6.1 正确连接键

最重要的映射关系：

- `screen_aggregate.parquet['Company SEDOL']`
- 对应 `returns.parquet` 的列名

不是：

- `ISIN`
- `Symbol`

### 6.2 当前 live 覆盖结果

在最新月 `2026-03-31`：

- 最新月有效 `Company SEDOL` 数：`10,920`
- 在 `returns.parquet` 中都能找到对应列：`10,920`
- 真正缺失的有效 SEDOL 数：`0`

也就是说，当前最新月的 `screen` 与 `returns` 连接覆盖是完整的。

### 6.3 推荐连接方式

如果要为某个月的 `screen` 截面抽取对应收益序列，推荐写法：

```python
screen = pd.read_parquet("screen_aggregate.parquet")
if "ISIN" not in screen.columns and screen.index.name == "ISIN":
    screen = screen.reset_index()
screen["Date"] = pd.to_datetime(screen["Date"])

returns = pd.read_parquet("returns.parquet")

date_last = screen["Date"].max()
screen_last = screen.loc[screen["Date"] == date_last].copy()
sedols = screen_last["Company SEDOL"].dropna().astype(str).unique()

returns_sub = returns.loc[:, returns.columns.astype(str).isin(sedols)]
```

## 7. 下游 LLM 应遵守的默认规则

如果其他项目的 LLM 只读到本文件，建议默认采用下面这些规则：

1. `screen_aggregate.parquet` 是月度横截面主表，`returns.parquet` 是日频收益底表。
2. `screen` 和 `returns` 的证券连接键默认使用 `Company SEDOL`。
3. benchmark 成分判断默认使用 `Weight in XXX`.fillna(0) > 0。
4. 不要把 benchmark weight 列的空值直接解释为数据缺失。
5. `screen['Date']` 是月末日期，不是日频日期。
6. `returns.index` 是交易日，不是月末对齐索引。
7. 如果发现说明文档和 parquet 实测不一致，优先信任 parquet。
8. 精确使用列名，尤其注意：
   - ` Benchmark ICB Industry `
   - ` Benchmark ICB Supersector `
   - `Benchmark Market Value Millions in EUR`
9. 对 `returns.parquet` 做统计时，要意识到存在极端正收益异常值。

## 8. 适合问这两张表的问题

其他项目的 LLM 适合用这两张表回答的问题包括：

- 某个月末的横截面选股、打分、分层和 benchmark 过滤
- 某类因子字段在不同行业 / 区域中的解释
- benchmark 成分股数量、权重覆盖和 universe 构造
- 用 `returns.parquet` 做收益、波动率、最大回撤、滚动表现等时间序列计算
- 用月末 `screen` 定义当月持仓，再用 `returns` 做后续收益跟踪

不适合直接假设的问题包括：

- “所有 `Weight in XXX` 都应该非空”
- “`returns.parquet` 已经自带 benchmark return 列”
- “`ISIN` 可以直接连接到 `returns.parquet`”
- “说明文档里的列数和当前 parquet 一定一致”

## 9. 最后结论

如果只保留一个最小可用心智模型，可以记住下面这四句话：

1. `screen_aggregate.parquet` 是**月末证券特征宽表**。
2. `returns.parquet` 是**日频证券收益宽矩阵**。
3. 两者通过 `Company SEDOL` 连接。
4. benchmark 权重列的空值大多表示“非成分股”，不是坏数据。


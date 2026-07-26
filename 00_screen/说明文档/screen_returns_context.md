# `screen_aggregate.parquet` 与 `returns.parquet` 上下文

本文档只说明长期稳定的数据语义。最新行数、列数、日期范围和覆盖率应读取 database profile、月更 QA 或运行 inspect，不在本文手工维护。

## 数据角色

| 数据集 | 粒度 | 主要用途 |
| --- | --- | --- |
| `screen_aggregate.parquet` | 证券 × 月末 | PIT universe、基本面、因子、指数权重和月度研究特征 |
| `last_screen.parquet` | 证券 × 最新月末 | 轻量生产与展示 |
| `returns.parquet` | 交易日 × SEDOL | 风险、表现、标签和回测 |
| `screen_aggregate_5Y.parquet` | 证券 × 近年月末 | 轻量下游 |

路径以根目录 `DATA_SOURCES.md` 和 `tp_core.data_sources` 为准。

## Screen 主键与日期

- 逻辑主键是 `(ISIN, Date)`。
- `Date` 标准化为月末，表示该截面的评价期。
- 指数 universe 必须使用当期已知权重字段，例如 `Weight in SP500 > 0`，不能以今天的成分回填历史。
- `TTR_Fwd1M` 等未来字段只能作为研究标签，不能进入同日可交易信号。
- 字段存在不等于当期可用；供应商发布时间或额外可用时间必须进入 PIT 判断。

常见字段族：

- 标识：`ISIN`、`Company SEDOL`、`Symbol`、`Name`。
- 分类：国家、地区、ICB Industry/Supersector。
- Universe：各指数 PIT 权重。
- 因子：Value、Quality、Growth、Momentum、LowVol、Size、Dividend、ML。
- 风险与表现：波动率、VaR、Beta、回撤、近期 Perf。
- 研究标签：未来收益、未来波动和未来回撤。

字段业务定义见 `Screen_Agg数据库字典.md`；若模板字典与实际 schema 不一致，以数据契约、月更 QA 和真实 parquet 为准。

## Returns 主键与语义

- 行索引是交易日。
- 列名是证券 SEDOL；历史数据可能带 `-R` 等供应商后缀，连接前应通过共享标识规则规范化。
- 单元格是该证券对应交易日的收益值；单位和异常边界以根目录 `DATA_CONTRACT.md` 为准。
- 缺失值不是零收益，不能未经说明直接填零。
- Benchmark 收益通常由当期 PIT 权重与成分收益计算，不是 `returns.parquet` 的固定原始列。

## 连接规则

Screen 与 returns 不共享同一时间粒度：

1. 用 `Company SEDOL` 的规范化基础标识映射 returns 列。
2. 用 Screen 当月已知 universe 确定证券集合和权重。
3. 对日频收益按研究目的聚合到月度或风险窗口。
4. 信号、权重和标签必须分别保存 `as_of_date`、`effective_date` 或等价可用时间。
5. 对未匹配、重复标识、标识变更和退市证券保留明确审计记录。

不要直接把月末 `Date` 与某个日频交易日做未经解释的等值连接。

## 推荐读取方式

```python
from tp_core.io import read_returns, read_screen_aggregate

screen = read_screen_aggregate()
returns = read_returns()
```

业务模块不应自行硬编码文件路径或维护数据副本。

## 质量检查

每次刷新至少检查：

- Screen `(ISIN, Date)` 唯一性和目标月份替换边界。
- Returns 日期索引唯一、排序和新增区间。
- SEDOL 规范化后的映射率。
- 主要指数权重和、成分数量与异常跳变。
- 关键因子、风险和表现字段的最新期缺失率。
- 输入 fingerprint、PIT 截止时间、配置、代码版本和 lineage。

机器证据位于 `00_screen/qa/`、`production_inputs/profiles/` 和 `artifacts/pipeline_runs/`。

## Technical 专项

`patterns.parquet` 的结构、可用日期和 Screen/returns 对齐规则只在 `03_technical_analysis/data/screen_returns_context.md` 维护；该专项文档不再复制本文件正文。

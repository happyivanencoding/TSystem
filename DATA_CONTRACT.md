# TP 数据契约

最后更新：2026-06-29

本文档定义 TP 项目中两张核心 canonical 数据集的统一契约：

- `C:\GoogleDrive\TP\00_screen\screen_aggregate.parquet`
- `C:\GoogleDrive\TP\00_screen\returns.parquet`

可执行契约位于 `tp_core.data_contract`。

## `screen_aggregate.parquet`

| 契约项 | 规则 |
| --- | --- |
| 粒度 | 每个证券、每个月末快照一行 |
| 逻辑主键 | `(ISIN, Date)` 必须唯一 |
| 索引 | `ISIN` 可能作为 parquet index 存储；读取函数必须同时兼容 index 或普通列 |
| 日期语义 | `Date` 统一归一到月末 timestamp |
| returns 连接键 | `Company SEDOL` 连接到 `returns.columns` |
| weight 空值语义 | `Weight in ...` 列为空通常表示非成分股或权重不可得，本身不等于数据错误 |
| 成分股判断 | 使用 `screen[weight_col].fillna(0) > 0` |
| 已废弃列 | `EM CountryCluster` 与 `Weight in MSCI EM - ...` 已停用，写入时必须删除 |

## `returns.parquet`

| 契约项 | 规则 |
| --- | --- |
| 粒度 | 每行一个交易日，每列一个 `Company SEDOL` |
| 索引 | 日频交易 `Date`，必须唯一且可解析为 datetime |
| 数值 | 日度简单收益率，使用小数格式，例如 `0.01` 表示 +1% |
| Screen 连接 | 列名必须匹配有效的 `screen_aggregate.Company SEDOL` |
| 异常审计 | 风险计算或回测前应检查极端收益值 |

## 字段族

| 字段族 | 示例 |
| --- | --- |
| 标识符 | `ISIN`, `Company SEDOL`, `Symbol`, `Name` |
| 地区 | `Exchange Country Name`, `Exchange Country Region`, `Benchmark Country English` |
| 行业 | ` Benchmark ICB Industry `, ` Benchmark ICB Supersector `, `ICB19 Supersector`, `FactSet Ind` |
| 权重 | `Weight in MSCI WORLD`, `Weight in SP500`, `Weight in STOXX EUROPE 600`, `Weight in MSCI EM` |
| ML universe | `Weight in Univ ML EU`, `Weight in Univ ML US`, `Weight in Univ ML OTHER` |
| 因子 | Value、Quality、Growth、Momentum、LowVol、Dividend、Size 的原始值与 percentile 字段 |
| 风险 | EWMA 波动率、VaR、最大回撤、SXXP Beta、区域 Beta 字段 |
| 表现 | `Perf5D`, `Perf1M`, `Perf3M`, `Perf6M` |
| CIQ | 通过 `(ISIN, Date)` 合并的财务报表与预测字段 |

## 共享 API

```python
from tp_core.io import read_screen_aggregate, read_returns
from tp_core.data_contract import validate_screen_contract, validate_returns_contract, sedol_coverage

screen = read_screen_aggregate()
returns = read_returns()
print(validate_screen_contract(screen))
print(validate_returns_contract(returns))
print(sedol_coverage(screen, returns))
```

## 区域 Beta

月度风险流水线保留 legacy 字段 `Beta vs SXXP (Rolling ewma 250D)`，同时写入 `Beta vs Regional Benchmark (Rolling ewma 250D)`。区域 Beta 将 US 证券映射到 SP500，West Europe 证券映射到 STOXX Europe 600，其他证券映射到 MSCI WORLD。

## Returns 异常审计

```powershell
python -m tp_core.returns_audit --report-path C:\GoogleDrive\TP\00_screen\qa\returns_anomaly_audit.json
```

默认阈值会标记 `abs(return) >= 100%`、`return >= 200%` 或 `return <= -95%` 的日收益。
